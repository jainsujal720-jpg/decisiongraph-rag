from dataclasses import dataclass

from pydantic import BaseModel, Field


class DraftClaim(BaseModel):
    """One atomic factual claim proposed by the drafting model."""

    text: str = Field(min_length=1, max_length=800)
    citations: list[str] = Field(min_length=1, max_length=8)


class DraftResponse(BaseModel):
    claims: list[DraftClaim] = Field(default_factory=list, max_length=8)


class CitationVerdict(BaseModel):
    claim_index: int = Field(ge=0)
    citation: str = Field(min_length=1, max_length=32)
    supported: bool
    reason: str = Field(min_length=1, max_length=500)


class VerificationResponse(BaseModel):
    verdicts: list[CitationVerdict] = Field(default_factory=list)


@dataclass(frozen=True)
class VerifiedClaim:
    text: str
    citations: tuple[str, ...]
    supported: bool
    verification_reasons: tuple[str, ...]


@dataclass(frozen=True)
class ConfidenceScore:
    overall: float
    retrieval_quality: float
    groundedness: float
    citation_coverage: float
    label: str


@dataclass(frozen=True)
class AnswerResult:
    query: str
    answer: str
    decision: str
    confidence: ConfidenceScore
    claims: tuple[VerifiedClaim, ...]
    citations: tuple[dict, ...]
    route: str
    route_reason: str
    model_calls: tuple[dict, ...] = ()
