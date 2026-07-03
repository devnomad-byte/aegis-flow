from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.model_gateway.models import (
    ModelGatewayInvocation,
    ModelGatewayPolicy,
    PromptTemplate,
    PromptTemplateVersion,
)
from backend.app.model_gateway.schemas import (
    ModelGatewayInvocationCreate,
    ModelGatewayInvocationRead,
    ModelGatewayPolicyCreate,
    ModelGatewayPolicyRead,
    PromptTemplateCreate,
    PromptTemplateRead,
    PromptTemplateVersionCreate,
    PromptTemplateVersionRead,
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

    async def list_policies(self, project_id: UUID) -> list[ModelGatewayPolicyRead]:
        statement = (
            select(ModelGatewayPolicy)
            .where(ModelGatewayPolicy.project_id == project_id)
            .order_by(ModelGatewayPolicy.policy_ref, ModelGatewayPolicy.id)
        )
        result = await self._session.execute(statement)
        return [ModelGatewayPolicyRead.model_validate(policy) for policy in result.scalars().all()]

    async def create_prompt_template(
        self,
        request: PromptTemplateCreate,
    ) -> PromptTemplateRead:
        template = PromptTemplate(**request.model_dump())
        self._session.add(template)
        await self._session.commit()
        await self._session.refresh(template)
        return PromptTemplateRead.model_validate(template)

    async def get_prompt_template(
        self,
        *,
        project_id: UUID,
        template_ref: str,
    ) -> PromptTemplateRead | None:
        statement = select(PromptTemplate).where(
            PromptTemplate.project_id == project_id,
            PromptTemplate.template_ref == template_ref,
            PromptTemplate.status == "active",
        )
        result = await self._session.execute(statement)
        template = result.scalar_one_or_none()
        if template is None:
            return None
        return PromptTemplateRead.model_validate(template)

    async def create_prompt_template_version(
        self,
        request: PromptTemplateVersionCreate,
    ) -> PromptTemplateVersionRead:
        template = await self._get_prompt_template_model(
            project_id=request.project_id,
            template_id=request.template_id,
        )
        version = PromptTemplateVersion(
            **request.model_dump(),
            template_ref=template.template_ref,
        )
        self._session.add(version)
        await self._session.commit()
        await self._session.refresh(version)
        return PromptTemplateVersionRead.model_validate(version)

    async def get_prompt_template_version(
        self,
        *,
        project_id: UUID,
        template_ref: str,
        version: str,
    ) -> PromptTemplateVersionRead | None:
        statement = (
            select(PromptTemplateVersion)
            .join(PromptTemplate, PromptTemplate.id == PromptTemplateVersion.template_id)
            .where(
                PromptTemplateVersion.project_id == project_id,
                PromptTemplateVersion.version == version,
                PromptTemplateVersion.status == "active",
                PromptTemplate.project_id == project_id,
                PromptTemplate.template_ref == template_ref,
                PromptTemplate.status == "active",
            )
        )
        result = await self._session.execute(statement)
        prompt_version = result.scalar_one_or_none()
        if prompt_version is None:
            return None
        return PromptTemplateVersionRead.model_validate(prompt_version)

    async def list_prompt_template_versions(
        self,
        *,
        project_id: UUID,
        template_ref: str,
    ) -> list[PromptTemplateVersionRead]:
        statement = (
            select(PromptTemplateVersion)
            .join(PromptTemplate, PromptTemplate.id == PromptTemplateVersion.template_id)
            .where(
                PromptTemplateVersion.project_id == project_id,
                PromptTemplate.project_id == project_id,
                PromptTemplate.template_ref == template_ref,
            )
            .order_by(PromptTemplateVersion.created_at, PromptTemplateVersion.id)
        )
        result = await self._session.execute(statement)
        return [
            PromptTemplateVersionRead.model_validate(prompt_version)
            for prompt_version in result.scalars().all()
        ]

    async def record_invocation(
        self,
        request: ModelGatewayInvocationCreate,
    ) -> ModelGatewayInvocationRead:
        invocation = ModelGatewayInvocation(**request.model_dump())
        self._session.add(invocation)
        await self._session.commit()
        await self._session.refresh(invocation)
        return ModelGatewayInvocationRead.model_validate(invocation)

    async def list_invocations(
        self,
        *,
        project_id: UUID,
        run_id: str | None = None,
        node_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[ModelGatewayInvocationRead]:
        conditions = [ModelGatewayInvocation.project_id == project_id]
        if run_id:
            conditions.append(ModelGatewayInvocation.run_id == run_id)
        if node_id:
            conditions.append(ModelGatewayInvocation.node_id == node_id)
        if trace_id:
            conditions.append(ModelGatewayInvocation.trace_id == trace_id)

        statement = (
            select(ModelGatewayInvocation)
            .where(*conditions)
            .order_by(ModelGatewayInvocation.created_at.desc(), ModelGatewayInvocation.id)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [
            ModelGatewayInvocationRead.model_validate(invocation)
            for invocation in result.scalars().all()
        ]

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

    async def _get_prompt_template_model(
        self,
        *,
        project_id: UUID,
        template_id: UUID,
    ) -> PromptTemplate:
        statement = select(PromptTemplate).where(
            PromptTemplate.project_id == project_id,
            PromptTemplate.id == template_id,
            PromptTemplate.status == "active",
        )
        result = await self._session.execute(statement)
        return result.scalar_one()
