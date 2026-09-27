# RelayGuard — Governed LLM Gateway

In the integrated DecisionGraph package, use `../docs/STAGE_11_GUIDE.md` for the expanded
six-class model policy. The examples below describe standalone RelayGuard Stage 10.

RelayGuard is one controlled API in front of AI models. It applies input policies,
routes simple requests to an economical model, sends complex requests to a higher
quality model, and uses an approved backup when the primary model is unavailable.

## Stage 10 capabilities

- `relay-mini` for simple tasks
- `relay-pro` for complex reasoning tasks
- `relay-backup` for simulated primary-provider failure
- input-size and private-key guardrails
- PostgreSQL-backed, tenant-aware request, cost, and fallback audit metrics
- Redis tenant rate limits (60 requests per minute by default)
- per-tenant spending budget checked before a model call
- provider retries, timeout configuration, and a circuit breaker for repeated failures
- live provider-circuit status: closed, open, failure count, and recovery countdown
- Redis-backed circuit state shared across API restarts and future replicas
- tenant-bound API-key authentication through `X-API-Key`
- cross-tenant requests rejected before routing or audit writes
- tenant-bound `viewer` and `operator` roles
- privileged governed actions blocked unless the caller is an operator
- a tenant-specific hash chain over completed audit events
- dashboard verification of the audit chain before it is displayed as intact
- operator-only tenant-scoped audit evidence bundles
- operator-only governance risk signals for fallback, budget, circuit, and audit integrity
- optional OpenAI provider adapter; the key stays in the API container, never in the dashboard
- local reviewer dashboard at `http://localhost:3100`
- local deterministic providers; no AI key or spend required

## Run

```zsh
docker compose up --build -d
curl http://localhost:8100/health/live
```

The API runs on port `8100`; the dashboard runs on `3100`. PostgreSQL uses `5440`
and Redis uses `6380` on your laptop to avoid colliding with DecisionGraph.

## Demonstrate fallback

```zsh
curl -s -X POST http://localhost:8100/v1/chat/completions \\
  -H 'Content-Type: application/json' \\
  -d '{"tenant_id":"acme","user_id":"sujal","prompt":"Summarize this note","simulate_primary_failure":true}'
```

The response reports `served_by: relay-backup` and `fallback_used: true`.

## Persistence demonstration

Run one request, restart only the API, then inspect metrics. The request count remains
because the event is stored in PostgreSQL rather than API memory:

```zsh
docker compose restart api
curl -s 'http://localhost:8100/v1/metrics?tenant_id=acme'
```

## Stage 3 resilience controls

Every tenant has a default `$0.05` budget in this demo. RelayGuard estimates the
cost before routing and rejects a request that would cross that limit. It does not
send the rejected request to a model or store it as a completed request.

For real providers, a request gets up to two retries after a transient provider
failure. After two failed primary-provider requests, its circuit opens for 30 seconds;
RelayGuard then uses the approved fallback immediately instead of wasting time on the
known-unhealthy primary.

## Stage 4: make resilience observable

The dashboard now shows the state of the circuit for each approved model. Send two
requests with **Simulate primary-model failure** enabled. The primary circuit opens;
subsequent requests skip it and use `relay-backup`. After 30 seconds, the circuit
automatically closes and the primary model can receive traffic again.

## Stage 5: keep safety state after a restart

Stage 4's circuit state lived inside one API process. Stage 5 stores it in Redis.
Open the `relay-mini` circuit with two simulated failures, then restart only the API:

```zsh
docker compose restart api
```

Refresh the dashboard immediately. `relay-mini` remains open and requests still use
the approved fallback until its countdown expires. This models how production systems
keep protective decisions consistent during deploys and across multiple API instances.

## Stage 6: prove tenant identity before routing

The local dashboard starts with the demo `acme` tenant and its demo key,
`demo-acme-key`. Every governed endpoint requires that key. The caller cannot
submit a request for another tenant: changing the tenant to `globex` while
keeping the `acme` key returns `403` before a model provider or audit store is
used. Switch to the demo `globex` key, `demo-globex-key`, to authorize that
tenant instead.

The demonstration keys are intentionally fake and local-only. In a real
deployment, inject rotated, hashed credentials from a secrets manager rather
than committing them to configuration.

## Stage 7: authorize sensitive actions by role

Stage 6 proves a caller belongs to a tenant. Stage 7 also determines what that
caller may do. Normal governed requests work for a `viewer`; requests marked as
privileged require an `operator`. The dashboard identifies the active role and
lets you test the policy with fake local keys:

- `demo-acme-viewer-key` — ordinary work only
- `demo-acme-operator-key` — ordinary and privileged work

This gives a concrete separation between authentication (who is calling) and
authorization (what the caller may do).

## Stage 8: make the audit trail tamper-evident

Every completed request is linked to the previous audit event for that tenant.
Changing a historical event breaks the hash chain, which the API exposes through
`GET /v1/audit/integrity`. The dashboard shows how many events were checked and
whether the ledger is intact. This preserves the existing PostgreSQL audit trail
while making unauthorized historical edits detectable.

## Stage 9: export verifiable audit evidence

An operator can now create a tenant-scoped evidence bundle containing the
verified chain status plus the request, routing, fallback, cost, timestamp, and
ledger-hash record for each completed event. Viewers are denied before any
evidence is returned. This models a controlled handoff to compliance or an
incident-review process.

## Stage 10: turn governance metrics into alerts

The dashboard now converts separate governance controls into an actionable
operator alert center. It raises attention when fallback use reaches 25%, a
tenant reaches 80% of its budget, a provider circuit is open, or ledger
verification fails. The signals remain tenant-scoped and operator-only.

## Optional real OpenAI provider

Leave `RELAYGUARD_PROVIDER_MODE=mock` for the free deterministic demo. To use a
real provider, set these **in `.env` only** and restart the stack:

```dotenv
RELAYGUARD_PROVIDER_MODE=openai
RELAYGUARD_OPENAI_API_KEY=your_key_here
```

RelayGuard maps simple work to `gpt-6-luna`, complex work to `gpt-6-sol`, and
falls back to `gpt-6-luna`. Never enter that key in the browser dashboard.
