import pytest

from decisiongraph.graph.models import GraphHit
from decisiongraph.knowledge.models import SearchHit
from decisiongraph.orchestration.router import RuleBasedQueryRouter
from decisiongraph.orchestration.service import RetrievalOrchestrator


def vector_hit(chunk_id: str = "chunk-1") -> SearchHit:
    return SearchHit(
        chunk_id,
        "doc-1",
        "atlas.md",
        "Payment retry testing was pending.",
        "The Atlas launch was delayed because payment retry testing was pending.",
        ("Atlas", "Decision"),
        (),
        1,
        1,
        0.9,
        0.8,
        0.03,
    )


def graph_hit() -> GraphHit:
    return GraphHit(
        "entity-1",
        "Priya Shah",
        "PERSON",
        "Payment owner",
        "Priya Shah",
        "OWNS",
        "payment-reliability workstream",
        "Priya Shah owns the payment-reliability workstream.",
        "atlas.md",
        "graph-chunk-1",
        2.0,
    )


class FakeKnowledgeService:
    def __init__(self):
        self.calls = []

    def search(self, *args):
        self.calls.append(args)
        return [vector_hit()]


class FakeGraphService:
    def __init__(self):
        self.calls = []

    def search(self, *args):
        self.calls.append(args)
        return [graph_hit(), graph_hit()]


def test_router_selects_explainable_routes():
    router = RuleBasedQueryRouter()
    assert router.plan("Why was Atlas delayed?").route == "vector"
    assert router.plan("Who owns payment reliability?").route == "graph"
    assert router.plan("Who owns payment reliability and why was Atlas delayed?").route == "hybrid"
    assert router.plan("Atlas").route == "hybrid"


def test_orchestrator_routes_fuses_deduplicates_and_assembles_context():
    knowledge, graph = FakeKnowledgeService(), FakeGraphService()
    service = RetrievalOrchestrator(knowledge, graph, candidate_limit=5, context_max_tokens=500)
    result = service.retrieve(
        "Who owns payment reliability and why was Atlas delayed?", "acme", "u1", ["team"], 5
    )
    assert result.plan.route == "hybrid"
    assert len(knowledge.calls) == 1
    assert len(graph.calls) == 1
    assert len(result.evidence) == 2
    assert result.evidence[0].citation == "E1"
    assert any(item.channels == ("graph",) for item in result.evidence)
    assert "[E1]" in result.context
    assert result.context_token_estimate > 0


def test_orchestrator_merges_graph_evidence_into_matching_passage_context():
    class MatchingGraphService(FakeGraphService):
        def search(self, *args):
            self.calls.append(args)
            return [
                GraphHit(
                    "entity-1",
                    "Atlas Launch",
                    "INITIATIVE",
                    "Launch",
                    "Atlas Launch",
                    "AFFECTED_BY",
                    "payment retry testing",
                    "The Atlas launch was delayed because payment retry testing was pending.",
                    "atlas.md",
                    "graph-chunk-1",
                    2.0,
                ),
                GraphHit(
                    "entity-2",
                    "payment retry testing",
                    "TEST_SUITE",
                    "Testing",
                    "payment retry testing",
                    "REQUIRES_PASS_RATE",
                    "98% pass rate",
                    "The Atlas launch was delayed because payment retry testing was pending.",
                    "atlas.md",
                    "graph-chunk-1",
                    1.9,
                ),
            ]

    result = RetrievalOrchestrator(FakeKnowledgeService(), MatchingGraphService()).retrieve(
        "Who owns Atlas and why was it delayed?", "acme", "u1", ["team"], 5
    )
    assert len(result.evidence) == 1
    assert result.evidence[0].channels == ("graph", "vector_keyword")
    assert result.evidence[0].relation_type == "AFFECTED_BY"
    assert result.evidence[0].graph_relations[0].target_entity == "payment retry testing"
    assert len(result.evidence[0].graph_relations) == 2


def test_orchestrator_uses_only_graph_for_relationship_questions():
    knowledge, graph = FakeKnowledgeService(), FakeGraphService()
    result = RetrievalOrchestrator(knowledge, graph).retrieve(
        "Who owns payment reliability?", "acme", "u1", ["team"], 5
    )
    assert result.plan.route == "graph"
    assert knowledge.calls == []
    assert len(graph.calls) == 1


def test_orchestrator_falls_back_when_graph_has_no_authorized_hit():
    class EmptyGraphService(FakeGraphService):
        def search(self, *args):
            self.calls.append(args)
            return []

    knowledge, graph = FakeKnowledgeService(), EmptyGraphService()
    result = RetrievalOrchestrator(knowledge, graph).retrieve(
        "Who owns payment reliability?", "acme", "u1", ["team"], 5
    )
    assert result.plan.route == "graph_with_vector_fallback"
    assert len(knowledge.calls) == 1
    assert len(graph.calls) == 1


def test_orchestrator_enforces_context_budget_and_input_validation():
    knowledge, graph = FakeKnowledgeService(), FakeGraphService()
    service = RetrievalOrchestrator(knowledge, graph, context_max_tokens=1)
    result = service.retrieve("Why was Atlas delayed?", "acme", "u1", ["team"], 5)
    assert result.evidence
    assert result.context == ""
    with pytest.raises(ValueError):
        service.retrieve(" ", "acme", "u1", ["team"], 5)
