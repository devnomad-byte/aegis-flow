from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.model_gateway.models import ModelGatewayInvocation, ModelGatewayPolicy
from backend.app.model_gateway.schemas import (
    ModelGatewayInvocationCreate,
    ModelGatewayInvocationRead,
    ModelGatewayPolicyCreate,
    ModelGatewayPolicyRead,
)


class SqlAlchemyModelGatewayStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_policy(self, request: ModelGatewayPolicyCreate) -> ModelGatewayPolicyRead:
        statement = select(ModelGatewayPolicy).where(
            ModelGatewayPolicy.project_id == request.project_id,
            ModelGatewayPolicy.policy_ref == request.policy_ref,
        )
        result = await self._session.execute(statement)
        policy = result.scalar_one_or_none()
        if policy is None:
            policy = ModelGatewayPolicy(**request.model_dump())
            self._session.add(policy)
        else:
            for field, value in request.model_dump().items():
                setattr(policy, field, value)

        await self._session.commit()
        await self._session.refresh(policy)
        return ModelGatewayPolicyRead.model_validate(policy)

    async def get_policy(
        self,
        *,
        project_id: UUID,
        policy_ref: str,
    ) -> ModelGatewayPolicyRead | None:
        statement = select(ModelGatewayPolicy).where(
            ModelGatewayPolicy.project_id == project_id,
            ModelGatewayPolicy.policy_ref == policy_ref,
            ModelGatewayPolicy.status == "active",
        )
        result = await self._session.execute(statement)
        policy = result.scalar_one_or_none()
        if policy is None:
            return None
        return ModelGatewayPolicyRead.model_validate(policy)

    async def record_invocation(
        self,
        request: ModelGatewayInvocationCreate,
    ) -> ModelGatewayInvocationRead:
        invocation = ModelGatewayInvocation(**request.model_dump())
        self._session.add(invocation)
        await self._session.commit()
        await self._session.refresh(invocation)
        return ModelGatewayInvocationRead.model_validate(invocation)

    async def list_invocations_for_run(
        self,
        *,
        project_id: UUID,
        run_id: str,
    ) -> list[ModelGatewayInvocationRead]:
        statement = (
            select(ModelGatewayInvocation)
            .where(
                ModelGatewayInvocation.project_id == project_id,
                ModelGatewayInvocation.run_id == run_id,
            )
            .order_by(ModelGatewayInvocation.created_at, ModelGatewayInvocation.id)
        )
        result = await self._session.execute(statement)
        return [
            ModelGatewayInvocationRead.model_validate(invocation)
            for invocation in result.scalars().all()
        ]
