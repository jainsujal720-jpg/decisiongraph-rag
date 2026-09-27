# RelayGuard Stage 2 — Durable Governance

## What changed

Stage 1 proved routing and fallback with data held in API memory. Stage 2 separates
short-lived processing from durable governance records:

- **API container**: applies input policy, model route, fallback, and returns an answer.
- **PostgreSQL**: stores each request's tenant, user, route, fallback status, and cost.
- **Redis**: counts requests per tenant in a rolling 60-second window.
- **Dashboard**: lets a reviewer send a safe mock request and inspect persisted metrics.

## Why this matters

Restarting the API loses its process memory, but it does not remove PostgreSQL's named
volume. Therefore `GET /v1/metrics?tenant_id=acme` still reports prior requests after
`docker compose restart api`.

## Run it

```zsh
docker compose up --build -d
curl http://localhost:8100/health/live
open http://localhost:3100
```

Use `acme` as tenant and `sujal` as user in the dashboard. It starts in mock mode and
does not call any external model or use an API key.

## Prove persistence

In a second terminal from this project folder:

```zsh
curl -s -X POST http://localhost:8100/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"acme","user_id":"sujal","prompt":"Summarize the release notes"}'
docker compose restart api
curl -s 'http://localhost:8100/v1/metrics?tenant_id=acme'
```

The request total remains after the API restart. Do not run `docker compose down -v`
unless you intentionally want to erase the Stage 2 database volume.

## Optional real model mode

The default is intentionally `mock`. When ready to spend against a real provider:

1. Copy `.env.example` to `.env`.
2. In `.env`, set `RELAYGUARD_PROVIDER_MODE=openai` and add
   `RELAYGUARD_OPENAI_API_KEY=...`.
3. Run `docker compose up --build -d` again.

The dashboard never receives this key. It talks only to the local API, which holds the
provider key server-side.

## What can go wrong

| Symptom | Likely reason | Fix |
|---|---|---|
| API unhealthy | PostgreSQL or Redis is still starting | wait 15 seconds, then run `docker compose ps` |
| Dashboard says API unavailable | API was not started or port 8100 is occupied | run `docker compose ps`; stop the conflicting app if needed |
| Metrics reset after `down -v` | Docker volume was deliberately deleted | expected; do not use `-v` for normal stopping |
| Real mode fails | API key is missing/invalid | keep mock mode or correct the server-side `.env` value |
| HTTP 429 | a tenant exceeded the 60/minute demo limit | wait one minute or increase the server setting |
