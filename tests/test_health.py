from decisiongraph.core.config import Settings
from decisiongraph.infrastructure.health import (
    ComponentHealth,
    _timed_check,
    check_neo4j,
    check_postgres,
    check_redis,
    readiness_report,
)


def test_readiness_is_degraded_when_any_component_fails(monkeypatch):
    up = ComponentHealth("service", "up", 1.0)
    down = ComponentHealth("service", "down", 1.0, "ConnectionError")
    monkeypatch.setattr("decisiongraph.infrastructure.health.check_postgres", lambda _: up)
    monkeypatch.setattr("decisiongraph.infrastructure.health.check_neo4j", lambda _: down)
    monkeypatch.setattr("decisiongraph.infrastructure.health.check_redis", lambda _: up)

    report = readiness_report(Settings())
    assert report["status"] == "degraded"
    assert [item["status"] for item in report["components"]] == ["up", "down", "up"]


def test_timed_check_converts_exceptions_to_safe_health_details():
    def fail():
        raise RuntimeError("database URL must not be exposed")

    result = _timed_check("database", fail)
    assert result.status == "down"
    assert result.detail == "RuntimeError"
    assert "database URL" not in repr(result)


def test_postgres_check_executes_probe(monkeypatch):
    events = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, statement):
            events.append(statement)

        def fetchone(self):
            return (1,)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(
        "decisiongraph.infrastructure.health.psycopg.connect", lambda *a, **k: Connection()
    )
    result = check_postgres(Settings())
    assert result.status == "up"
    assert events == ["SELECT 1"]


def test_neo4j_and_redis_checks_close_connections(monkeypatch):
    events = []

    class Driver:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("neo4j-closed")

        def verify_connectivity(self):
            events.append("neo4j-ping")

    class RedisClient:
        def ping(self):
            events.append("redis-ping")

        def close(self):
            events.append("redis-closed")

    monkeypatch.setattr(
        "decisiongraph.infrastructure.health.GraphDatabase.driver", lambda *a, **k: Driver()
    )
    monkeypatch.setattr(
        "decisiongraph.infrastructure.health.redis.Redis.from_url",
        lambda *a, **k: RedisClient(),
    )

    assert check_neo4j(Settings()).status == "up"
    assert check_redis(Settings()).status == "up"
    assert events == ["neo4j-ping", "neo4j-closed", "redis-ping", "redis-closed"]
