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
    AuthorizedToolRead,
    AuthorizedToolsResolveResponse,
    CredentialAccessIntentRead,
    CredentialRefCreateRequest,
    CredentialRefRead,
    EnvironmentCreateRequest,
    EnvironmentRead,
    McpServerCreateRequest,
    McpServerRead,
    ShellTemplateCreateRequest,
    ShellTemplateRead,
    ToolDefinitionRead,
    ToolGroupCreateRequest,
    ToolGroupItemCreateRequest,
    ToolGroupItemRead,
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
        self.credential_refs: dict[UUID, list[CredentialRefRead]] = {}
        self.credential_access_intents: list[CredentialAccessIntentRead] = []
        self.tool_definitions: dict[UUID, list[ToolDefinitionRead]] = {}
        self.tool_groups: dict[UUID, list[ToolGroupRead]] = {}
        self.tool_group_items: dict[UUID, list[ToolGroupItemRead]] = {}
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
                credential_ref=str(request.credential_ref),
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
        group = ToolGroupRead(
            **_resource(
                project_id,
                actor_id,
                name=str(request.name),
                group_ref=group_ref,
                risk_level=str(request.risk_level),
                environment_key=str(request.environment_key),
            )
        )
        self.tool_groups.setdefault(project_id, []).append(group)
        return group

    async def create_credential_ref(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: CredentialRefCreateRequest,
    ) -> CredentialRefRead:
        now = datetime.now(UTC).isoformat()
        credential = CredentialRefRead(
            id=uuid4(),
            project_id=project_id,
            credential_ref=str(request.credential_ref),
            name=str(request.name),
            description=str(request.description),
            provider=str(request.provider),
            external_path=str(request.external_path),
            secret_kind=str(request.secret_kind),
            environment_key=str(request.environment_key),
            usage_scope=str(request.usage_scope),
            data_classification=str(request.data_classification),
            rotation_policy=str(request.rotation_policy),
            expires_at=request.expires_at,
            last_rotated_at=request.last_rotated_at,
            owner=str(request.owner),
            status="active",
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        self.credential_refs.setdefault(project_id, []).append(credential)
        return credential

    async def list_project_credential_refs(self, project_id: UUID) -> list[CredentialRefRead]:
        return self.credential_refs.get(project_id, [])

    async def archive_credential_ref(
        self,
        *,
        project_id: UUID,
        credential_ref_id: UUID,
        actor_id: UUID,
    ) -> CredentialRefRead:
        for credential in self.credential_refs.get(project_id, []):
            if credential.id == credential_ref_id:
                archived = credential.model_copy(
                    update={"status": "archived", "updated_by": actor_id}
                )
                self.credential_refs[project_id] = [
                    archived if item.id == credential_ref_id else item
                    for item in self.credential_refs[project_id]
                ]
                return archived
        raise ToolRegistryResourceNotFoundError("credential ref not found")

    async def record_credential_access_intent(
        self,
        *,
        project_id: UUID,
        credential_ref: str,
        actor_id: UUID,
        requester_type: str,
        requester_ref: str,
        purpose: str,
        run_id: str = "",
        node_id: str = "",
        trace_id: str = "",
    ) -> CredentialAccessIntentRead:
        for credential in self.credential_refs.get(project_id, []):
            if credential.credential_ref == credential_ref and credential.status == "active":
                now = datetime.now(UTC).isoformat()
                intent = CredentialAccessIntentRead(
                    id=uuid4(),
                    project_id=project_id,
                    credential_ref_id=credential.id,
                    credential_ref=credential_ref,
                    actor_id=actor_id,
                    requester_type=requester_type,
                    requester_ref=requester_ref,
                    purpose=purpose,
                    run_id=run_id,
                    node_id=node_id,
                    trace_id=trace_id,
                    decision="recorded",
                    denial_reason="",
                    created_by=actor_id,
                    updated_by=actor_id,
                    created_at=now,
                    updated_at=now,
                )
                self.credential_access_intents.append(intent)
                return intent
        raise ToolRegistryResourceNotFoundError("credential ref not found")

    async def list_project_tool_definitions(self, project_id: UUID) -> list[ToolDefinitionRead]:
        return self.tool_definitions.get(project_id, [])

    async def create_tool_group_item(
        self,
        *,
        project_id: UUID,
        tool_group_id: UUID,
        actor_id: UUID,
        request: ToolGroupItemCreateRequest,
    ) -> ToolGroupItemRead:
        group = self._find_tool_group(project_id, tool_group_id)
        definition = self._find_tool_definition(project_id, request.tool_definition_id)
        now = datetime.now(UTC).isoformat()
        risk_level_override = getattr(request, "risk_level_override", None)
        effective_risk_level = _highest_test_risk(
            [group.risk_level, definition.risk_level, risk_level_override or "low"]
        )
        item = ToolGroupItemRead(
            id=uuid4(),
            project_id=project_id,
            tool_group_id=group.id,
            tool_definition_id=definition.id,
            group_ref=group.group_ref,
            tool_ref=definition.tool_ref,
            server_ref=definition.server_ref,
            tool_name=definition.tool_name,
            display_name=definition.display_name,
            description=definition.description,
            input_schema=definition.input_schema,
            output_schema=definition.output_schema,
            annotations=definition.annotations,
            risk_level_override=risk_level_override,
            effective_risk_level=effective_risk_level,
            approval_required=bool(getattr(request, "approval_required", False)),
            parameter_policy=getattr(request, "parameter_policy", {}),
            allowed_role_refs=request.allowed_role_refs,
            allowed_workflow_refs=request.allowed_workflow_refs,
            allowed_agent_refs=request.allowed_agent_refs,
            status="active",
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        self.tool_group_items.setdefault(project_id, []).append(item)
        return item

    async def list_tool_group_items(
        self,
        *,
        project_id: UUID,
        tool_group_id: UUID,
    ) -> list[ToolGroupItemRead]:
        group = self._find_tool_group(project_id, tool_group_id)
        return [
            item
            for item in self.tool_group_items.get(project_id, [])
            if item.tool_group_id == group.id and item.status == "active"
        ]

    async def archive_tool_group_item(
        self,
        *,
        project_id: UUID,
        tool_group_id: UUID,
        item_id: UUID,
        actor_id: UUID,
    ) -> ToolGroupItemRead:
        group = self._find_tool_group(project_id, tool_group_id)
        for index, item in enumerate(self.tool_group_items.get(project_id, [])):
            if item.id == item_id and item.tool_group_id == group.id:
                archived = item.model_copy(
                    update={
                        "status": "archived",
                        "updated_by": actor_id,
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                )
                self.tool_group_items[project_id][index] = archived
                return archived
        raise ToolRegistryResourceNotFoundError("tool group item not found")

    async def resolve_authorized_tools(
        self,
        *,
        project_id: UUID,
        request: object,
    ) -> AuthorizedToolsResolveResponse:
        requested_groups = set(getattr(request, "tool_group_refs", []))
        tools = [
            item
            for item in self.tool_group_items.get(project_id, [])
            if item.status == "active"
            and item.group_ref in requested_groups
            and _test_authorized_context_matches(
                item,
                workflow_ref=getattr(request, "workflow_ref", ""),
                agent_ref=getattr(request, "agent_ref", ""),
                role_refs=getattr(request, "role_refs", []),
            )
        ]
        return AuthorizedToolsResolveResponse(
            project_id=project_id,
            workflow_ref=getattr(request, "workflow_ref", ""),
            agent_ref=getattr(request, "agent_ref", ""),
            role_refs=getattr(request, "role_refs", []),
            tool_group_refs=sorted(requested_groups),
            tools=[
                AuthorizedToolRead(
                    project_id=item.project_id,
                    tool_group_id=item.tool_group_id,
                    tool_definition_id=item.tool_definition_id,
                    group_ref=item.group_ref,
                    tool_ref=item.tool_ref,
                    server_ref=item.server_ref,
                    tool_name=item.tool_name,
                    display_name=item.display_name,
                    description=item.description,
                    input_schema=item.input_schema,
                    output_schema=item.output_schema,
                    annotations=item.annotations,
                    effective_risk_level=item.effective_risk_level,
                    approval_required=item.approval_required,
                    parameter_policy=item.parameter_policy,
                    allowed_role_refs=item.allowed_role_refs,
                    allowed_workflow_refs=item.allowed_workflow_refs,
                    allowed_agent_refs=item.allowed_agent_refs,
                )
                for item in tools
            ],
        )

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

    def _find_tool_group(self, project_id: UUID, tool_group_id: UUID) -> ToolGroupRead:
        for group in self.tool_groups.get(project_id, []):
            if group.id == tool_group_id and group.status == "active":
                return group
        raise ToolRegistryResourceNotFoundError("tool group not found")

    def _find_tool_definition(
        self,
        project_id: UUID,
        tool_definition_id: UUID,
    ) -> ToolDefinitionRead:
        for definition in self.tool_definitions.get(project_id, []):
            if definition.id == tool_definition_id and definition.status == "active":
                return definition
        raise ToolRegistryResourceNotFoundError("tool definition not found")

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
                credential_ref=str(request.credential_ref),
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


def _highest_test_risk(risk_levels: list[str]) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return max(risk_levels, key=lambda risk_level: order.get(risk_level, 0))


def _test_authorized_context_matches(
    item: ToolGroupItemRead,
    *,
    workflow_ref: str,
    agent_ref: str,
    role_refs: list[str],
) -> bool:
    if item.allowed_workflow_refs and workflow_ref not in item.allowed_workflow_refs:
        return False
    if item.allowed_agent_refs and agent_ref not in item.allowed_agent_refs:
        return False
    return not (item.allowed_role_refs and not set(role_refs).intersection(item.allowed_role_refs))


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


def test_tool_registry_creates_lists_and_archives_credential_refs_without_secret_values() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
    )

    create_response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/credential-refs",
        json={
            "credential_ref": "vault://ops/k8s/readonly",
            "name": "K8s 只读凭据",
            "provider": "external_vault",
            "external_path": "ops/k8s/readonly",
            "secret_kind": "bearer_token",
            "environment_key": "test",
            "usage_scope": "mcp",
            "data_classification": "secret",
            "owner": "platform-security",
        },
    )
    list_response = client.get(f"/api/v1/projects/{project.id}/tool-registry/credential-refs")
    archive_response = client.delete(
        f"/api/v1/projects/{project.id}/tool-registry/credential-refs/"
        f"{create_response.json()['id']}"
    )

    assert create_response.status_code == 201
    assert create_response.json()["credential_ref"] == "vault://ops/k8s/readonly"
    assert "secret_value" not in create_response.text
    assert "token-value" not in create_response.text
    assert list_response.status_code == 200
    assert list_response.json()[0]["provider"] == "external_vault"
    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == "archived"
    assert [event["action"] for event in audit_store.events] == [
        "tool_registry.credential_ref.create",
        "tool_registry.credential_ref.list",
        "tool_registry.credential_ref.archive",
    ]


def test_tool_registry_rejects_plain_secret_fields_in_credential_ref_request() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=InMemoryToolRegistryStore(),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/credential-refs",
        json={
            "credential_ref": "vault://ops/k8s/admin",
            "name": "K8s 管理凭据",
            "provider": "external_vault",
            "external_path": "ops/k8s/admin",
            "secret_kind": "bearer_token",
            "environment_key": "prod",
            "usage_scope": "mcp",
            "secret_value": "token-value",
        },
    )

    assert response.status_code == 422
    assert "token-value" not in response.text


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


def test_tool_registry_assigns_tool_group_items_and_resolves_authorized_tools() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
    )
    server = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/mcp-servers",
        json={
            "server_ref": "mcp-k8s-test",
            "name": "K8s 测试 MCP",
            "base_url": "https://mcp.internal.example/k8s",
            "environment_key": "test",
        },
    )
    sync_response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/mcp-servers/{server.json()['id']}/sync-tools"
    )
    tool_definition_id = sync_response.json()["tool_definitions"][0]["id"]
    group = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/tool-groups",
        json={
            "group_ref": "k8s.readonly",
            "name": "K8s 只读工具",
            "risk_level": "medium",
            "environment_key": "test",
        },
    )

    create_item = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/tool-groups/{group.json()['id']}/items",
        json={
            "tool_definition_id": tool_definition_id,
            "risk_level_override": "low",
            "approval_required": True,
            "parameter_policy": {"allowed_namespaces": ["default", "ops"]},
            "allowed_role_refs": ["oncall"],
            "allowed_workflow_refs": ["incident-response"],
            "allowed_agent_refs": ["ops-agent"],
        },
    )
    list_items = client.get(
        f"/api/v1/projects/{project.id}/tool-registry/tool-groups/{group.json()['id']}/items"
    )
    resolve_response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/authorized-tools/resolve",
        json={
            "tool_group_refs": ["k8s.readonly"],
            "workflow_ref": "incident-response",
            "agent_ref": "ops-agent",
            "role_refs": ["oncall"],
        },
    )
    denied_context = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/authorized-tools/resolve",
        json={
            "tool_group_refs": ["k8s.readonly"],
            "workflow_ref": "incident-response",
            "agent_ref": "ops-agent",
            "role_refs": ["viewer"],
        },
    )

    assert create_item.status_code == 201
    assert create_item.json()["tool_ref"] == "mcp-k8s-test.kubectl_get_pods"
    assert create_item.json()["effective_risk_level"] == "medium"
    assert create_item.json()["approval_required"] is True
    assert list_items.status_code == 200
    assert list_items.json()[0]["parameter_policy"] == {"allowed_namespaces": ["default", "ops"]}
    assert resolve_response.status_code == 200
    assert resolve_response.json()["workflow_ref"] == "incident-response"
    assert resolve_response.json()["role_refs"] == ["oncall"]
    assert resolve_response.json()["tools"][0]["tool_name"] == "kubectl_get_pods"
    assert resolve_response.json()["tools"][0]["input_schema"] == {"type": "object"}
    assert denied_context.status_code == 200
    assert denied_context.json()["tools"] == []
    assert [event["action"] for event in audit_store.events][-4:] == [
        "tool_registry.tool_group_item.create",
        "tool_registry.tool_group_item.list",
        "tool_registry.authorized_tools.resolve",
        "tool_registry.authorized_tools.resolve",
    ]


def test_tool_registry_tool_group_item_assignment_is_project_scoped() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    other_project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project, other_project]),
        registry_store=registry_store,
        audit_store=InMemoryAuditEventStore(),
    )
    other_server = client.post(
        f"/api/v1/projects/{other_project.id}/tool-registry/mcp-servers",
        json={
            "server_ref": "other-mcp",
            "name": "Other MCP",
            "base_url": "https://mcp.internal.example/other",
            "environment_key": "test",
        },
    )
    other_sync = client.post(
        f"/api/v1/projects/{other_project.id}/tool-registry/mcp-servers/"
        f"{other_server.json()['id']}/sync-tools"
    )
    group = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/tool-groups",
        json={
            "group_ref": "k8s.readonly",
            "name": "K8s 只读工具",
            "risk_level": "medium",
            "environment_key": "test",
        },
    )

    denied = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/tool-groups/{group.json()['id']}/items",
        json={"tool_definition_id": other_sync.json()["tool_definitions"][0]["id"]},
    )
    resolve_response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/authorized-tools/resolve",
        json={"tool_group_refs": ["other.secret"]},
    )

    assert denied.status_code == 404
    assert resolve_response.status_code == 200
    assert resolve_response.json()["tools"] == []


def test_tool_registry_resources_bind_credential_refs_without_exposing_secrets() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
    )
    credential = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/credential-refs",
        json={
            "credential_ref": "vault://ops/k8s/readonly",
            "name": "K8s 只读凭据",
            "provider": "external_vault",
            "external_path": "ops/k8s/readonly",
            "secret_kind": "bearer_token",
            "environment_key": "test",
            "usage_scope": "mcp",
        },
    )
    assert credential.status_code == 201

    mcp_response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/mcp-servers",
        json={
            "server_ref": "mcp-k8s-test",
            "name": "K8s 测试 MCP",
            "base_url": "https://mcp.internal.example/k8s",
            "environment_key": "test",
            "credential_ref": "vault://ops/k8s/readonly",
        },
    )
    shell_response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-templates",
        json={
            "template_ref": "k8s-log-collector",
            "template_version": 3,
            "name": "日志采集",
            "risk_level": "medium",
            "environment_key": "test",
            "credential_ref": "vault://ops/k8s/readonly",
        },
    )

    assert mcp_response.status_code == 201
    assert mcp_response.json()["credential_ref"] == "vault://ops/k8s/readonly"
    assert shell_response.status_code == 201
    assert shell_response.json()["credential_ref"] == "vault://ops/k8s/readonly"
    assert "token-value" not in mcp_response.text
    assert "token-value" not in shell_response.text


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
