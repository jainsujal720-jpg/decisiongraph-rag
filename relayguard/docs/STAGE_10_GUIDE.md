# Stage 10 guide — governance risk signals

Stage 10 transforms audit, budget, fallback, and circuit observations into
operator-facing risk signals. It does not invent production monitoring claims:
the alerts are calculated from this local gateway's real demo events.

## Demonstrate an alert

1. Run the stack and open `http://localhost:3100` using the default operator key.
2. Enable **Simulate primary-model failure**.
3. Submit one request.

The request safely falls back to `relay-backup`. The **Governance alerts** panel
then reports that the fallback rate is at least 25%. A second simulated failure
also opens the shared `relay-mini` circuit, which creates an additional circuit
alert.

Signals require an operator key because they reveal tenant operational status.
They are available from `GET /v1/governance/signals?tenant_id=acme`.
