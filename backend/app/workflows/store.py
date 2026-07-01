from typing import Protocol
from uuid import UUID

from backend.app.workflows.dsl import WorkflowDefinition
from backend.app.workflows.schemas import WorkflowDraftRead
from backend.app.workflows.yaml_io import WorkflowImportAnalysis


class WorkflowDraftStore(Protocol):
    async def list_project_drafts(self, project_id: UUID) -> list[WorkflowDraftRead]:
        raise NotImplementedError

    async def get_project_draft(
        self,
        project_id: UUID,
        draft_id: UUID,
    ) -> WorkflowDraftRead | None:
        raise NotImplementedError

    async def upsert_project_draft(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        workflow: WorkflowDefinition,
        analysis: WorkflowImportAnalysis,
    ) -> WorkflowDraftRead:
        raise NotImplementedError

    async def update_project_draft(
        self,
        *,
        project_id: UUID,
        draft_id: UUID,
        actor_id: UUID,
        workflow: WorkflowDefinition,
        analysis: WorkflowImportAnalysis,
    ) -> WorkflowDraftRead | None:
        raise NotImplementedError

    async def delete_project_draft(self, project_id: UUID, draft_id: UUID) -> bool:
        raise NotImplementedError
