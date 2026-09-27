# Stage 7 guide — role-based authorization

Stage 7 adds authorization after tenant authentication. Each API key now maps
to a tenant and a role. A `viewer` can make ordinary governed requests, while
an `operator` can also perform requests explicitly marked as privileged.

## Run

```zsh
docker compose up --build -d
open http://localhost:3100
```

The dashboard starts as `acme` using `demo-acme-operator-key` and shows the
authenticated role in the Caller identity panel.

## Demonstrate the policy

1. Replace the API key with `demo-acme-viewer-key`.
2. Select **Mark as a privileged governed action**.
3. Click **Route safely**.

The API returns `403 This governed action requires an operator role.` before
routing or audit writes occur.

Then replace the API key with `demo-acme-operator-key` and submit the same
privileged request again. It succeeds.

The keys are fake local demonstration credentials. In production, use a
central identity provider and short-lived credentials rather than this local
configuration map.
