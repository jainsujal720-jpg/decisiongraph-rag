# Stage 11 — RelayGuard integration

Stage 11 places RelayGuard between DecisionGraph's evidence-grounded answer workflow and the LLM.
The gateway receives the same `tenant_id` and `user_id` used by DecisionGraph, so its rate limits,
budgets, fallback records and audit trail remain tenant-scoped.

The gateway supports the following workload policy. The `task_class` values can be supplied
explicitly to its chat endpoint; without one, a size/keyword heuristic chooses a class.

| Task class | Primary | Fallback |
| --- | --- | --- |
| `simple` | GPT-4.1 Mini | GPT-5.6 Luna |
| `moderate` | GPT-5.6 Luna | GPT-4.1 Mini |
| `involved` | GPT-5.6 Terra | GPT-5.6 Luna |
| `complex` | GPT-5.6 Sol | GPT-5.6 Terra |
| `heavy` | GPT-6 Sol | GPT-5.6 Sol |
| `long_context` | GPT-6 Luna | GPT-5.6 Terra |

DecisionGraph's draft class depends on question complexity and retrieved evidence length.
Its citation-verification pass uses `involved` normally and `heavy` when evidence exceeds 8500
characters. A short factual question routes through GPT-5.6 Luna for drafting and GPT-5.6 Terra
for verification, subject to fallbacks. The chat response includes `served_model` to distinguish
the provider model from the gateway route label.

GPT-5.6 and GPT-6 calls use low reasoning effort without `temperature`. An API key must have
access to the models. The displayed USD cost remains a prototype word-count estimate,
not provider-billed token usage; treat the budget display accordingly.

## What is governed

1. DecisionGraph retrieves authorized graph and passage evidence.
2. The answer draft is sent to `relayguard-api` with a strict JSON schema.
3. RelayGuard routes by the selected task class, applies input policy and records the request.
4. DecisionGraph verifies every cited claim through a second governed RelayGuard request.
5. DecisionGraph rejects unsupported claims, calculates confidence and creates human review items
   when required.

Embeddings and graph extraction are deliberately unchanged. They are not chat completions and must
continue to use the configured OpenAI key until RelayGuard gains a governed embeddings endpoint.

## Run

```bash
cp .env.example .env
# Add OPENAI_API_KEY and set RELAYGUARD_PROVIDER_MODE=openai in .env
docker compose up --build -d
docker compose ps
curl http://localhost:8000/health/ready
curl http://localhost:8100/health/live
```

## Verify the integration

After making a normal `POST /v1/answers` request, inspect RelayGuard's tenant metrics:

```bash
curl 'http://localhost:8100/v1/metrics?tenant_id=acme'
```

One successful DecisionGraph answer normally creates two gateway events: one for drafting and one
for citation verification. The generated answer is still accepted only if its claims pass
DecisionGraph's local evidence checks.

## Security note

Local Compose starts RelayGuard with authentication off to keep the existing DecisionGraph local
workflow friction-free. For a shared deployment set `RELAYGUARD_AUTH_MODE=api_key`, configure a
tenant-key mapping and set the matching `RELAYGUARD_API_KEY` in DecisionGraph.
