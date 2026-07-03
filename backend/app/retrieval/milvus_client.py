from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from backend.app.core.settings import MilvusSettings
from backend.app.retrieval.schemas import RetrievalQueryRequest


@dataclass(frozen=True)
class MilvusSearchHit:
    chunk_id: UUID
    score: float
    rank: int
    vector_id: str = ""


class MilvusRetrievalClient(Protocol):
    async def search(
        self,
        *,
        request: RetrievalQueryRequest,
        allowed_chunk_ids: list[UUID],
    ) -> list[MilvusSearchHit]:
        raise NotImplementedError


class NoopMilvusRetrievalClient:
    async def search(
        self,
        *,
        request: RetrievalQueryRequest,
        allowed_chunk_ids: list[UUID],
    ) -> list[MilvusSearchHit]:
        return []


class PymilvusRetrievalClient:
    def __init__(self, settings: MilvusSettings) -> None:
        self._settings = settings

    async def search(
        self,
        *,
        request: RetrievalQueryRequest,
        allowed_chunk_ids: list[UUID],
    ) -> list[MilvusSearchHit]:
        # The real Milvus query requires an embedding/indexing task first. Until
        # that exists, keep production behavior safe by returning no vector hits.
        return []


def build_milvus_retrieval_client(settings: MilvusSettings) -> MilvusRetrievalClient:
    if not settings.uri:
        return NoopMilvusRetrievalClient()
    return PymilvusRetrievalClient(settings)
