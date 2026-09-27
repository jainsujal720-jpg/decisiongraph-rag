import asyncio
import hashlib
import io
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx

from decisiongraph.api.main import app
from decisiongraph.cloud import s3_uploads


def test_cloud_upload_rejects_unsupported_or_oversized_file_before_signing():
    service = object.__new__(s3_uploads.S3CloudUploads)
    digest = hashlib.sha256(b"test").hexdigest()
    for filename, size in (("evil.exe", 4), ("notes.md", 21 * 1024 * 1024)):
        try:
            service.prepare("acme", "sujal", "team", filename,
                            "text/plain", size, digest)
        except s3_uploads.CloudUploadError:
            pass
        else:
            raise AssertionError("Unsupported file must not reach S3 or PostgreSQL")


def test_cloud_upload_checks_owner_and_content_before_indexing(monkeypatch):
    data = b"The Orion launch moved because rehearsal failed."
    checksum = hashlib.sha256(data).hexdigest()
    rows = {}
    now = datetime.now(UTC)
    calls = []

    class Result:
        def __init__(self, row=None):
            self.row = row

        def fetchone(self):
            return self.row

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql, args):
            if "INSERT INTO cloud_uploads" in sql:
                upload_id, tenant, owner, scope, bucket, key, name, mime, digest, size = args
                rows[upload_id] = {"id": upload_id, "tenant_id": tenant,
                                   "owner_id": owner, "access_scope": scope, "bucket": bucket,
                                   "object_key": key, "filename": name, "content_type": mime,
                                   "checksum_sha256": digest, "size_bytes": size,
                                   "status": "requested", "document_id": None,
                                   "error_message": None, "created_at": now,
                                   "updated_at": now}
                return Result()
            if "UPDATE cloud_uploads SET status = 'processing'" in sql:
                upload_id, tenant, owner = args
                row = rows.get(upload_id)
                if row and row["tenant_id"] == tenant and row["owner_id"] == owner \
                        and row["status"] in {"requested", "failed"}:
                    row["status"] = "processing"
                    return Result(row.copy())
                return Result()
            if "UPDATE cloud_uploads SET status = 'indexed'" in sql:
                doc_id, upload_id = args
                rows[upload_id].update(status="indexed", document_id=doc_id)
                return Result()
            if "UPDATE cloud_uploads SET status = %s" in sql:
                state, error, upload_id = args
                rows[upload_id].update(status=state, error_message=error)
                return Result()
            if "FROM cloud_uploads" in sql:
                upload_id, tenant, owner = args
                row = rows.get(upload_id)
                return Result(row.copy() if row and row["tenant_id"] == tenant
                              and row["owner_id"] == owner else None)
            raise AssertionError(sql)

    class Client:
        def generate_presigned_url(self, *_args, **kwargs):
            calls.append(kwargs)
            return "https://example.invalid/signed"

        def head_object(self, **_kwargs):
            return {"ContentLength": len(data), "ETag": '"v1"'}

        def get_object(self, **_kwargs):
            return {"Body": io.BytesIO(data), "ETag": '"v1"'}

    class Knowledge:
        def ingest(self, filename, content, *_args):
            assert content == data
            assert filename.endswith(".md")
            calls.append("indexed")
            return SimpleNamespace(document_id="f0a6a5cf-401b-4f87-a9bc-53b273efb2d1",
                                   child_chunks=1, deduplicated=False)

    monkeypatch.setattr(s3_uploads.psycopg, "connect", lambda *_a, **_k: Connection())
    service = object.__new__(s3_uploads.S3CloudUploads)
    service.postgres_url = "fake"
    service.bucket = "private-test"
    service.client = Client()
    service.knowledge_service = Knowledge()
    prepared = service.prepare("acme", "sujal", "team", "orion.md", "text/markdown",
                               len(data), checksum)
    assert calls[0]["Params"]["ChecksumSHA256"] == prepared["headers"]["x-amz-checksum-sha256"]
    import uuid
    upload_id = uuid.UUID(prepared["upload_id"])
    assert service.status(upload_id, "acme", "another") is None
    try:
        service.finish(upload_id, "acme", "another")
    except s3_uploads.CloudUploadError:
        pass
    else:
        raise AssertionError("An upload must not be claimable by another user")
    assert "indexed" not in calls
    result = service.finish(upload_id, "acme", "sujal")
    assert result["status"] == "indexed" and result["child_chunks"] == 1
    assert service.finish(upload_id, "acme", "sujal")["document_id"] == result["document_id"]

    bad = service.prepare("acme", "sujal", "team", "different.md", "text/markdown",
                          len(data), hashlib.sha256(b"x" * len(data)).hexdigest())
    bad_id = uuid.UUID(bad["upload_id"])
    try:
        service.finish(bad_id, "acme", "sujal")
    except s3_uploads.CloudUploadError:
        pass
    else:
        raise AssertionError("Tampered cloud content must not be indexed")
    assert service.status(bad_id, "acme", "sujal")["status"] == "failed"
    assert calls.count("indexed") == 1


def test_cloud_config_defaults_to_disabled(monkeypatch):
    monkeypatch.setattr("decisiongraph.api.main.settings.cloud_s3_bucket", None)

    async def get():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/v1/cloud/config")

    response = asyncio.run(get())
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "provider": "s3"}
