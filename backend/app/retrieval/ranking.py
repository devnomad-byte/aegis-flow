from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class RetrievalCandidate:
    chunk_id: UUID
    source: str
    rank: int
    score: float
    sources: tuple[str, ...] = ()


class RetrievalReranker(Protocol):
    def rerank(
        self,
        *,
        query: str,
        candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        raise NotImplementedError


class NoopRetrievalReranker:
    strategy = "none"

    def rerank(
        self,
        *,
        query: str,
        candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        return candidates


def reciprocal_rank_fusion(
    *candidate_lists: list[RetrievalCandidate],
    rank_constant: int = 60,
) -> list[RetrievalCandidate]:
    scores: dict[UUID, float] = {}
    best_rank: dict[UUID, int] = {}
    sources: dict[UUID, list[str]] = {}

    for candidates in candidate_lists:
        for index, candidate in enumerate(candidates, start=1):
            rank = candidate.rank or index
            scores[candidate.chunk_id] = scores.get(candidate.chunk_id, 0.0) + (
                1.0 / (rank_constant + rank)
            )
            best_rank[candidate.chunk_id] = min(best_rank.get(candidate.chunk_id, rank), rank)
            source_list = sources.setdefault(candidate.chunk_id, [])
            if candidate.source not in source_list:
                source_list.append(candidate.source)

    fused = [
        RetrievalCandidate(
            chunk_id=chunk_id,
            source="hybrid" if len(source_list) > 1 else source_list[0],
            rank=best_rank[chunk_id],
            score=score,
            sources=tuple(source_list),
        )
        for chunk_id, score in scores.items()
        for source_list in [sources[chunk_id]]
    ]
    return sorted(
        fused,
        key=lambda candidate: (-candidate.score, candidate.rank, str(candidate.chunk_id)),
    )
