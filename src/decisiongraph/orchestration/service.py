import math
import re
from collections.abc import Iterable, Sequence

from decisiongraph.graph.models import GraphHit
from decisiongraph.knowledge.models import SearchHit
from decisiongraph.orchestration.models import (
    EvidenceItem,
    GraphRelationEvidence,
    RetrievalPlan,
    RetrievalResponse,
)
from decisiongraph.orchestration.router import RuleBasedQueryRouter


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def _normalized_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


class RetrievalOrchestrator:
    def __init__(
        self,
        knowledge_service,
        graph_service,
        router: RuleBasedQueryRouter | None = None,
        candidate_limit: int = 12,
        context_max_tokens: int = 3000,
    ):
        self.knowledge_service = knowledge_service
        self.graph_service = graph_service
        self.router = router or RuleBasedQueryRouter()
        self.candidate_limit = candidate_limit
        self.context_max_tokens = context_max_tokens

    def retrieve(
        self,
        query: str,
        tenant_id: str,
        user_id: str,
        allowed_scopes: Sequence[str],
        limit: int,
    ) -> RetrievalResponse:
        if not query.strip():
            raise ValueError("query must not be empty")
        if limit <= 0:
            raise ValueError("limit must be positive")
        plan = self.router.plan(query)
        vector_hits: list[SearchHit] = []
        graph_hits: list[GraphHit] = []
        if plan.route in {"vector", "hybrid"}:
            vector_hits = self.knowledge_service.search(
                query, tenant_id, user_id, allowed_scopes, self.candidate_limit
            )
        if plan.route in {"graph", "hybrid"}:
            graph_hits = self.graph_service.search(
                query, tenant_id, user_id, list(allowed_scopes), self.candidate_limit
            )
        if plan.route == "graph" and not graph_hits:
            vector_hits = self.knowledge_service.search(
                query, tenant_id, user_id, allowed_scopes, self.candidate_limit
            )
            plan = RetrievalPlan(
                "graph_with_vector_fallback",
                "No authorized graph evidence was found, so passage retrieval was used as a "
                "fallback.",
            )
        evidence = self._fuse_and_rerank(query, vector_hits, graph_hits, limit)
        context, token_estimate = self._assemble_context(evidence)
        return RetrievalResponse(query, plan, tuple(evidence), context, token_estimate)

    def _fuse_and_rerank(
        self,
        query: str,
        vector_hits: Iterable[SearchHit],
        graph_hits: Iterable[GraphHit],
        limit: int,
    ) -> list[EvidenceItem]:
        records: dict[str, dict] = {}
        for rank, hit in enumerate(vector_hits, 1):
            key = f"chunk:{hit.chunk_id}"
            record = records.setdefault(
                key,
                {
                    "source_name": hit.source_name,
                    "chunk_id": hit.chunk_id,
                    "content": hit.context,
                    "section_path": hit.section_path,
                    "page_numbers": hit.page_numbers,
                    "channels": set(),
                    "rrf": 0.0,
                    "entity_name": None,
                    "relation_type": None,
                    "graph_relations": [],
                },
            )
            record["channels"].add("vector_keyword")
            record["rrf"] += 1 / (60 + rank)
        for rank, hit in enumerate(graph_hits, 1):
            if not hit.source_name or not hit.chunk_id or not hit.evidence:
                continue
            normalized_evidence = _normalized_text(hit.evidence)
            graph_relation = GraphRelationEvidence(
                hit.source_entity, hit.relation_type, hit.target_entity, hit.evidence
            )
            matching_passage = next(
                (
                    record
                    for record in records.values()
                    if record["source_name"] == hit.source_name
                    and normalized_evidence in _normalized_text(record["content"])
                ),
                None,
            )
            if matching_passage:
                matching_passage["channels"].add("graph")
                matching_passage["rrf"] += 1 / (60 + rank)
                if graph_relation not in matching_passage["graph_relations"]:
                    matching_passage["graph_relations"].append(graph_relation)
                if matching_passage["entity_name"] is None:
                    matching_passage["entity_name"] = hit.entity_name
                    matching_passage["relation_type"] = hit.relation_type
                continue
            key = f"graph:{hit.source_name}:{hit.chunk_id}:{hit.evidence.casefold()}"
            record = records.setdefault(
                key,
                {
                    "source_name": hit.source_name,
                    "chunk_id": hit.chunk_id,
                    "content": hit.evidence,
                    "section_path": (),
                    "page_numbers": (),
                    "channels": set(),
                    "rrf": 0.0,
                    "entity_name": hit.entity_name,
                    "relation_type": hit.relation_type,
                    "graph_relations": [graph_relation],
                },
            )
            record["channels"].add("graph")
            record["rrf"] += 1 / (60 + rank)
        if not records:
            return []

        maximum_rrf = max(record["rrf"] for record in records.values())
        query_tokens = _tokens(query)
        ranked = []
        for key, record in records.items():
            content_tokens = _tokens(record["content"])
            overlap = len(query_tokens & content_tokens) / max(1, len(query_tokens))
            retrieval_score = record["rrf"] / maximum_rrf
            rerank_score = 0.7 * retrieval_score + 0.3 * overlap
            ranked.append((key, record, retrieval_score, rerank_score))
        ranked.sort(key=lambda item: (-item[3], item[0]))
        evidence = []
        for position, (key, record, retrieval_score, rerank_score) in enumerate(ranked[:limit], 1):
            evidence.append(
                EvidenceItem(
                    evidence_id=key,
                    citation=f"E{position}",
                    source_name=record["source_name"],
                    chunk_id=record["chunk_id"],
                    content=record["content"],
                    section_path=tuple(record["section_path"]),
                    page_numbers=tuple(record["page_numbers"]),
                    channels=tuple(sorted(record["channels"])),
                    retrieval_score=round(retrieval_score, 6),
                    rerank_score=round(rerank_score, 6),
                    entity_name=record["entity_name"],
                    relation_type=record["relation_type"],
                    graph_relations=tuple(record["graph_relations"]),
                )
            )
        return evidence

    def _assemble_context(self, evidence: Sequence[EvidenceItem]) -> tuple[str, int]:
        blocks = []
        total = 0
        for item in evidence:
            section = " > ".join(item.section_path) if item.section_path else "Graph evidence"
            block = (
                f"[{item.citation}] source={item.source_name}; section={section}\n{item.content}"
            )
            block_tokens = _estimate_tokens(block)
            if total + block_tokens > self.context_max_tokens:
                break
            blocks.append(block)
            total += block_tokens
        return "\n\n".join(blocks), total
