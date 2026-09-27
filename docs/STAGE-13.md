# Stage 13: measure cheaper drafts without Jev

## What changes

The default `CAUSAL_DRAFT_OPTIMIZATION=false` preserves the working Stage 12
rules. Jev remains `RELAYGUARD_JEV_MODE=off` and requires no TypeSafe key.

When `CAUSAL_DRAFT_OPTIMIZATION=true`, a short "why" question with an explicit
"because" or "due to" in a relevant top-three evidence block uses the RelayGuard
`moderate` draft tier instead of `complex`. A draft with no claims gets exactly
one retry at `complex`. Every claim still goes through the existing citation
verification and abstention policy. Questions requiring comparisons or analysis,
long contexts, and other questions keep their existing route. An unsupported
claim is still rejected; no model tier guarantees correctness.

This is an experiment. The four Atlas questions cannot establish a statistically
reliable savings rate for a company workload. A lower bill on one run can result
from prompt length or model variation. Compare real provider invoices, retrieval
embedding costs, case-level quality and latency before changing the default.

## Mac installation and comparison

1. Unzip Stage 13 into a new folder; copy `.env` and `rules-fixed.json` from
   your working Stage 12 folder. Do not copy the new `.env.example` over your key.
   Compose retains project name `decisiongraph` and the existing database volumes.
2. Confirm `.env` has `RELAYGUARD_JEV_MODE=off` and add
   `CAUSAL_DRAFT_OPTIMIZATION=true`. Run `docker compose up -d --build api` and
   check `docker compose ps api` until healthy. There is no need to rebuild the
   gateway or databases.
3. Ask the Atlas delay question once in the DecisionGraph dashboard. The
   draft should show `gpt-5.6-luna` on the moderate tier when the top evidence
   directly states its cause. It might show an additional `gpt-5.6-sol` draft
   if the first draft was empty. Verification must still succeed.
4. Compare the same four questions:

   `python3 scripts/compare_routing.py --label optimized --output optimized.json --compare rules-fixed.json`

   Require 4/4 and fully measured calls before treating the estimated cost
   difference as useful. The script includes per-question model and cost details
   and marks a comparison invalid when question sets or measured usage differ.
5. To return to Stage 12 behavior, set `CAUSAL_DRAFT_OPTIMIZATION=false` and
   recreate the API with `docker compose up -d --force-recreate api`.

The comparison script may need `DECISIONGRAPH_API_KEY` and
`DECISIONGRAPH_BEARER_TOKEN` in your terminal if your API is protected; never
paste either into chat. Local reports contain answer text and should remain
private. `usage.token_cost_usd` is an estimate based on recorded tokens, not an
invoice. It excludes embeddings and several other pipeline costs.

## External APIs per case

- Browser or script calls DecisionGraph `POST /v1/answers`.
- Vector retrieval calls OpenAI embeddings. Graph lookup uses local Neo4j.
- DecisionGraph calls RelayGuard `POST /v1/chat/completions` for the draft
  (and a second time only if an empty optimized draft needs escalation) and
  for citation verification when valid draft claims exist.
- RelayGuard calls the selected OpenAI model provider. Jev makes **zero** calls.

Local tests: 72 DecisionGraph tests passed. Live cost and quality remain to be
validated using the existing Mac deployment and API credentials.

The DecisionGraph dashboard uses dedicated full-width rows for each model
decision so model names, tokens, and routing details remain readable.

Answer claims now require an exact, contiguous excerpt in every cited source
passage. The answer model is instructed to copy a full sentence, preserving
the document's wording (for example, "moved" instead of a paraphrase such as
"delayed"). Parent-chunk indexing prefixes are excluded from this check.
Paraphrases and unsupported claims are rejected before model verification;
the request abstains if no verified verbatim claim remains. Citation labels
and the standardized abstention message are system text, not quotations.

The dashboard now shows the current request's review notice in its answer
card, while older review items remain in a collapsed tenant-wide backlog.
The backlog is not evidence for the current question. It can be opened by a
reviewer; prior abstentions are retained for audit until explicitly resolved.

The graph extractor now drops model-produced relationships whose source or
target entity was not included in the same extraction. Valid relationships
still require verbatim evidence in the document. This lets ingestion continue
when an extraction has one invalid edge without fabricating an entity.

The optional causal draft optimization examines all available evidence blocks,
not just the first three. It requires the subject of a "why" question and an
explicit causal phrase in the same evidence sentence. An unrelated Atlas cause
must not downgrade an Orion question. This affects only the draft route;
citation verification and extractive answer enforcement remain in place.
Evidence blocks are separated by citation headers, since indexed parent chunks
can contain blank lines inside a single block.
