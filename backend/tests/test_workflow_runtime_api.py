from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_workflow_run_store,
    get_workflow_runtime_runner,
    get_workflow_version_store,
)
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.workflow_runtime.schemas import (
    WorkflowRunCheckpointCreate,
    WorkflowRunCheckpointRead,
    WorkflowRunCreate,
    WorkflowRunRead,
    WorkflowRunRequest,
    WorkflowRunResult,
    WorkflowRunResumeRequest,
    WorkflowRunUpdate,
)
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


class InMemoryRunStore:
    def __init__(
        self,
        *,
        run: WorkflowRunRead | None = None,
        checkpoints: Iterable[WorkflowRunCheckpointRead] = (),
    ) -> None:
        self.run = run
        self.checkpoints = list(checkpoints)

    async def create_run(self, request: WorkflowRunCreate) -> WorkflowRunRead:
        raise NotImplementedError

    async def update_run(self, request: WorkflowRunUpdate) -> WorkflowRunRead:
        raise NotImplementedError

    async def get_run(
        self,
        *,
        project_id: UUID,
        run_id: str,
    ) -> WorkflowRunRead | None:
        if self.run is None:
            return None
        if self.run.project_id != project_id or self.run.run_id != run_id:
            return None
        return self.run

    async def record_checkpoint(
        self,
        request: WorkflowRunCheckpointCreate,
    ) -> WorkflowRunCheckpointRead:
        raise NotImplementedError

    async def list_checkpoints(
        self,
        *,
        project_id: UUID,
        run_id: str,
    ) -> list[WorkflowRunCheckpointRead]:
        return [
            checkpoint
            for checkpoint in self.checkpoints
            if checkpoint.project_id == project_id and checkpoint.run_id == run_id
        ]


class RecordingRuntimeRunner:
    def __init__(self) -> None:
        self.requests: list[WorkflowRunRequest] = []
        self.resume_requests: list[WorkflowRunResumeRequest] = []

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

    async def resume(self, request: WorkflowRunResumeRequest) -> WorkflowRunResult:
        self.resume_requests.append(request)
        now = datetime.now(UTC)
        return WorkflowRunResult(
            id=uuid4(),
            project_id=request.project_id,
            workflow_version_id=request.version.id,
            workflow_ref=f"{request.version.workflow_id}:{request.version.version}",
            run_id=request.run_id,
            trace_id="trace-api",
            status="success",
            outputs={"resumed": True},
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


def test_workflow_runtime_api_get_run_detail_requires_workflow_run_permission() -> None:
    project_id = uuid4()
    account = AccountPrincipal(account_id=uuid4(), status="active")
    version = make_version(project_id)
    run = make_run(project_id, version.id)
    client, _, _ = build_client(
        account=account,
        project=make_project(project_id, permissions=["workflow:view"]),
        version=version,
        run_store=InMemoryRunStore(run=run),
    )

    response = client.get(
        f"/api/v1/projects/{project_id}/workflows/versions/{version.id}/runs/{run.run_id}",
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required project permission"}


def test_workflow_runtime_api_get_run_detail_returns_checkpoints_and_audits() -> None:
    project_id = uuid4()
    account = AccountPrincipal(account_id=uuid4(), status="active")
    version = make_version(project_id)
    run = make_run(project_id, version.id, status="pending_approval")
    checkpoints = [
        make_checkpoint(
            project_id,
            version.id,
            workflow_run_id=run.id,
            run_id=run.run_id,
            trace_id=run.trace_id,
            node_id="human_approval_1",
            status="pending_approval",
        )
    ]
    client, _, audit_store = build_client(
        account=account,
        project=make_project(project_id, permissions=["workflow:run"]),
        version=version,
        run_store=InMemoryRunStore(run=run, checkpoints=checkpoints),
    )

    response = client.get(
        f"/api/v1/projects/{project_id}/workflows/versions/{version.id}/runs/{run.run_id}",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["run_id"] == "run-api"
    assert payload["run"]["trace_id"] == "trace-api"
    assert payload["run"]["status"] == "pending_approval"
    assert payload["checkpoints"][0]["node_id"] == "human_approval_1"
    assert payload["checkpoints"][0]["status"] == "pending_approval"
    assert audit_store.events[-1]["action"] == "workflow.run.view"
    metadata = audit_store.events[-1]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["checkpoint_count"] == 1


def test_workflow_runtime_api_get_run_detail_hides_version_mismatch() -> None:
    project_id = uuid4()
    account = AccountPrincipal(account_id=uuid4(), status="active")
    version = make_version(project_id)
    run = make_run(project_id, uuid4())
    client, _, _ = build_client(
        account=account,
        project=make_project(project_id, permissions=["workflow:run"]),
        version=version,
        run_store=InMemoryRunStore(run=run),
    )

    response = client.get(
        f"/api/v1/projects/{project_id}/workflows/versions/{version.id}/runs/{run.run_id}",
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Workflow run not found"}


def test_workflow_runtime_api_resume_requires_workflow_run_permission() -> None:
    project_id = uuid4()
    account = AccountPrincipal(account_id=uuid4(), status="active")
    version = make_version(project_id)
    client, _, _ = build_client(
        account=account,
        project=make_project(project_id, permissions=["workflow:view"]),
        version=version,
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/workflows/versions/{version.id}/runs/run-api/resume",
        json={"decision": "approved"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required project permission"}


def test_workflow_runtime_api_resumes_run_and_audits() -> None:
    project_id = uuid4()
    account = AccountPrincipal(account_id=uuid4(), status="active")
    version = make_version(project_id)
    approval_task_id = uuid4()
    client, runner, audit_store = build_client(
        account=account,
        project=make_project(project_id, permissions=["workflow:run"]),
        version=version,
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/workflows/versions/{version.id}/runs/run-api/resume",
        json={
            "decision": "approved",
            "payload": {"reason": "ok"},
            "approval_task_id": str(approval_task_id),
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert len(runner.resume_requests) == 1
    assert runner.resume_requests[0].run_id == "run-api"
    assert runner.resume_requests[0].approval_task_id == approval_task_id
    assert audit_store.events[-1]["action"] == "workflow.run.resume"
    metadata = audit_store.events[-1]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["status"] == "success"


def build_client(
    *,
    account: AccountPrincipal,
    project: ProjectSummary,
    version: WorkflowVersionRead,
    run_store: InMemoryRunStore | None = None,
) -> tuple[TestClient, RecordingRuntimeRunner, RecordingAuditStore]:
    app = create_app()
    runner = RecordingRuntimeRunner()
    audit_store = RecordingAuditStore()
    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: PermissionAwareProjectProvider(
        [project]
    )
    app.dependency_overrides[get_workflow_version_store] = lambda: InMemoryVersionStore(version)
    app.dependency_overrides[get_workflow_run_store] = lambda: run_store or InMemoryRunStore()
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


def make_run(
    project_id: UUID,
    version_id: UUID,
    *,
    status: str = "success",
) -> WorkflowRunRead:
    now = datetime.now(UTC)
    return WorkflowRunRead(
        id=uuid4(),
        project_id=project_id,
        actor_id=uuid4(),
        workflow_version_id=version_id,
        workflow_id="ops_incident_triage",
        workflow_ref="ops_incident_triage:1",
        definition_hash="sha256:api",
        run_id="run-api",
        trace_id="trace-api",
        status=status,
        inputs_summary="input keys: change_id",
        outputs_summary="awaiting approval" if status == "pending_approval" else "ok",
        error_type="",
        error_message="",
        pending_approval={
            "node_id": "human_approval_1",
            "node_name": "Approve rollout",
            "approval_policy_ref": "ops.approval",
            "message": "Human approval required",
            "approval_task_id": str(uuid4()),
        }
        if status == "pending_approval"
        else {},
        created_by=uuid4(),
        updated_by=uuid4(),
        created_at=now,
        updated_at=now,
    )


def make_checkpoint(
    project_id: UUID,
    version_id: UUID,
    *,
    workflow_run_id: UUID,
    run_id: str,
    trace_id: str,
    node_id: str,
    status: str,
) -> WorkflowRunCheckpointRead:
    now = datetime.now(UTC)
    return WorkflowRunCheckpointRead(
        id=uuid4(),
        project_id=project_id,
        actor_id=uuid4(),
        workflow_run_id=workflow_run_id,
        workflow_version_id=version_id,
        workflow_ref="ops_incident_triage:1",
        run_id=run_id,
        trace_id=trace_id,
        node_id=node_id,
        node_type="human_approval",
        status=status,
        state={"safe_summary": "approval checkpoint"},
        output={"summary": "awaiting approval"},
        error_type="",
        error_message="",
        created_by=uuid4(),
        updated_by=uuid4(),
        created_at=now,
        updated_at=now,
    )
