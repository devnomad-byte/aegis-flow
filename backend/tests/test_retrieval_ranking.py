from uuid import uuid4

from backend.app.retrieval.ranking import (
    NoopRetrievalReranker,
    RetrievalCandidate,
    reciprocal_rank_fusion,
)


def test_reciprocal_rank_fusion_merges_keyword_and_vector_hits() -> None:
    chunk_a = uuid4()
    chunk_b = uuid4()
    chunk_c = uuid4()

    fused = reciprocal_rank_fusion(
        [
            RetrievalCandidate(chunk_id=chunk_a, source="keyword", rank=1, score=9.0),
            RetrievalCandidate(chunk_id=chunk_b, source="keyword", rank=2, score=5.0),
        ],
        [
            RetrievalCandidate(chunk_id=chunk_b, source="vector", rank=1, score=0.92),
            RetrievalCandidate(chunk_id=chunk_c, source="vector", rank=2, score=0.81),
        ],
    )

    assert [candidate.chunk_id for candidate in fused] == [chunk_b, chunk_a, chunk_c]
    assert fused[0].sources == ("keyword", "vector")
    assert fused[0].score > fused[1].score


def test_noop_reranker_preserves_fused_order() -> None:
    candidates = [
        RetrievalCandidate(chunk_id=uuid4(), source="keyword", rank=1, score=0.3),
        RetrievalCandidate(chunk_id=uuid4(), source="vector", rank=2, score=0.2),
    ]

    reranked = NoopRetrievalReranker().rerank(query="502 ingress", candidates=candidates)

    assert reranked == candidates
