from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_tool_registry_store,
)
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.tool_registry.schemas import (
    EnvironmentCreateRequest,
    EnvironmentRead,
    McpServerCreateRequest,
    McpServerRead,
    ShellTemplateCreateRequest,
    ShellTemplateRead,
    ToolDefinitionRead,
    ToolGroupCreateRequest,
    ToolGroupRead,
    ToolSyncRunRead,
)
from backend.app.tool_registry.store import ToolRegistryResourceNotFoundError, ToolSyncFailedError
from backend.app.workflows.yaml_io import ProjectResourceCatalog
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


class InMemoryToolRegistryStore:
    def __init__(self) -> None:
        self.catalogs: dict[UUID, ProjectResourceCatalog] = {}
        self.tool_definitions: dict[UUID, list[ToolDefinitionRead]] = {}
        self.fail_next_sync = False

    async def build_project_resource_catalog(self, project_id: UUID) -> ProjectResourceCatalog:
        return self.catalogs.get(project_id, ProjectResourceCatalog())

    async def create_environment(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: EnvironmentCreateRequest,
    ) -> EnvironmentRead:
        key = str(request.key)
        self.catalogs[project_id] = self.catalogs.get(
            project_id,
            ProjectResourceCatalog(),
        ).model_copy(update={"environments": frozenset({key})})
        return EnvironmentRead(**_resource(project_id, actor_id, key=key, name=str(request.name)))

    async def create_mcp_server(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: McpServerCreateRequest,
    ) -> McpServerRead:
        server_ref = str(request.server_ref)
        catalog = self.catalogs.get(project_id, ProjectResourceCatalog())
        self.catalogs[project_id] = catalog.model_copy(
            update={"mcp_servers": catalog.mcp_servers | frozenset({server_ref})}
        )
        resource = McpServerRead(
            **_resource(
                project_id,
                actor_id,
                name=str(request.name),
                server_ref=server_ref,
                base_url=str(request.base_url),
                transport=str(request.transport),
                environment_key=str(request.environment_key),
                owner=str(request.owner),
                last_health_status="unknown",
                last_health_checked_at=None,
                last_sync_version=0,
                last_sync_status="never",
                last_sync_error="",
            )
        )
        self.tool_definitions.setdefault(project_id, [])
        return resource

    async def create_tool_group(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ToolGroupCreateRequest,
    ) -> ToolGroupRead:
        group_ref = str(request.group_ref)
        catalog = self.catalogs.get(project_id, ProjectResourceCatalog())
        self.catalogs[project_id] = catalog.model_copy(
            update={"tool_groups": catalog.tool_groups | frozenset({group_ref})}
        )
        return ToolGroupRead(
            **_resource(
                project_id,
                actor_id,
                name=str(request.name),
                group_ref=group_ref,
                risk_level=str(request.risk_level),
                environment_key=str(request.environment_key),
            )
        )

    async def list_project_tool_definitions(self, project_id: UUID) -> list[ToolDefinitionRead]:
        return self.tool_definitions.get(project_id, [])

    async def sync_mcp_server_tools(
        self,
        *,
        project_id: UUID,
        mcp_server_id: UUID,
        actor_id: UUID,
        tools_client: object,
    ) -> ToolSyncRunRead:
        if self.fail_next_sync:
            raise ToolSyncFailedError(
                public_message="Authorization failed for bearer [redacted]",
                target_id=str(mcp_server_id),
            )
        if project_id not in self.catalogs:
            raise ToolRegistryResourceNotFoundError("mcp server not found")

        now = datetime.now(UTC).isoformat()
        definition = ToolDefinitionRead(
            id=uuid4(),
            project_id=project_id,
            mcp_server_id=mcp_server_id,
            server_ref="mcp-k8s-test",
            tool_ref="mcp-k8s-test.kubectl_get_pods",
            tool_name="kubectl_get_pods",
            display_name="获取 Pod",
            description="List pods",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            annotations={"readOnlyHint": True, "openWorldHint": False},
            risk_level="low",
            schema_hash="sha256:pods",
            sync_version=1,
            status="active",
            last_seen_at=now,
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        self.tool_definitions[project_id] = [definition]
        return ToolSyncRunRead(
            id=uuid4(),
            project_id=project_id,
            mcp_server_id=mcp_server_id,
            server_ref="mcp-k8s-test",
            sync_version=1,
            status="success",
            started_at=now,
            finished_at=now,
            tool_count=1,
            error_type="",
            error_message="",
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
            tool_definitions=[definition],
        )

    async def create_shell_template(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellTemplateCreateRequest,
    ) -> ShellTemplateRead:
        template_ref = str(request.template_ref)
        template_version = int(request.template_version)
        reference = f"{template_ref}@{template_version}"
        catalog = self.catalogs.get(project_id, ProjectResourceCatalog())
        self.catalogs[project_id] = catalog.model_copy(
            update={"shell_templates": catalog.shell_templates | frozenset({reference})}
        )
        return ShellTemplateRead(
            **_resource(
                project_id,
                actor_id,
                name=str(request.name),
                template_ref=template_ref,
                template_version=template_version,
                risk_level=str(request.risk_level),
                environment_key=str(request.environment_key),
            )
        )


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


def _resource(
    project_id: UUID,
    actor_id: UUID,
    *,
    name: str,
    key: str | None = None,
    **extra: object,
) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    resource = {
        "id": str(uuid4()),
        "project_id": str(project_id),
        "name": name,
        "status": "active",
        "description": "",
        "created_by": str(actor_id),
        "updated_by": str(actor_id),
        "created_at": now,
        "updated_at": now,
        **extra,
    }
    if key is not None:
        resource["key"] = key
    return resource


def build_client(
    *,
    account: AccountPrincipal,
    provider: ProjectAccessProvider,
    registry_store: InMemoryToolRegistryStore,
    audit_store: InMemoryAuditEventStore,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: provider
    app.dependency_overrides[get_tool_registry_store] = lambda: registry_store
    app.dependency_overrides[get_audit_event_store] = lambda: audit_store
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
        roles=["project_admin"],
        permissions=permissions,
    )


def test_tool_registry_creates_project_resources_and_returns_catalog() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
    )

    assert (
        client.post(
            f"/api/v1/projects/{project.id}/tool-registry/environments",
            json={"key": "test", "name": "测试环境"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/v1/projects/{project.id}/tool-registry/mcp-servers",
            json={
                "server_ref": "mcp-k8s-test",
                "name": "K8s 测试 MCP",
                "base_url": "https://mcp.internal.example/k8s",
                "environment_key": "test",
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/v1/projects/{project.id}/tool-registry/tool-groups",
            json={
                "group_ref": "k8s.readonly",
                "name": "K8s 只读工具",
                "risk_level": "medium",
                "environment_key": "test",
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/v1/projects/{project.id}/tool-registry/shell-templates",
            json={
                "template_ref": "k8s-log-collector",
                "template_version": 3,
                "name": "日志采集",
                "risk_level": "medium",
                "environment_key": "test",
            },
        ).status_code
        == 201
    )

    response = client.get(f"/api/v1/projects/{project.id}/tool-registry/catalog")

    assert response.status_code == 200
    assert response.json() == {
        "tool_groups": ["k8s.readonly"],
        "mcp_servers": ["mcp-k8s-test"],
        "shell_templates": ["k8s-log-collector@3"],
        "environments": ["test"],
    }
    assert [event["action"] for event in audit_store.events] == [
        "tool_registry.environment.create",
        "tool_registry.mcp_server.create",
        "tool_registry.tool_group.create",
        "tool_registry.shell_template.create",
        "tool_registry.catalog.view",
    ]


def test_tool_registry_syncs_mcp_tools_and_lists_project_tool_definitions() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    account = make_account()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
    )
    created = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/mcp-servers",
        json={
            "server_ref": "mcp-k8s-test",
            "name": "K8s 测试 MCP",
            "base_url": "https://mcp.internal.example/k8s",
            "environment_key": "test",
        },
    )
    server_id = created.json()["id"]

    sync_response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/mcp-servers/{server_id}/sync-tools"
    )
    list_response = client.get(f"/api/v1/projects/{project.id}/tool-registry/tool-definitions")

    assert sync_response.status_code == 200
    assert sync_response.json()["status"] == "success"
    assert sync_response.json()["tool_definitions"][0]["tool_ref"] == (
        "mcp-k8s-test.kubectl_get_pods"
    )
    assert list_response.status_code == 200
    assert list_response.json()[0]["risk_level"] == "low"
    assert [event["action"] for event in audit_store.events][-2:] == [
        "tool_registry.mcp_server.sync_tools",
        "tool_registry.tool_definition.list",
    ]


def test_tool_registry_sync_failure_returns_sanitized_error_and_audit_failure() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    registry_store.fail_next_sync = True
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
    )
    created = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/mcp-servers",
        json={
            "server_ref": "mcp-k8s-test",
            "name": "K8s 测试 MCP",
            "base_url": "https://mcp.internal.example/k8s",
            "environment_key": "test",
        },
    )
    server_id = created.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/mcp-servers/{server_id}/sync-tools"
    )

    assert response.status_code == 502
    assert "bearer [redacted]" in response.json()["detail"]
    assert "secret" not in response.text.lower()
    assert audit_store.events[-1]["action"] == "tool_registry.mcp_server.sync_tools"
    assert audit_store.events[-1]["result"] == "failure"


def test_tool_registry_enforces_view_and_write_permissions() -> None:
    project = make_project(permissions=["tool-registry:view"])
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=InMemoryToolRegistryStore(),
        audit_store=InMemoryAuditEventStore(),
    )

    denied_write = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/environments",
        json={"key": "test", "name": "测试环境"},
    )
    denied_sync = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/mcp-servers/{uuid4()}/sync-tools"
    )
    allowed_view = client.get(f"/api/v1/projects/{project.id}/tool-registry/catalog")

    assert denied_write.status_code == 403
    assert denied_sync.status_code == 403
    assert allowed_view.status_code == 200


def test_tool_registry_catalog_is_project_scoped() -> None:
    project = make_project(permissions=["tool-registry:view"])
    other_project = make_project(permissions=["tool-registry:view"])
    registry_store = InMemoryToolRegistryStore()
    registry_store.catalogs[other_project.id] = ProjectResourceCatalog(
        tool_groups=frozenset({"other.secret"}),
        mcp_servers=frozenset({"other-mcp"}),
        shell_templates=frozenset({"other-template@1"}),
        environments=frozenset({"prod"}),
    )
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project, other_project]),
        registry_store=registry_store,
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.get(f"/api/v1/projects/{project.id}/tool-registry/catalog")

    assert response.status_code == 200
    assert response.json() == {
        "tool_groups": [],
        "mcp_servers": [],
        "shell_templates": [],
        "environments": [],
    }
