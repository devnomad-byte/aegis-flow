import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import cast
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_mcp_egress_policy,
    get_project_access_provider,
    get_tool_registry_store,
)
from backend.app.api.routes.tool_registry import (
    get_oci_digest_resolver,
    get_shell_image_artifact_object_store,
    get_shell_image_evidence_provider,
)
from backend.app.execution.shell_policy import (
    ShellTemplatePolicyInput,
    build_shell_template_preview,
    validate_shell_template_policy,
)
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.security.egress_policy import (
    EgressPolicy,
    EgressPolicyViolation,
    validate_egress_url,
)
from backend.app.tool_registry.image_artifacts import (
    InMemoryShellImageArtifactObjectStore,
    StoredShellImageArtifact,
)
from backend.app.tool_registry.image_evidence import (
    ShellImageEvidenceResult,
    StaticShellImageEvidenceProvider,
)
from backend.app.tool_registry.image_governance import (
    summarize_shell_image_admission_governance,
)
from backend.app.tool_registry.image_supply_chain import OciManifestDigestResult
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
    NotationTrustCertificateCreateRequest,
    NotationTrustCertificateRead,
    SecretLeaseCreateRequest,
    SecretLeaseRead,
    ShellImageAdmissionGovernanceRead,
    ShellImageAdmissionPolicyRead,
    ShellImageAdmissionPolicyUpdateRequest,
    ShellImageAdmissionRead,
    ShellImageAdmissionResolveRequest,
    ShellImageArtifactCleanupRunRead,
    ShellImageArtifactCleanupScheduleRead,
    ShellImageArtifactCleanupScheduleUpdateRequest,
    ShellTemplateCreateRequest,
    ShellTemplatePolicySummary,
    ShellTemplatePreviewRequest,
    ShellTemplatePreviewResponse,
    ShellTemplateRead,
    ToolDefinitionRead,
    ToolGroupCreateRequest,
    ToolGroupItemCreateRequest,
    ToolGroupItemRead,
    ToolGroupRead,
    ToolSyncRunRead,
    default_shell_image_admission_policy,
)
from backend.app.tool_registry.store import (
    ShellImageAdmissionRequiredError,
    ToolRegistryEgressPolicyError,
    ToolRegistryResourceNotFoundError,
    ToolSyncFailedError,
)
from backend.app.workflows.yaml_io import ProjectResourceCatalog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
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
        self.environment_allowed_hosts: dict[tuple[UUID, str], list[str]] = {}
        self.credential_access_intents: list[CredentialAccessIntentRead] = []
        self.secret_leases: dict[UUID, list[SecretLeaseRead]] = {}
        self.tool_definitions: dict[UUID, list[ToolDefinitionRead]] = {}
        self.tool_groups: dict[UUID, list[ToolGroupRead]] = {}
        self.tool_group_items: dict[UUID, list[ToolGroupItemRead]] = {}
        self.shell_templates: dict[UUID, list[ShellTemplateRead]] = {}
        self.image_admissions: dict[UUID, list[ShellImageAdmissionRead]] = {}
        self.image_policies: dict[UUID, ShellImageAdmissionPolicyRead] = {}
        self.image_artifact_cleanup_runs: dict[UUID, list[ShellImageArtifactCleanupRunRead]] = {}
        self.image_artifact_cleanup_schedules: dict[
            UUID, ShellImageArtifactCleanupScheduleRead
        ] = {}
        self.notation_trust_certificates: dict[UUID, list[NotationTrustCertificateRead]] = {}
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
        self.environment_allowed_hosts[(project_id, key)] = list(request.egress_allowed_hosts)
        return EnvironmentRead(
            **_resource(
                project_id,
                actor_id,
                key=key,
                name=str(request.name),
                egress_allowed_hosts=list(request.egress_allowed_hosts),
                egress_allowed_ports=list(request.egress_allowed_ports),
                egress_proxy_mode=request.egress_proxy_mode,
                egress_proxy_url=request.egress_proxy_url,
                egress_proxy_network=request.egress_proxy_network,
                egress_dns_pinning_required=request.egress_dns_pinning_required,
            )
        )

    async def create_mcp_server(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: McpServerCreateRequest,
        egress_policy: EgressPolicy | None = None,
    ) -> McpServerRead:
        server_ref = str(request.server_ref)
        egress_allowed_hosts = self.environment_allowed_hosts.get(
            (project_id, str(request.environment_key)),
            [],
        )
        try:
            validate_egress_url(
                str(request.base_url),
                policy=egress_policy,
                allowed_hosts=egress_allowed_hosts,
            )
        except EgressPolicyViolation as exc:
            raise ToolRegistryEgressPolicyError(exc) from exc
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

    async def create_secret_lease(
        self,
        *,
        project_id: UUID,
        credential_ref_id: UUID,
        actor_id: UUID,
        request: SecretLeaseCreateRequest,
    ) -> SecretLeaseRead:
        for credential in self.credential_refs.get(project_id, []):
            if credential.id == credential_ref_id and credential.status == "active":
                now = datetime.now(UTC)
                lease = SecretLeaseRead(
                    id=uuid4(),
                    project_id=project_id,
                    credential_ref_id=credential.id,
                    credential_ref=credential.credential_ref,
                    provider=credential.provider,
                    external_path=credential.external_path,
                    lease_ref=f"lease-{uuid4().hex}",
                    provider_lease_id="",
                    requester_type=request.requester_type,
                    requester_ref=request.requester_ref,
                    purpose=request.purpose,
                    run_id=request.run_id,
                    node_id=request.node_id,
                    trace_id=request.trace_id,
                    ttl_seconds=request.ttl_seconds,
                    expires_at=now,
                    revoked_at=None,
                    status="active",
                    denial_reason="",
                    created_by=actor_id,
                    updated_by=actor_id,
                    created_at=now,
                    updated_at=now,
                )
                self.secret_leases.setdefault(project_id, []).append(lease)
                return lease
        raise ToolRegistryResourceNotFoundError("credential ref not found")

    async def list_project_secret_leases(self, project_id: UUID) -> list[SecretLeaseRead]:
        return self.secret_leases.get(project_id, [])

    async def revoke_secret_lease(
        self,
        *,
        project_id: UUID,
        lease_id: UUID,
        actor_id: UUID,
    ) -> SecretLeaseRead:
        for index, lease in enumerate(self.secret_leases.get(project_id, [])):
            if lease.id == lease_id:
                revoked = lease.model_copy(
                    update={
                        "status": "revoked",
                        "revoked_at": datetime.now(UTC),
                        "updated_by": actor_id,
                    }
                )
                self.secret_leases[project_id][index] = revoked
                return revoked
        raise ToolRegistryResourceNotFoundError("secret lease not found")

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
        egress_policy: EgressPolicy | None = None,
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
        policy = await self.get_shell_image_admission_policy(project_id)
        admission = self._find_accepted_admission(
            project_id,
            image_ref=str(request.image_ref),
            image_digest=str(request.image_digest),
            accepted_decisions={"approved", "would_reject"}
            if policy.enforcement_mode == "dry_run"
            else {"approved"},
        )
        if (
            str(request.environment_key).lower() in {"prod", "production"}
            or str(request.risk_level) in {"high", "critical"}
        ) and admission is None:
            raise ShellImageAdmissionRequiredError(
                "Approved shell image admission is required for production or high risk templates"
            )
        validate_shell_template_policy(
            ShellTemplatePolicyInput(
                project_id=project_id,
                template_ref=template_ref,
                template_version=template_version,
                risk_level=str(request.risk_level),
                environment_key=str(request.environment_key),
                image_ref=str(request.image_ref),
                image_digest=str(request.image_digest),
                entrypoint=str(request.entrypoint),
                argv_template=list(request.argv_template),
                parameter_schema=dict(request.parameter_schema),
                timeout_seconds=int(request.timeout_seconds),
                image_registry_digest=admission.registry_digest if admission else "",
                image_admission_status=admission.policy_decision if admission else "not_required",
            )
        )
        catalog = self.catalogs.get(project_id, ProjectResourceCatalog())
        self.catalogs[project_id] = catalog.model_copy(
            update={"shell_templates": catalog.shell_templates | frozenset({reference})}
        )
        template = ShellTemplateRead(
            **_resource(
                project_id,
                actor_id,
                name=str(request.name),
                template_ref=template_ref,
                template_version=template_version,
                risk_level=str(request.risk_level),
                environment_key=str(request.environment_key),
                credential_ref=str(request.credential_ref),
                image_ref=str(request.image_ref),
                image_digest=str(request.image_digest),
                image_registry_digest=admission.registry_digest if admission else "",
                image_registry_checked_at=admission.checked_at if admission else None,
                image_signature_status=admission.signature_status if admission else "not_checked",
                image_sbom_status=admission.sbom_status if admission else "not_checked",
                image_vulnerability_status=admission.vulnerability_status
                if admission
                else "not_checked",
                image_admission_status=admission.policy_decision if admission else "not_required",
                image_admission_reason=admission.decision_reason if admission else "",
                entrypoint=str(request.entrypoint),
                argv_template=list(request.argv_template),
                parameter_schema=dict(request.parameter_schema),
                timeout_seconds=int(request.timeout_seconds),
            )
        )
        self.shell_templates.setdefault(project_id, []).append(template)
        return template

    async def record_shell_image_admission(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageAdmissionResolveRequest,
        digest_result: OciManifestDigestResult,
        digest_match: bool,
        policy_decision: str,
        decision_reason: str,
        signature_status: str,
        sbom_status: str,
        vulnerability_status: str,
        evidence_summary: dict[str, object],
    ) -> ShellImageAdmissionRead:
        now = datetime.now(UTC)
        existing = [
            item
            for item in self.image_admissions.get(project_id, [])
            if item.image_ref == request.image_ref and item.image_digest == request.image_digest
        ]
        admission = ShellImageAdmissionRead(
            id=existing[0].id if existing else uuid4(),
            project_id=project_id,
            image_ref=request.image_ref,
            image_digest=request.image_digest,
            registry_url=digest_result.registry_url,
            registry_digest=digest_result.registry_digest,
            digest_match=digest_match,
            signature_status=signature_status,
            sbom_status=sbom_status,
            vulnerability_status=vulnerability_status,
            policy_decision=policy_decision,
            decision_reason=decision_reason,
            checked_at=now,
            evidence={
                **evidence_summary,
                "content_type": digest_result.content_type,
                "manifest_size_bytes": digest_result.manifest_size_bytes,
                "computed_digest": digest_result.computed_digest,
            },
            created_by=actor_id,
            updated_by=actor_id,
            created_at=existing[0].created_at if existing else now,
            updated_at=now,
        )
        self.image_admissions[project_id] = [
            item for item in self.image_admissions.get(project_id, []) if item.id != admission.id
        ] + [admission]
        return admission

    def _find_accepted_admission(
        self,
        project_id: UUID,
        *,
        image_ref: str,
        image_digest: str,
        accepted_decisions: set[str],
    ) -> ShellImageAdmissionRead | None:
        for admission in self.image_admissions.get(project_id, []):
            if (
                admission.image_ref == image_ref
                and admission.image_digest == image_digest
                and admission.policy_decision in accepted_decisions
            ):
                return admission
        return None

    async def get_shell_image_admission_policy(
        self,
        project_id: UUID,
    ) -> ShellImageAdmissionPolicyRead:
        return self.image_policies.get(project_id) or default_shell_image_admission_policy(
            project_id
        )

    async def summarize_shell_image_admission_governance(
        self,
        project_id: UUID,
    ) -> ShellImageAdmissionGovernanceRead:
        return summarize_shell_image_admission_governance(self.image_admissions.get(project_id, []))

    async def list_shell_image_admissions(self, project_id: UUID) -> list[ShellImageAdmissionRead]:
        return self.image_admissions.get(project_id, [])

    async def update_shell_image_admission_evidence(
        self,
        *,
        project_id: UUID,
        admission_id: UUID,
        actor_id: UUID,
        evidence: dict[str, object],
    ) -> ShellImageAdmissionRead:
        updated: ShellImageAdmissionRead | None = None
        next_admissions: list[ShellImageAdmissionRead] = []
        for admission in self.image_admissions.get(project_id, []):
            if admission.id == admission_id:
                updated = admission.model_copy(
                    update={
                        "evidence": evidence,
                        "updated_by": actor_id,
                        "updated_at": datetime.now(UTC),
                    }
                )
                next_admissions.append(updated)
            else:
                next_admissions.append(admission)
        if updated is None:
            raise ToolRegistryResourceNotFoundError("image admission not found")
        self.image_admissions[project_id] = next_admissions
        return updated

    async def record_shell_image_artifact_cleanup_run(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        run: ShellImageArtifactCleanupRunRead,
    ) -> ShellImageArtifactCleanupRunRead:
        self.image_artifact_cleanup_runs.setdefault(project_id, []).insert(0, run)
        return run

    async def list_shell_image_artifact_cleanup_runs(
        self,
        project_id: UUID,
        *,
        limit: int = 20,
    ) -> list[ShellImageArtifactCleanupRunRead]:
        return self.image_artifact_cleanup_runs.get(project_id, [])[:limit]

    async def get_shell_image_artifact_cleanup_schedule(
        self,
        project_id: UUID,
    ) -> ShellImageArtifactCleanupScheduleRead | None:
        return self.image_artifact_cleanup_schedules.get(project_id)

    async def upsert_shell_image_artifact_cleanup_schedule(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageArtifactCleanupScheduleUpdateRequest,
    ) -> ShellImageArtifactCleanupScheduleRead:
        now = datetime.now(UTC)
        existing = self.image_artifact_cleanup_schedules.get(project_id)
        schedule = ShellImageArtifactCleanupScheduleRead(
            id=existing.id if existing else uuid4(),
            project_id=project_id,
            enabled=request.enabled,
            interval_hours=request.interval_hours,
            limit=request.limit,
            next_run_at=request.next_run_at or now + timedelta(hours=request.interval_hours),
            last_run_id=existing.last_run_id if existing else None,
            last_run_at=existing.last_run_at if existing else None,
            created_by=existing.created_by if existing else actor_id,
            updated_by=actor_id,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self.image_artifact_cleanup_schedules[project_id] = schedule
        return schedule

    async def list_due_shell_image_artifact_cleanup_schedules(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[ShellImageArtifactCleanupScheduleRead]:
        schedules = [
            schedule
            for schedule in self.image_artifact_cleanup_schedules.values()
            if schedule.enabled and schedule.next_run_at is not None and schedule.next_run_at <= now
        ]
        return schedules[:limit]

    async def mark_shell_image_artifact_cleanup_schedule_run(
        self,
        *,
        project_id: UUID,
        schedule_id: UUID,
        actor_id: UUID,
        run_id: UUID,
        completed_at: datetime,
    ) -> ShellImageArtifactCleanupScheduleRead:
        schedule = self.image_artifact_cleanup_schedules[project_id]
        updated = schedule.model_copy(
            update={
                "last_run_id": run_id,
                "last_run_at": completed_at,
                "next_run_at": completed_at + timedelta(hours=schedule.interval_hours),
                "updated_by": actor_id,
                "updated_at": completed_at,
            }
        )
        self.image_artifact_cleanup_schedules[project_id] = updated
        return updated

    async def upsert_shell_image_admission_policy(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageAdmissionPolicyUpdateRequest,
    ) -> ShellImageAdmissionPolicyRead:
        now = datetime.now(UTC)
        existing = self.image_policies.get(project_id)
        policy = ShellImageAdmissionPolicyRead(
            id=existing.id if existing else uuid4(),
            configured=True,
            project_id=project_id,
            enforcement_mode=request.enforcement_mode,
            cosign_required=request.cosign_required,
            notation_enabled=request.notation_enabled,
            notation_trust_policy=request.notation_trust_policy,
            sbom_artifact_retention_enabled=request.sbom_artifact_retention_enabled,
            scan_report_retention_enabled=request.scan_report_retention_enabled,
            artifact_store_prefix=request.artifact_store_prefix,
            artifact_retention_days=request.artifact_retention_days,
            blocked_severities=request.blocked_severities,
            created_by=existing.created_by if existing else actor_id,
            updated_by=actor_id,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self.image_policies[project_id] = policy
        return policy

    async def create_notation_trust_certificate(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: NotationTrustCertificateCreateRequest,
    ) -> NotationTrustCertificateRead:
        now = datetime.now(UTC)
        version = (
            len(
                [
                    item
                    for item in self.notation_trust_certificates.get(project_id, [])
                    if item.store_type == request.store_type
                    and item.store_name == request.store_name
                    and item.certificate_ref == request.certificate_ref
                ]
            )
            + 1
        )
        certificate = NotationTrustCertificateRead(
            id=uuid4(),
            project_id=project_id,
            store_type=request.store_type,
            store_name=request.store_name,
            certificate_ref=request.certificate_ref,
            version=version,
            artifact_ref=(
                f"s3://capievo/notation-trust/{project_id}/"
                f"{request.store_type}/{request.store_name}/{version}.pem"
            ),
            artifact_sha256="a" * 64,
            artifact_size_bytes=len(request.certificate_pem.encode("utf-8")),
            artifact_content_type="application/x-pem-file",
            certificate_subject="CN=AegisFlow Test Root",
            certificate_issuer="CN=AegisFlow Test Root",
            certificate_not_before=now,
            certificate_not_after=now + timedelta(days=365),
            certificate_count=1,
            description=request.description,
            status="active",
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        self.notation_trust_certificates.setdefault(project_id, []).append(certificate)
        return certificate

    async def list_notation_trust_certificates(
        self,
        project_id: UUID,
    ) -> list[NotationTrustCertificateRead]:
        return self.notation_trust_certificates.get(project_id, [])

    async def list_project_shell_templates(self, project_id: UUID) -> list[ShellTemplateRead]:
        return self.shell_templates.get(project_id, [])

    async def preview_shell_template(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellTemplatePreviewRequest,
    ) -> ShellTemplatePreviewResponse:
        template = await self.get_active_shell_template(
            project_id=project_id,
            template_ref=request.template_ref,
            template_version=request.template_version,
        )
        if template is None:
            raise ToolRegistryResourceNotFoundError("shell template not found")
        preview = build_shell_template_preview(
            ShellTemplatePolicyInput(
                project_id=template.project_id,
                template_ref=template.template_ref,
                template_version=template.template_version,
                risk_level=template.risk_level,
                environment_key=template.environment_key,
                image_ref=template.image_ref,
                image_digest=template.image_digest,
                entrypoint=template.entrypoint,
                argv_template=template.argv_template,
                parameter_schema=template.parameter_schema,
                timeout_seconds=template.timeout_seconds,
                image_registry_digest=template.image_registry_digest,
                image_admission_status=template.image_admission_status,
            ),
            parameters=request.parameters,
            run_id=request.run_id,
            trace_id=request.trace_id,
        )
        return ShellTemplatePreviewResponse(
            template_ref=template.template_ref,
            template_version=template.template_version,
            rendered_argv=preview.rendered_argv,
            command_preview=preview.command_preview,
            command_hash=preview.command_hash,
            sandbox=preview.sandbox,
            policy=ShellTemplatePolicySummary(
                approval_required=preview.policy.approval_required,
                digest_required=preview.policy.digest_required,
                allowlisted=preview.policy.allowlisted,
                reasons=preview.policy.reasons,
            ),
            trace_link=preview.trace_link,
        )

    async def get_active_shell_template(
        self,
        *,
        project_id: UUID,
        template_ref: str,
        template_version: int,
    ) -> ShellTemplateRead | None:
        for template in self.shell_templates.get(project_id, []):
            if (
                template.template_ref == template_ref
                and template.template_version == template_version
                and template.status == "active"
            ):
                return template
        return None


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


def _public_certificate_pem(common_name: str = "AegisFlow Test Root") -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime(2026, 7, 1, tzinfo=UTC))
        .not_valid_after(datetime(2027, 7, 1, tzinfo=UTC))
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


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


class StaticDigestResolver:
    def __init__(self, result: OciManifestDigestResult) -> None:
        self._result = result

    async def resolve(self, image_ref: str) -> OciManifestDigestResult:
        return self._result.model_copy(update={"image_ref": image_ref})


def build_client(
    *,
    account: AccountPrincipal,
    provider: ProjectAccessProvider,
    registry_store: InMemoryToolRegistryStore,
    audit_store: InMemoryAuditEventStore,
    egress_policy: EgressPolicy | None = None,
    digest_resolver: object | None = None,
    evidence_provider: object | None = None,
    artifact_object_store: object | None = None,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: provider
    app.dependency_overrides[get_tool_registry_store] = lambda: registry_store
    app.dependency_overrides[get_audit_event_store] = lambda: audit_store
    resolved_egress_policy = egress_policy or EgressPolicy(
        resolver=lambda _host, _port: [ip_address("93.184.216.34")]
    )
    app.dependency_overrides[get_mcp_egress_policy] = lambda: resolved_egress_policy
    if digest_resolver is not None:
        app.dependency_overrides[get_oci_digest_resolver] = lambda: digest_resolver
    if evidence_provider is not None:
        app.dependency_overrides[get_shell_image_evidence_provider] = lambda: evidence_provider
    if artifact_object_store is not None:
        app.dependency_overrides[get_shell_image_artifact_object_store] = lambda: (
            artifact_object_store
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
        roles=["project_admin"],
        permissions=permissions,
    )


def test_tool_registry_shell_image_policy_round_trips_with_sanitized_audit() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
    )
    trust_policy = {
        "version": "1.0",
        "trustPolicies": [
            {
                "name": "internal-runtime-images",
                "registryScopes": ["registry.example/aegis/runtime"],
                "signatureVerification": {"level": "strict"},
                "trustStores": ["ca:aegis-runtime"],
                "trustedIdentities": ["x509.subject: C=CN, ST=ZJ, O=AegisFlow, CN=SecureBuilder"],
            }
        ],
    }

    default_response = client.get(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/admission-policy"
    )
    update_response = client.put(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/admission-policy",
        json={
            "enforcement_mode": "enforce",
            "cosign_required": True,
            "notation_enabled": True,
            "notation_trust_policy": trust_policy,
            "sbom_artifact_retention_enabled": True,
            "scan_report_retention_enabled": True,
            "artifact_store_prefix": "shell-image-admissions/prod",
            "artifact_retention_days": 90,
            "blocked_severities": ["CRITICAL", "HIGH", "HIGH"],
        },
    )
    follow_up_response = client.get(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/admission-policy"
    )

    assert default_response.status_code == 200
    assert default_response.json()["configured"] is False
    assert default_response.json()["enforcement_mode"] == "dry_run"
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["configured"] is True
    assert updated["enforcement_mode"] == "enforce"
    assert updated["cosign_required"] is True
    assert updated["notation_enabled"] is True
    assert updated["notation_trust_policy"] == trust_policy
    assert updated["sbom_artifact_retention_enabled"] is True
    assert updated["scan_report_retention_enabled"] is True
    assert updated["artifact_store_prefix"] == "shell-image-admissions/prod"
    assert updated["artifact_retention_days"] == 90
    assert updated["blocked_severities"] == ["HIGH", "CRITICAL"]
    assert follow_up_response.status_code == 200
    assert follow_up_response.json()["id"] == updated["id"]
    assert follow_up_response.json()["configured"] is True

    update_event = next(
        event
        for event in audit_store.events
        if event["action"] == "tool_registry.shell_image_policy.update"
    )
    metadata = update_event["metadata"]
    assert metadata == {
        "configured": True,
        "enforcement_mode": "enforce",
        "cosign_required": True,
        "notation_enabled": True,
        "trust_policy_count": 1,
        "sbom_artifact_retention_enabled": True,
        "scan_report_retention_enabled": True,
        "artifact_retention_days": 90,
        "blocked_severities": ["HIGH", "CRITICAL"],
    }
    assert "SecureBuilder" not in str(metadata)
    assert "trustedIdentities" not in str(metadata)


def test_tool_registry_shell_image_policy_rejects_secret_like_trust_policy_keys() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=InMemoryToolRegistryStore(),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.put(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/admission-policy",
        json={
            "notation_enabled": True,
            "notation_trust_policy": {
                "version": "1.0",
                "trustPolicies": [],
                "token": "raw-secret-token",
            },
        },
    )

    assert response.status_code == 422
    assert "raw-secret-token" not in response.text


def test_tool_registry_notation_trust_certificate_api_stores_descriptor_without_raw_pem() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
    )
    certificate_pem = _public_certificate_pem()

    create_response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/notation/trust-certificates",
        json={
            "store_type": "ca",
            "store_name": "aegis-flow",
            "certificate_ref": "root",
            "certificate_pem": certificate_pem,
            "description": "AegisFlow public root CA",
        },
    )
    list_response = client.get(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/notation/trust-certificates"
    )

    assert create_response.status_code == 201
    body = create_response.json()
    assert body["store_type"] == "ca"
    assert body["store_name"] == "aegis-flow"
    assert body["certificate_ref"] == "root"
    assert body["version"] == 1
    assert body["artifact_ref"].startswith("s3://")
    assert "certificate_pem" not in body
    assert "BEGIN CERTIFICATE" not in create_response.text
    assert list_response.status_code == 200
    assert list_response.json()[0]["artifact_sha256"] == "a" * 64
    create_event = next(
        event
        for event in audit_store.events
        if event["action"] == "tool_registry.notation_trust_certificate.create"
    )
    metadata = cast(dict[str, object], create_event["metadata"])
    assert metadata["store_type"] == "ca"
    assert metadata["store_name"] == "aegis-flow"
    assert "BEGIN CERTIFICATE" not in json.dumps(metadata)


def test_tool_registry_notation_trust_certificate_api_rejects_private_key_material() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=InMemoryToolRegistryStore(),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/notation/trust-certificates",
        json={
            "store_type": "ca",
            "store_name": "aegis-flow",
            "certificate_ref": "root",
            "certificate_pem": (
                "-----BEGIN PRIVATE KEY-----\nprivate-key-material\n-----END PRIVATE KEY-----\n"
            ),
        },
    )

    assert response.status_code == 422
    assert "private-key-material" not in response.text
    assert "private" in response.text.lower()


def test_tool_registry_shell_image_policy_write_requires_permission() -> None:
    project = make_project(permissions=["tool-registry:view"])
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=InMemoryToolRegistryStore(),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.put(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/admission-policy",
        json={"enforcement_mode": "enforce"},
    )

    assert response.status_code == 403


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


def test_tool_registry_environment_returns_egress_allowed_hosts() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/environments",
        json={
            "key": "prod",
            "name": "Production",
            "egress_allowed_hosts": [" MCP.Example.com ", "*.Trusted.Example"],
        },
    )

    assert response.status_code == 201
    assert response.json()["egress_allowed_hosts"] == [
        "mcp.example.com",
        "*.trusted.example",
    ]


def test_tool_registry_shell_template_accepts_execution_metadata() -> None:
    project = make_project(permissions=["tool-registry:write"])
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=InMemoryToolRegistryStore(),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-templates",
        json={
            "template_ref": "echo-shell",
            "template_version": 1,
            "name": "Echo Shell",
            "risk_level": "low",
            "environment_key": "test",
            "image_ref": "redis:7-alpine",
            "image_digest": "sha256:" + ("1" * 64),
            "entrypoint": "/bin/sh",
            "argv_template": ["-lc", "echo {{message}}"],
            "parameter_schema": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
                "additionalProperties": False,
            },
            "timeout_seconds": 30,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["template_ref"] == "echo-shell"
    assert payload["image_ref"] == "redis:7-alpine"
    assert payload["image_digest"] == "sha256:" + ("1" * 64)
    assert payload["entrypoint"] == "/bin/sh"
    assert payload["argv_template"] == ["-lc", "echo {{message}}"]
    assert payload["parameter_schema"]["required"] == ["message"]
    assert payload["timeout_seconds"] == 30


def test_tool_registry_rejects_mcp_server_when_environment_allowlist_does_not_match() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    audit_store = InMemoryAuditEventStore()
    registry_store = InMemoryToolRegistryStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
    )
    env_response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/environments",
        json={
            "key": "prod",
            "name": "Production",
            "egress_allowed_hosts": ["mcp.example.com"],
        },
    )
    assert env_response.status_code == 201

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/mcp-servers",
        json={
            "server_ref": "mcp-other",
            "name": "Other MCP",
            "base_url": "https://other.example.com/mcp?token=must-not-log",
            "environment_key": "prod",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "MCP server egress target is not allowed"
    assert "must-not-log" not in response.text
    assert audit_store.events[-1]["action"] == "tool_registry.mcp_server.egress_denied"
    assert audit_store.events[-1]["result"] == "failure"
    metadata = audit_store.events[-1]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["reason_code"] == "host_not_allowlisted"
    assert metadata["hostname"] == "other.example.com"
    assert "must-not-log" not in str(metadata)


def test_tool_registry_rejects_mcp_server_localhost_by_default() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=InMemoryToolRegistryStore(),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/mcp-servers",
        json={
            "server_ref": "local-mcp",
            "name": "Local MCP",
            "base_url": "http://127.0.0.1:8765/mcp",
            "environment_key": "test",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "MCP server egress target is not allowed"


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


def test_tool_registry_enforces_shell_template_image_policy_on_create() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=InMemoryToolRegistryStore(),
        audit_store=InMemoryAuditEventStore(),
    )
    valid_digest = "sha256:" + ("a" * 64)

    missing_digest = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-templates",
        json={
            "template_ref": "diag-missing-digest",
            "template_version": 1,
            "name": "Diagnostics Missing Digest",
            "risk_level": "low",
            "environment_key": "test",
            "image_ref": "redis:7-alpine",
            "entrypoint": "/bin/sh",
            "argv_template": ["-lc", "echo {{message}}"],
            "parameter_schema": {"type": "object"},
            "timeout_seconds": 10,
        },
    )
    disallowed_image = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-templates",
        json={
            "template_ref": "diag-disallowed-image",
            "template_version": 1,
            "name": "Diagnostics Disallowed Image",
            "risk_level": "low",
            "environment_key": "test",
            "image_ref": "alpine:3.20",
            "image_digest": valid_digest,
            "entrypoint": "/bin/sh",
            "argv_template": ["-lc", "echo {{message}}"],
            "parameter_schema": {"type": "object"},
            "timeout_seconds": 10,
        },
    )
    latest_image = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-templates",
        json={
            "template_ref": "diag-latest-image",
            "template_version": 1,
            "name": "Diagnostics Latest Image",
            "risk_level": "low",
            "environment_key": "test",
            "image_ref": "redis:latest",
            "image_digest": valid_digest,
            "entrypoint": "/bin/sh",
            "argv_template": ["-lc", "echo {{message}}"],
            "parameter_schema": {"type": "object"},
            "timeout_seconds": 10,
        },
    )

    assert missing_digest.status_code == 400
    assert missing_digest.json()["detail"] == "Shell template image digest is required"
    assert disallowed_image.status_code == 400
    assert disallowed_image.json()["detail"] == "Shell template image is not allowlisted"
    assert latest_image.status_code == 400
    assert latest_image.json()["detail"] == "Shell template image tag latest is forbidden"


def test_tool_registry_lists_and_previews_shell_templates_without_leaking_secrets() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    valid_digest = "sha256:" + ("b" * 64)
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
        digest_resolver=StaticDigestResolver(
            OciManifestDigestResult(
                image_ref="registry.example/aegis/runtime:7-alpine",
                registry_url="https://registry.example/v2/aegis/runtime/manifests/7-alpine",
                registry_digest=valid_digest,
                computed_digest=valid_digest,
                digest_match=True,
                content_type="application/vnd.oci.image.manifest.v1+json",
                manifest_size_bytes=128,
            )
        ),
    )
    admission_response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/admissions/resolve",
        json={
            "image_ref": "registry.example/aegis/runtime:7-alpine",
            "image_digest": valid_digest,
        },
    )
    create_response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-templates",
        json={
            "template_ref": "k8s-log-collector",
            "template_version": 3,
            "name": "日志采集",
            "risk_level": "high",
            "environment_key": "prod",
            "image_ref": "registry.example/aegis/runtime:7-alpine",
            "image_digest": valid_digest,
            "entrypoint": "/bin/sh",
            "argv_template": ["-lc", "echo {{message}} && echo token={{token}}"],
            "parameter_schema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "token": {"type": "string"},
                },
                "required": ["message", "token"],
                "additionalProperties": False,
            },
            "timeout_seconds": 20,
        },
    )

    list_response = client.get(f"/api/v1/projects/{project.id}/tool-registry/shell-templates")
    preview_response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-templates/preview",
        json={
            "template_ref": "k8s-log-collector",
            "template_version": 3,
            "parameters": {"message": "hello", "token": "raw-token-value"},
            "run_id": "run-shell-preview",
            "trace_id": "trace-shell-preview",
        },
    )

    assert admission_response.status_code == 200
    assert admission_response.json()["policy_decision"] == "approved"
    assert create_response.status_code == 201
    assert create_response.json()["image_admission_status"] == "approved"
    assert list_response.status_code == 200
    assert list_response.json()[0]["template_ref"] == "k8s-log-collector"
    assert preview_response.status_code == 200
    body = preview_response.json()
    assert body["template_ref"] == "k8s-log-collector"
    assert body["rendered_argv"] == ["-lc", "echo hello && echo token=[redacted]"]
    assert body["command_hash"].startswith("sha256:")
    assert body["sandbox"]["network_mode"] == "none"
    assert body["policy"]["approval_required"] is True
    assert body["trace_link"].endswith("run_id=run-shell-preview&trace_id=trace-shell-preview")
    assert "raw-token-value" not in preview_response.text
    assert [event["action"] for event in audit_store.events][-4:] == [
        "tool_registry.shell_image_admission.resolve",
        "tool_registry.shell_template.create",
        "tool_registry.shell_template.list",
        "tool_registry.shell_template.preview",
    ]


def test_tool_registry_resolves_shell_image_admission_and_allows_high_risk_template() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    digest = "sha256:" + ("c" * 64)
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
        digest_resolver=StaticDigestResolver(
            OciManifestDigestResult(
                image_ref="registry.example/aegis/runtime:7-alpine",
                registry_url="https://registry.example/v2/aegis/runtime/manifests/7-alpine",
                registry_digest=digest,
                computed_digest=digest,
                digest_match=True,
                content_type="application/vnd.oci.image.manifest.v1+json",
                manifest_size_bytes=128,
            )
        ),
    )

    admission = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/admissions/resolve",
        json={
            "image_ref": "registry.example/aegis/runtime:7-alpine",
            "image_digest": digest,
        },
    )
    created = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-templates",
        json={
            "template_ref": "prod-diag",
            "template_version": 1,
            "name": "Production Diagnostics",
            "risk_level": "high",
            "environment_key": "prod",
            "image_ref": "registry.example/aegis/runtime:7-alpine",
            "image_digest": digest,
            "entrypoint": "/bin/sh",
            "argv_template": ["-lc", "echo ok"],
            "parameter_schema": {"type": "object"},
            "timeout_seconds": 30,
        },
    )

    assert admission.status_code == 200
    assert admission.json()["policy_decision"] == "approved"
    assert admission.json()["signature_status"] == "not_checked"
    assert "schemaVersion" not in admission.text
    assert "layers" not in admission.text
    assert "token" not in admission.text.lower()
    assert created.status_code == 201
    assert created.json()["image_admission_status"] == "approved"
    assert created.json()["image_registry_digest"] == digest
    assert [event["action"] for event in audit_store.events][-2:] == [
        "tool_registry.shell_image_admission.resolve",
        "tool_registry.shell_template.create",
    ]
    admission_metadata = cast(dict[str, object], audit_store.events[-2]["metadata"])
    assert admission_metadata["policy_decision"] == "approved"


def test_tool_registry_shell_image_policy_dry_run_allows_would_reject_template() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    digest = "sha256:" + ("d" * 64)
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
        digest_resolver=StaticDigestResolver(
            OciManifestDigestResult(
                image_ref="registry.example/aegis/runtime:7-alpine",
                registry_url="https://registry.example/v2/aegis/runtime/manifests/7-alpine",
                registry_digest=digest,
                computed_digest=digest,
                digest_match=True,
                content_type="application/vnd.oci.image.manifest.v1+json",
                manifest_size_bytes=128,
            )
        ),
        evidence_provider=StaticShellImageEvidenceProvider(
            ShellImageEvidenceResult(
                signature_status="not_checked",
                sbom_status="passed",
                vulnerability_status="passed",
                policy_decision="approved",
                decision_reason="SBOM and vulnerability evidence passed",
                evidence={
                    "sbom": {"tool": "trivy", "format": "CycloneDX", "component_count": 2},
                    "vulnerabilities": {
                        "tool": "trivy",
                        "severity_counts": {"HIGH": 0, "CRITICAL": 0},
                        "blocked_count": 0,
                    },
                },
            )
        ),
    )

    policy_response = client.put(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/admission-policy",
        json={
            "enforcement_mode": "dry_run",
            "cosign_required": True,
            "notation_trust_policy": {
                "version": "1.0",
                "trustPolicies": [
                    {
                        "name": "runtime-images",
                        "registryScopes": ["registry.example/aegis/runtime"],
                        "signatureVerification": {"level": "strict"},
                        "trustStores": ["ca:aegis-runtime"],
                        "trustedIdentities": ["x509.subject: CN=SecureBuilder"],
                    }
                ],
            },
        },
    )
    admission = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/admissions/resolve",
        json={
            "image_ref": "registry.example/aegis/runtime:7-alpine",
            "image_digest": digest,
        },
    )
    created = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-templates",
        json={
            "template_ref": "dry-run-diag",
            "template_version": 1,
            "name": "Dry Run Diagnostics",
            "risk_level": "high",
            "environment_key": "prod",
            "image_ref": "registry.example/aegis/runtime:7-alpine",
            "image_digest": digest,
            "entrypoint": "/bin/sh",
            "argv_template": ["-lc", "echo ok"],
            "parameter_schema": {"type": "object"},
            "timeout_seconds": 30,
        },
    )

    assert policy_response.status_code == 200
    assert admission.status_code == 200
    assert admission.json()["policy_decision"] == "would_reject"
    assert created.status_code == 201
    assert created.json()["image_admission_status"] == "would_reject"
    rendered = admission.text + repr(audit_store.events)
    assert "SecureBuilder" not in rendered
    admission_metadata = cast(dict[str, object], audit_store.events[-2]["metadata"])
    assert admission_metadata["policy_decision"] == "would_reject"
    assert admission_metadata["enforcement_mode"] == "dry_run"
    assert admission_metadata["cosign_required"] is True


def test_tool_registry_shell_image_policy_runs_notation_provider_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    digest = "sha256:" + ("9" * 64)
    monkeypatch.setattr(
        "backend.app.tool_registry.image_evidence.shutil.which",
        lambda _: None,
    )
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
        digest_resolver=StaticDigestResolver(
            OciManifestDigestResult(
                image_ref="registry.example/aegis/runtime:7-alpine",
                registry_url="https://registry.example/v2/aegis/runtime/manifests/7-alpine",
                registry_digest=digest,
                computed_digest=digest,
                digest_match=True,
                content_type="application/vnd.oci.image.manifest.v1+json",
                manifest_size_bytes=128,
            )
        ),
    )

    policy_response = client.put(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/admission-policy",
        json={
            "enforcement_mode": "dry_run",
            "notation_enabled": True,
            "notation_trust_policy": {
                "version": "1.0",
                "trustPolicies": [
                    {
                        "name": "runtime-images",
                        "registryScopes": ["registry.example/aegis/runtime"],
                        "signatureVerification": {"level": "strict"},
                        "trustStores": ["ca:aegis-runtime"],
                        "trustedIdentities": ["x509.subject: CN=SecureBuilder"],
                    }
                ],
            },
        },
    )
    admission = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/admissions/resolve",
        json={
            "image_ref": "registry.example/aegis/runtime:7-alpine",
            "image_digest": digest,
        },
    )

    assert policy_response.status_code == 200
    assert admission.status_code == 200
    body = admission.json()
    assert body["signature_status"] == "failed"
    assert body["policy_decision"] == "would_reject"
    assert body["evidence"]["signature"] == {"tool": "notation", "status": "failed"}
    rendered = admission.text + repr(audit_store.events)
    assert "SecureBuilder" not in rendered
    assert "trustPolicies" not in rendered
    admission_metadata = cast(dict[str, object], audit_store.events[-1]["metadata"])
    assert admission_metadata["policy_decision"] == "would_reject"
    assert admission_metadata["enforcement_mode"] == "dry_run"


def test_tool_registry_shell_image_admission_records_real_evidence_statuses_safely() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    digest = "sha256:" + ("e" * 64)
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
        digest_resolver=StaticDigestResolver(
            OciManifestDigestResult(
                image_ref="registry.example/aegis/runtime:7-alpine",
                registry_url="https://registry.example/v2/aegis/runtime/manifests/7-alpine",
                registry_digest=digest,
                computed_digest=digest,
                digest_match=True,
                content_type="application/vnd.oci.image.manifest.v1+json",
                manifest_size_bytes=128,
            )
        ),
        evidence_provider=StaticShellImageEvidenceProvider(
            ShellImageEvidenceResult(
                signature_status="passed",
                sbom_status="passed",
                vulnerability_status="passed",
                policy_decision="approved",
                decision_reason=(
                    "registry digest, signature, SBOM, and vulnerability evidence passed"
                ),
                evidence={
                    "signature": {
                        "tool": "cosign",
                        "identity": "aegis-ci@example.com",
                        "raw_payload": "raw-token-value",
                    },
                    "sbom": {
                        "tool": "trivy",
                        "format": "CycloneDX",
                        "component_count": 12,
                        "raw_sbom": {"components": [{"name": "secret-package"}]},
                    },
                    "vulnerabilities": {
                        "tool": "trivy",
                        "severity_counts": {"LOW": 1, "HIGH": 0, "CRITICAL": 0},
                        "blocked_count": 0,
                        "raw_report": {"Description": "raw details"},
                    },
                },
            )
        ),
    )

    admission = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/admissions/resolve",
        json={
            "image_ref": "registry.example/aegis/runtime:7-alpine",
            "image_digest": digest,
        },
    )

    assert admission.status_code == 200
    body = admission.json()
    assert body["policy_decision"] == "approved"
    assert body["signature_status"] == "passed"
    assert body["sbom_status"] == "passed"
    assert body["vulnerability_status"] == "passed"
    assert body["evidence"]["sbom"]["component_count"] == 12
    assert body["evidence"]["vulnerabilities"]["blocked_count"] == 0
    rendered = admission.text + repr(audit_store.events[-1])
    assert "raw-token-value" not in rendered
    assert "raw_sbom" not in rendered
    assert "raw_report" not in rendered
    metadata = cast(dict[str, object], audit_store.events[-1]["metadata"])
    assert metadata["signature_status"] == "passed"
    assert metadata["sbom_status"] == "passed"
    assert metadata["vulnerability_status"] == "passed"
    assert metadata["blocked_vulnerability_count"] == 0


def test_tool_registry_shell_image_governance_summarizes_artifacts_and_blocks() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    now = datetime.now(UTC)
    registry_store.image_admissions[project.id] = [
        ShellImageAdmissionRead(
            id=uuid4(),
            project_id=project.id,
            image_ref="registry.example/aegis/runtime:7-alpine",
            image_digest="sha256:" + ("a" * 64),
            registry_url="https://registry.example/v2/aegis/runtime/manifests/7-alpine",
            registry_digest="sha256:" + ("a" * 64),
            digest_match=True,
            signature_status="passed",
            sbom_status="passed",
            vulnerability_status="failed",
            policy_decision="would_reject",
            decision_reason=("dry-run would reject: vulnerability scan found blocked severities"),
            checked_at=now,
            evidence={
                "sbom": {
                    "tool": "trivy",
                    "format": "CycloneDX",
                    "component_count": 2,
                    "status": "passed",
                    "artifact_ref": "s3://capievo/shell-image-admissions/sbom.json",
                    "artifact_sha256": "a" * 64,
                    "artifact_size_bytes": 120,
                    "artifact_retention_days": 1,
                    "artifact_retention_expires_at": (now - timedelta(days=1)).isoformat(),
                },
                "vulnerabilities": {
                    "tool": "trivy",
                    "severity_counts": {"HIGH": 1},
                    "total_count": 1,
                    "blocked_severities": ["HIGH"],
                    "blocked_count": 1,
                    "status": "failed",
                    "artifact_ref": "s3://capievo/shell-image-admissions/scan.json",
                    "artifact_sha256": "b" * 64,
                    "artifact_size_bytes": 240,
                    "artifact_retention_days": 30,
                    "artifact_retention_expires_at": (now + timedelta(days=30)).isoformat(),
                },
            },
            created_by=uuid4(),
            updated_by=uuid4(),
            created_at=now,
            updated_at=now,
        ),
        ShellImageAdmissionRead(
            id=uuid4(),
            project_id=project.id,
            image_ref="registry.example/aegis/worker:7-alpine",
            image_digest="sha256:" + ("b" * 64),
            registry_url="https://registry.example/v2/aegis/worker/manifests/7-alpine",
            registry_digest="sha256:" + ("b" * 64),
            digest_match=True,
            signature_status="passed",
            sbom_status="passed",
            vulnerability_status="passed",
            policy_decision="approved",
            decision_reason="registry digest, SBOM, and vulnerability evidence passed",
            checked_at=now,
            evidence={},
            created_by=uuid4(),
            updated_by=uuid4(),
            created_at=now,
            updated_at=now,
        ),
    ]
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
    )

    response = client.get(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/admissions/governance"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_admissions"] == 2
    assert body["policy_decisions"] == {"approved": 1, "would_reject": 1, "rejected": 0}
    assert body["artifact_counts"] == {
        "sbom": 1,
        "scan_report": 1,
        "expired": 1,
    }
    assert body["blocked_vulnerability_count"] == 1
    assert body["top_block_reasons"] == [
        {"reason": "vulnerability scan found blocked severities", "count": 1}
    ]
    assert audit_store.events[-1]["action"] == "tool_registry.shell_image_admission.governance"
    metadata = cast(dict[str, object], audit_store.events[-1]["metadata"])
    assert metadata["total_admissions"] == 2
    assert metadata["expired_artifact_count"] == 1
    rendered = response.text + repr(audit_store.events[-1])
    assert "raw_report" not in rendered
    assert "raw vulnerability" not in rendered


def test_tool_registry_shell_image_artifact_cleanup_dry_run_and_execute() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    audit_store = InMemoryAuditEventStore()
    now = datetime.now(UTC)
    expired_ref = "s3://capievo/shell-image-admissions/expired-sbom.json"
    object_store = InMemoryShellImageArtifactObjectStore(
        bucket="capievo",
        versioning_status="Enabled",
        object_lock_enabled=True,
        default_retention_mode="GOVERNANCE",
        default_retention_days=30,
        lifecycle_rules=[
            {
                "ID": "shell-image-admission-expiration",
                "Status": "Enabled",
                "Filter": {"Prefix": "shell-image-admissions/"},
                "Expiration": {"Days": 30},
                "NoncurrentVersionExpiration": {"NoncurrentDays": 30},
            }
        ],
        version_reconciliation={
            "shell-image-admissions/": {
                "current_version_count": 1,
                "noncurrent_version_count": 0,
                "delete_marker_count": 0,
            }
        },
    )
    object_store.objects[expired_ref] = StoredShellImageArtifact(
        body=b'{"components":[{"name":"secret-package"}]}',
        content_type="application/vnd.cyclonedx+json",
        metadata={
            "artifact-kind": "sbom",
            "artifact-sha256": "a" * 64,
            "project-id": str(project.id),
        },
    )
    registry_store.image_admissions[project.id] = [
        ShellImageAdmissionRead(
            id=uuid4(),
            project_id=project.id,
            image_ref="registry.example/aegis/runtime:7-alpine",
            image_digest="sha256:" + ("a" * 64),
            registry_url="https://registry.example/v2/aegis/runtime/manifests/7-alpine",
            registry_digest="sha256:" + ("a" * 64),
            digest_match=True,
            signature_status="passed",
            sbom_status="passed",
            vulnerability_status="passed",
            policy_decision="approved",
            decision_reason="registry digest, SBOM, and vulnerability evidence passed",
            checked_at=now,
            evidence={
                "sbom": {
                    "tool": "trivy",
                    "format": "CycloneDX",
                    "component_count": 1,
                    "status": "passed",
                    "artifact_ref": expired_ref,
                    "artifact_sha256": "a" * 64,
                    "artifact_size_bytes": 39,
                    "artifact_retention_days": 1,
                    "artifact_retention_expires_at": (now - timedelta(days=1)).isoformat(),
                    "raw_sbom": {"components": [{"name": "secret-package"}]},
                }
            },
            created_by=uuid4(),
            updated_by=uuid4(),
            created_at=now,
            updated_at=now,
        )
    ]
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        audit_store=audit_store,
        artifact_object_store=object_store,
    )

    governance = client.get(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/artifacts/governance"
    )
    dry_run = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/artifacts/cleanup-runs",
        json={"dry_run": True, "limit": 10},
    )

    assert governance.status_code == 200
    assert governance.json()["retention_controls"] == {
        "bucket": "capievo",
        "versioning_status": "Enabled",
        "object_lock_enabled": True,
        "worm_capable": True,
        "default_retention_configured": True,
        "default_retention_mode": "GOVERNANCE",
        "default_retention_days": 30,
        "default_retention_years": None,
        "error": "",
    }
    assert governance.json()["lifecycle_drift"]["status"] == "ready"
    assert governance.json()["version_reconciliation"]["status"] == "ready"
    assert governance.json()["expired_artifact_count"] == 1
    assert governance.json()["candidates"] == []
    assert dry_run.status_code == 200
    assert dry_run.json()["id"]
    assert dry_run.json()["project_id"] == str(project.id)
    assert dry_run.json()["trigger_type"] == "manual"
    assert dry_run.json()["status"] == "succeeded"
    assert dry_run.json()["dry_run"] is True
    assert dry_run.json()["candidate_count"] == 1
    assert dry_run.json()["candidates"][0]["artifact_ref_hash"]
    assert dry_run.json()["candidates"][0]["artifact_sha256_prefix"] == "a" * 12
    assert "artifact_ref" not in dry_run.json()["candidates"][0]
    assert "artifact_sha256" not in dry_run.json()["candidates"][0]
    assert expired_ref in object_store.objects
    history = client.get(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/artifacts/cleanup-runs"
    )
    assert history.status_code == 200
    assert history.json()[0]["id"] == dry_run.json()["id"]
    assert history.json()[0]["lifecycle_drift"]["status"] == "ready"
    assert "artifact_ref" not in history.json()[0]["candidates"][0]
    assert "artifact_sha256" not in history.json()[0]["candidates"][0]
    schedule = client.put(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/artifacts/cleanup-schedule",
        json={"enabled": True, "interval_hours": 12, "limit": 25},
    )
    assert schedule.status_code == 200
    assert schedule.json()["enabled"] is True
    assert schedule.json()["interval_hours"] == 12
    assert schedule.json()["limit"] == 25
    assert schedule.json()["next_run_at"]
    fetched_schedule = client.get(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/artifacts/cleanup-schedule"
    )
    assert fetched_schedule.status_code == 200
    assert fetched_schedule.json()["enabled"] is True
    execute = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/artifacts/cleanup-runs",
        json={"dry_run": False, "limit": 10},
    )
    assert execute.status_code == 200
    assert execute.json()["deleted_count"] == 1
    assert execute.json()["candidates"][0]["cleanup_status"] == "deleted"
    assert "artifact_ref" not in execute.json()["candidates"][0]
    assert "artifact_sha256" not in execute.json()["candidates"][0]
    assert expired_ref not in object_store.objects
    updated = registry_store.image_admissions[project.id][0].evidence["sbom"]
    assert updated["artifact_cleanup_status"] == "deleted"
    actions = [event["action"] for event in audit_store.events]
    assert "tool_registry.shell_image_artifact.governance" in actions
    assert actions.count("tool_registry.shell_image_artifact.cleanup_run") == 2
    assert "tool_registry.shell_image_artifact.cleanup_run.list" in actions
    assert "tool_registry.shell_image_artifact.cleanup_schedule.update" in actions
    assert "tool_registry.shell_image_artifact.cleanup_schedule.get" in actions
    rendered = governance.text + dry_run.text + execute.text + repr(audit_store.events)
    assert "raw_sbom" not in rendered
    assert "secret-package" not in rendered
    assert expired_ref not in rendered
    assert "a" * 64 not in rendered
    assert expired_ref not in governance.text


def test_tool_registry_shell_image_artifact_cleanup_history_is_project_scoped() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    other_project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    registry_store = InMemoryToolRegistryStore()
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project, other_project]),
        registry_store=registry_store,
        audit_store=InMemoryAuditEventStore(),
        artifact_object_store=InMemoryShellImageArtifactObjectStore(bucket="capievo"),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/artifacts/cleanup-runs",
        json={"dry_run": True, "limit": 10},
    )
    other_history = client.get(
        f"/api/v1/projects/{other_project.id}/tool-registry/shell-images/artifacts/cleanup-runs"
    )

    assert response.status_code == 200
    assert other_history.status_code == 200
    assert other_history.json() == []


def test_tool_registry_shell_image_artifact_cleanup_requires_write_permission() -> None:
    project = make_project(permissions=["tool-registry:view"])
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project]),
        registry_store=InMemoryToolRegistryStore(),
        audit_store=InMemoryAuditEventStore(),
        artifact_object_store=InMemoryShellImageArtifactObjectStore(bucket="capievo"),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/shell-images/artifacts/cleanup-runs",
        json={"dry_run": True},
    )

    assert response.status_code == 403


def test_tool_registry_creates_lists_and_revokes_secret_leases_without_secret_values() -> None:
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

    lease_response = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/credential-refs/"
        f"{credential.json()['id']}/leases",
        json={
            "requester_type": "tool_gateway",
            "requester_ref": "mcp-k8s-test.kubectl_get_pods",
            "purpose": "invoke authorized MCP tool",
            "run_id": "run-123",
            "node_id": "agent_1",
            "trace_id": "trace-123",
            "ttl_seconds": 900,
        },
    )
    list_response = client.get(f"/api/v1/projects/{project.id}/tool-registry/secret-leases")
    revoke_response = client.delete(
        f"/api/v1/projects/{project.id}/tool-registry/secret-leases/{lease_response.json()['id']}"
    )

    assert lease_response.status_code == 201
    assert lease_response.json()["credential_ref"] == "vault://ops/k8s/readonly"
    assert lease_response.json()["provider"] == "external_vault"
    assert lease_response.json()["ttl_seconds"] == 900
    assert lease_response.json()["status"] == "active"
    assert lease_response.json()["lease_ref"].startswith("lease-")
    assert "secret_value" not in lease_response.text
    assert "token" not in lease_response.text.lower()
    assert "password" not in lease_response.text.lower()
    assert list_response.status_code == 200
    assert list_response.json()[0]["lease_ref"] == lease_response.json()["lease_ref"]
    assert revoke_response.status_code == 200
    assert revoke_response.json()["status"] == "revoked"
    assert revoke_response.json()["revoked_at"] is not None
    assert [event["action"] for event in audit_store.events][-3:] == [
        "tool_registry.secret_lease.create",
        "tool_registry.secret_lease.list",
        "tool_registry.secret_lease.revoke",
    ]


def test_tool_registry_secret_lease_is_project_scoped() -> None:
    project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    other_project = make_project(permissions=["tool-registry:view", "tool-registry:write"])
    client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([project, other_project]),
        registry_store=InMemoryToolRegistryStore(),
        audit_store=InMemoryAuditEventStore(),
    )
    other_credential = client.post(
        f"/api/v1/projects/{other_project.id}/tool-registry/credential-refs",
        json={
            "credential_ref": "vault://other/prod/admin",
            "name": "Other Admin",
            "provider": "external_vault",
            "external_path": "other/prod/admin",
            "secret_kind": "bearer_token",
            "environment_key": "prod",
            "usage_scope": "mcp",
        },
    )

    denied = client.post(
        f"/api/v1/projects/{project.id}/tool-registry/credential-refs/"
        f"{other_credential.json()['id']}/leases",
        json={
            "requester_type": "tool_gateway",
            "purpose": "cross project attempt",
            "ttl_seconds": 300,
        },
    )

    assert denied.status_code == 404


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
