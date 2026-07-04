from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.observability.models import RuntimeTraceSpan
from backend.app.observability.projection import policy_gate_event_to_span
from backend.app.policy_gate.models import PolicyGateEvent
from backend.app.policy_gate.schemas import PolicyGateEventCreate, PolicyGateEventRead


class SqlAlchemyPolicyGateEventStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_event(self, request: PolicyGateEventCreate) -> PolicyGateEventRead:
        event = PolicyGateEvent(**request.model_dump())
        self._session.add(event)
        await self._session.flush()
        self._session.add(RuntimeTraceSpan(**policy_gate_event_to_span(event).model_dump()))
        await self._session.commit()
        await self._session.refresh(event)
        return PolicyGateEventRead.model_validate(event)

    async def list_events(
        self,
        *,
        project_id: UUID,
        run_id: str | None = None,
        node_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[PolicyGateEventRead]:
        conditions = [PolicyGateEvent.project_id == project_id]
        if run_id is not None:
            conditions.append(PolicyGateEvent.run_id == run_id)
        if node_id is not None:
            conditions.append(PolicyGateEvent.node_id == node_id)
        if trace_id is not None:
            conditions.append(PolicyGateEvent.trace_id == trace_id)

        statement = (
            select(PolicyGateEvent)
            .where(*conditions)
            .order_by(PolicyGateEvent.created_at, PolicyGateEvent.id)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [PolicyGateEventRead.model_validate(row) for row in result.scalars()]
