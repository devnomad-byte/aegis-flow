from datetime import UTC, datetime, timedelta
from typing import TypeVar, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.security.egress_policy import (
    EgressPolicy,
    EgressPolicyViolation,
    validate_egress_url,
)
from backend.app.tool_registry.mcp_client import (
    McpServerConnection,
    McpTool,
    McpToolListError,
    McpToolsClient,
    tool_schema_hash,
)
from backend.app.tool_registry.models import (
    ToolRegistryCredentialAccessIntent,
    ToolRegistryCredentialRef,
    ToolRegistryEnvironment,
    ToolRegistryMcpServer,
    ToolRegistrySecretLease,
    ToolRegistryShellTemplate,
    ToolRegistryToolDefinition,
    ToolRegistryToolGroup,
    ToolRegistryToolGroupItem,
    ToolRegistryToolSyncRun,
)
from backend.app.tool_registry.schemas import (
    AuthorizedToolRead,
    AuthorizedToolsResolveRequest,
    AuthorizedToolsResolveResponse,
    CredentialAccessIntentRead,
    CredentialRefCreateRequest,
    CredentialRefRead,
    EnvironmentCreateRequest,
    EnvironmentRead,
    McpServerCreateRequest,
    McpServerRead,
    SecretLeaseCreateRequest,
    SecretLeaseRead,
    ShellTemplateCreateRequest,
    ShellTemplateRead,
    ToolDefinitionRead,
    ToolGroupCreateRequest,
    ToolGroupItemCreateRequest,
    ToolGroupItemRead,
    ToolGroupRead,
    ToolMcpServerCredentialRead,
    ToolSyncRunRead,
)
from backend.app.tool_registry.store import (
    DuplicateToolRegistryResourceError,
    ToolRegistryEgressPolicyError,
    ToolRegistryResourceNotFoundError,
    ToolSyncFailedError,
)
from backend.app.workflows.yaml_io import ProjectResourceCatalog

ModelT = TypeVar(
    "ModelT",
    ToolRegistryEnvironment,
    ToolRegistryMcpServer,
    ToolRegistryToolGroup,
    ToolRegistryShellTemplate,
    ToolRegistryToolDefinition,
    ToolRegistryToolGroupItem,
    ToolRegistryToolSyncRun,
    ToolRegistryCredentialRef,
    ToolRegistrySecretLease,
)


class SqlAlchemyToolRegistryStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build_project_resource_catalog(self, project_id: UUID) -> ProjectResourceCatalog:
        environments = await self._active_values(
            ToolRegistryEnvironment,
            project_id=project_id,
            value_attribute="key",
        )
        mcp_servers = await self._active_values(
            ToolRegistryMcpServer,
            project_id=project_id,
            value_attribute="server_ref",
        )
        tool_groups = await self._active_values(
            ToolRegistryToolGroup,
            project_id=project_id,
            value_attribute="group_ref",
        )
        shell_templates = await self._active_shell_templates(project_id)
        return ProjectResourceCatalog(
            tool_groups=frozenset(tool_groups),
            mcp_servers=frozenset(mcp_servers),
            shell_templates=frozenset(shell_templates),
            environments=frozenset(environments),
        )

    async def create_environment(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: EnvironmentCreateRequest,
    ) -> EnvironmentRead:
        resource = ToolRegistryEnvironment(
            project_id=project_id,
            key=request.key,
            name=request.name,
            egress_allowed_hosts=request.egress_allowed_hosts,
            description=request.description,
            created_by=actor_id,
            updated_by=actor_id,
        )
        return EnvironmentRead.model_validate(await self._insert(resource))

    async def create_mcp_server(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: McpServerCreateRequest,
        egress_policy: EgressPolicy | None = None,
    ) -> McpServerRead:
        await self._ensure_active_credential_ref(
            project_id=project_id,
            credential_ref=request.credential_ref,
        )
        environment = await self._get_active_environment(project_id, request.environment_key)
        if environment is None:
            raise ToolRegistryResourceNotFoundError("environment not found")
        self._validate_mcp_egress_target(
            str(request.base_url),
            environment=environment,
            egress_policy=egress_policy,
        )
        resource = ToolRegistryMcpServer(
            project_id=project_id,
            server_ref=request.server_ref,
            name=request.name,
            base_url=str(request.base_url),
            transport=request.transport,
            environment_key=request.environment_key,
            owner=request.owner,
            credential_ref=request.credential_ref,
            description=request.description,
            created_by=actor_id,
            updated_by=actor_id,
        )
        return McpServerRead.model_validate(await self._insert(resource))

    async def create_tool_group(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ToolGroupCreateRequest,
    ) -> ToolGroupRead:
        resource = ToolRegistryToolGroup(
            project_id=project_id,
            group_ref=request.group_ref,
            name=request.name,
            risk_level=request.risk_level,
            environment_key=request.environment_key,
            description=request.description,
            created_by=actor_id,
            updated_by=actor_id,
        )
        return ToolGroupRead.model_validate(await self._insert(resource))

    async def create_shell_template(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellTemplateCreateRequest,
    ) -> ShellTemplateRead:
        await self._ensure_active_credential_ref(
            project_id=project_id,
            credential_ref=request.credential_ref,
        )
        resource = ToolRegistryShellTemplate(
            project_id=project_id,
            template_ref=request.template_ref,
            template_version=request.template_version,
            name=request.name,
            risk_level=request.risk_level,
            environment_key=request.environment_key,
            credential_ref=request.credential_ref,
            description=request.description,
            created_by=actor_id,
            updated_by=actor_id,
        )
        return ShellTemplateRead.model_validate(await self._insert(resource))

    async def create_credential_ref(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: CredentialRefCreateRequest,
    ) -> CredentialRefRead:
        resource = ToolRegistryCredentialRef(
            project_id=project_id,
            credential_ref=request.credential_ref,
            name=request.name,
            description=request.description,
            provider=request.provider,
            external_path=request.external_path,
            secret_kind=request.secret_kind,
            environment_key=request.environment_key,
            usage_scope=request.usage_scope,
            data_classification=request.data_classification,
            rotation_policy=request.rotation_policy,
            expires_at=request.expires_at,
            last_rotated_at=request.last_rotated_at,
            owner=request.owner,
            created_by=actor_id,
            updated_by=actor_id,
        )
        return CredentialRefRead.model_validate(await self._insert(resource))

    async def list_project_credential_refs(self, project_id: UUID) -> list[CredentialRefRead]:
        result = await self._session.scalars(
            select(ToolRegistryCredentialRef)
            .where(ToolRegistryCredentialRef.project_id == project_id)
            .order_by(ToolRegistryCredentialRef.credential_ref)
        )
        return [CredentialRefRead.model_validate(resource) for resource in result.all()]

    async def archive_credential_ref(
        self,
        *,
        project_id: UUID,
        credential_ref_id: UUID,
        actor_id: UUID,
    ) -> CredentialRefRead:
        credential = await self._get_project_credential_ref_by_id(project_id, credential_ref_id)
        if credential is None:
            raise ToolRegistryResourceNotFoundError("credential ref not found")
        credential.status = "archived"
        credential.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(credential)
        return CredentialRefRead.model_validate(credential)

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
        credential = await self._get_active_credential_ref(project_id, credential_ref)
        if credential is None:
            raise ToolRegistryResourceNotFoundError("credential ref not found")
        intent = ToolRegistryCredentialAccessIntent(
            project_id=project_id,
            credential_ref_id=credential.id,
            credential_ref=credential.credential_ref,
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
        )
        self._session.add(intent)
        await self._session.commit()
        await self._session.refresh(intent)
        return CredentialAccessIntentRead.model_validate(intent)

    async def create_secret_lease(
        self,
        *,
        project_id: UUID,
        credential_ref_id: UUID,
        actor_id: UUID,
        request: SecretLeaseCreateRequest,
    ) -> SecretLeaseRead:
        credential = await self._get_active_credential_ref_by_id(project_id, credential_ref_id)
        if credential is None:
            raise ToolRegistryResourceNotFoundError("credential ref not found")

        now = datetime.now(UTC)
        lease = ToolRegistrySecretLease(
            project_id=project_id,
            credential_ref_id=credential.id,
            credential_ref=credential.credential_ref,
            provider=credential.provider,
            external_path=credential.external_path,
            lease_ref=f"lease_{uuid4().hex}",
            provider_lease_id="",
            requester_type=request.requester_type,
            requester_ref=request.requester_ref,
            purpose=request.purpose,
            run_id=request.run_id,
            node_id=request.node_id,
            trace_id=request.trace_id,
            ttl_seconds=request.ttl_seconds,
            expires_at=now + timedelta(seconds=request.ttl_seconds),
            revoked_at=None,
            status="active",
            denial_reason="",
            created_by=actor_id,
            updated_by=actor_id,
        )
        intent = ToolRegistryCredentialAccessIntent(
            project_id=project_id,
            credential_ref_id=credential.id,
            credential_ref=credential.credential_ref,
            actor_id=actor_id,
            requester_type=request.requester_type,
            requester_ref=request.requester_ref,
            purpose=request.purpose,
            run_id=request.run_id,
            node_id=request.node_id,
            trace_id=request.trace_id,
            decision="recorded",
            denial_reason="",
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add_all([lease, intent])
        await self._session.commit()
        await self._session.refresh(lease)
        return SecretLeaseRead.model_validate(lease)

    async def list_project_secret_leases(self, project_id: UUID) -> list[SecretLeaseRead]:
        result = await self._session.scalars(
            select(ToolRegistrySecretLease)
            .where(ToolRegistrySecretLease.project_id == project_id)
            .order_by(ToolRegistrySecretLease.created_at.desc())
        )
        return [SecretLeaseRead.model_validate(resource) for resource in result.all()]

    async def revoke_secret_lease(
        self,
        *,
        project_id: UUID,
        lease_id: UUID,
        actor_id: UUID,
    ) -> SecretLeaseRead:
        lease = await self._get_project_secret_lease(project_id, lease_id)
        if lease is None:
            raise ToolRegistryResourceNotFoundError("secret lease not found")
        if lease.status != "revoked":
            lease.status = "revoked"
            lease.revoked_at = datetime.now(UTC)
        lease.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(lease)
        return SecretLeaseRead.model_validate(lease)

    async def list_project_tool_definitions(self, project_id: UUID) -> list[ToolDefinitionRead]:
        result = await self._session.scalars(
            select(ToolRegistryToolDefinition)
            .where(ToolRegistryToolDefinition.project_id == project_id)
            .order_by(
                ToolRegistryToolDefinition.server_ref,
                ToolRegistryToolDefinition.tool_name,
            )
        )
        return [ToolDefinitionRead.model_validate(resource) for resource in result.all()]

    async def create_tool_group_item(
        self,
        *,
        project_id: UUID,
        tool_group_id: UUID,
        actor_id: UUID,
        request: ToolGroupItemCreateRequest,
    ) -> ToolGroupItemRead:
        group = await self._get_active_tool_group(project_id, tool_group_id)
        if group is None:
            raise ToolRegistryResourceNotFoundError("tool group not found")
        definition = await self._get_active_tool_definition(project_id, request.tool_definition_id)
        if definition is None:
            raise ToolRegistryResourceNotFoundError("tool definition not found")

        effective_risk_level = _highest_risk_level(
            [group.risk_level, definition.risk_level, request.risk_level_override]
        )
        resource = ToolRegistryToolGroupItem(
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
            risk_level_override=request.risk_level_override,
            effective_risk_level=effective_risk_level,
            approval_required=request.approval_required
            or effective_risk_level in {"high", "critical"},
            parameter_policy=request.parameter_policy,
            allowed_role_refs=request.allowed_role_refs,
            allowed_workflow_refs=request.allowed_workflow_refs,
            allowed_agent_refs=request.allowed_agent_refs,
            created_by=actor_id,
            updated_by=actor_id,
        )
        return ToolGroupItemRead.model_validate(await self._insert(resource))

    async def list_tool_group_items(
        self,
        *,
        project_id: UUID,
        tool_group_id: UUID,
    ) -> list[ToolGroupItemRead]:
        group = await self._get_active_tool_group(project_id, tool_group_id)
        if group is None:
            raise ToolRegistryResourceNotFoundError("tool group not found")
        result = await self._session.scalars(
            select(ToolRegistryToolGroupItem)
            .where(
                ToolRegistryToolGroupItem.project_id == project_id,
                ToolRegistryToolGroupItem.tool_group_id == tool_group_id,
                ToolRegistryToolGroupItem.status == "active",
            )
            .order_by(ToolRegistryToolGroupItem.tool_ref)
        )
        return [ToolGroupItemRead.model_validate(resource) for resource in result.all()]

    async def archive_tool_group_item(
        self,
        *,
        project_id: UUID,
        tool_group_id: UUID,
        item_id: UUID,
        actor_id: UUID,
    ) -> ToolGroupItemRead:
        group = await self._get_active_tool_group(project_id, tool_group_id)
        if group is None:
            raise ToolRegistryResourceNotFoundError("tool group not found")
        item = await self._get_tool_group_item(project_id, tool_group_id, item_id)
        if item is None:
            raise ToolRegistryResourceNotFoundError("tool group item not found")
        item.status = "archived"
        item.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(item)
        return ToolGroupItemRead.model_validate(item)

    async def resolve_authorized_tools(
        self,
        *,
        project_id: UUID,
        request: AuthorizedToolsResolveRequest,
    ) -> AuthorizedToolsResolveResponse:
        requested_refs = sorted(set(request.tool_group_refs))
        if not requested_refs:
            return AuthorizedToolsResolveResponse(
                project_id=project_id,
                workflow_ref=request.workflow_ref,
                agent_ref=request.agent_ref,
                role_refs=request.role_refs,
                tool_group_refs=[],
                tools=[],
            )

        result = await self._session.scalars(
            select(ToolRegistryToolGroupItem)
            .join(
                ToolRegistryToolGroup,
                ToolRegistryToolGroup.id == ToolRegistryToolGroupItem.tool_group_id,
            )
            .join(
                ToolRegistryToolDefinition,
                ToolRegistryToolDefinition.id == ToolRegistryToolGroupItem.tool_definition_id,
            )
            .where(
                ToolRegistryToolGroupItem.project_id == project_id,
                ToolRegistryToolGroupItem.status == "active",
                ToolRegistryToolGroup.status == "active",
                ToolRegistryToolDefinition.status == "active",
                ToolRegistryToolGroupItem.group_ref.in_(requested_refs),
            )
            .order_by(ToolRegistryToolGroupItem.group_ref, ToolRegistryToolGroupItem.tool_ref)
        )
        tools = [
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
            for item in result.all()
            if _authorized_context_matches(
                item,
                workflow_ref=request.workflow_ref,
                agent_ref=request.agent_ref,
                role_refs=request.role_refs,
            )
        ]
        return AuthorizedToolsResolveResponse(
            project_id=project_id,
            workflow_ref=request.workflow_ref,
            agent_ref=request.agent_ref,
            role_refs=request.role_refs,
            tool_group_refs=requested_refs,
            tools=tools,
        )

    async def get_mcp_server_credential_for_tool(
        self,
        *,
        project_id: UUID,
        tool_ref: str,
    ) -> ToolMcpServerCredentialRead | None:
        result = await self._session.execute(
            select(
                ToolRegistryMcpServer.id,
                ToolRegistryMcpServer.server_ref,
                ToolRegistryMcpServer.base_url,
                ToolRegistryMcpServer.transport,
                ToolRegistryMcpServer.credential_ref,
                ToolRegistryEnvironment.egress_allowed_hosts,
                ToolRegistryCredentialRef.id.label("credential_ref_id"),
            )
            .join(
                ToolRegistryToolDefinition,
                ToolRegistryToolDefinition.mcp_server_id == ToolRegistryMcpServer.id,
            )
            .outerjoin(
                ToolRegistryEnvironment,
                (ToolRegistryEnvironment.project_id == ToolRegistryMcpServer.project_id)
                & (ToolRegistryEnvironment.key == ToolRegistryMcpServer.environment_key)
                & (ToolRegistryEnvironment.status == "active"),
            )
            .outerjoin(
                ToolRegistryCredentialRef,
                (ToolRegistryCredentialRef.project_id == ToolRegistryMcpServer.project_id)
                & (ToolRegistryCredentialRef.credential_ref == ToolRegistryMcpServer.credential_ref)
                & (ToolRegistryCredentialRef.status == "active"),
            )
            .where(
                ToolRegistryMcpServer.project_id == project_id,
                ToolRegistryMcpServer.status == "active",
                ToolRegistryEnvironment.id.is_not(None),
                ToolRegistryToolDefinition.project_id == project_id,
                ToolRegistryToolDefinition.tool_ref == tool_ref,
                ToolRegistryToolDefinition.status == "active",
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        return ToolMcpServerCredentialRead(
            mcp_server_id=row.id,
            server_ref=row.server_ref,
            base_url=row.base_url,
            transport=row.transport,
            credential_ref_id=row.credential_ref_id,
            credential_ref=row.credential_ref,
            egress_allowed_hosts=row.egress_allowed_hosts or [],
        )

    async def sync_mcp_server_tools(
        self,
        *,
        project_id: UUID,
        mcp_server_id: UUID,
        actor_id: UUID,
        tools_client: McpToolsClient,
        egress_policy: EgressPolicy | None = None,
    ) -> ToolSyncRunRead:
        server = await self._get_project_mcp_server(project_id, mcp_server_id)
        if server is None:
            raise ToolRegistryResourceNotFoundError("mcp server not found")
        environment = await self._get_active_environment(project_id, server.environment_key)
        if environment is None:
            raise ToolRegistryResourceNotFoundError("environment not found")

        started_at = datetime.now(UTC)
        sync_version = server.last_sync_version + 1
        try:
            self._validate_mcp_egress_target(
                server.base_url,
                environment=environment,
                egress_policy=egress_policy,
            )
            tools_result = await tools_client.list_tools(
                McpServerConnection(
                    server_ref=server.server_ref,
                    base_url=server.base_url,
                    transport=server.transport,
                    egress_allowed_hosts=environment.egress_allowed_hosts,
                )
            )
        except (McpToolListError, ToolRegistryEgressPolicyError) as exc:
            failed_run = await self._record_failed_sync_run(
                server=server,
                project_id=project_id,
                actor_id=actor_id,
                sync_version=sync_version,
                started_at=started_at,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )
            raise ToolSyncFailedError(
                public_message=failed_run.error_message,
                target_id=str(failed_run.id),
            ) from exc

        now = datetime.now(UTC)
        definitions = await self._upsert_tool_definitions(
            project_id=project_id,
            actor_id=actor_id,
            server=server,
            sync_version=sync_version,
            observed_at=now,
            tools=tools_result.tools,
        )
        server.last_health_status = "healthy"
        server.last_health_checked_at = now
        server.last_sync_version = sync_version
        server.last_sync_status = "success"
        server.last_sync_error = ""
        server.updated_by = actor_id
        success_run = ToolRegistryToolSyncRun(
            project_id=project_id,
            mcp_server_id=server.id,
            server_ref=server.server_ref,
            sync_version=sync_version,
            status="success",
            started_at=started_at,
            finished_at=now,
            tool_count=len(definitions),
            error_type="",
            error_message="",
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(success_run)
        await self._session.commit()
        await self._session.refresh(success_run)
        refreshed_definitions = await self._list_definitions_for_sync(
            project_id=project_id,
            mcp_server_id=server.id,
            sync_version=sync_version,
        )
        return ToolSyncRunRead.model_validate(success_run).model_copy(
            update={"tool_definitions": refreshed_definitions}
        )

    async def _active_values(
        self,
        model: type[ModelT],
        *,
        project_id: UUID,
        value_attribute: str,
    ) -> list[str]:
        result = await self._session.scalars(
            select(model).where(model.project_id == project_id, model.status == "active")
        )
        return sorted(str(getattr(resource, value_attribute)) for resource in result.all())

    async def _active_shell_templates(self, project_id: UUID) -> list[str]:
        result = await self._session.scalars(
            select(ToolRegistryShellTemplate).where(
                ToolRegistryShellTemplate.project_id == project_id,
                ToolRegistryShellTemplate.status == "active",
            )
        )
        return sorted(
            f"{resource.template_ref}@{resource.template_version}" for resource in result.all()
        )

    async def _insert(self, resource: ModelT) -> ModelT:
        self._session.add(resource)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateToolRegistryResourceError(
                "tool registry resource already exists"
            ) from exc
        await self._session.refresh(resource)
        return resource

    async def _get_project_mcp_server(
        self,
        project_id: UUID,
        mcp_server_id: UUID,
    ) -> ToolRegistryMcpServer | None:
        return cast(
            ToolRegistryMcpServer | None,
            await self._session.scalar(
                select(ToolRegistryMcpServer).where(
                    ToolRegistryMcpServer.project_id == project_id,
                    ToolRegistryMcpServer.id == mcp_server_id,
                )
            ),
        )

    async def _get_active_environment(
        self,
        project_id: UUID,
        environment_key: str,
    ) -> ToolRegistryEnvironment | None:
        return cast(
            ToolRegistryEnvironment | None,
            await self._session.scalar(
                select(ToolRegistryEnvironment).where(
                    ToolRegistryEnvironment.project_id == project_id,
                    ToolRegistryEnvironment.key == environment_key,
                    ToolRegistryEnvironment.status == "active",
                )
            ),
        )

    def _validate_mcp_egress_target(
        self,
        base_url: str,
        *,
        environment: ToolRegistryEnvironment,
        egress_policy: EgressPolicy | None,
    ) -> None:
        try:
            validate_egress_url(
                base_url,
                policy=egress_policy,
                allowed_hosts=environment.egress_allowed_hosts,
            )
        except EgressPolicyViolation as exc:
            raise ToolRegistryEgressPolicyError(exc) from exc

    async def _get_active_tool_group(
        self,
        project_id: UUID,
        tool_group_id: UUID,
    ) -> ToolRegistryToolGroup | None:
        return cast(
            ToolRegistryToolGroup | None,
            await self._session.scalar(
                select(ToolRegistryToolGroup).where(
                    ToolRegistryToolGroup.project_id == project_id,
                    ToolRegistryToolGroup.id == tool_group_id,
                    ToolRegistryToolGroup.status == "active",
                )
            ),
        )

    async def _get_active_tool_definition(
        self,
        project_id: UUID,
        tool_definition_id: UUID,
    ) -> ToolRegistryToolDefinition | None:
        return cast(
            ToolRegistryToolDefinition | None,
            await self._session.scalar(
                select(ToolRegistryToolDefinition).where(
                    ToolRegistryToolDefinition.project_id == project_id,
                    ToolRegistryToolDefinition.id == tool_definition_id,
                    ToolRegistryToolDefinition.status == "active",
                )
            ),
        )

    async def _get_tool_group_item(
        self,
        project_id: UUID,
        tool_group_id: UUID,
        item_id: UUID,
    ) -> ToolRegistryToolGroupItem | None:
        return cast(
            ToolRegistryToolGroupItem | None,
            await self._session.scalar(
                select(ToolRegistryToolGroupItem).where(
                    ToolRegistryToolGroupItem.project_id == project_id,
                    ToolRegistryToolGroupItem.tool_group_id == tool_group_id,
                    ToolRegistryToolGroupItem.id == item_id,
                )
            ),
        )

    async def _get_project_credential_ref_by_id(
        self,
        project_id: UUID,
        credential_ref_id: UUID,
    ) -> ToolRegistryCredentialRef | None:
        return cast(
            ToolRegistryCredentialRef | None,
            await self._session.scalar(
                select(ToolRegistryCredentialRef).where(
                    ToolRegistryCredentialRef.project_id == project_id,
                    ToolRegistryCredentialRef.id == credential_ref_id,
                )
            ),
        )

    async def _get_active_credential_ref_by_id(
        self,
        project_id: UUID,
        credential_ref_id: UUID,
    ) -> ToolRegistryCredentialRef | None:
        return cast(
            ToolRegistryCredentialRef | None,
            await self._session.scalar(
                select(ToolRegistryCredentialRef).where(
                    ToolRegistryCredentialRef.project_id == project_id,
                    ToolRegistryCredentialRef.id == credential_ref_id,
                    ToolRegistryCredentialRef.status == "active",
                )
            ),
        )

    async def _get_project_secret_lease(
        self,
        project_id: UUID,
        lease_id: UUID,
    ) -> ToolRegistrySecretLease | None:
        return cast(
            ToolRegistrySecretLease | None,
            await self._session.scalar(
                select(ToolRegistrySecretLease).where(
                    ToolRegistrySecretLease.project_id == project_id,
                    ToolRegistrySecretLease.id == lease_id,
                )
            ),
        )

    async def _get_active_credential_ref(
        self,
        project_id: UUID,
        credential_ref: str,
    ) -> ToolRegistryCredentialRef | None:
        if not credential_ref:
            return None
        return cast(
            ToolRegistryCredentialRef | None,
            await self._session.scalar(
                select(ToolRegistryCredentialRef).where(
                    ToolRegistryCredentialRef.project_id == project_id,
                    ToolRegistryCredentialRef.credential_ref == credential_ref,
                    ToolRegistryCredentialRef.status == "active",
                )
            ),
        )

    async def _ensure_active_credential_ref(
        self,
        *,
        project_id: UUID,
        credential_ref: str,
    ) -> None:
        if not credential_ref:
            return
        credential = await self._get_active_credential_ref(project_id, credential_ref)
        if credential is None:
            raise ToolRegistryResourceNotFoundError("credential ref not found")

    async def _record_failed_sync_run(
        self,
        *,
        server: ToolRegistryMcpServer,
        project_id: UUID,
        actor_id: UUID,
        sync_version: int,
        started_at: datetime,
        error_type: str,
        error_message: str,
    ) -> ToolSyncRunRead:
        now = datetime.now(UTC)
        server.last_health_status = "unhealthy"
        server.last_health_checked_at = now
        server.last_sync_status = "failed"
        server.last_sync_error = error_message
        server.updated_by = actor_id
        run = ToolRegistryToolSyncRun(
            project_id=project_id,
            mcp_server_id=server.id,
            server_ref=server.server_ref,
            sync_version=sync_version,
            status="failed",
            started_at=started_at,
            finished_at=now,
            tool_count=0,
            error_type=error_type,
            error_message=error_message,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return ToolSyncRunRead.model_validate(run)

    async def _upsert_tool_definitions(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        server: ToolRegistryMcpServer,
        sync_version: int,
        observed_at: datetime,
        tools: list[McpTool],
    ) -> list[ToolRegistryToolDefinition]:
        existing_result = await self._session.scalars(
            select(ToolRegistryToolDefinition).where(
                ToolRegistryToolDefinition.project_id == project_id,
                ToolRegistryToolDefinition.mcp_server_id == server.id,
            )
        )
        existing_by_name = {
            definition.tool_name: definition for definition in existing_result.all()
        }
        observed_names: set[str] = set()
        definitions: list[ToolRegistryToolDefinition] = []

        for tool in tools:
            tool_name = str(tool.name)
            observed_names.add(tool_name)
            tool_ref = f"{server.server_ref}.{tool_name}"
            definition = existing_by_name.get(tool_name)
            if definition is None:
                definition = ToolRegistryToolDefinition(
                    project_id=project_id,
                    mcp_server_id=server.id,
                    server_ref=server.server_ref,
                    tool_ref=tool_ref,
                    tool_name=tool_name,
                    created_by=actor_id,
                    updated_by=actor_id,
                    last_seen_at=observed_at,
                    display_name=tool.display_name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    output_schema=tool.output_schema,
                    annotations=tool.annotations,
                    risk_level=tool.risk_level,
                    schema_hash=tool_schema_hash(tool),
                    sync_version=sync_version,
                    status="active",
                )
                self._session.add(definition)
            else:
                definition.server_ref = server.server_ref
                definition.tool_ref = tool_ref
                definition.display_name = tool.display_name
                definition.description = tool.description
                definition.input_schema = tool.input_schema
                definition.output_schema = tool.output_schema
                definition.annotations = tool.annotations
                definition.risk_level = tool.risk_level
                definition.schema_hash = tool_schema_hash(tool)
                definition.sync_version = sync_version
                definition.status = "active"
                definition.last_seen_at = observed_at
                definition.updated_by = actor_id
            definitions.append(definition)

        for tool_name, definition in existing_by_name.items():
            if tool_name not in observed_names and definition.status == "active":
                definition.status = "stale"
                definition.updated_by = actor_id

        return definitions

    async def _list_definitions_for_sync(
        self,
        *,
        project_id: UUID,
        mcp_server_id: UUID,
        sync_version: int,
    ) -> list[ToolDefinitionRead]:
        result = await self._session.scalars(
            select(ToolRegistryToolDefinition)
            .where(
                ToolRegistryToolDefinition.project_id == project_id,
                ToolRegistryToolDefinition.mcp_server_id == mcp_server_id,
                ToolRegistryToolDefinition.sync_version == sync_version,
                ToolRegistryToolDefinition.status == "active",
            )
            .order_by(ToolRegistryToolDefinition.tool_name)
        )
        return [ToolDefinitionRead.model_validate(resource) for resource in result.all()]


def _highest_risk_level(risk_levels: list[str | None]) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    cleaned = [risk_level for risk_level in risk_levels if risk_level]
    if not cleaned:
        return "low"
    return max(cleaned, key=lambda risk_level: order.get(risk_level, 0))


def _authorized_context_matches(
    item: ToolRegistryToolGroupItem,
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
