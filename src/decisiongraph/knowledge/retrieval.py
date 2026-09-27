from collections.abc import Sequence

from decisiongraph.knowledge.models import Candidate, SearchHit


def reciprocal_rank_fusion(
    vector_results: Sequence[Candidate],
    keyword_results: Sequence[Candidate],
    limit: int,
    constant: int = 60,
) -> list[SearchHit]:
    """Merge independently ranked result lists without comparing unlike raw scores."""
    if limit <= 0 or constant <= 0:
        raise ValueError("limit and RRF constant must be positive")

    merged: dict[str, dict] = {}
    for channel, results in (("vector", vector_results), ("keyword", keyword_results)):
        for rank, candidate in enumerate(results, 1):
            record = merged.setdefault(
                candidate.chunk_id,
                {
                    "candidate": candidate,
                    "vector_rank": None,
                    "keyword_rank": None,
                    "vector_score": None,
                    "keyword_score": None,
                    "fused_score": 0.0,
                },
            )
            record[f"{channel}_rank"] = rank
            record[f"{channel}_score"] = candidate.raw_score
            record["fused_score"] += 1 / (constant + rank)

    ordered = sorted(
        merged.values(),
        key=lambda item: (-item["fused_score"], item["candidate"].chunk_id),
    )[:limit]
    return [
        SearchHit(
            chunk_id=item["candidate"].chunk_id,
            document_id=item["candidate"].document_id,
            source_name=item["candidate"].source_name,
            content=item["candidate"].content,
            context=item["candidate"].parent_content or item["candidate"].content,
            section_path=item["candidate"].section_path,
            page_numbers=item["candidate"].page_numbers,
            vector_rank=item["vector_rank"],
            keyword_rank=item["keyword_rank"],
            vector_score=item["vector_score"],
            keyword_score=item["keyword_score"],
            fused_score=item["fused_score"],
        )
        for item in ordered
    ]
