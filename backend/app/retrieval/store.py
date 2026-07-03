from typing import Protocol
from uuid import UUID

from backend.app.retrieval.schemas import (
    RetrievalQueryRequest,
    RetrievalQueryResponse,
    RetrievalSubject,
)


class RetrievalGatewayStore(Protocol):
    async def query(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        subjects: list[RetrievalSubject],
        request: RetrievalQueryRequest,
    ) -> RetrievalQueryResponse:
        raise NotImplementedError
