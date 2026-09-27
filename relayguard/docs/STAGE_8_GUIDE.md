# Stage 8 guide — tamper-evident audit ledger

Stage 8 links each tenant's completed audit events into a SHA-256 hash chain.
Every new event stores the previous event hash plus its own calculated hash. A
change to an earlier event changes the expected next hash, making the chain fail
verification.

## Run and verify

```zsh
docker compose up --build -d
open http://localhost:3100
```

The **Audit integrity** panel initially reports an intact empty chain. Submit a
governed request. The panel then reports **Verified hash chain · 1 event
checked**. Each additional completed request increases that number.

The integrity endpoint is tenant-scoped and still requires the tenant's API
key:

```zsh
curl -s 'http://localhost:8100/v1/audit/integrity?tenant_id=acme' \
  -H 'X-API-Key: demo-acme-operator-key'
```

This is a local demonstration of tamper evidence, not a substitute for a
write-once storage policy, access monitoring, or an external trust anchor.
