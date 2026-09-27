"""Idempotent PostgreSQL migrations for local and container deployments."""

import psycopg

from decisiongraph.core.config import get_settings

MIGRATIONS = (
    "ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS checksum_sha256 TEXT",
    "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunk_level TEXT NOT NULL DEFAULT 'child'",
    "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS deterministic_id TEXT",
    "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS page_numbers INTEGER[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_tenant_id_checksum_sha256_key",
    "ALTER TABLE chunks DROP CONSTRAINT IF EXISTS chunks_document_version_id_chunk_index_key",
    "CREATE UNIQUE INDEX IF NOT EXISTS documents_tenant_source_name_uidx "
    "ON documents (tenant_id, source_name)",
    "CREATE UNIQUE INDEX IF NOT EXISTS chunks_version_level_index_uidx "
    "ON chunks (document_version_id, chunk_level, chunk_index)",
    "CREATE INDEX IF NOT EXISTS chunks_parent_idx ON chunks (parent_chunk_id)",
    "CREATE INDEX IF NOT EXISTS query_events_tenant_created_idx "
    "ON query_events (tenant_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS review_queue (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        query_event_id UUID REFERENCES query_events(id) ON DELETE SET NULL,
        tenant_id TEXT NOT NULL,
        requester_id TEXT NOT NULL,
        question TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'approved', 'rejected')),
        proposed_answer TEXT,
        confidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        reviewer_id TEXT,
        resolution_notes TEXT,
        resolved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS review_queue_tenant_status_created_idx "
    "ON review_queue (tenant_id, status, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS document_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id TEXT NOT NULL,
        document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
        actor_id TEXT NOT NULL,
        action TEXT NOT NULL CHECK (action IN ('uploaded', 'reindexed', 'access_updated', 'deleted')),
        details JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS document_events_tenant_document_created_idx "
    "ON document_events (tenant_id, document_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS cloud_uploads (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        access_scope TEXT NOT NULL CHECK (access_scope IN ('private', 'team', 'company')),
        bucket TEXT NOT NULL,
        object_key TEXT NOT NULL UNIQUE,
        filename TEXT NOT NULL,
        content_type TEXT NOT NULL,
        checksum_sha256 TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('requested', 'processing', 'indexed', 'failed')),
        document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
        error_message TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS cloud_uploads_owner_idx "
    "ON cloud_uploads (tenant_id, owner_id, created_at DESC)",
)


def main() -> None:
    settings = get_settings()
    with psycopg.connect(settings.postgres_url) as connection:
        with connection.cursor() as cursor:
            for statement in MIGRATIONS:
                cursor.execute(statement)
        connection.commit()
    print("PostgreSQL schema migrations are ready.")


if __name__ == "__main__":
    main()
