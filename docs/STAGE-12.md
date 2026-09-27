# Stage 12: Jev decisions and model visibility

Stage 11 connected DecisionGraph's answer drafting and citation verification to RelayGuard.
This stage instruments that connection and adds optional Jev routing without resetting data.

## Roles

- DecisionGraph retrieves permitted evidence and presents cited, verified answers.
- RelayGuard manages the approved model, tenant policy, rate limits, fallback, and audit.
- Jev is an optional external TypeSafe decision API. It selects a **task class** with
  confidence; it never writes an answer or verifies a citation. RelayGuard maps its
  chosen class to an approved GPT model.

## Stage 12A: one-screen visibility

Open http://localhost:3000 and ask `Who owns the payment-reliability workstream?`.
The cited answer should now have **Model decisions** listing the draft and verify
models separately. An evidence-free question can abstain before calling either model.
The standalone http://localhost:3100 gateway dashboard displays the actual model,
route, Jev choice, measured tokens, and both cost estimates on a direct request.

## Stage 12B: usage and workload check

RelayGuard returns `usage` with provider input and output tokens. The tenant metrics
include `measured_requests` and `token_cost_usd`. The new `gateway_usage` table is
created on startup even with an existing database volume. It does not alter the
original signed ledger hash format. **Usage telemetry itself is not hash chained.**

`cost_usd` and the budget meter are still the old word-count estimates.
`usage.token_cost_usd` uses measured tokens and a price table last checked
2026-09-26; it is an estimate, not the provider's invoice. It excludes failed
calls, retries, embeddings, document extraction, cache-write surcharges, and
future price changes. Jev's input-based estimate is separate in
`routing.jev_cost_usd`. Compare complete workloads using invoices too.

`scripts/atlas_cases.json` contains four demonstration questions. The script
checks expected decision, keywords, and source and prints route and cost traces.
Each report also records the actual answer, citation source names, and which
checks failed; inspect these before attributing a failure to routing. The
keyword checks are exact substring checks and can flag a valid paraphrase.
Reports can contain private answer text, so keep them in your local workspace.
Resolve baseline failures before turning on Jev so the comparison is meaningful.
After a retrieval check confirmed that Atlas's 98% payment retry passage reached
the drafter, we corrected a citation-format mismatch: prompts now request raw
labels (`E1`), and the answer service also normalizes bracketed labels (`[E1]`)
before validating and verifying them. Unknown labels still fail closed. Rerun
the failing question once on the rebuilt API to verify the live result.
Add representative company questions and human-reviewed ground truth before
drawing production conclusions. Each comparison run makes actual API calls.

## Stage 12C: Jev as an optional decision layer

Set `RELAYGUARD_JEV_MODE` to `off`, `shadow`, or `active`.
`off` requires no TypeSafe key and sends nothing to Jev.
`shadow` calls Jev and records its choice, while deterministic rules route the
model request. `active` can choose a route at least as strong as any task class
explicitly specified by DecisionGraph, once both confidence and selected-option
probability exceed 0.80. An invalid response, timeout, or uncertainty uses the
deterministic rules; model fallback still applies. The Jev model is pinned to
`jev-1.13.0` by default for repeatable comparisons.

Enabling Jev sends the request prompt, potentially including retrieved document
excerpts, to TypeSafe. Obtain approval for that data transfer where needed; keep
the key on the server. Jev classifies but cannot generate the final answer.

## Install and verify on your Mac

1. Unzip this Stage 12 package to a **new** folder and copy your working Stage 11
   `.env` into the new folder. The old folder remains your rollback copy.
2. From the new folder run `docker compose up -d --build` and `docker compose ps`.
   Wait for both APIs to be healthy. The Compose project and volumes remain
   `decisiongraph`, preserving the indexed data.
3. Open http://localhost:3000 and ask the payment-reliability ownership question.
   Confirm the answer cites `atlas_status.md` and shows both model calls.
4. Collect a baseline (requires the Atlas document to be indexed):

   `python3 scripts/compare_routing.py --label rules --output rules.json`

5. Obtain your Jev API key at https://console.typesafe.ai/ . In the **new** `.env`,
   set `TYPESAFE_API_KEY=...` and `RELAYGUARD_JEV_MODE=shadow`. Run
   `docker compose up -d --force-recreate relayguard-api api`. Ask the same
   question. Jev's choice should appear, with routing source still `rules`.
6. When ready to evaluate live choices, set `RELAYGUARD_JEV_MODE=active`, recreate
   both APIs again, then run:

   `python3 scripts/compare_routing.py --label jev --output jev.json --compare rules.json`

   Examine errors, passing answers, citations, and the **combined** GPT and Jev
   cost. Some `active` requests may still use rules when Jev is uncertain.

For a private API, the comparison script reads `DECISIONGRAPH_API_KEY` and/or
`DECISIONGRAPH_BEARER_TOKEN` from your terminal environment. In JWT mode the
token must identify the same tenant and user as the script arguments and permit
the `team` scope. Do not put tokens in `scripts/atlas_cases.json` or paste them
into chat. Reports are saved in your chosen local output file.

## Verification and company readiness

Local checks: 27 gateway tests, 69 DecisionGraph tests and both dashboard builds
passed. Jev's wire shape was compared with TypeSafe's official quick start and
tested with a simulated HTTP response. No Docker daemon or TypeSafe key was
available in this environment, so the live Jev and database smoke tests remain
for the Mac.

For production, add centralized identity and permissions, atomic token-based
budgets across concurrent requests, auditable telemetry including failed calls,
price-version tracking, privacy review for TypeSafe traffic, representative
quality labels, and drift monitoring. This stage builds the measurable base.
