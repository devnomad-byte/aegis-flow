from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.knowledge.models import RetrievalEvalRun
from backend.app.model_gateway.models import (
    ModelGatewayInvocation,
    ModelGatewayPolicy,
    PromptTemplate,
    PromptTemplateRelease,
    PromptTemplateVersion,
)
from backend.app.model_gateway.schemas import (
    ModelGatewayInvocationCreate,
    ModelGatewayInvocationRead,
    ModelGatewayPolicyCreate,
    ModelGatewayPolicyRead,
    PromptTemplateCreate,
    PromptTemplateRead,
    PromptTemplateReleaseRead,
    PromptTemplateVersionCreate,
    PromptTemplateVersionRead,
)
from backend.app.observability.models import RuntimeTraceSpan
from backend.app.observability.projection import model_invocation_to_span

PROTECTED_PROMPT_LABELS = frozenset({"production", "staging", "latest"})
RELEASE_EVAL_GATE_THRESHOLDS = {
    "average_recall_at_k": 0.8,
    "average_mrr": 0.5,
    "average_context_recall": 0.8,
}


class PromptReleaseEvalGateFailed(ValueError):
    """Raised when a protected prompt release does not meet eval gate requirements."""


class PromptTemplateVersionNotFound(LookupError):
    """Raised when a prompt template version cannot be resolved in the project scope."""


class PromptReleaseTargetInvalid(ValueError):
    """Raised when a prompt release label or environment is invalid after normalization."""


class PromptReleaseConflict(RuntimeError):
    """Raised when an active prompt release changed concurrently."""


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

    async def list_prompt_templates(self, project_id: UUID) -> list[PromptTemplateRead]:
        statement = (
            select(PromptTemplate)
            .where(PromptTemplate.project_id == project_id)
            .order_by(PromptTemplate.template_ref, PromptTemplate.id)
        )
        result = await self._session.execute(statement)
        return [PromptTemplateRead.model_validate(template) for template in result.scalars().all()]

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

    async def publish_prompt_template_release(
        self,
        *,
        project_id: UUID,
        template_ref: str,
        version: str,
        label: str,
        environment: str,
        eval_run_id: UUID | None,
        release_note: str,
        actor_id: UUID,
    ) -> PromptTemplateReleaseRead:
        normalized_label = _normalize_release_part(label)
        normalized_environment = _normalize_release_part(environment)
        if not normalized_label:
            raise PromptReleaseTargetInvalid("prompt release label must not be blank")
        if not normalized_environment:
            raise PromptReleaseTargetInvalid("prompt release environment must not be blank")
        prompt_version = await self._get_prompt_template_version_model(
            project_id=project_id,
            template_ref=template_ref,
            version=version,
        )
        is_protected = normalized_label in PROTECTED_PROMPT_LABELS
        eval_gate_status = await self._validate_prompt_release_eval_gate(
            project_id=project_id,
            eval_run_id=eval_run_id,
            is_protected=is_protected,
        )

        await self._session.execute(
            update(PromptTemplateRelease)
            .where(
                PromptTemplateRelease.project_id == project_id,
                PromptTemplateRelease.template_id == prompt_version.template_id,
                PromptTemplateRelease.label == normalized_label,
                PromptTemplateRelease.environment == normalized_environment,
                PromptTemplateRelease.status == "active",
            )
            .values(status="archived", updated_by=actor_id)
        )
        release = PromptTemplateRelease(
            project_id=project_id,
            template_id=prompt_version.template_id,
            template_ref=template_ref,
            version_id=prompt_version.id,
            version=prompt_version.version,
            label=normalized_label,
            environment=normalized_environment,
            status="active",
            is_protected=is_protected,
            eval_gate_status=eval_gate_status,
            eval_run_id=eval_run_id,
            release_note=release_note,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(release)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise PromptReleaseConflict(
                "active prompt release changed concurrently; retry publish",
            ) from exc
        await self._session.refresh(release)
        return PromptTemplateReleaseRead.model_validate(release)

    async def list_prompt_template_releases(
        self,
        *,
        project_id: UUID,
        template_ref: str,
        label: str | None = None,
        environment: str | None = None,
    ) -> list[PromptTemplateReleaseRead]:
        conditions = [
            PromptTemplateRelease.project_id == project_id,
            PromptTemplateRelease.template_ref == template_ref,
        ]
        if label:
            conditions.append(PromptTemplateRelease.label == _normalize_release_part(label))
        if environment:
            conditions.append(
                PromptTemplateRelease.environment == _normalize_release_part(environment)
            )

        statement = (
            select(PromptTemplateRelease)
            .where(*conditions)
            .order_by(PromptTemplateRelease.created_at.desc(), PromptTemplateRelease.id.desc())
        )
        result = await self._session.execute(statement)
        return [
            PromptTemplateReleaseRead.model_validate(release) for release in result.scalars().all()
        ]

    async def get_prompt_template_version_by_label(
        self,
        *,
        project_id: UUID,
        template_ref: str,
        label: str,
        environment: str,
    ) -> PromptTemplateVersionRead | None:
        statement = (
            select(PromptTemplateVersion)
            .join(PromptTemplate, PromptTemplate.id == PromptTemplateVersion.template_id)
            .join(
                PromptTemplateRelease, PromptTemplateRelease.version_id == PromptTemplateVersion.id
            )
            .where(
                PromptTemplateRelease.project_id == project_id,
                PromptTemplateRelease.template_ref == template_ref,
                PromptTemplateRelease.label == _normalize_release_part(label),
                PromptTemplateRelease.environment == _normalize_release_part(environment),
                PromptTemplateRelease.status == "active",
                PromptTemplateVersion.project_id == project_id,
                PromptTemplateVersion.status == "active",
                PromptTemplate.project_id == project_id,
                PromptTemplate.template_ref == template_ref,
                PromptTemplate.status == "active",
            )
            .order_by(PromptTemplateRelease.created_at.desc(), PromptTemplateRelease.id.desc())
            .limit(1)
        )
        result = await self._session.execute(statement)
        prompt_version = result.scalar_one_or_none()
        if prompt_version is None:
            return None
        return PromptTemplateVersionRead.model_validate(prompt_version)

    async def record_invocation(
        self,
        request: ModelGatewayInvocationCreate,
    ) -> ModelGatewayInvocationRead:
        invocation = ModelGatewayInvocation(**request.model_dump())
        self._session.add(invocation)
        await self._session.flush()
        trace_span = RuntimeTraceSpan(**model_invocation_to_span(invocation).model_dump())
        self._session.add(trace_span)
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

    async def _get_prompt_template_version_model(
        self,
        *,
        project_id: UUID,
        template_ref: str,
        version: str,
    ) -> PromptTemplateVersion:
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
            raise PromptTemplateVersionNotFound("Prompt template version not found")
        return prompt_version

    async def _validate_prompt_release_eval_gate(
        self,
        *,
        project_id: UUID,
        eval_run_id: UUID | None,
        is_protected: bool,
    ) -> str:
        if not is_protected:
            return "not_required"
        if eval_run_id is None:
            raise PromptReleaseEvalGateFailed(
                "protected prompt release requires a passing eval gate",
            )

        run = await self._session.scalar(
            select(RetrievalEvalRun).where(
                RetrievalEvalRun.project_id == project_id,
                RetrievalEvalRun.id == eval_run_id,
            )
        )
        if run is None:
            raise PromptReleaseEvalGateFailed("eval gate run not found for project")
        if run.status != "completed":
            raise PromptReleaseEvalGateFailed("eval gate run is not completed")
        if run.case_count <= 0:
            raise PromptReleaseEvalGateFailed("eval gate requires at least one case")
        if run.leakage_count > 0:
            raise PromptReleaseEvalGateFailed("eval gate leakage_count must be zero")
        if run.deleted_visible_count > 0:
            raise PromptReleaseEvalGateFailed("eval gate deleted_visible_count must be zero")
        for metric, minimum in RELEASE_EVAL_GATE_THRESHOLDS.items():
            value = getattr(run, metric)
            if value < minimum:
                raise PromptReleaseEvalGateFailed(
                    f"eval gate {metric}={value:.3f} is below {minimum:.3f}",
                )
        return "passed"


def _normalize_release_part(value: str) -> str:
    return value.strip().lower()
