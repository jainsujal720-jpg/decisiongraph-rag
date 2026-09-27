# Stage 6 guide — tenant API-key authentication

Stage 6 makes the gateway verify who is calling before it performs routing,
provider work, or audit writes. This prevents a caller for one tenant from
claiming another tenant's identity in a request payload.

## Run locally

```zsh
docker compose up --build -d
open http://localhost:3100
```

The dashboard pre-fills the local demo identity:

- Tenant: `acme`
- API key: `demo-acme-key`

Submit a normal request. It succeeds and the dashboard updates its metrics.

## Demonstrate tenant isolation

1. Leave the API key as `demo-acme-key`.
2. Change the tenant field to `globex`.
3. Submit the request.

The API returns `403 API key is not authorized for the requested tenant.` No
model provider is called and no request is added to the audit history.

Then change the API key to `demo-globex-key` and submit again. The same request
is now authorized for `globex`.

## API example

```zsh
curl -s -X POST http://localhost:8100/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: demo-acme-key' \
  -d '{"tenant_id":"acme","user_id":"sujal","prompt":"Summarize this note"}'
```

For production, replace the demonstration mapping with rotated, hashed
credentials from a secrets manager. Never put a provider key in the browser.
