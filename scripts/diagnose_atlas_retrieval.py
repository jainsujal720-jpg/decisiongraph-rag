"""Inspect evidence for the failed Atlas question without running answer models.

Run from a Mac with DecisionGraph on localhost:8000:
    python3 diagnose_atlas_retrieval.py
Reads optional DECISIONGRAPH_API_KEY and DECISIONGRAPH_BEARER_TOKEN environment
variables. Never prints either credential.
"""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


QUESTION = "Why was the Atlas launch delayed?"
NEEDLE = "payment retry testing had not reached the required 98% pass rate"


def diagnose(base_url: str = "http://localhost:8000") -> None:
    headers = {"Content-Type": "application/json"}
    if key := os.getenv("DECISIONGRAPH_API_KEY"):
        headers["X-API-Key"] = key
    if token := os.getenv("DECISIONGRAPH_BEARER_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"{base_url.rstrip('/')}/v1/retrieve",
        data=json.dumps({"query": QUESTION, "tenant_id": "acme", "user_id": "sujal",
                         "allowed_scopes": ["team"], "limit": 8}).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            result = json.load(response)
    except HTTPError as error:
        print(f"Retrieval HTTP {error.code}: {error.read().decode(errors='replace')[:500]}")
        return
    except URLError as error:
        print(f"Cannot reach DecisionGraph: {error.reason}")
        return
    print(f"Route: {result.get('route')}; evidence count: {result.get('evidence_count')}")
    context = result.get("context") or ""
    print(f"Delay reason available to answer model: {NEEDLE in context.casefold()}")
    for item in result.get("evidence", []):
        snippet = " ".join((item.get("content") or "").split())
        print(f"{item.get('citation')}: {item.get('source_name')} | "
              f"score {item.get('rerank_score')} | {snippet[:500]}")
    if not context and result.get("evidence_count"):
        print("WARNING: evidence exists but the answer context is empty.")


if __name__ == "__main__":
    diagnose(os.getenv("DECISIONGRAPH_URL", "http://localhost:8000"))
