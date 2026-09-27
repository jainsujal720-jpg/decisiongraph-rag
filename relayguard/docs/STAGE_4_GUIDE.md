# RelayGuard Stage 4 — Observable Circuit Recovery

Stage 3 added a circuit breaker. Stage 4 makes that safety mechanism visible to a
reviewer, so the team can see when RelayGuard has stopped sending requests to an
unhealthy provider and when it will attempt recovery.

## What to test

1. Start the stack with `docker compose up --build -d`.
2. Open `http://localhost:3100`.
3. In **Provider resilience**, all circuits begin **closed**.
4. Enable **Simulate primary-model failure** and send two requests for the same task.
5. The relevant primary circuit becomes **open**. A recovery countdown appears.
6. Send another request while the circuit is open. RelayGuard chooses
   `relay-backup` immediately, avoiding a call to the unhealthy primary.
7. After 30 seconds, refresh the page. The circuit returns to **closed**.

## Why this matters

A fallback alone reacts after a provider fails. A circuit breaker changes future
decisions: it stops repeatedly calling a provider that is already known to be
unhealthy. The status endpoint exposes only operational state—never provider keys,
prompts, or credentials.
