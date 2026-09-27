from collections.abc import Callable
from dataclasses import asdict, dataclass
from time import perf_counter

import psycopg
import redis
from neo4j import GraphDatabase

from decisiongraph.core.config import Settings


@dataclass(frozen=True)
class ComponentHealth:
    name: str
    status: str
    latency_ms: float
    detail: str | None = None


def _timed_check(name: str, check: Callable[[], None]) -> ComponentHealth:
    started = perf_counter()
    try:
        check()
        status, detail = "up", None
    except Exception as exc:  # Health endpoints must report failures instead of crashing.
        status = "down"
        detail = type(exc).__name__
    latency_ms = round((perf_counter() - started) * 1000, 2)
    return ComponentHealth(name, status, latency_ms, detail)


def check_postgres(settings: Settings) -> ComponentHealth:
    def check() -> None:
        with psycopg.connect(settings.postgres_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()

    return _timed_check("postgres", check)


def check_neo4j(settings: Settings) -> ComponentHealth:
    def check() -> None:
        with GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
            connection_timeout=2,
        ) as driver:
            driver.verify_connectivity()

    return _timed_check("neo4j", check)


def check_redis(settings: Settings) -> ComponentHealth:
    def check() -> None:
        client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        try:
            client.ping()
        finally:
            client.close()

    return _timed_check("redis", check)


def readiness_report(settings: Settings) -> dict:
    checks = [
        check_postgres(settings),
        check_neo4j(settings),
        check_redis(settings),
    ]
    return {
        "status": "ready" if all(item.status == "up" for item in checks) else "degraded",
        "components": [asdict(item) for item in checks],
    }
