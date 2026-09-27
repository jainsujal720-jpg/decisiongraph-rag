# Stage 8 — Reviewer Dashboard

Stage 8 adds a production-style React dashboard without changing the evidence or governance rules from earlier stages. It calls the live FastAPI API; it does not invent demo responses or bypass server-side audit logic.

## What the dashboard does

- Shows `/health/ready` so an operator can see PostgreSQL, Neo4j and Redis status.
- Shows tenant-scoped operational metrics from `/v1/metrics`.
- Sends questions to `/v1/answers`, then renders the grounded answer, verified claims and source citations.
- Lists pending reviewer work from `/v1/reviews`.
- Lets a human approve or reject a pending review with notes through `/v1/reviews/{review_id}/resolve`.

## Security boundary

The browser dashboard can only call explicitly configured CORS origins. By default they are `http://localhost:3000` and `http://127.0.0.1:3000`. Set `CORS_ALLOW_ORIGINS` to a comma-separated allowlist before deploying it elsewhere.

The optional API key is held only in the running browser tab. It is not saved in local storage, source code or Docker configuration. The FastAPI backend still performs API-key enforcement, rate limiting and all audit/review writes.

## Run it

```bash
docker compose up --build -d
```

Then open `http://localhost:3000`. The API documentation remains at `http://localhost:8000/docs`.

## Manual reviewer workflow

1. Set tenant, user and allowed scopes in the sidebar.
2. Ask a question. An answered result must display citations and supported claims.
3. For an abstention or low-confidence result, open the pending review item.
4. Enter notes and approve only after independently verifying the evidence; otherwise reject.

## What can go wrong

- **Dashboard says it cannot reach the API:** verify Docker containers with `docker compose ps`; the API must be healthy before the dashboard can load data.
- **HTTP 401:** add the same value configured as `API_ACCESS_KEY` to the optional dashboard key field.
- **Browser CORS error:** add the dashboard's actual deployment origin to `CORS_ALLOW_ORIGINS`, rebuild, and never use an unrestricted wildcard for a privileged deployment.
- **A review item is not available:** it may have been resolved by another reviewer. Refresh the dashboard and preserve the audit history rather than overwriting it.

## Portfolio talking point

"The UI is deliberately a reviewer surface, not an opaque chat window: every answer exposes its route, citations, claim-verification result and operational state; risky outputs become auditable human decisions."
