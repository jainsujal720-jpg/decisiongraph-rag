from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewItem:
    id: str
    query_event_id: str | None
    tenant_id: str
    requester_id: str
    question: str
    reason: str
    status: str
    proposed_answer: str | None
    confidence: dict
    reviewer_id: str | None
    resolution_notes: str | None
    created_at: str
    resolved_at: str | None


@dataclass(frozen=True)
class EvaluationCaseResult:
    question: str
    expected_decision: str
    actual_decision: str
    expected_terms: tuple[str, ...]
    answer_correct: bool
    citation_source: str | None
    source_hit: bool | None
    confidence: float


@dataclass(frozen=True)
class EvaluationReport:
    case_count: int
    decision_accuracy: float
    answer_accuracy: float
    source_hit_rate: float | None
    average_confidence: float
    results: tuple[EvaluationCaseResult, ...]


@dataclass(frozen=True)
class OperationsMetrics:
    tenant_id: str
    total_queries: int
    answered_queries: int
    abstained_queries: int
    average_latency_ms: float | None
    average_confidence: float | None
    pending_reviews: int
