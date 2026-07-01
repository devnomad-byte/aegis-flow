from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.audit.models import AuditLog


class SqlAlchemyAuditEventStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        self._session.add(
            AuditLog(
                project_id=project_id,
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                result=result,
                risk_level=risk_level,
                event_metadata=metadata or {},
            )
        )
        await self._session.commit()
