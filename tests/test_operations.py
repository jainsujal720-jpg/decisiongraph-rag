from decisiongraph.generation.models import AnswerResult, ConfidenceScore
from decisiongraph.operations.security import FixedWindowRateLimiter, RedisFixedWindowRateLimiter
from decisiongraph.operations.service import EvaluationService
from decisiongraph.operations.store import PostgresOperationsStore


class FakeAnswerService:
    def answer(self, question, *_args):
        if "budget" in question.casefold():
            return AnswerResult(
                question,
                "I don't have enough verified evidence to answer that safely.",
                "abstained",
                ConfidenceScore(0.0, 0.0, 0.0, 0.0, "low"),
                (),
                (),
                "hybrid",
                "Fallback retrieval.",
            )
        return AnswerResult(
            question,
            "Priya Shah owns payment reliability. [E1]",
            "answered",
            ConfidenceScore(0.9, 0.8, 1.0, 1.0, "high"),
            (),
            ({"source_name": "atlas.md"},),
            "hybrid",
            "Relationship and detail.",
        )


def test_evaluation_reports_decision_answer_and_source_metrics():
    report = EvaluationService(FakeAnswerService()).run(
        [
            {
                "question": "Who owns payment reliability?",
                "expected_decision": "answered",
                "expected_terms": ["Priya Shah"],
                "expected_source": "atlas.md",
            },
            {
                "question": "What budget was approved?",
                "expected_decision": "abstained",
                "expected_terms": ["enough verified evidence"],
            },
        ],
        "acme",
        "u1",
        ["team"],
        8,
    )
    assert report.case_count == 2
    assert report.decision_accuracy == 1.0
    assert report.answer_accuracy == 1.0
    assert report.source_hit_rate == 1.0


def test_fixed_window_rate_limiter_enforces_a_limit():
    limiter = FixedWindowRateLimiter(max_requests=2, window_seconds=60)
    assert limiter.allow("client") is True
    assert limiter.allow("client") is True
    assert limiter.allow("client") is False
    assert limiter.allow("another-client") is True


def test_redis_rate_limiter_uses_one_atomic_counter(monkeypatch):
    class Pipeline:
        def __init__(self):
            self.count = 0

        def incr(self, _key):
            self.count += 1
            return self

        def expire(self, *_args):
            return self

        def execute(self):
            return [self.count, True]

    class Client:
        def __init__(self):
            self.pipeline_value = Pipeline()

        def pipeline(self):
            return self.pipeline_value

    from decisiongraph.operations import security

    monkeypatch.setattr(security.redis, "from_url", lambda *_args, **_kwargs: Client())
    limiter = RedisFixedWindowRateLimiter("redis://example", max_requests=2)
    assert limiter.allow("sujal") is True
    assert limiter.allow("sujal") is True
    assert limiter.allow("sujal") is False


def test_operations_store_aggregates_tenant_metrics(monkeypatch):
    class Cursor:
        def __init__(self):
            self.rows = [
                {
                    "total_queries": 3,
                    "answered_queries": 2,
                    "abstained_queries": 1,
                    "average_latency_ms": 120.125,
                    "average_confidence": 0.75,
                },
                {"pending_reviews": 1},
            ]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args):
            return None

        def fetchone(self):
            return self.rows.pop(0)

    class Connection:
        def __init__(self):
            self.cursor_value = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self):
            return self.cursor_value

    from decisiongraph.operations import store

    monkeypatch.setattr(store.psycopg, "connect", lambda *_args, **_kwargs: Connection())
    metrics = PostgresOperationsStore("postgresql://example").metrics("acme")
    assert metrics.total_queries == 3
    assert metrics.average_latency_ms == 120.12
    assert metrics.pending_reviews == 1
