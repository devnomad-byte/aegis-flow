from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_tool_registry_store,
    get_workflow_draft_store,
)
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.workflows.dsl import WorkflowDefinition
from backend.app.workflows.schemas import WorkflowDraftRead
from backend.app.workflows.yaml_io import ProjectResourceCatalog, WorkflowImportAnalysis
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


class InMemoryWorkflowDraftStore:
    def __init__(self) -> None:
        self.drafts: dict[UUID, WorkflowDraftRead] = {}

    async def list_project_drafts(self, project_id: UUID) -> list[WorkflowDraftRead]:
        return [draft for draft in self.drafts.values() if draft.project_id == project_id]

    async def get_project_draft(
        self,
        project_id: UUID,
        draft_id: UUID,
    ) -> WorkflowDraftRead | None:
        draft = self.drafts.get(draft_id)
        if draft is None or draft.project_id != project_id:
            return None
        return draft

    async def upsert_project_draft(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        workflow: WorkflowDefinition,
        analysis: WorkflowImportAnalysis,
    ) -> WorkflowDraftRead:
        now = datetime.now(UTC)
        existing = next(
            (
                draft
                for draft in self.drafts.values()
                if draft.project_id == project_id
                and draft.workflow_id == workflow.workflow.id
                and draft.version == workflow.workflow.version
            ),
            None,
        )
        draft_id = existing.id if existing is not None else uuid4()
        created_at = existing.created_at if existing is not None else now
        created_by = existing.created_by if existing is not None else actor_id
        draft = WorkflowDraftRead(
            id=draft_id,
            project_id=project_id,
            workflow_id=workflow.workflow.id,
            name=workflow.workflow.name,
            version=workflow.workflow.version,
            status=workflow.workflow.status,
            definition=workflow,
            analysis=analysis,
            can_publish_or_run=analysis.can_publish_or_run,
            created_by=created_by,
            updated_by=actor_id,
            created_at=created_at,
            updated_at=now,
        )
        self.drafts[draft_id] = draft
        return draft

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


class InMemoryAuditEventStore:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

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
        self.events.append(
            {
                "project_id": project_id,
                "actor_id": actor_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "result": result,
                "risk_level": risk_level,
                "metadata": metadata or {},
            }
        )


class InMemoryToolRegistryStore:
    def __init__(self, catalogs: dict[UUID, ProjectResourceCatalog] | None = None) -> None:
        self.catalogs = catalogs or {}

    async def build_project_resource_catalog(self, project_id: UUID) -> ProjectResourceCatalog:
        return self.catalogs.get(project_id, ProjectResourceCatalog())


def build_client(
    *,
    account: AccountPrincipal,
    provider: ProjectAccessProvider,
    draft_store: InMemoryWorkflowDraftStore,
    audit_store: InMemoryAuditEventStore,
    registry_store: InMemoryToolRegistryStore | None = None,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: provider
    app.dependency_overrides[get_workflow_draft_store] = lambda: draft_store
    app.dependency_overrides[get_audit_event_store] = lambda: audit_store
    app.dependency_overrides[get_tool_registry_store] = lambda: (
        registry_store or InMemoryToolRegistryStore()
    )
    return TestClient(app)


def make_account() -> AccountPrincipal:
    return AccountPrincipal(account_id=uuid4(), status="active")


def make_project(*, permissions: list[str]) -> ProjectSummary:
    project_id = uuid4()
    return ProjectSummary(
        id=project_id,
        slug=f"project-{project_id.hex[:8]}",
        name="运维排障项目",
        status="active",
        roles=["workflow_builder"],
        permissions=permissions,
    )


def test_list_workflow_templates_requires_view_and_returns_project_analysis() -> None:
    project = make_project(permissions=["workflow:view"])
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        draft_store=InMemoryWorkflowDraftStore(),
        audit_store=audit_store,
    )

    response = client.get(f"/api/v1/projects/{project.id}/workflow-templates")

    assert response.status_code == 200
    body = response.json()
    template_ids = {template["id"] for template in body["templates"]}
    assert {
        "ops-incident-diagnosis",
        "support-complaint-triage",
        "internal-reporting",
    } <= template_ids
    ops_template = next(
        template for template in body["templates"] if template["id"] == "ops-incident-diagnosis"
    )
    assert ops_template["category"] == "ops"
    assert ops_template["analysis"]["can_create_draft"] is True
    assert ops_template["analysis"]["can_publish_or_run"] is False
    assert {
        (item["reference_type"], item["reference"])
        for item in ops_template["analysis"]["missing_references"]
    } == {
        ("environment", "prod"),
        ("mcp_server", "mcp-k8s-prod"),
        ("tool_group", "k8s.readonly"),
    }
    assert audit_store.events[0]["action"] == "workflow_template.list"
    assert audit_store.events[0]["metadata"] == {"template_count": body["count"]}


def test_workflow_template_instantiate_creates_project_draft_and_sanitized_audit() -> None:
    project = make_project(permissions=["workflow:view", "workflow:write"])
    draft_store = InMemoryWorkflowDraftStore()
    audit_store = InMemoryAuditEventStore()
    registry_store = InMemoryToolRegistryStore(
        {
            project.id: ProjectResourceCatalog(
                tool_groups=frozenset({"k8s.readonly"}),
                mcp_servers=frozenset({"mcp-k8s-prod"}),
                shell_templates=frozenset(),
                environments=frozenset({"test", "prod"}),
            )
        }
    )
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        draft_store=draft_store,
        audit_store=audit_store,
        registry_store=registry_store,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/workflow-templates/ops-incident-diagnosis/instantiate",
        json={"workflow_name": "生产 502 排障助手"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["template"]["id"] == "ops-incident-diagnosis"
    assert body["draft"]["project_id"] == str(project.id)
    assert body["draft"]["workflow_id"] == "ops_incident_diagnosis"
    assert body["draft"]["name"] == "生产 502 排障助手"
    assert body["draft"]["definition"]["workflow"]["project_id"] == str(project.id)
    assert body["draft"]["analysis"]["missing_references"] == []
    assert body["draft"]["can_publish_or_run"] is True
    assert len(draft_store.drafts) == 1

    audit_text = "\n".join(str(event) for event in audit_store.events)
    assert "You are" not in audit_text
    assert "raw prompt" not in audit_text
    assert audit_store.events[-1]["action"] == "workflow_template.instantiate"
    assert audit_store.events[-1]["metadata"] == {
        "template_id": "ops-incident-diagnosis",
        "workflow_id": "ops_incident_diagnosis",
        "draft_id": body["draft"]["id"],
        "missing_reference_count": 0,
        "can_publish_or_run": True,
    }


def test_workflow_template_instantiate_requires_write_and_unknown_template_404() -> None:
    project = make_project(permissions=["workflow:view"])
    draft_store = InMemoryWorkflowDraftStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        draft_store=draft_store,
        audit_store=InMemoryAuditEventStore(),
    )

    denied = client.post(
        f"/api/v1/projects/{project.id}/workflow-templates/ops-incident-diagnosis/instantiate",
        json={},
    )

    assert denied.status_code == 403
    assert draft_store.drafts == {}

    project_with_write = ProjectSummary(
        id=project.id,
        slug=project.slug,
        name=project.name,
        status=project.status,
        roles=project.roles,
        permissions=["workflow:view", "workflow:write"],
    )
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project_with_write]),
        draft_store=draft_store,
        audit_store=InMemoryAuditEventStore(),
    )

    missing = client.post(
        f"/api/v1/projects/{project.id}/workflow-templates/no-such-template/instantiate",
        json={},
    )

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Workflow template not found"}
