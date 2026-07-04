from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_workflow_runtime_runner,
    get_workflow_version_store,
)
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.workflow_runtime.schemas import WorkflowRunRequest, WorkflowRunResult
from backend.app.workflows.schemas import WorkflowPublishGateResult, WorkflowVersionRead
from backend.app.workflows.yaml_io import WorkflowImportAnalysis, WorkflowImportDiff
from backend.tests.test_workflow_runtime import workflow_with_human_approval
from fastapi.testclient import TestClient


class PermissionAwareProjectProvider(ProjectAccessProvider):
    def __init__(self, projects: Iterable[ProjectSummary]) -> None:
        self._projects = {project.id: project for project in projects}

    def list_visible_projects(self, principal: AccountPrincipal) -> list[ProjectSummary]:
        return list(self._projects.values())

    def get_project_for_account(
        self,
        principal: AccountPrincipal,
        project_id: UUID,
        required_permission: str,
    ) -> ProjectSummary | None:
        project = self._projects.get(project_id)
        if project is None:
            return None
        if required_permission not in project.permissions:
            raise PermissionError(required_permission)
        return project


class InMemoryVersionStore:
    def __init__(self, version: WorkflowVersionRead | None) -> None:
        self.version = version

    async def get_project_version(
        self,
        project_id: UUID,
        version_id: UUID,
    ) -> WorkflowVersionRead | None:
        if self.version is None:
            return None
        if self.version.project_id != project_id or self.version.id != version_id:
            return None
        return self.version


class RecordingRuntimeRunner:
    def __init__(self) -> None:
        self.requests: list[WorkflowRunRequest] = []

    async def run(self, request: WorkflowRunRequest) -> WorkflowRunResult:
        self.requests.append(request)
        now = datetime.now(UTC)
        return WorkflowRunResult(
            id=uuid4(),
            project_id=request.project_id,
            workflow_version_id=request.version.id,
            workflow_ref=f"{request.version.workflow_id}:{request.version.version}",
            run_id=request.run_id or "run-api",
            trace_id=request.trace_id or "trace-api",
            status="success",
            outputs={"ok": True},
            node_results=[],
            created_at=now,
            updated_at=now,
        )


class RecordingAuditStore:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def record_project_event(self, **kwargs: object) -> None:
        self.events.append(kwargs)


def test_workflow_runtime_api_requires_workflow_run_permission() -> None:
    project_id = uuid4()
    account = AccountPrincipal(account_id=uuid4(), status="active")
    version = make_version(project_id)
    client, _, _ = build_client(
        account=account,
        project=make_project(project_id, permissions=["workflow:view"]),
        version=version,
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/workflows/versions/{version.id}/runs",
        json={"inputs": {}},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required project permission"}


def test_workflow_runtime_api_runs_published_version_and_audits() -> None:
    project_id = uuid4()
    account = AccountPrincipal(account_id=uuid4(), status="active")
    version = make_version(project_id)
    client, runner, audit_store = build_client(
        account=account,
        project=make_project(project_id, permissions=["workflow:run"]),
        version=version,
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/workflows/versions/{version.id}/runs",
        json={
            "inputs": {"change_id": "CHG-123"},
            "run_ref": "run-api",
            "trace_id": "trace-api",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "success"
    assert response.json()["run_id"] == "run-api"
    assert len(runner.requests) == 1
    assert runner.requests[0].inputs == {"change_id": "CHG-123"}
    assert audit_store.events[-1]["action"] == "workflow.run.start"
    metadata = audit_store.events[-1]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["status"] == "success"


def build_client(
    *,
    account: AccountPrincipal,
    project: ProjectSummary,
    version: WorkflowVersionRead,
) -> tuple[TestClient, RecordingRuntimeRunner, RecordingAuditStore]:
    app = create_app()
    runner = RecordingRuntimeRunner()
    audit_store = RecordingAuditStore()
    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: PermissionAwareProjectProvider(
        [project]
    )
    app.dependency_overrides[get_workflow_version_store] = lambda: InMemoryVersionStore(version)
    app.dependency_overrides[get_workflow_runtime_runner] = lambda: runner
    app.dependency_overrides[get_audit_event_store] = lambda: audit_store
    return TestClient(app), runner, audit_store


def make_project(project_id: UUID, *, permissions: list[str]) -> ProjectSummary:
    return ProjectSummary(
        id=project_id,
        slug=f"project-{project_id.hex[:8]}",
        name="Workflow Runtime API",
        status="active",
        roles=["workflow_runner"],
        permissions=permissions,
    )


def make_version(project_id: UUID) -> WorkflowVersionRead:
    now = datetime.now(UTC)
    definition = workflow_with_human_approval()
    return WorkflowVersionRead(
        id=uuid4(),
        project_id=project_id,
        workflow_id=definition.workflow.id,
        name=definition.workflow.name,
        version=definition.workflow.version,
        status="published",
        definition=definition,
        analysis=WorkflowImportAnalysis(
            permission_impact=definition.permission_impact(),
            missing_references=[],
            import_diff=WorkflowImportDiff(
                added_nodes=[],
                modified_nodes=[],
                removed_nodes=[],
                added_edges=[],
                removed_edges=[],
                changed_tool_groups=[],
                has_breaking_changes=False,
            ),
            can_create_draft=True,
            can_publish_or_run=True,
        ),
        gate_result=WorkflowPublishGateResult(can_publish=True, reasons=[]),
        definition_hash="sha256:api",
        release_note="api test",
        published_by=uuid4(),
        archived_by=None,
        archived_at=None,
        created_by=uuid4(),
        updated_by=uuid4(),
        created_at=now,
        updated_at=now,
    )
