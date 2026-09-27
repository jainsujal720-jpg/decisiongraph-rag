import uuid
from collections.abc import Sequence
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from decisiongraph.graph.models import GraphSource
from decisiongraph.ingestion.models import ChunkedDocument
from decisiongraph.knowledge.models import (
    Candidate,
    DocumentDetail,
    DocumentSummary,
    IngestionResult,
)


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.10g}" for value in values) + "]"


class PostgresKnowledgeStore:
    def __init__(self, postgres_url: str):
        self.postgres_url = postgres_url

    def find_ready_document(
        self, tenant_id: str, filename: str, checksum_sha256: str
    ) -> IngestionResult | None:
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.id AS document_id, dv.id AS version_id,
                           COUNT(c.id) FILTER (WHERE c.chunk_level = 'parent') AS parents,
                           COUNT(c.id) FILTER (WHERE c.chunk_level = 'child') AS children
                    FROM documents d
                    JOIN document_versions dv ON dv.document_id = d.id
                    LEFT JOIN chunks c ON c.document_version_id = dv.id
                    WHERE d.tenant_id = %s AND d.source_name = %s
                      AND d.checksum_sha256 = %s AND dv.status = 'ready'
                    GROUP BY d.id, dv.id, dv.version_number
                    ORDER BY dv.version_number DESC LIMIT 1
                    """,
                    (tenant_id, filename, checksum_sha256),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return IngestionResult(
            str(row["document_id"]),
            str(row["version_id"]),
            filename,
            int(row["parents"]),
            int(row["children"]),
            True,
        )

    def list_documents(
        self, tenant_id: str, user_id: str, allowed_scopes: Sequence[str], limit: int
    ) -> list[DocumentSummary]:
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH latest AS (
                      SELECT DISTINCT ON (document_id) document_id, id, version_number, status
                      FROM document_versions ORDER BY document_id, version_number DESC
                    )
                    SELECT d.id, d.source_name, d.source_type, d.access_scope, d.owner_id,
                           d.created_at, d.updated_at, latest.version_number, latest.status,
                           COUNT(c.id) FILTER (WHERE c.chunk_level = 'parent') AS parent_chunks,
                           COUNT(c.id) FILTER (WHERE c.chunk_level = 'child') AS child_chunks
                    FROM documents d JOIN latest ON latest.document_id = d.id
                    LEFT JOIN chunks c ON c.document_version_id = latest.id
                    WHERE d.tenant_id = %s AND d.access_scope = ANY(%s)
                      AND (d.access_scope <> 'private' OR d.owner_id = %s)
                    GROUP BY d.id, latest.version_number, latest.status
                    ORDER BY d.updated_at DESC LIMIT %s
                    """,
                    (tenant_id, list(allowed_scopes), user_id, limit),
                )
                rows = cursor.fetchall()
        return [self._summary(row) for row in rows]

    def document_detail(
        self, document_id: str, tenant_id: str, user_id: str, allowed_scopes: Sequence[str]
    ) -> DocumentDetail | None:
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.id, d.source_name, d.source_type, d.access_scope, d.owner_id,
                           d.checksum_sha256, d.created_at, d.updated_at
                    FROM documents d WHERE d.id = %s AND d.tenant_id = %s
                      AND d.access_scope = ANY(%s)
                      AND (d.access_scope <> 'private' OR d.owner_id = %s)
                    """,
                    (uuid.UUID(document_id), tenant_id, list(allowed_scopes), user_id),
                )
                document = cursor.fetchone()
                if not document:
                    return None
                cursor.execute(
                    """SELECT id, version_number, status, parser_version, error_message, created_at
                       FROM document_versions WHERE document_id = %s ORDER BY version_number DESC""",
                    (uuid.UUID(document_id),),
                )
                versions = [dict(row) for row in cursor.fetchall()]
                cursor.execute(
                    """SELECT actor_id, action, details, created_at FROM document_events
                       WHERE tenant_id = %s AND document_id = %s ORDER BY created_at DESC LIMIT 30""",
                    (tenant_id, uuid.UUID(document_id)),
                )
                events = [dict(row) for row in cursor.fetchall()]
                latest = versions[0]
                cursor.execute(
                    """SELECT COUNT(*) FILTER (WHERE chunk_level = 'parent') AS parent_chunks,
                              COUNT(*) FILTER (WHERE chunk_level = 'child') AS child_chunks
                       FROM chunks WHERE document_version_id = %s""",
                    (latest["id"],),
                )
                counts = cursor.fetchone()
        return DocumentDetail(
            str(document["id"]),
            document["source_name"],
            document["source_type"],
            document["access_scope"],
            document["owner_id"],
            int(latest["version_number"]),
            latest["status"],
            int(counts["parent_chunks"]),
            int(counts["child_chunks"]),
            document["created_at"].isoformat(),
            document["updated_at"].isoformat(),
            document["checksum_sha256"],
            tuple(self._serialize_rows(versions)),
            tuple(self._serialize_rows(events)),
        )

    def update_access(
        self, document_id: str, tenant_id: str, access_scope: str, actor_id: str
    ) -> DocumentSummary | None:
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE documents SET access_scope = %s, updated_at = NOW()
                       WHERE id = %s AND tenant_id = %s RETURNING *""",
                    (access_scope, uuid.UUID(document_id), tenant_id),
                )
                document = cursor.fetchone()
                if not document:
                    return None
                self._event(
                    cursor,
                    tenant_id,
                    document_id,
                    actor_id,
                    "access_updated",
                    {"access_scope": access_scope},
                )
                cursor.execute(
                    """SELECT id, version_number, status FROM document_versions
                       WHERE document_id = %s ORDER BY version_number DESC LIMIT 1""",
                    (uuid.UUID(document_id),),
                )
                latest = cursor.fetchone()
                cursor.execute(
                    """SELECT COUNT(*) FILTER (WHERE chunk_level = 'parent') AS parent_chunks,
                              COUNT(*) FILTER (WHERE chunk_level = 'child') AS child_chunks
                       FROM chunks WHERE document_version_id = %s""",
                    (latest["id"],),
                )
                counts = cursor.fetchone()
        return DocumentSummary(
            str(document["id"]),
            document["source_name"],
            document["source_type"],
            document["access_scope"],
            document["owner_id"],
            int(latest["version_number"]),
            latest["status"],
            int(counts["parent_chunks"]),
            int(counts["child_chunks"]),
            document["created_at"].isoformat(),
            document["updated_at"].isoformat(),
        )

    def reindex_payload(self, document_id: str, tenant_id: str) -> tuple[str, list[str]] | None:
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT dv.id FROM document_versions dv JOIN documents d ON d.id = dv.document_id
                       WHERE d.id = %s AND d.tenant_id = %s ORDER BY dv.version_number DESC LIMIT 1""",
                    (uuid.UUID(document_id), tenant_id),
                )
                version = cursor.fetchone()
                if not version:
                    return None
                cursor.execute(
                    """SELECT id, content FROM chunks WHERE document_version_id = %s
                       AND chunk_level = 'child' ORDER BY chunk_index""",
                    (version["id"],),
                )
                rows = cursor.fetchall()
        return str(version["id"]), [(str(row["id"]), row["content"]) for row in rows]

    def replace_embeddings_and_audit(
        self,
        document_id: str,
        tenant_id: str,
        version_id: str,
        embeddings: Sequence[Sequence[float]],
        actor_id: str,
    ) -> int:
        payload = self.reindex_payload(document_id, tenant_id)
        if not payload or payload[0] != version_id:
            raise ValueError("Document version changed; retry reindexing")
        chunks = payload[1]
        if len(chunks) != len(embeddings):
            raise ValueError("Embedding count does not match document chunks")
        with psycopg.connect(self.postgres_url) as connection:
            with connection.cursor() as cursor:
                for (chunk_id, _), embedding in zip(chunks, embeddings, strict=True):
                    cursor.execute(
                        "UPDATE chunks SET embedding = %s::vector WHERE id = %s",
                        (_vector_literal(embedding), uuid.UUID(chunk_id)),
                    )
                self._event(
                    cursor,
                    tenant_id,
                    document_id,
                    actor_id,
                    "reindexed",
                    {"version_id": version_id, "child_chunks": len(chunks)},
                )
        return len(chunks)

    def delete_document(self, document_id: str, tenant_id: str, actor_id: str) -> bool:
        with psycopg.connect(self.postgres_url) as connection:
            with connection.cursor() as cursor:
                self._event(cursor, tenant_id, document_id, actor_id, "deleted", {})
                cursor.execute(
                    "DELETE FROM documents WHERE id = %s AND tenant_id = %s",
                    (uuid.UUID(document_id), tenant_id),
                )
                return cursor.rowcount == 1

    @staticmethod
    def _serialize_rows(rows: list[dict]) -> list[dict]:
        output = []
        for row in rows:
            output.append(
                {
                    key: value.isoformat() if hasattr(value, "isoformat") else value
                    for key, value in row.items()
                }
            )
        return output

    @staticmethod
    def _summary(row: dict) -> DocumentSummary:
        return DocumentSummary(
            str(row["id"]),
            row["source_name"],
            row["source_type"],
            row["access_scope"],
            row["owner_id"],
            int(row["version_number"]),
            row["status"],
            int(row["parent_chunks"]),
            int(row["child_chunks"]),
            row["created_at"].isoformat(),
            row["updated_at"].isoformat(),
        )

    @staticmethod
    def _event(
        cursor, tenant_id: str, document_id: str, actor_id: str, action: str, details: dict
    ) -> None:
        cursor.execute(
            "INSERT INTO document_events (tenant_id, document_id, actor_id, action, details) VALUES (%s,%s,%s,%s,%s)",
            (tenant_id, uuid.UUID(document_id), actor_id, action, Jsonb(details)),
        )

    def graph_sources(
        self,
        document_id: str,
        tenant_id: str,
        user_id: str,
        allowed_scopes: Sequence[str],
        limit: int,
    ) -> list[tuple[GraphSource, str, str]]:
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.id AS document_id, d.source_name, d.owner_id, d.access_scope,
                           dv.id AS version_id, dv.version_number,
                           c.id AS chunk_id, c.content, c.section_path
                    FROM documents d
                    JOIN document_versions dv ON dv.document_id = d.id
                    JOIN chunks c ON c.document_version_id = dv.id
                    WHERE d.id = %s AND d.tenant_id = %s AND dv.status = 'ready'
                      AND c.chunk_level = 'parent' AND d.access_scope = ANY(%s)
                      AND (d.access_scope <> 'private' OR d.owner_id = %s)
                      AND NOT EXISTS (
                          SELECT 1 FROM document_versions newer
                          WHERE newer.document_id = dv.document_id AND newer.status = 'ready'
                            AND newer.version_number > dv.version_number
                      )
                    ORDER BY c.chunk_index
                    LIMIT %s
                    """,
                    (document_id, tenant_id, list(allowed_scopes), user_id, limit),
                )
                rows = cursor.fetchall()
        return [
            (
                GraphSource(
                    str(row["document_id"]),
                    str(row["chunk_id"]),
                    row["source_name"],
                    row["content"],
                    tuple(row["section_path"] or ()),
                    str(row["version_id"]),
                    int(row["version_number"]),
                ),
                row["owner_id"],
                row["access_scope"],
            )
            for row in rows
        ]

    def ingest(
        self,
        result: ChunkedDocument,
        embeddings: Sequence[Sequence[float]],
        tenant_id: str,
        owner_id: str,
        access_scope: str,
    ) -> IngestionResult:
        if len(embeddings) != len(result.children):
            raise ValueError("Every child chunk must have exactly one embedding")
        document = result.document
        source_type = Path(document.filename).suffix.lower().lstrip(".")
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, checksum_sha256 FROM documents "
                    "WHERE tenant_id = %s AND source_name = %s FOR UPDATE",
                    (tenant_id, document.filename),
                )
                existing = cursor.fetchone()
                if existing and existing["checksum_sha256"] == document.checksum_sha256:
                    cursor.execute(
                        "SELECT id FROM document_versions WHERE document_id = %s "
                        "AND status = 'ready' ORDER BY version_number DESC LIMIT 1",
                        (existing["id"],),
                    )
                    version = cursor.fetchone()
                    if version:
                        return IngestionResult(
                            str(existing["id"]),
                            str(version["id"]),
                            document.filename,
                            len(result.parents),
                            len(result.children),
                            True,
                        )

                if existing:
                    document_id = existing["id"]
                    cursor.execute(
                        "UPDATE documents SET checksum_sha256 = %s, source_type = %s, "
                        "access_scope = %s, owner_id = %s, updated_at = NOW() WHERE id = %s",
                        (
                            document.checksum_sha256,
                            source_type,
                            access_scope,
                            owner_id,
                            document_id,
                        ),
                    )
                else:
                    document_id = uuid.uuid4()
                    cursor.execute(
                        "INSERT INTO documents "
                        "(id, tenant_id, source_name, source_type, checksum_sha256, "
                        "access_scope, owner_id, metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            document_id,
                            tenant_id,
                            document.filename,
                            source_type,
                            document.checksum_sha256,
                            access_scope,
                            owner_id,
                            Jsonb({"media_type": document.media_type}),
                        ),
                    )

                cursor.execute(
                    "SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version "
                    "FROM document_versions WHERE document_id = %s",
                    (document_id,),
                )
                version_number = cursor.fetchone()["next_version"]
                version_id = uuid.uuid4()
                cursor.execute(
                    "INSERT INTO document_versions "
                    "(id, document_id, version_number, checksum_sha256, parser_version, status) "
                    "VALUES (%s,%s,%s,%s,%s,'processing')",
                    (version_id, document_id, version_number, document.checksum_sha256, "0.3.0"),
                )

                parent_ids: dict[str, uuid.UUID] = {}
                for chunk in result.parents:
                    database_id = uuid.uuid4()
                    parent_ids[chunk.chunk_id] = database_id
                    self._insert_chunk(
                        cursor, database_id, version_id, tenant_id, chunk, None, None
                    )
                for chunk, embedding in zip(result.children, embeddings, strict=True):
                    self._insert_chunk(
                        cursor,
                        uuid.uuid4(),
                        version_id,
                        tenant_id,
                        chunk,
                        parent_ids[chunk.parent_chunk_id],
                        embedding,
                    )
                cursor.execute(
                    "UPDATE document_versions SET status = 'ready' WHERE id = %s", (version_id,)
                )
                self._event(
                    cursor,
                    tenant_id,
                    str(document_id),
                    owner_id,
                    "uploaded",
                    {"version_id": str(version_id), "filename": document.filename},
                )
            connection.commit()
        return IngestionResult(
            str(document_id),
            str(version_id),
            document.filename,
            len(result.parents),
            len(result.children),
            False,
        )

    def _insert_chunk(
        self,
        cursor,
        database_id: uuid.UUID,
        version_id: uuid.UUID,
        tenant_id: str,
        chunk,
        parent_id: uuid.UUID | None,
        embedding: Sequence[float] | None,
    ) -> None:
        cursor.execute(
            "INSERT INTO chunks (id, document_version_id, tenant_id, chunk_index, "
            "chunk_level, deterministic_id, parent_chunk_id, content, section_path, "
            "page_number, page_numbers, token_count, metadata, embedding) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)",
            (
                database_id,
                version_id,
                tenant_id,
                chunk.chunk_index,
                chunk.level,
                chunk.chunk_id,
                parent_id,
                chunk.content,
                list(chunk.section_path),
                chunk.page_numbers[0] if chunk.page_numbers else None,
                list(chunk.page_numbers),
                chunk.token_count,
                Jsonb(chunk.metadata),
                _vector_literal(embedding) if embedding is not None else None,
            ),
        )

    def vector_candidates(
        self,
        embedding: Sequence[float],
        tenant_id: str,
        user_id: str,
        allowed_scopes: Sequence[str],
        limit: int,
    ) -> list[Candidate]:
        sql = """
            SELECT c.id, d.id AS document_id, d.source_name, c.content,
                   p.content AS parent_content, c.section_path, c.page_numbers,
                   1 - (c.embedding <=> %(embedding)s::vector) AS raw_score
            FROM chunks c
            JOIN document_versions dv ON dv.id = c.document_version_id
            JOIN documents d ON d.id = dv.document_id
            LEFT JOIN chunks p ON p.id = c.parent_chunk_id
            WHERE c.tenant_id = %(tenant_id)s AND c.chunk_level = 'child'
              AND dv.status = 'ready' AND d.access_scope = ANY(%(scopes)s)
              AND (d.access_scope <> 'private' OR d.owner_id = %(user_id)s)
              AND NOT EXISTS (
                  SELECT 1 FROM document_versions newer
                  WHERE newer.document_id = dv.document_id AND newer.status = 'ready'
                    AND newer.version_number > dv.version_number
              )
              AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %(embedding)s::vector
            LIMIT %(limit)s
        """
        return self._candidates(
            sql,
            {
                "embedding": _vector_literal(embedding),
                "tenant_id": tenant_id,
                "user_id": user_id,
                "scopes": list(allowed_scopes),
                "limit": limit,
            },
        )

    def keyword_candidates(
        self,
        query: str,
        tenant_id: str,
        user_id: str,
        allowed_scopes: Sequence[str],
        limit: int,
    ) -> list[Candidate]:
        sql = """
            SELECT c.id, d.id AS document_id, d.source_name, c.content,
                   p.content AS parent_content, c.section_path, c.page_numbers,
                   ts_rank_cd(c.search_vector, websearch_to_tsquery('english', %(query)s))
                   AS raw_score
            FROM chunks c
            JOIN document_versions dv ON dv.id = c.document_version_id
            JOIN documents d ON d.id = dv.document_id
            LEFT JOIN chunks p ON p.id = c.parent_chunk_id
            WHERE c.tenant_id = %(tenant_id)s AND c.chunk_level = 'child'
              AND dv.status = 'ready' AND d.access_scope = ANY(%(scopes)s)
              AND (d.access_scope <> 'private' OR d.owner_id = %(user_id)s)
              AND NOT EXISTS (
                  SELECT 1 FROM document_versions newer
                  WHERE newer.document_id = dv.document_id AND newer.status = 'ready'
                    AND newer.version_number > dv.version_number
              )
              AND c.search_vector @@ websearch_to_tsquery('english', %(query)s)
            ORDER BY raw_score DESC
            LIMIT %(limit)s
        """
        return self._candidates(
            sql,
            {
                "query": query,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "scopes": list(allowed_scopes),
                "limit": limit,
            },
        )

    def _candidates(self, sql: str, parameters: dict) -> list[Candidate]:
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, parameters)
                rows = cursor.fetchall()
        return [
            Candidate(
                chunk_id=str(row["id"]),
                document_id=str(row["document_id"]),
                source_name=row["source_name"],
                content=row["content"],
                parent_content=row["parent_content"],
                section_path=tuple(row["section_path"] or ()),
                page_numbers=tuple(row["page_numbers"] or ()),
                raw_score=float(row["raw_score"]),
            )
            for row in rows
        ]
