import hashlib
import json
from typing import Protocol

import psycopg


class EventStore(Protocol):
    def add(self, event: dict) -> None: ...

    def add_usage(self, usage: dict) -> None: ...

    def metrics(self, tenant_id: str) -> dict: ...

    def total_cost(self, tenant_id: str) -> float: ...

    def verify_integrity(self, tenant_id: str) -> dict: ...

    def evidence_events(self, tenant_id: str) -> list[dict]: ...


class PostgresAuditStore:
    """Append-only gateway audit ledger, persisted outside the API container."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        # Separate telemetry leaves the existing signed hash-chain payload intact.
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute("""
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
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS gateway_usage_tenant_idx ON gateway_usage(tenant_id)"
            )

    def add_usage(self, usage: dict) -> None:
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO gateway_usage
                    (request_id, tenant_id, model, input_tokens,
                     cached_input_tokens, output_tokens, token_cost_usd,
                     routing_source, jev_mode, jev_class, jev_cost_usd)
                VALUES (%(request_id)s, %(tenant_id)s, %(model)s, %(input_tokens)s,
                        %(cached_input_tokens)s, %(output_tokens)s, %(token_cost_usd)s,
                        %(routing_source)s, %(jev_mode)s, %(jev_class)s, %(jev_cost_usd)s)
            """,
                usage,
            )

    def add(self, event: dict) -> None:
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (event["tenant_id"],))
            cursor.execute(
                "SELECT ledger_hash FROM gateway_events WHERE tenant_id = %s "
                "ORDER BY ledger_sequence DESC LIMIT 1",
                (event["tenant_id"],),
            )
            row = cursor.fetchone()
            previous_hash = row[0] if row else "GENESIS"
            ledger_hash = self._hash_event(event, previous_hash)
            cursor.execute(
                """
                INSERT INTO gateway_events
                    (request_id, tenant_id, user_id, primary_model, served_by,
                     fallback_used, cost_usd, previous_hash, ledger_hash)
                VALUES (%(request_id)s, %(tenant_id)s, %(user_id)s, %(primary_model)s,
                        %(served_by)s, %(fallback_used)s, %(cost_usd)s,
                        %(previous_hash)s, %(ledger_hash)s)
                """,
                {**event, "previous_hash": previous_hash, "ledger_hash": ledger_hash},
            )

    def metrics(self, tenant_id: str) -> dict:
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*), COUNT(*) FILTER (WHERE fallback_used), COALESCE(SUM(cost_usd), 0)
                FROM gateway_events WHERE tenant_id = %s
                """,
                (tenant_id,),
            )
            requests, fallbacks, total_cost = cursor.fetchone()
            cursor.execute(
                """
                SELECT served_by, COUNT(*) FROM gateway_events
                WHERE tenant_id = %s GROUP BY served_by
                """,
                (tenant_id,),
            )
            models = dict(cursor.fetchall())
            cursor.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(token_cost_usd), 0)
                FROM gateway_usage WHERE tenant_id = %s
            """,
                (tenant_id,),
            )
            measured_requests, token_cost = cursor.fetchone()
            return {
                "requests": requests,
                "fallbacks": fallbacks,
                "total_cost_usd": float(total_cost),
                "models_used": models,
                "measured_requests": measured_requests,
                "token_cost_usd": float(token_cost),
            }

    def total_cost(self, tenant_id: str) -> float:
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM gateway_events WHERE tenant_id = %s",
                (tenant_id,),
            )
            return float(cursor.fetchone()[0])

    def verify_integrity(self, tenant_id: str) -> dict:
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT request_id, tenant_id, user_id, primary_model, served_by, fallback_used,
                       cost_usd, previous_hash, ledger_hash
                FROM gateway_events WHERE tenant_id = %s ORDER BY ledger_sequence
                """,
                (tenant_id,),
            )
            previous_hash = "GENESIS"
            checked = 0
            for row in cursor.fetchall():
                event = {
                    "request_id": str(row[0]),
                    "tenant_id": row[1],
                    "user_id": row[2],
                    "primary_model": row[3],
                    "served_by": row[4],
                    "fallback_used": row[5],
                    "cost_usd": float(row[6]),
                }
                if row[7] != previous_hash or row[8] != self._hash_event(event, previous_hash):
                    return {"tenant_id": tenant_id, "verified": False, "events_checked": checked}
                previous_hash = row[8]
                checked += 1
            return {
                "tenant_id": tenant_id,
                "verified": True,
                "events_checked": checked,
                "head_hash": previous_hash,
            }

    def evidence_events(self, tenant_id: str) -> list[dict]:
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT request_id, user_id, primary_model, served_by, fallback_used, cost_usd,
                       created_at, ledger_hash
                FROM gateway_events WHERE tenant_id = %s ORDER BY ledger_sequence
                """,
                (tenant_id,),
            )
            return [
                {
                    "request_id": str(row[0]),
                    "user_id": row[1],
                    "primary_model": row[2],
                    "served_by": row[3],
                    "fallback_used": row[4],
                    "cost_usd": float(row[5]),
                    "created_at": row[6].isoformat(),
                    "ledger_hash": row[7],
                }
                for row in cursor.fetchall()
            ]

    @staticmethod
    def _hash_event(event: dict, previous_hash: str) -> str:
        payload = {
            key: event[key]
            for key in (
                "request_id",
                "tenant_id",
                "user_id",
                "primary_model",
                "served_by",
                "fallback_used",
                "cost_usd",
            )
        }
        encoded = json.dumps(
            {"previous_hash": previous_hash, "event": payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode()).hexdigest()
