"""Private, tenant-bound S3 uploads that feed the existing ingestion pipeline."""

import base64
import hashlib
import re
import uuid
from pathlib import Path

import boto3
import psycopg
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from psycopg.rows import dict_row

from decisiongraph.ingestion.parsers import MAX_FILE_BYTES, SUPPORTED_EXTENSIONS


class CloudUploadError(ValueError):
    pass


class S3CloudUploads:
    def __init__(self, postgres_url: str, bucket: str, region: str, knowledge_service):
        self.postgres_url = postgres_url
        self.bucket = bucket
        self.knowledge_service = knowledge_service
        # Botocore can use the global hostname for presigned URLs even when
        # its regular S3 requests target the configured Region. Pin the signing
        # endpoint as well: a newly created bucket can redirect global-host
        # PUTs, and following that redirect would invalidate the signature.
        self.client = boto3.client(
            "s3", region_name=region,
            endpoint_url=f"https://s3.{region}.amazonaws.com",
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )

    def prepare(
        self, tenant_id: str, owner_id: str, access_scope: str, filename: str,
        content_type: str, size_bytes: int, checksum_sha256: str,
    ) -> dict:
        name = Path(filename.replace("\\", "/")).name
        if (name in {"", ".", ".."} or len(name) > 200
                or any(ord(char) < 32 for char in name)
                or Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS):
            raise CloudUploadError("Choose a supported PDF, DOCX, TXT, MD, CSV, or XLSX file")
        if not 0 < size_bytes <= MAX_FILE_BYTES:
            raise CloudUploadError("Cloud uploads must be between 1 byte and 20 MB")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", checksum_sha256):
            raise CloudUploadError("A SHA-256 checksum is required")
        if (not content_type or len(content_type) > 150
                or any(ord(char) < 32 for char in content_type)):
            raise CloudUploadError("A valid content type is required")
        upload_id = uuid.uuid4()
        tenant_prefix = hashlib.sha256(tenant_id.encode()).hexdigest()[:20]
        key = f"tenants/{tenant_prefix}/uploads/{upload_id}/{name}"
        checksum = checksum_sha256.lower()
        aws_checksum = base64.b64encode(bytes.fromhex(checksum)).decode()
        with psycopg.connect(self.postgres_url) as connection:
            connection.execute(
                """INSERT INTO cloud_uploads
                   (id, tenant_id, owner_id, access_scope, bucket, object_key, filename,
                    content_type, checksum_sha256, size_bytes, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'requested')""",
                (upload_id, tenant_id, owner_id, access_scope, self.bucket, key, name,
                 content_type, checksum, size_bytes),
            )
        try:
            url = self.client.generate_presigned_url(
                "put_object",
                Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type,
                        "ChecksumSHA256": aws_checksum},
                ExpiresIn=900,
            )
        except (ClientError, BotoCoreError):
            self._set_status(upload_id, "failed", "Unable to prepare S3 upload")
            raise
        return {"upload_id": str(upload_id), "upload_url": url,
                "headers": {"Content-Type": content_type,
                            "x-amz-checksum-sha256": aws_checksum},
                "expires_in_seconds": 900}

    def status(self, upload_id: uuid.UUID, tenant_id: str, owner_id: str) -> dict | None:
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """SELECT id, filename, status, document_id, error_message, created_at,
                          updated_at FROM cloud_uploads
                   WHERE id = %s AND tenant_id = %s AND owner_id = %s""",
                (upload_id, tenant_id, owner_id),
            ).fetchone()
        if row is None:
            return None
        return {**row, "id": str(row["id"]),
                "document_id": str(row["document_id"]) if row["document_id"] else None,
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat()}

    def finish(self, upload_id: uuid.UUID, tenant_id: str, owner_id: str) -> dict:
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """UPDATE cloud_uploads SET status = 'processing', updated_at = NOW(),
                          error_message = NULL
                   WHERE id = %s AND tenant_id = %s AND owner_id = %s
                     AND status IN ('requested', 'failed')
                   RETURNING *""",
                (upload_id, tenant_id, owner_id),
            ).fetchone()
            if row is None:
                existing = connection.execute(
                    """SELECT status, document_id, filename, access_scope FROM cloud_uploads
                       WHERE id = %s AND tenant_id = %s AND owner_id = %s""",
                    (upload_id, tenant_id, owner_id),
                ).fetchone()
                if existing is None:
                    raise CloudUploadError("Cloud upload not found")
                if existing["status"] == "indexed":
                    return {"upload_id": str(upload_id), "status": "indexed",
                            "document_id": str(existing["document_id"]),
                            "filename": existing["filename"],
                            "access_scope": existing["access_scope"], "child_chunks": None}
                raise CloudUploadError("Cloud upload is already processing")
        try:
            head = self.client.head_object(Bucket=row["bucket"], Key=row["object_key"])
            if head["ContentLength"] != row["size_bytes"] or head["ContentLength"] > MAX_FILE_BYTES:
                raise CloudUploadError("Uploaded size does not match the authorized file")
            obj = self.client.get_object(Bucket=row["bucket"], Key=row["object_key"])
            data = obj["Body"].read(MAX_FILE_BYTES + 1)
            obj["Body"].close()
            if (len(data) != row["size_bytes"] or len(data) > MAX_FILE_BYTES
                    or hashlib.sha256(data).hexdigest() != row["checksum_sha256"]):
                raise CloudUploadError("Uploaded file does not match its signed checksum")
            if obj.get("ETag") != head.get("ETag"):
                raise CloudUploadError("The cloud object changed while it was being indexed")
            extension = Path(row["filename"]).suffix
            stem = Path(row["filename"]).stem
            # Stable per tenant/owner/scope/name so that repeats become versions.
            identity = hashlib.sha256((row["bucket"] + "/" + tenant_id + "/" +
                                       owner_id + "/" + row["access_scope"] + "/" +
                                       row["filename"]).encode()).hexdigest()[:12]
            source_name = f"{stem}__s3_{identity}{extension}"
            result = self.knowledge_service.ingest(
                source_name, data, row["content_type"], tenant_id, owner_id,
                row["access_scope"],
            )
        except Exception:
            # Leave the upload retryable, and never expose provider credentials or
            # internal errors through the API/status response.
            self._set_status(upload_id, "failed", "Upload verification or indexing failed")
            raise
        with psycopg.connect(self.postgres_url) as connection:
            connection.execute(
                """UPDATE cloud_uploads SET status = 'indexed', document_id = %s,
                          updated_at = NOW() WHERE id = %s AND status = 'processing'""",
                (uuid.UUID(result.document_id), upload_id),
            )
        return {"upload_id": str(upload_id), "status": "indexed",
                "document_id": result.document_id, "filename": row["filename"],
                "access_scope": row["access_scope"],
                "source_name": source_name, "child_chunks": result.child_chunks,
                "deduplicated": result.deduplicated}

    def _set_status(self, upload_id: uuid.UUID, status: str, error: str) -> None:
        with psycopg.connect(self.postgres_url) as connection:
            connection.execute(
                """UPDATE cloud_uploads SET status = %s, error_message = %s,
                          updated_at = NOW() WHERE id = %s""",
                (status, error, upload_id),
            )
