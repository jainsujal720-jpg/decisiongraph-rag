# Stage 1 — Core LLM Gateway

RelayGuard is the controlled API between an application and LLM providers.

1. A request first passes the policy guard.
2. The router classifies it as simple or complex.
3. The appropriate primary model is selected.
4. If that model fails, the approved backup is used automatically.
5. The request outcome, model, fallback state, and estimated cost are audited.

Mock providers make these decisions testable without exposing API keys or
spending money. They will be replaced by real provider adapters after the
governance and reliability behaviors are proven.
