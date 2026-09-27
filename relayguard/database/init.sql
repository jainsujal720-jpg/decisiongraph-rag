CREATE TABLE IF NOT EXISTS gateway_events (
    ledger_sequence BIGSERIAL UNIQUE,
    request_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    primary_model TEXT NOT NULL,
    served_by TEXT NOT NULL,
    fallback_used BOOLEAN NOT NULL,
    cost_usd NUMERIC(12, 6) NOT NULL,
    previous_hash TEXT NOT NULL DEFAULT 'GENESIS',
    ledger_hash TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS gateway_events_tenant_created_idx
    ON gateway_events (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS gateway_events_tenant_ledger_idx
    ON gateway_events (tenant_id, ledger_sequence);

CREATE TABLE IF NOT EXISTS gateway_usage (
    request_id UUID PRIMARY KEY REFERENCES gateway_events(request_id),
    tenant_id TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    cached_input_tokens INTEGER,
    output_tokens INTEGER NOT NULL,
    token_cost_usd NUMERIC(15, 9) NOT NULL,
    routing_source TEXT NOT NULL,
    jev_mode TEXT NOT NULL,
    jev_class TEXT,
    jev_cost_usd NUMERIC(15, 9)
);
CREATE INDEX IF NOT EXISTS gateway_usage_tenant_idx ON gateway_usage(tenant_id);
