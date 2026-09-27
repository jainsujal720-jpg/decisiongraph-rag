from collections.abc import Sequence

from decisiongraph.operations.models import EvaluationCaseResult, EvaluationReport


class EvaluationService:
    """Runs a transparent, user-supplied evaluation set against the answer service."""

    def __init__(self, answer_service):
        self.answer_service = answer_service

    def run(
        self,
        cases: Sequence[dict],
        tenant_id: str,
        user_id: str,
        allowed_scopes: Sequence[str],
        limit: int,
    ) -> EvaluationReport:
        if not cases:
            raise ValueError("at least one evaluation case is required")
        results = []
        for case in cases:
            answer = self.answer_service.answer(
                case["question"], tenant_id, user_id, allowed_scopes, limit
            )
            expected_terms = tuple(term.casefold() for term in case.get("expected_terms", []))
            answer_correct = all(term in answer.answer.casefold() for term in expected_terms)
            expected_source = case.get("expected_source")
            source_hit = (
                any(item["source_name"] == expected_source for item in answer.citations)
                if expected_source
                else None
            )
            results.append(
                EvaluationCaseResult(
                    case["question"],
                    case.get("expected_decision", "answered"),
                    answer.decision,
                    expected_terms,
                    answer_correct,
                    expected_source,
                    source_hit,
                    answer.confidence.overall,
                )
            )
        count = len(results)
        decision_accuracy = (
            sum(result.actual_decision == result.expected_decision for result in results) / count
        )
        answer_accuracy = sum(result.answer_correct for result in results) / count
        source_results = [result.source_hit for result in results if result.source_hit is not None]
        source_hit_rate = sum(source_results) / len(source_results) if source_results else None
        return EvaluationReport(
            count,
            round(decision_accuracy, 4),
            round(answer_accuracy, 4),
            round(source_hit_rate, 4) if source_hit_rate is not None else None,
            round(sum(result.confidence for result in results) / count, 4),
            tuple(results),
        )
