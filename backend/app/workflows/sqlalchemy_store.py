from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.workflows.dsl import WorkflowDefinition
from backend.app.workflows.models import WorkflowDraft
from backend.app.workflows.schemas import WorkflowDraftRead
from backend.app.workflows.yaml_io import WorkflowImportAnalysis


class SqlAlchemyWorkflowDraftStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_project_drafts(self, project_id: UUID) -> list[WorkflowDraftRead]:
        result = await self._session.scalars(
            select(WorkflowDraft)
            .where(WorkflowDraft.project_id == project_id)
            .order_by(WorkflowDraft.updated_at.desc())
        )
        return [_draft_to_read(draft) for draft in result.all()]

    async def get_project_draft(
        self,
        project_id: UUID,
        draft_id: UUID,
    ) -> WorkflowDraftRead | None:
        draft = await self._session.get(WorkflowDraft, draft_id)
        if draft is None or draft.project_id != project_id:
            return None
        return _draft_to_read(draft)

    async def upsert_project_draft(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        workflow: WorkflowDefinition,
        analysis: WorkflowImportAnalysis,
    ) -> WorkflowDraftRead:
        existing = await self._session.scalar(
            select(WorkflowDraft).where(
                WorkflowDraft.project_id == project_id,
                WorkflowDraft.workflow_id == workflow.workflow.id,
                WorkflowDraft.version == workflow.workflow.version,
            )
        )
        if existing is None:
            existing = WorkflowDraft(
                project_id=project_id,
                workflow_id=workflow.workflow.id,
                name=workflow.workflow.name,
                version=workflow.workflow.version,
                status=workflow.workflow.status,
                definition=workflow.model_dump(mode="json"),
                analysis=analysis.model_dump(mode="json"),
                can_publish_or_run=analysis.can_publish_or_run,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self._session.add(existing)
        else:
            _apply_definition(existing, actor_id=actor_id, workflow=workflow, analysis=analysis)

        await self._session.commit()
        await self._session.refresh(existing)
        return _draft_to_read(existing)

    async def update_project_draft(
        self,
        *,
        project_id: UUID,
        draft_id: UUID,
        actor_id: UUID,
        workflow: WorkflowDefinition,
        analysis: WorkflowImportAnalysis,
    ) -> WorkflowDraftRead | None:
        draft = await self._session.get(WorkflowDraft, draft_id)
        if draft is None or draft.project_id != project_id:
            return None

        _apply_definition(draft, actor_id=actor_id, workflow=workflow, analysis=analysis)
        await self._session.commit()
        await self._session.refresh(draft)
        return _draft_to_read(draft)

    async def delete_project_draft(self, project_id: UUID, draft_id: UUID) -> bool:
        draft = await self._session.get(WorkflowDraft, draft_id)
        if draft is None or draft.project_id != project_id:
            return False

        await self._session.delete(draft)
        await self._session.commit()
        return True


def _apply_definition(
    draft: WorkflowDraft,
    *,
    actor_id: UUID,
    workflow: WorkflowDefinition,
    analysis: WorkflowImportAnalysis,
) -> None:
    draft.workflow_id = workflow.workflow.id
    draft.name = workflow.workflow.name
    draft.version = workflow.workflow.version
    draft.status = workflow.workflow.status
    draft.definition = workflow.model_dump(mode="json")
    draft.analysis = analysis.model_dump(mode="json")
    draft.can_publish_or_run = analysis.can_publish_or_run
    draft.updated_by = actor_id


def _draft_to_read(draft: WorkflowDraft) -> WorkflowDraftRead:
    return WorkflowDraftRead(
        id=draft.id,
        project_id=draft.project_id,
        workflow_id=draft.workflow_id,
        name=draft.name,
        version=draft.version,
        status=draft.status,
        definition=WorkflowDefinition.model_validate(draft.definition),
        analysis=WorkflowImportAnalysis.model_validate(draft.analysis),
        can_publish_or_run=draft.can_publish_or_run,
        created_by=draft.created_by,
        updated_by=draft.updated_by,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )
