import json
import uuid
from collections.abc import Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from decisiongraph.operations.models import OperationsMetrics, ReviewItem


class PostgresOperationsStore:
    def __init__(self, postgres_url: str):
        self.postgres_url = postgres_url

    def record_answer(
        self,
        tenant_id: str,
        user_id: str,
        question: str,
        route: str,
        decision: str,
        latency_ms: int,
        chunk_ids: Sequence[str],
        scores: dict,
    ) -> str:
        event_id = uuid.uuid4()
        with psycopg.connect(self.postgres_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO query_events
                    (id, tenant_id, user_id, question, route, decision, latency_ms,
                     retrieved_chunk_ids, scores)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        event_id,
                        tenant_id,
                        user_id,
                        question,
                        route,
                        decision,
                        latency_ms,
                        [uuid.UUID(chunk_id) for chunk_id in chunk_ids],
                        Jsonb(scores),
                    ),
                )
        return str(event_id)

    def create_review(
        self,
        event_id: str | None,
        tenant_id: str,
        requester_id: str,
        question: str,
        reason: str,
        proposed_answer: str | None,
        confidence: dict,
    ) -> ReviewItem:
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO review_queue
                    (query_event_id, tenant_id, requester_id, question, reason,
                     proposed_answer, confidence)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    RETURNING *
                    """,
                    (
                        uuid.UUID(event_id) if event_id else None,
                        tenant_id,
                        requester_id,
                        question,
                        reason,
                        proposed_answer,
                        Jsonb(confidence),
                    ),
                )
                row = cursor.fetchone()
        return self._review_item(row)

    def list_reviews(self, tenant_id: str, review_status: str, limit: int) -> list[ReviewItem]:
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM review_queue
                    WHERE tenant_id = %s AND status = %s
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (tenant_id, review_status, limit),
                )
                rows = cursor.fetchall()
        return [self._review_item(row) for row in rows]

    def resolve_review(
        self,
        review_id: str,
        tenant_id: str,
        reviewer_id: str,
        outcome: str,
        notes: str | None,
    ) -> ReviewItem | None:
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE review_queue
                    SET status = %s, reviewer_id = %s, resolution_notes = %s, resolved_at = NOW()
                    WHERE id = %s AND tenant_id = %s AND status = 'pending'
                    RETURNING *
                    """,
                    (outcome, reviewer_id, notes, uuid.UUID(review_id), tenant_id),
                )
                row = cursor.fetchone()
        return self._review_item(row) if row else None

    def metrics(self, tenant_id: str) -> OperationsMetrics:
        with psycopg.connect(self.postgres_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS total_queries,
                           COUNT(*) FILTER (WHERE decision = 'answered') AS answered_queries,
                           COUNT(*) FILTER (WHERE decision = 'abstained') AS abstained_queries,
                           AVG(latency_ms) AS average_latency_ms,
                           AVG((scores ->> 'overall')::double precision) AS average_confidence
                    FROM query_events WHERE tenant_id = %s
                    """,
                    (tenant_id,),
                )
                query_metrics = cursor.fetchone()
                cursor.execute(
                    "SELECT COUNT(*) AS pending_reviews FROM review_queue "
                    "WHERE tenant_id = %s AND status = 'pending'",
                    (tenant_id,),
                )
                review_metrics = cursor.fetchone()
        return OperationsMetrics(
            tenant_id,
            int(query_metrics["total_queries"]),
            int(query_metrics["answered_queries"]),
            int(query_metrics["abstained_queries"]),
            round(float(query_metrics["average_latency_ms"]), 2)
            if query_metrics["average_latency_ms"] is not None
            else None,
            round(float(query_metrics["average_confidence"]), 4)
            if query_metrics["average_confidence"] is not None
            else None,
            int(review_metrics["pending_reviews"]),
        )

    @staticmethod
    def _review_item(row: dict) -> ReviewItem:
        confidence = row["confidence"]
        if isinstance(confidence, str):
            confidence = json.loads(confidence)
        return ReviewItem(
            str(row["id"]),
            str(row["query_event_id"]) if row["query_event_id"] else None,
            row["tenant_id"],
            row["requester_id"],
            row["question"],
            row["reason"],
            row["status"],
            row["proposed_answer"],
            confidence,
            row["reviewer_id"],
            row["resolution_notes"],
            row["created_at"].isoformat(),
            row["resolved_at"].isoformat() if row["resolved_at"] else None,
        )
