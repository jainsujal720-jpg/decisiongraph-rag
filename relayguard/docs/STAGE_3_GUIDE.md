# RelayGuard Stage 3 — Spend and Failure Controls

## The three new controls

1. **Budget guard**: before a request goes to a model, RelayGuard estimates its cost
   and checks the tenant's accumulated spend. A request that would exceed the budget
   is rejected with HTTP `429`; it is neither routed nor added as a completed audit event.
2. **Retry policy**: a real provider gets two additional attempts after a temporary
   provider failure. The timeout is configured server-side at eight seconds.
3. **Circuit breaker**: after two failed primary-provider requests, the primary's
   circuit opens for 30 seconds. During that window RelayGuard chooses the approved
   backup immediately.

## Why they are different

| Control | Problem it prevents | When it acts |
|---|---|---|
| Rate limit | Too many requests in one minute | Before routing |
| Budget limit | Too much accumulated cost | Before routing |
| Retry | A temporary upstream failure | During provider call |
| Circuit breaker | Repeating calls to a known failing provider | Before provider call |

## Safe demo settings

Stage 3 defaults to mock models and a `$0.05` tenant budget. No API key or money is
used. The dashboard displays each response's retries and remaining budget.

## Verify after starting

```zsh
curl -s 'http://localhost:8100/v1/budget?tenant_id=acme'
```

It returns the configured budget, spend, and remaining amount for that tenant.
