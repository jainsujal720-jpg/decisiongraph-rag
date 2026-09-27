"""Repeat a labelled DecisionGraph workload; compare reports after changing Jev mode.

Example: python scripts/compare_routing.py --label rules --output rules.json
         python scripts/compare_routing.py --label jev --output jev.json --compare rules.json
"""

import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


def evaluate_case(case: dict, answer: dict) -> dict:
    """Explain every quality check so a failed benchmark can be investigated."""
    actual_answer = answer.get("answer") or ""
    expected_decision = case["expected_decision"]
    missing_terms = [term for term in case.get("expected_terms", [])
                     if term.casefold() not in actual_answer.casefold()]
    expected_source = case.get("expected_source")
    source_names = [citation.get("source_name") for citation in answer.get("citations", [])
                    if isinstance(citation, dict)]
    failed_checks = []
    if answer.get("decision") != expected_decision:
        failed_checks.append("decision")
    if missing_terms:
        failed_checks.append("expected_terms")
    if expected_source and expected_source not in source_names:
        failed_checks.append("expected_source")
    return {
        "quality_pass": not failed_checks,
        "failed_checks": failed_checks,
        "actual_answer": actual_answer,
        "claims": answer.get("claims", []),
        "retrieval_route": answer.get("route"),
        "expected_decision": expected_decision,
        "missing_terms": missing_terms,
        "expected_source": expected_source,
        "source_names": source_names,
    }


def run(base_url: str, cases: list[dict], tenant: str, user: str,
        api_key: str, bearer_token: str = "") -> list[dict]:
    results = []
    for case in cases:
        payload = {"query": case["question"], "tenant_id": tenant, "user_id": user,
                   "allowed_scopes": ["team"], "limit": 8}
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        request = Request(f"{base_url.rstrip('/')}/v1/answers", json.dumps(payload).encode(),
                          headers, method="POST")
        try:
            with urlopen(request, timeout=180) as response:
                answer = json.load(response)
            checks = evaluate_case(case, answer)
            calls = answer.get("model_calls", [])
            model_costs = [call.get("usage", {}).get("token_cost_usd") for call in calls
                           if isinstance(call.get("usage"), dict)]
            jev_costs = [call.get("routing", {}).get("jev_cost_usd") for call in calls
                         if isinstance(call.get("routing"), dict)]
            results.append({
                "question": case["question"], "decision": answer.get("decision"),
                **checks,
                "models": [call.get("model") for call in calls],
                "jev_modes": [call.get("routing", {}).get("jev_mode") for call in calls],
                "routing_sources": [call.get("routing", {}).get("source") for call in calls],
                "token_cost_usd": round(sum(value for value in model_costs if value is not None), 9),
                "jev_cost_usd": round(sum(value for value in jev_costs if value is not None), 9),
                "measured_calls": len([value for value in model_costs if value is not None]),
                "model_calls": len(calls),
            })
        except Exception as error:
            results.append({"question": case["question"], "quality_pass": False,
                            "failed_checks": ["request_error"], "error": str(error)})
    return results


def summary(results: list[dict]) -> dict:
    return {
        "cases": len(results), "passing": sum(item["quality_pass"] for item in results),
        "model_token_cost_usd": round(sum(item.get("token_cost_usd", 0) for item in results), 9),
        "jev_token_cost_usd": round(sum(item.get("jev_cost_usd", 0) for item in results), 9),
        "measured_calls": sum(item.get("measured_calls", 0) for item in results),
        "model_calls": sum(item.get("model_calls", 0) for item in results),
        "failures": [item["question"] for item in results if not item["quality_pass"]],
    }


def comparison(before: dict, after: dict) -> dict:
    """Compare matched, fully measured workloads without hiding quality regressions."""
    baseline, candidate = before["summary"], after["summary"]
    baseline_questions = [item["question"] for item in before["results"]]
    candidate_questions = [item["question"] for item in after["results"]]
    if baseline_questions != candidate_questions:
        return {"comparable": False, "reason": "Question sets or order differ."}
    if any(item["measured_calls"] != item["model_calls"]
           for item in (baseline, candidate)):
        return {"comparable": False, "reason": "At least one model call lacks token usage."}
    before_cost = baseline["model_token_cost_usd"] + baseline["jev_token_cost_usd"]
    after_cost = candidate["model_token_cost_usd"] + candidate["jev_token_cost_usd"]
    return {
        "comparable": True,
        "quality_passed": all(not old["quality_pass"] or new["quality_pass"]
                              for old, new in zip(before["results"], after["results"])),
        "passing_change": candidate["passing"] - baseline["passing"],
        "baseline_estimated_cost_usd": round(before_cost, 9),
        "candidate_estimated_cost_usd": round(after_cost, 9),
        "estimated_savings_pct": round(100 * (before_cost - after_cost) / before_cost, 2)
        if before_cost else None,
        "per_question": [
            {
                "question": old["question"],
                "baseline_pass": old["quality_pass"],
                "candidate_pass": new["quality_pass"],
                "baseline_cost_usd": round(old.get("token_cost_usd", 0)
                                           + old.get("jev_cost_usd", 0), 9),
                "candidate_cost_usd": round(new.get("token_cost_usd", 0)
                                            + new.get("jev_cost_usd", 0), 9),
                "candidate_models": new.get("models", []),
            }
            for old, new in zip(before["results"], after["results"])
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="scripts/atlas_cases.json")
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--compare", help="Previous report JSON")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--tenant", default="acme")
    parser.add_argument("--user", default="sujal")
    args = parser.parse_args()
    cases = json.loads(Path(args.cases).read_text())
    results = run(args.url, cases, args.tenant, args.user,
                  os.getenv("DECISIONGRAPH_API_KEY", ""),
                  os.getenv("DECISIONGRAPH_BEARER_TOKEN", ""))
    report = {"label": args.label, "summary": summary(results), "results": results,
              "note": "Usage-based estimates only. Provider invoice and all other pipeline calls excluded."}
    if args.compare:
        report["comparison"] = comparison(json.loads(Path(args.compare).read_text()), report)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(f"{args.label}: {report['summary']}")
    for item in results:
        if not item["quality_pass"]:
            print(f"  failed {item['question']}: {item.get('failed_checks', [])}; "
                  f"missing terms {item.get('missing_terms', [])}; "
                  f"sources {item.get('source_names', [])}; "
                  f"decision {item.get('decision')}")
    if args.compare:
        print("comparison:", report["comparison"])
    if report["summary"]["measured_calls"] != report["summary"]["model_calls"]:
        print("Some calls lack token usage; do not use this run for cost comparison.")


if __name__ == "__main__":
    main()
