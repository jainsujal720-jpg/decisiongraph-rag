# Stage 9 guide — controlled audit evidence export

Stage 9 turns the verified audit chain into a review-ready evidence bundle.
The bundle is tenant-scoped and includes chain verification plus the routing,
fallback, cost, timestamp, and ledger hash for each completed request.

## Demonstrate authorization

1. Run the stack and open `http://localhost:3100`.
2. Change the API key to `demo-acme-viewer-key`.
3. Click **Generate evidence bundle**.

The API returns `403 This governed action requires an operator role.`

Then switch to `demo-acme-operator-key` and click the button again. The panel
shows a verified bundle and event count.

The endpoint is `GET /v1/audit/evidence?tenant_id=acme`. It requires the
tenant's matching operator API key. In production, this bundle would be sent to
an approved compliance store instead of rendering the evidence directly.
