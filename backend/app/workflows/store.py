from typing import Protocol
from uuid import UUID

from backend.app.workflows.dsl import WorkflowDefinition
from backend.app.workflows.schemas import (
    WorkflowDraftRead,
    WorkflowPublishGateResult,
    WorkflowVersionRead,
)
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


class WorkflowVersionConflict(RuntimeError):
    """Raised when publishing would duplicate an immutable workflow version."""


class WorkflowVersionStore(Protocol):
    async def publish_project_version(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        draft: WorkflowDraftRead,
        analysis: WorkflowImportAnalysis,
        gate_result: WorkflowPublishGateResult,
        release_note: str,
    ) -> WorkflowVersionRead:
        raise NotImplementedError

    async def list_project_versions(
        self,
        *,
        project_id: UUID,
        workflow_id: str | None = None,
    ) -> list[WorkflowVersionRead]:
        raise NotImplementedError

    async def get_project_version(
        self,
        project_id: UUID,
        version_id: UUID,
    ) -> WorkflowVersionRead | None:
        raise NotImplementedError

    async def restore_version_as_draft(
        self,
        *,
        project_id: UUID,
        version_id: UUID,
        actor_id: UUID,
        draft_store: WorkflowDraftStore,
    ) -> WorkflowDraftRead | None:
        raise NotImplementedError

    async def archive_project_version(
        self,
        *,
        project_id: UUID,
        version_id: UUID,
        actor_id: UUID,
    ) -> WorkflowVersionRead | None:
        raise NotImplementedError
