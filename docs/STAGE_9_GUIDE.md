# Stage 9 — Production Security Controls

Stage 9 turns the earlier development-only API guardrails into deployable controls. It keeps the local dashboard workflow simple by default, but creates an explicit path to a protected shared deployment.

## Controls implemented

| Control | Local development | Shared deployment |
|---|---|---|
| Authentication | `AUTH_MODE=development` | `AUTH_MODE=jwt` validates a signed bearer JWT |
| Identity source | Request fields remain convenient for local learning | `sub`, `tenant_id`, `roles`, and `scope` come from token claims |
| Authorization | Open for local testing | Tenant isolation, subject matching, scope filtering, and least-privilege roles |
| Rate limiting | Process-local memory limiter | Redis atomic counter shared by all API replicas |
| Browser/API traceability | Request ID returned on every `/v1` response | Same request ID can be correlated with gateway and log records |
| Browser hardening | Security headers | Same security headers behind HTTPS and an approved gateway |

## Roles

- `reader` — search, retrieve evidence, and ask grounded questions.
- `editor` — ingest documents and enrich the knowledge graph.
- `reviewer` — view and resolve human-review items.
- `operator` — view metrics and run evaluations.
- `admin` — has all roles and may request all permitted scopes.

## Enable JWT mode locally

Use a **new, non-production** signing secret in `.env`; never reuse an OpenAI key or a real IdP secret.

```dotenv
AUTH_MODE=jwt
JWT_SIGNING_KEY=replace-with-a-long-local-test-secret
JWT_ISSUER=decisiongraph-local
JWT_AUDIENCE=decisiongraph-api
RATE_LIMIT_REQUESTS_PER_MINUTE=60
RATE_LIMIT_BACKEND=redis
```

Rebuild the containers. Then create a short-lived local testing token:

```bash
docker compose exec api python scripts/create_local_jwt.py
```

Paste that token into the dashboard's **Optional bearer token** field. The token expires after 15 minutes. In a real deployment, do not run the helper: configure validation details to match your company identity provider and issue tokens only through that provider.

The API explicitly permits the browser's `Authorization` header only from configured CORS origins. Keep this allowlist narrow when deploying the dashboard.

## Why the client can no longer impersonate another user

In JWT mode, the API compares the request's tenant and user values with signed `tenant_id` and `sub` claims. It also checks requested document scopes and required role. A browser changing `tenant_id=other-company` or `user_id=another-person` receives HTTP 403 instead of accessing another tenant's data.

## Redis rate-limit behavior

Each identity has a counter in a time window. `INCR` and `EXPIRE` execute atomically, so two API containers cannot both accidentally allow the same final request. This differs from the earlier in-memory limiter, which resets per process and cannot protect a scaled deployment.

## Deployment requirements that remain external

This project intentionally does not pretend to replace enterprise infrastructure. Before a real deployment, use an approved identity provider with asymmetric/JWKS validation, HTTPS/TLS termination, secret manager, private network/database access, centralized logs, retention policy, backups, and incident response. Keep OpenAI keys and signing keys server-side only.
