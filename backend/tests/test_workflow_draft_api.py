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
from backend.app.workflows.yaml_io import (
    ProjectResourceCatalog,
    WorkflowImportAnalysis,
    import_workflow_yaml,
)
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
        existing = await self.get_project_draft(project_id, draft_id)
        if existing is None:
            return None

        updated = existing.model_copy(
            update={
                "workflow_id": workflow.workflow.id,
                "name": workflow.workflow.name,
                "version": workflow.workflow.version,
                "status": workflow.workflow.status,
                "definition": workflow,
                "analysis": analysis,
                "can_publish_or_run": analysis.can_publish_or_run,
                "updated_by": actor_id,
                "updated_at": datetime.now(UTC),
            }
        )
        self.drafts[draft_id] = updated
        return updated

    async def delete_project_draft(self, project_id: UUID, draft_id: UUID) -> bool:
        draft = await self.get_project_draft(project_id, draft_id)
        if draft is None:
            return False
        del self.drafts[draft_id]
        return True


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


def make_project(
    project_id: UUID | None = None,
    *,
    permissions: list[str],
) -> ProjectSummary:
    resolved_id = project_id or uuid4()
    return ProjectSummary(
        id=resolved_id,
        slug=f"project-{resolved_id.hex[:8]}",
        name="运维排障项目",
        status="active",
        roles=["workflow_builder"],
        permissions=permissions,
    )


def workflow_yaml(project_id: UUID, *, workflow_id: str = "ops_502_diagnosis") -> str:
    return f"""
schema_version: workflow.dsl/v0.1
workflow:
  id: {workflow_id}
  name: 502 排障助手
  project_id: "{project_id}"
  version: 1
  status: draft
inputs:
  - key: incident_summary
    type: string
    required: true
    description: 用户输入的故障摘要
nodes:
  - id: start_1
    name: 开始
    type: start
  - id: tool_1
    name: 查询 Pod 状态
    type: mcp_tool
    risk_level: medium
    data:
      mcp_server_ref: mcp-k8s-test
      tool_group_ref: k8s.readonly
      tool_name: k8s.get_pod
      environment: test
  - id: end_1
    name: 结束
    type: end
edges:
  - source: start_1
    target: tool_1
  - source: tool_1
    target: end_1
policies:
  default_environment: test
  max_runtime_seconds: 900
  max_tool_calls: 20
"""


def renamed_workflow_payload(project_id: UUID) -> dict[str, object]:
    imported = import_workflow_yaml(workflow_yaml(project_id))
    workflow = imported.workflow.model_copy(
        update={
            "workflow": imported.workflow.workflow.model_copy(update={"name": "重命名后的排障助手"})
        }
    )
    return {"definition": workflow.model_dump(mode="json")}


def test_import_yaml_preview_requires_write_and_does_not_persist_draft() -> None:
    project = make_project(permissions=["workflow:view"])
    draft_store = InMemoryWorkflowDraftStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        draft_store=draft_store,
        audit_store=audit_store,
    )

    denied_response = client.post(
        f"/api/v1/projects/{project.id}/workflows/import-yaml/preview",
        json={"yaml_text": workflow_yaml(project.id)},
    )

    assert denied_response.status_code == 403
    assert draft_store.drafts == {}

    project_with_write = make_project(
        project.id,
        permissions=["workflow:view", "workflow:write"],
    )
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project_with_write]),
        draft_store=draft_store,
        audit_store=audit_store,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/workflows/import-yaml/preview",
        json={"yaml_text": workflow_yaml(project.id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow"]["nodes"][1]["name"] == "查询 Pod 状态"
    assert body["analysis"]["can_create_draft"] is True
    assert body["analysis"]["can_publish_or_run"] is False
    assert {
        (item["reference_type"], item["reference"])
        for item in body["analysis"]["missing_references"]
    } == {
        ("environment", "test"),
        ("mcp_server", "mcp-k8s-test"),
        ("tool_group", "k8s.readonly"),
    }
    assert draft_store.drafts == {}
    assert [event["action"] for event in audit_store.events] == ["workflow.import_preview"]


def test_import_yaml_preview_uses_project_tool_registry_catalog() -> None:
    project = make_project(permissions=["workflow:view", "workflow:write"])
    registry_store = InMemoryToolRegistryStore(
        {
            project.id: ProjectResourceCatalog(
                tool_groups=frozenset({"k8s.readonly"}),
                mcp_servers=frozenset({"mcp-k8s-test"}),
                shell_templates=frozenset(),
                environments=frozenset({"test"}),
            )
        }
    )
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        draft_store=InMemoryWorkflowDraftStore(),
        audit_store=InMemoryAuditEventStore(),
        registry_store=registry_store,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/workflows/import-yaml/preview",
        json={"yaml_text": workflow_yaml(project.id)},
    )

    assert response.status_code == 200
    assert response.json()["analysis"]["missing_references"] == []
    assert response.json()["analysis"]["can_publish_or_run"] is True


def test_import_draft_persists_project_draft_and_exports_round_trippable_yaml() -> None:
    project = make_project(permissions=["workflow:view", "workflow:write"])
    draft_store = InMemoryWorkflowDraftStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        draft_store=draft_store,
        audit_store=audit_store,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/workflows/import-yaml",
        json={"yaml_text": workflow_yaml(project.id)},
    )

    assert response.status_code == 201
    imported = response.json()
    draft_id = imported["id"]
    assert imported["project_id"] == str(project.id)
    assert imported["workflow_id"] == "ops_502_diagnosis"
    assert imported["definition"]["nodes"][1]["name"] == "查询 Pod 状态"
    assert imported["can_publish_or_run"] is False

    list_response = client.get(f"/api/v1/projects/{project.id}/workflows/drafts")
    assert list_response.status_code == 200
    assert [draft["id"] for draft in list_response.json()["drafts"]] == [draft_id]

    get_response = client.get(f"/api/v1/projects/{project.id}/workflows/drafts/{draft_id}")
    assert get_response.status_code == 200
    assert get_response.json()["definition"]["workflow"]["project_id"] == str(project.id)

    export_response = client.get(
        f"/api/v1/projects/{project.id}/workflows/drafts/{draft_id}/export-yaml"
    )
    assert export_response.status_code == 200
    round_tripped = import_workflow_yaml(export_response.json()["yaml_text"])
    assert round_tripped.workflow.workflow.project_id == str(project.id)
    assert round_tripped.workflow.nodes[1].name == "查询 Pod 状态"

    assert [event["action"] for event in audit_store.events] == [
        "workflow.import_draft",
        "workflow.draft.export_yaml",
    ]


def test_import_yaml_rejects_project_mismatch() -> None:
    project = make_project(permissions=["workflow:view", "workflow:write"])
    other_project_id = uuid4()
    draft_store = InMemoryWorkflowDraftStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        draft_store=draft_store,
        audit_store=audit_store,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/workflows/import-yaml",
        json={"yaml_text": workflow_yaml(other_project_id)},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "workflow project_id must match project path"}
    assert draft_store.drafts == {}


def test_cross_project_draft_access_is_hidden() -> None:
    project = make_project(permissions=["workflow:view", "workflow:write"])
    other_project = make_project(permissions=["workflow:view"])
    draft_store = InMemoryWorkflowDraftStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project, other_project]),
        draft_store=draft_store,
        audit_store=audit_store,
    )
    import_response = client.post(
        f"/api/v1/projects/{project.id}/workflows/import-yaml",
        json={"yaml_text": workflow_yaml(project.id)},
    )
    draft_id = import_response.json()["id"]

    response = client.get(f"/api/v1/projects/{other_project.id}/workflows/drafts/{draft_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Workflow draft not found"}


def test_update_and_delete_workflow_draft_require_write_and_record_audit() -> None:
    project = make_project(permissions=["workflow:view", "workflow:write"])
    draft_store = InMemoryWorkflowDraftStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        draft_store=draft_store,
        audit_store=audit_store,
    )
    import_response = client.post(
        f"/api/v1/projects/{project.id}/workflows/import-yaml",
        json={"yaml_text": workflow_yaml(project.id)},
    )
    draft_id = import_response.json()["id"]

    update_response = client.put(
        f"/api/v1/projects/{project.id}/workflows/drafts/{draft_id}",
        json=renamed_workflow_payload(project.id),
    )

    assert update_response.status_code == 200
    assert update_response.json()["name"] == "重命名后的排障助手"

    delete_response = client.delete(f"/api/v1/projects/{project.id}/workflows/drafts/{draft_id}")

    assert delete_response.status_code == 204
    assert (
        client.get(f"/api/v1/projects/{project.id}/workflows/drafts/{draft_id}").status_code == 404
    )
    assert [event["action"] for event in audit_store.events] == [
        "workflow.import_draft",
        "workflow.draft.update",
        "workflow.draft.delete",
    ]


def test_publish_check_reanalyzes_draft_against_live_project_catalog_and_records_audit() -> None:
    project = make_project(permissions=["workflow:view", "workflow:write"])
    draft_store = InMemoryWorkflowDraftStore()
    audit_store = InMemoryAuditEventStore()
    registry_store = InMemoryToolRegistryStore(
        {
            project.id: ProjectResourceCatalog(
                tool_groups=frozenset({"k8s.readonly"}),
                mcp_servers=frozenset({"mcp-k8s-test"}),
                shell_templates=frozenset(),
                environments=frozenset({"test"}),
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
    import_response = client.post(
        f"/api/v1/projects/{project.id}/workflows/import-yaml",
        json={"yaml_text": workflow_yaml(project.id)},
    )
    draft_id = import_response.json()["id"]

    check_response = client.post(
        f"/api/v1/projects/{project.id}/workflows/drafts/{draft_id}/publish-check"
    )

    assert check_response.status_code == 200
    body = check_response.json()
    assert body["missing_references"] == []
    assert body["can_publish_or_run"] is True
    assert [event["action"] for event in audit_store.events] == [
        "workflow.import_draft",
        "workflow.draft.publish_check",
    ]

    registry_store.catalogs[project.id] = ProjectResourceCatalog()
    blocked_response = client.post(
        f"/api/v1/projects/{project.id}/workflows/drafts/{draft_id}/publish-check"
    )

    assert blocked_response.status_code == 200
    assert blocked_response.json()["can_publish_or_run"] is False
    assert {
        (item["reference_type"], item["reference"])
        for item in blocked_response.json()["missing_references"]
    } == {
        ("environment", "test"),
        ("mcp_server", "mcp-k8s-test"),
        ("tool_group", "k8s.readonly"),
    }
