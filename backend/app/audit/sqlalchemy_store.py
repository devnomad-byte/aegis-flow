from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.audit.models import AuditLog
from backend.app.audit.schemas import AuditEventRead
from backend.app.audit.store import AuditEventFilters


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
        self._session.add(
            AuditLog(
                project_id=None,
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

    async def list_project_events(
        self,
        *,
        project_id: UUID,
        filters: AuditEventFilters,
    ) -> list[AuditEventRead]:
        statement = self._apply_filters(select(AuditLog), filters, project_id=project_id)
        result = await self._session.execute(statement)
        return [_audit_log_to_read(row) for row in result.scalars().all()]

    async def list_global_events(self, *, filters: AuditEventFilters) -> list[AuditEventRead]:
        statement = self._apply_filters(select(AuditLog), filters)
        result = await self._session.execute(statement)
        return [_audit_log_to_read(row) for row in result.scalars().all()]

    def _apply_filters(
        self,
        statement: Select[tuple[AuditLog]],
        filters: AuditEventFilters,
        *,
        project_id: UUID | None = None,
    ) -> Select[tuple[AuditLog]]:
        if project_id is not None:
            statement = statement.where(AuditLog.project_id == project_id)
        elif filters.project_id is not None:
            statement = statement.where(AuditLog.project_id == filters.project_id)
        if filters.actor_id is not None:
            statement = statement.where(AuditLog.actor_id == filters.actor_id)
        if filters.action is not None:
            statement = statement.where(AuditLog.action == filters.action)
        if filters.risk_level is not None:
            statement = statement.where(AuditLog.risk_level == filters.risk_level)
        if filters.result is not None:
            statement = statement.where(AuditLog.result == filters.result)
        if filters.target_type is not None:
            statement = statement.where(AuditLog.target_type == filters.target_type)
        if filters.created_from is not None:
            statement = statement.where(AuditLog.created_at >= filters.created_from)
        if filters.created_to is not None:
            statement = statement.where(AuditLog.created_at <= filters.created_to)
        return statement.order_by(AuditLog.created_at.desc()).limit(filters.limit)


def _audit_log_to_read(row: AuditLog) -> AuditEventRead:
    return AuditEventRead(
        id=row.id,
        project_id=row.project_id,
        actor_id=row.actor_id,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        result=row.result,
        risk_level=row.risk_level,
        metadata=dict(row.event_metadata),
        created_at=row.created_at,
    )
