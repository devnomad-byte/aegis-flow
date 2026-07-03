from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from backend.app.audit.schemas import AuditEventRead


@dataclass(frozen=True)
class AuditEventFilters:
    project_id: UUID | None = None
    actor_id: UUID | None = None
    action: str | None = None
    risk_level: str | None = None
    result: str | None = None
    target_type: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    limit: int = 100


class AuditEventStore(Protocol):
    async def record_project_event(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        action: str,
        target_type: str,
        target_id: str,
        result: str = "success",
        risk_level: str = "low",
        metadata: dict[str, object] | None = None,
    ) -> None:
        raise NotImplementedError

    async def record_global_event(
        self,
        *,
        actor_id: UUID,
        action: str,
        target_type: str,
        target_id: str,
        result: str = "success",
        risk_level: str = "low",
        metadata: dict[str, object] | None = None,
    ) -> None:
        raise NotImplementedError

    async def list_project_events(
        self,
        *,
        project_id: UUID,
        filters: AuditEventFilters,
    ) -> list[AuditEventRead]:
        raise NotImplementedError

    async def list_global_events(self, *, filters: AuditEventFilters) -> list[AuditEventRead]:
        raise NotImplementedError
