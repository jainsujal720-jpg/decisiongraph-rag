from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalPlan:
    route: str
    reason: str


@dataclass(frozen=True)
class GraphRelationEvidence:
    source_entity: str | None
    relation_type: str | None
    target_entity: str | None
    evidence: str


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    citation: str
    source_name: str
    chunk_id: str
    content: str
    section_path: tuple[str, ...]
    page_numbers: tuple[int, ...]
    channels: tuple[str, ...]
    retrieval_score: float
    rerank_score: float
    entity_name: str | None = None
    relation_type: str | None = None
    graph_relations: tuple[GraphRelationEvidence, ...] = ()


@dataclass(frozen=True)
class RetrievalResponse:
    query: str
    plan: RetrievalPlan
    evidence: tuple[EvidenceItem, ...]
    context: str
    context_token_estimate: int
