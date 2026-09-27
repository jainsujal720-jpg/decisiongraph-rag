# RelayGuard Stage 5 — Shared Circuit State

Stage 5 moves circuit-breaker state from API memory into Redis. A provider failure
observed by one API process is therefore visible to every other process using the
same Redis instance.

## Demonstrate restart safety

1. Start the stack with `docker compose up --build -d`.
2. In the dashboard, enable **Simulate primary-model failure** and send two requests.
3. Confirm that `relay-mini` is **open** in **Shared provider resilience**.
4. In another terminal, run `docker compose restart api`.
5. Refresh the dashboard before the countdown expires.
6. The circuit still reads **open**. Send a request with failure simulation disabled:
   it is served by `relay-backup`.

## Why this changes the design

An in-memory circuit breaker resets when a process restarts. That can create a burst
of avoidable provider calls after a deploy. Redis gives all API replicas one shared
view of provider health and lets the recovery countdown continue independently of
the API process that originally detected the failure.
