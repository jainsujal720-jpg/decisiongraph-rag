import re

from decisiongraph.orchestration.models import RetrievalPlan

GRAPH_PATTERNS = (
    r"\bwho\b",
    r"\bowner\b",
    r"\bowns?\b",
    r"\brelationship\b",
    r"\bdepends?\b",
    r"\bconnected\b",
    r"\bresponsible\b",
)
PASSAGE_PATTERNS = (
    r"\bwhy\b",
    r"\bwhen\b",
    r"\bhow\b",
    r"\bsummar(?:y|ize)\b",
    r"\bdate\b",
    r"\bdecision\b",
    r"\bdetails?\b",
)


class RuleBasedQueryRouter:
    """Deterministic routing keeps the retrieval decision auditable and testable."""

    def plan(self, query: str) -> RetrievalPlan:
        normalized = query.casefold()
        graph_signals = sum(bool(re.search(pattern, normalized)) for pattern in GRAPH_PATTERNS)
        passage_signals = sum(bool(re.search(pattern, normalized)) for pattern in PASSAGE_PATTERNS)
        if graph_signals and passage_signals:
            return RetrievalPlan(
                "hybrid", "The question asks for both a relationship and passage detail."
            )
        if graph_signals:
            return RetrievalPlan("graph", "The question asks about an entity or relationship.")
        if passage_signals:
            return RetrievalPlan("vector", "The question asks for document-grounded detail.")
        return RetrievalPlan("hybrid", "No strong signal; retrieve from both systems for recall.")
