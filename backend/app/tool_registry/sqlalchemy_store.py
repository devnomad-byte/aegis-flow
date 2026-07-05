import hashlib
from datetime import UTC, datetime, timedelta
from typing import TypeVar, cast
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.settings import AppSettings
from backend.app.execution.shell_policy import (
    ShellTemplatePolicyInput,
    build_shell_template_preview,
    validate_shell_template_policy,
)
from backend.app.security.egress_policy import (
    EgressPolicy,
    EgressPolicyViolation,
)
from backend.app.security.egress_proxy import (
    EgressProxyMode,
    EgressProxyPolicy,
    EgressProxyPolicyViolation,
    build_egress_proxy_plan,
)
from backend.app.tool_registry.image_artifacts import (
    ShellImageArtifactObjectStore,
    build_shell_image_artifact_object_store,
)
from backend.app.tool_registry.image_governance import (
    summarize_shell_image_admission_governance,
)
from backend.app.tool_registry.image_supply_chain import OciManifestDigestResult
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
    ToolRegistryImageAdmission,
    ToolRegistryImageArtifactCleanupRun,
    ToolRegistryImageArtifactCleanupSchedule,
    ToolRegistryImageArtifactLifecycleRemediationApproval,
    ToolRegistryMcpServer,
    ToolRegistryNotationTrustCertificate,
    ToolRegistrySecretLease,
    ToolRegistryShellImagePolicy,
    ToolRegistryShellTemplate,
    ToolRegistryToolDefinition,
    ToolRegistryToolGroup,
    ToolRegistryToolGroupItem,
    ToolRegistryToolSyncRun,
)
from backend.app.tool_registry.notation_trust import (
    CERTIFICATE_CONTENT_TYPE,
    certificate_pem_sha256,
    normalize_certificate_pem,
    summarize_certificate_bundle,
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
    NotationTrustCertificateCreateRequest,
    NotationTrustCertificateRead,
    SecretLeaseCreateRequest,
    SecretLeaseRead,
    ShellImageAdmissionGovernanceRead,
    ShellImageAdmissionPolicyRead,
    ShellImageAdmissionPolicyUpdateRequest,
    ShellImageAdmissionRead,
    ShellImageAdmissionResolveRequest,
    ShellImageArtifactCleanupCandidateRead,
    ShellImageArtifactCleanupRunRead,
    ShellImageArtifactCleanupScheduleRead,
    ShellImageArtifactCleanupScheduleUpdateRequest,
    ShellImageArtifactLifecycleDriftRead,
    ShellImageArtifactLifecycleRemediationApprovalRead,
    ShellImageArtifactRetentionControlsRead,
    ShellImageArtifactVersionReconciliationRead,
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
    ToolMcpServerCredentialRead,
    ToolSyncRunRead,
    default_shell_image_admission_policy,
)
from backend.app.tool_registry.store import (
    DuplicateToolRegistryResourceError,
    ShellImageAdmissionRequiredError,
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
    ToolRegistryNotationTrustCertificate,
    ToolRegistryImageArtifactLifecycleRemediationApproval,
)


class SqlAlchemyToolRegistryStore:
    def __init__(
        self,
        session: AsyncSession,
        *,
        notation_trust_object_store: ShellImageArtifactObjectStore | None = None,
    ) -> None:
        self._session = session
        self._notation_trust_object_store = (
            notation_trust_object_store or build_shell_image_artifact_object_store(AppSettings().s3)
        )

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
            egress_allowed_ports=request.egress_allowed_ports,
            egress_proxy_mode=request.egress_proxy_mode,
            egress_proxy_url=request.egress_proxy_url,
            egress_proxy_network=request.egress_proxy_network,
            egress_dns_pinning_required=request.egress_dns_pinning_required,
            description=request.description,
            created_by=actor_id,
            updated_by=actor_id,
        )
        return EnvironmentRead.model_validate(await self._insert(resource))

    async def get_active_environment(
        self,
        *,
        project_id: UUID,
        environment_key: str,
    ) -> EnvironmentRead | None:
        environment = await self._get_active_environment(project_id, environment_key)
        if environment is None:
            return None
        return EnvironmentRead.model_validate(environment)

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
        policy = await self.get_shell_image_admission_policy(project_id)
        accepted_decisions = _accepted_image_admission_decisions(policy)
        admission = await self._find_accepted_image_admission(
            project_id=project_id,
            image_ref=request.image_ref,
            image_digest=request.image_digest,
            accepted_decisions=accepted_decisions,
        )
        if _requires_image_admission(request) and admission is None:
            raise ShellImageAdmissionRequiredError(_required_image_admission_message(policy))
        policy_input = _policy_input_from_shell_request(
            project_id=project_id,
            request=request,
            admission=admission,
        )
        validate_shell_template_policy(policy_input)
        resource = ToolRegistryShellTemplate(
            project_id=project_id,
            template_ref=request.template_ref,
            template_version=request.template_version,
            name=request.name,
            risk_level=request.risk_level,
            environment_key=request.environment_key,
            credential_ref=request.credential_ref,
            image_ref=request.image_ref,
            image_digest=request.image_digest,
            image_registry_digest=admission.registry_digest if admission else "",
            image_registry_checked_at=admission.checked_at if admission else None,
            image_signature_status=admission.signature_status if admission else "not_checked",
            image_sbom_status=admission.sbom_status if admission else "not_checked",
            image_vulnerability_status=admission.vulnerability_status
            if admission
            else "not_checked",
            image_admission_status=admission.policy_decision if admission else "not_required",
            image_admission_reason=admission.decision_reason if admission else "",
            entrypoint=request.entrypoint,
            argv_template=request.argv_template,
            parameter_schema=request.parameter_schema,
            timeout_seconds=request.timeout_seconds,
            description=request.description,
            created_by=actor_id,
            updated_by=actor_id,
        )
        return ShellTemplateRead.model_validate(await self._insert(resource))

    async def list_project_shell_templates(self, project_id: UUID) -> list[ShellTemplateRead]:
        result = await self._session.scalars(
            select(ToolRegistryShellTemplate)
            .where(ToolRegistryShellTemplate.project_id == project_id)
            .order_by(
                ToolRegistryShellTemplate.template_ref,
                ToolRegistryShellTemplate.template_version.desc(),
            )
        )
        return [ShellTemplateRead.model_validate(resource) for resource in result.all()]

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
        checked_at = datetime.now(UTC)
        result = await self._session.execute(
            select(ToolRegistryImageAdmission).where(
                ToolRegistryImageAdmission.project_id == project_id,
                ToolRegistryImageAdmission.image_ref == request.image_ref,
                ToolRegistryImageAdmission.image_digest == request.image_digest,
            )
        )
        admission = result.scalar_one_or_none()
        evidence = {
            **evidence_summary,
            "content_type": digest_result.content_type,
            "manifest_size_bytes": digest_result.manifest_size_bytes,
            "computed_digest": digest_result.computed_digest,
        }
        if admission is None:
            admission = ToolRegistryImageAdmission(
                project_id=project_id,
                image_ref=request.image_ref,
                image_digest=request.image_digest,
                created_by=actor_id,
                updated_by=actor_id,
                checked_at=checked_at,
            )
            self._session.add(admission)
        admission.registry_url = digest_result.registry_url
        admission.registry_digest = digest_result.registry_digest
        admission.digest_match = digest_match
        admission.signature_status = signature_status
        admission.sbom_status = sbom_status
        admission.vulnerability_status = vulnerability_status
        admission.policy_decision = policy_decision
        admission.decision_reason = decision_reason
        admission.checked_at = checked_at
        admission.evidence = evidence
        admission.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(admission)
        return ShellImageAdmissionRead.model_validate(admission)

    async def get_active_shell_template(
        self,
        *,
        project_id: UUID,
        template_ref: str,
        template_version: int,
    ) -> ShellTemplateRead | None:
        result = await self._session.execute(
            select(ToolRegistryShellTemplate).where(
                ToolRegistryShellTemplate.project_id == project_id,
                ToolRegistryShellTemplate.template_ref == template_ref,
                ToolRegistryShellTemplate.template_version == template_version,
                ToolRegistryShellTemplate.status == "active",
            )
        )
        template = result.scalar_one_or_none()
        if template is None:
            return None
        return ShellTemplateRead.model_validate(template)

    async def get_shell_image_admission_policy(
        self,
        project_id: UUID,
    ) -> ShellImageAdmissionPolicyRead:
        policy = await self._get_shell_image_policy(project_id)
        if policy is None:
            return default_shell_image_admission_policy(project_id)
        return ShellImageAdmissionPolicyRead.model_validate(policy).model_copy(
            update={"configured": True}
        )

    async def summarize_shell_image_admission_governance(
        self,
        project_id: UUID,
        *,
        now: datetime | None = None,
    ) -> ShellImageAdmissionGovernanceRead:
        result = await self._session.scalars(
            select(ToolRegistryImageAdmission)
            .where(ToolRegistryImageAdmission.project_id == project_id)
            .order_by(ToolRegistryImageAdmission.checked_at.desc())
        )
        admissions = [
            ShellImageAdmissionRead.model_validate(admission) for admission in result.all()
        ]
        return summarize_shell_image_admission_governance(admissions, now=now)

    async def list_shell_image_admissions(self, project_id: UUID) -> list[ShellImageAdmissionRead]:
        result = await self._session.scalars(
            select(ToolRegistryImageAdmission)
            .where(ToolRegistryImageAdmission.project_id == project_id)
            .order_by(ToolRegistryImageAdmission.checked_at.desc())
        )
        return [ShellImageAdmissionRead.model_validate(admission) for admission in result.all()]

    async def update_shell_image_admission_evidence(
        self,
        *,
        project_id: UUID,
        admission_id: UUID,
        actor_id: UUID,
        evidence: dict[str, object],
    ) -> ShellImageAdmissionRead:
        admission = await self._session.scalar(
            select(ToolRegistryImageAdmission).where(
                ToolRegistryImageAdmission.project_id == project_id,
                ToolRegistryImageAdmission.id == admission_id,
            )
        )
        if admission is None:
            raise ToolRegistryResourceNotFoundError("image admission not found")
        admission.evidence = evidence
        admission.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(admission)
        return ShellImageAdmissionRead.model_validate(admission)

    async def record_shell_image_artifact_cleanup_run(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        run: ShellImageArtifactCleanupRunRead,
    ) -> ShellImageArtifactCleanupRunRead:
        resource = ToolRegistryImageArtifactCleanupRun(
            id=run.id,
            project_id=project_id,
            trigger_type=run.trigger_type,
            status=run.status,
            dry_run=run.dry_run,
            candidate_count=run.candidate_count,
            deleted_count=run.deleted_count,
            failed_count=run.failed_count,
            retained_count=run.retained_count,
            retention_controls=run.retention_controls.model_dump(mode="json"),
            lifecycle_drift=run.lifecycle_drift.model_dump(mode="json"),
            version_reconciliation=run.version_reconciliation.model_dump(mode="json"),
            candidates=[candidate.model_dump(mode="json") for candidate in run.candidates],
            generated_at=run.generated_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(resource)
        await self._session.commit()
        await self._session.refresh(resource)
        return _cleanup_run_read(resource)

    async def list_shell_image_artifact_cleanup_runs(
        self,
        project_id: UUID,
        *,
        limit: int = 20,
    ) -> list[ShellImageArtifactCleanupRunRead]:
        result = await self._session.scalars(
            select(ToolRegistryImageArtifactCleanupRun)
            .where(ToolRegistryImageArtifactCleanupRun.project_id == project_id)
            .order_by(
                ToolRegistryImageArtifactCleanupRun.created_at.desc(),
                ToolRegistryImageArtifactCleanupRun.id.desc(),
            )
            .limit(limit)
        )
        return [_cleanup_run_read(resource) for resource in result.all()]

    async def get_shell_image_artifact_cleanup_schedule(
        self,
        project_id: UUID,
    ) -> ShellImageArtifactCleanupScheduleRead | None:
        schedule = await self._session.scalar(
            select(ToolRegistryImageArtifactCleanupSchedule).where(
                ToolRegistryImageArtifactCleanupSchedule.project_id == project_id,
            )
        )
        if schedule is None:
            return None
        return _cleanup_schedule_read(schedule)

    async def upsert_shell_image_artifact_cleanup_schedule(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageArtifactCleanupScheduleUpdateRequest,
    ) -> ShellImageArtifactCleanupScheduleRead:
        schedule = await self._session.scalar(
            select(ToolRegistryImageArtifactCleanupSchedule).where(
                ToolRegistryImageArtifactCleanupSchedule.project_id == project_id,
            )
        )
        now = datetime.now(UTC)
        if schedule is None:
            schedule = ToolRegistryImageArtifactCleanupSchedule(
                project_id=project_id,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self._session.add(schedule)
        schedule.enabled = request.enabled
        schedule.interval_hours = request.interval_hours
        schedule.limit = request.limit
        schedule.next_run_at = request.next_run_at or now + timedelta(hours=request.interval_hours)
        schedule.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(schedule)
        return _cleanup_schedule_read(schedule)

    async def claim_due_shell_image_artifact_cleanup_schedules(
        self,
        *,
        now: datetime,
        limit: int,
        worker_id: str,
        lease_seconds: int,
    ) -> list[ShellImageArtifactCleanupScheduleRead]:
        result = await self._session.scalars(
            select(ToolRegistryImageArtifactCleanupSchedule)
            .where(
                ToolRegistryImageArtifactCleanupSchedule.enabled.is_(True),
                ToolRegistryImageArtifactCleanupSchedule.next_run_at.is_not(None),
                ToolRegistryImageArtifactCleanupSchedule.next_run_at <= now,
                or_(
                    ToolRegistryImageArtifactCleanupSchedule.leased_until.is_(None),
                    ToolRegistryImageArtifactCleanupSchedule.leased_until <= now,
                ),
            )
            .order_by(
                ToolRegistryImageArtifactCleanupSchedule.next_run_at,
                ToolRegistryImageArtifactCleanupSchedule.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        schedules = list(result.all())
        leased_until = now + timedelta(seconds=lease_seconds)
        for schedule in schedules:
            schedule.lease_owner = worker_id[:160]
            schedule.leased_until = leased_until
        await self._session.commit()
        for schedule in schedules:
            await self._session.refresh(schedule)
        return [_cleanup_schedule_read(resource) for resource in schedules]

    async def mark_shell_image_artifact_cleanup_schedule_run(
        self,
        *,
        project_id: UUID,
        schedule_id: UUID,
        actor_id: UUID,
        run_id: UUID,
        completed_at: datetime,
    ) -> ShellImageArtifactCleanupScheduleRead:
        schedule = await self._session.scalar(
            select(ToolRegistryImageArtifactCleanupSchedule).where(
                ToolRegistryImageArtifactCleanupSchedule.project_id == project_id,
                ToolRegistryImageArtifactCleanupSchedule.id == schedule_id,
            )
        )
        if schedule is None:
            raise ToolRegistryResourceNotFoundError("artifact cleanup schedule not found")
        run = await self._session.scalar(
            select(ToolRegistryImageArtifactCleanupRun).where(
                ToolRegistryImageArtifactCleanupRun.id == run_id,
            )
        )
        if run is None or run.project_id != project_id:
            raise ToolRegistryResourceNotFoundError("artifact cleanup run not found")
        schedule.last_run_id = run_id
        schedule.last_run_at = completed_at
        if run.status == "failed":
            failure_count = schedule.failure_count + 1
            schedule.failure_count = failure_count
            schedule.last_error_type = _cleanup_run_error(run) or "scheduled_cleanup_failed"
            schedule.last_error_message = _cleanup_run_error(run) or "scheduled cleanup failed"
            schedule.next_run_at = completed_at + timedelta(
                seconds=_cleanup_schedule_backoff_seconds(failure_count)
            )
        else:
            schedule.failure_count = 0
            schedule.last_error_type = ""
            schedule.last_error_message = ""
            schedule.next_run_at = completed_at + timedelta(hours=schedule.interval_hours)
        schedule.leased_until = None
        schedule.lease_owner = ""
        schedule.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(schedule)
        return _cleanup_schedule_read(schedule)

    async def create_shell_image_artifact_lifecycle_remediation_approval(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        approval: ShellImageArtifactLifecycleRemediationApprovalRead,
    ) -> ShellImageArtifactLifecycleRemediationApprovalRead:
        resource = ToolRegistryImageArtifactLifecycleRemediationApproval(
            id=approval.id,
            project_id=project_id,
            status=approval.status,
            rule_id=approval.rule_id,
            prefixes=approval.prefixes,
            proposal_type=approval.proposal_type,
            reason=approval.reason,
            decision_reason=approval.decision_reason,
            requested_by=approval.requested_by,
            decided_by=approval.decided_by,
            decided_at=approval.decided_at,
            used_at=approval.used_at,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(resource)
        await self._session.commit()
        await self._session.refresh(resource)
        return ShellImageArtifactLifecycleRemediationApprovalRead.model_validate(resource)

    async def get_shell_image_artifact_lifecycle_remediation_approval(
        self,
        *,
        project_id: UUID,
        approval_id: UUID,
    ) -> ShellImageArtifactLifecycleRemediationApprovalRead | None:
        resource = await self._session.scalar(
            select(ToolRegistryImageArtifactLifecycleRemediationApproval).where(
                ToolRegistryImageArtifactLifecycleRemediationApproval.project_id == project_id,
                ToolRegistryImageArtifactLifecycleRemediationApproval.id == approval_id,
            )
        )
        if resource is None:
            return None
        return ShellImageArtifactLifecycleRemediationApprovalRead.model_validate(resource)

    async def update_shell_image_artifact_lifecycle_remediation_approval(
        self,
        *,
        project_id: UUID,
        approval_id: UUID,
        actor_id: UUID,
        status: str,
        decision_reason: str = "",
        decided_by: UUID | None = None,
        decided_at: datetime | None = None,
        used_at: datetime | None = None,
    ) -> ShellImageArtifactLifecycleRemediationApprovalRead:
        resource = await self._session.scalar(
            select(ToolRegistryImageArtifactLifecycleRemediationApproval).where(
                ToolRegistryImageArtifactLifecycleRemediationApproval.project_id == project_id,
                ToolRegistryImageArtifactLifecycleRemediationApproval.id == approval_id,
            )
        )
        if resource is None:
            raise ToolRegistryResourceNotFoundError("lifecycle remediation approval not found")
        resource.status = status
        if decision_reason:
            resource.decision_reason = decision_reason
        if decided_by is not None:
            resource.decided_by = decided_by
        if decided_at is not None:
            resource.decided_at = decided_at
        if used_at is not None:
            resource.used_at = used_at
        resource.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(resource)
        return ShellImageArtifactLifecycleRemediationApprovalRead.model_validate(resource)

    async def upsert_shell_image_admission_policy(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageAdmissionPolicyUpdateRequest,
    ) -> ShellImageAdmissionPolicyRead:
        policy = await self._get_shell_image_policy(project_id)
        if policy is None:
            policy = ToolRegistryShellImagePolicy(
                project_id=project_id,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self._session.add(policy)
        policy.enforcement_mode = request.enforcement_mode
        policy.cosign_required = request.cosign_required
        policy.notation_enabled = request.notation_enabled
        policy.notation_trust_policy = request.notation_trust_policy
        policy.sbom_artifact_retention_enabled = request.sbom_artifact_retention_enabled
        policy.scan_report_retention_enabled = request.scan_report_retention_enabled
        policy.artifact_store_prefix = request.artifact_store_prefix
        policy.artifact_retention_days = request.artifact_retention_days
        policy.blocked_severities = request.blocked_severities
        policy.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(policy)
        return ShellImageAdmissionPolicyRead.model_validate(policy).model_copy(
            update={"configured": True}
        )

    async def create_notation_trust_certificate(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: NotationTrustCertificateCreateRequest,
    ) -> NotationTrustCertificateRead:
        normalized_pem = normalize_certificate_pem(request.certificate_pem)
        body = normalized_pem.encode("utf-8")
        artifact_sha256 = certificate_pem_sha256(normalized_pem)
        version = await self._next_notation_trust_certificate_version(
            project_id=project_id,
            store_type=request.store_type,
            store_name=request.store_name,
            certificate_ref=request.certificate_ref,
        )
        summary = summarize_certificate_bundle(normalized_pem)
        key = _notation_trust_certificate_object_key(
            project_id=project_id,
            store_type=request.store_type,
            store_name=request.store_name,
            certificate_ref=request.certificate_ref,
            version=version,
            artifact_sha256=artifact_sha256,
        )
        artifact_ref = await self._notation_trust_object_store.put_artifact(
            key,
            body,
            content_type=CERTIFICATE_CONTENT_TYPE,
            metadata={
                "artifact-kind": "notation_trust_certificate",
                "artifact-sha256": artifact_sha256,
                "certificate-ref": request.certificate_ref,
                "project-id": str(project_id),
                "store-name": request.store_name,
                "store-type": request.store_type,
                "version": str(version),
            },
        )
        resource = ToolRegistryNotationTrustCertificate(
            project_id=project_id,
            store_type=request.store_type,
            store_name=request.store_name,
            certificate_ref=request.certificate_ref,
            version=version,
            artifact_ref=artifact_ref,
            artifact_sha256=artifact_sha256,
            artifact_size_bytes=len(body),
            artifact_content_type=CERTIFICATE_CONTENT_TYPE,
            certificate_subject=summary.certificate_subject,
            certificate_issuer=summary.certificate_issuer,
            certificate_not_before=summary.certificate_not_before,
            certificate_not_after=summary.certificate_not_after,
            certificate_count=summary.certificate_count,
            description=request.description,
            created_by=actor_id,
            updated_by=actor_id,
        )
        return NotationTrustCertificateRead.model_validate(await self._insert(resource))

    async def list_notation_trust_certificates(
        self,
        project_id: UUID,
    ) -> list[NotationTrustCertificateRead]:
        result = await self._session.scalars(
            select(ToolRegistryNotationTrustCertificate)
            .where(
                ToolRegistryNotationTrustCertificate.project_id == project_id,
                ToolRegistryNotationTrustCertificate.status == "active",
            )
            .order_by(
                ToolRegistryNotationTrustCertificate.store_type,
                ToolRegistryNotationTrustCertificate.store_name,
                ToolRegistryNotationTrustCertificate.certificate_ref,
                ToolRegistryNotationTrustCertificate.version.desc(),
            )
        )
        return [NotationTrustCertificateRead.model_validate(resource) for resource in result.all()]

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
        admission_policy = await self.get_shell_image_admission_policy(project_id)
        preview = build_shell_template_preview(
            _policy_input_from_shell_read(template),
            parameters=request.parameters,
            run_id=request.run_id,
            trace_id=request.trace_id,
            admission_enforcement_mode=admission_policy.enforcement_mode,
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
                runtime_admission_status=preview.policy.runtime_admission_status,
                runtime_recheck_required=preview.policy.runtime_recheck_required,
                runtime_blocked=preview.policy.runtime_blocked,
                runtime_reason=preview.policy.runtime_reason,
                reasons=preview.policy.reasons,
            ),
            trace_link=preview.trace_link,
        )

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
                ToolRegistryEnvironment.egress_allowed_ports,
                ToolRegistryEnvironment.egress_proxy_mode,
                ToolRegistryEnvironment.egress_proxy_url,
                ToolRegistryEnvironment.egress_dns_pinning_required,
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
            egress_allowed_ports=row.egress_allowed_ports or [],
            egress_proxy_mode=row.egress_proxy_mode or "direct",
            egress_proxy_url=row.egress_proxy_url or "",
            egress_dns_pinning_required=bool(row.egress_dns_pinning_required),
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
                    egress_allowed_ports=environment.egress_allowed_ports,
                    egress_proxy_mode=environment.egress_proxy_mode,
                    egress_proxy_url=environment.egress_proxy_url,
                    egress_dns_pinning_required=environment.egress_dns_pinning_required,
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
            build_egress_proxy_plan(
                base_url,
                egress_policy=egress_policy,
                proxy_policy=EgressProxyPolicy(
                    mode=EgressProxyMode(environment.egress_proxy_mode),
                    proxy_url=environment.egress_proxy_url,
                    docker_network=environment.egress_proxy_network,
                    allowed_hosts=environment.egress_allowed_hosts,
                    allowed_ports=environment.egress_allowed_ports,
                    dns_pinning_required=environment.egress_dns_pinning_required,
                ),
            )
        except EgressProxyPolicyViolation as exc:
            raise ToolRegistryEgressPolicyError(exc) from exc
        except ValueError as exc:
            raise ToolRegistryEgressPolicyError(
                EgressPolicyViolation("invalid_proxy_mode", "Egress proxy mode is invalid")
            ) from exc
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

    async def _get_shell_image_policy(
        self,
        project_id: UUID,
    ) -> ToolRegistryShellImagePolicy | None:
        return cast(
            ToolRegistryShellImagePolicy | None,
            await self._session.scalar(
                select(ToolRegistryShellImagePolicy).where(
                    ToolRegistryShellImagePolicy.project_id == project_id,
                )
            ),
        )

    async def _next_notation_trust_certificate_version(
        self,
        *,
        project_id: UUID,
        store_type: str,
        store_name: str,
        certificate_ref: str,
    ) -> int:
        current_version = await self._session.scalar(
            select(func.max(ToolRegistryNotationTrustCertificate.version)).where(
                ToolRegistryNotationTrustCertificate.project_id == project_id,
                ToolRegistryNotationTrustCertificate.store_type == store_type,
                ToolRegistryNotationTrustCertificate.store_name == store_name,
                ToolRegistryNotationTrustCertificate.certificate_ref == certificate_ref,
            )
        )
        return int(current_version or 0) + 1

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

    async def _find_accepted_image_admission(
        self,
        *,
        project_id: UUID,
        image_ref: str,
        image_digest: str,
        accepted_decisions: set[str],
    ) -> ShellImageAdmissionRead | None:
        if not image_ref or not image_digest:
            return None
        result = await self._session.execute(
            select(ToolRegistryImageAdmission).where(
                ToolRegistryImageAdmission.project_id == project_id,
                ToolRegistryImageAdmission.image_ref == image_ref,
                ToolRegistryImageAdmission.image_digest == image_digest,
                ToolRegistryImageAdmission.policy_decision.in_(accepted_decisions),
            )
        )
        admission = result.scalar_one_or_none()
        if admission is None:
            return None
        return ShellImageAdmissionRead.model_validate(admission)


def _highest_risk_level(risk_levels: list[str | None]) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    cleaned = [risk_level for risk_level in risk_levels if risk_level]
    if not cleaned:
        return "low"
    return max(cleaned, key=lambda risk_level: order.get(risk_level, 0))


def _policy_input_from_shell_request(
    *,
    project_id: UUID,
    request: ShellTemplateCreateRequest,
    admission: ShellImageAdmissionRead | None = None,
) -> ShellTemplatePolicyInput:
    return ShellTemplatePolicyInput(
        project_id=project_id,
        template_ref=request.template_ref,
        template_version=request.template_version,
        risk_level=request.risk_level,
        environment_key=request.environment_key,
        image_ref=request.image_ref,
        image_digest=request.image_digest,
        entrypoint=request.entrypoint,
        argv_template=request.argv_template,
        parameter_schema=request.parameter_schema,
        timeout_seconds=request.timeout_seconds,
        image_registry_digest=admission.registry_digest if admission else "",
        image_admission_status=admission.policy_decision if admission else "not_required",
    )


def _policy_input_from_shell_read(template: ShellTemplateRead) -> ShellTemplatePolicyInput:
    return ShellTemplatePolicyInput(
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
    )


def _requires_image_admission(request: ShellTemplateCreateRequest) -> bool:
    return request.environment_key.lower() in {"prod", "production"} or request.risk_level in {
        "high",
        "critical",
    }


def _accepted_image_admission_decisions(policy: ShellImageAdmissionPolicyRead) -> set[str]:
    if policy.enforcement_mode == "dry_run":
        return {"approved", "would_reject"}
    return {"approved"}


def _required_image_admission_message(policy: ShellImageAdmissionPolicyRead) -> str:
    if policy.enforcement_mode == "dry_run":
        return (
            "Approved or dry-run shell image admission is required for production or high risk "
            "templates"
        )
    return "Approved shell image admission is required for production or high risk templates"


def _notation_trust_certificate_object_key(
    *,
    project_id: UUID,
    store_type: str,
    store_name: str,
    certificate_ref: str,
    version: int,
    artifact_sha256: str,
) -> str:
    digest_prefix = hashlib.sha256(
        f"{project_id}:{store_type}:{store_name}:{certificate_ref}:{version}".encode()
    ).hexdigest()[:12]
    return (
        "notation-trust/"
        f"{project_id}/{store_type}/{store_name}/{certificate_ref}/"
        f"v{version}-{artifact_sha256[:12]}-{digest_prefix}.pem"
    )


def _cleanup_run_read(
    resource: ToolRegistryImageArtifactCleanupRun,
) -> ShellImageArtifactCleanupRunRead:
    return ShellImageArtifactCleanupRunRead(
        id=resource.id,
        project_id=resource.project_id,
        trigger_type=resource.trigger_type,
        status=resource.status,
        dry_run=resource.dry_run,
        candidate_count=resource.candidate_count,
        deleted_count=resource.deleted_count,
        failed_count=resource.failed_count,
        retained_count=resource.retained_count,
        retention_controls=ShellImageArtifactRetentionControlsRead.model_validate(
            resource.retention_controls
        ),
        lifecycle_drift=ShellImageArtifactLifecycleDriftRead.model_validate(
            resource.lifecycle_drift
        ),
        version_reconciliation=ShellImageArtifactVersionReconciliationRead.model_validate(
            resource.version_reconciliation
        ),
        candidates=[
            ShellImageArtifactCleanupCandidateRead.model_validate(
                _cleanup_candidate_record(candidate)
            )
            for candidate in resource.candidates
        ],
        generated_at=resource.generated_at,
        started_at=resource.started_at,
        completed_at=resource.completed_at,
        created_by=resource.created_by,
        updated_by=resource.updated_by,
        created_at=resource.created_at,
        updated_at=resource.updated_at,
    )


def _cleanup_candidate_record(candidate: object) -> object:
    if not isinstance(candidate, dict):
        return candidate
    record = dict(candidate)
    artifact_ref = record.get("artifact_ref")
    artifact_sha256 = record.get("artifact_sha256")
    if "artifact_ref_hash" not in record and isinstance(artifact_ref, str):
        record["artifact_ref_hash"] = hashlib.sha256(artifact_ref.encode("utf-8")).hexdigest()
    if "artifact_sha256_prefix" not in record and isinstance(artifact_sha256, str):
        record["artifact_sha256_prefix"] = artifact_sha256[:12]
    return record


def _cleanup_schedule_read(
    resource: ToolRegistryImageArtifactCleanupSchedule,
) -> ShellImageArtifactCleanupScheduleRead:
    return ShellImageArtifactCleanupScheduleRead(
        id=resource.id,
        configured=True,
        project_id=resource.project_id,
        enabled=resource.enabled,
        interval_hours=resource.interval_hours,
        limit=resource.limit,
        next_run_at=_ensure_aware_datetime(resource.next_run_at),
        last_run_id=resource.last_run_id,
        last_run_at=_ensure_aware_datetime(resource.last_run_at),
        leased_until=_ensure_aware_datetime(resource.leased_until),
        lease_owner=resource.lease_owner,
        failure_count=resource.failure_count,
        last_error_type=resource.last_error_type,
        last_error_message=resource.last_error_message,
        created_by=resource.created_by,
        updated_by=resource.updated_by,
        created_at=_ensure_aware_datetime(resource.created_at),
        updated_at=_ensure_aware_datetime(resource.updated_at),
    )


def _ensure_aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _cleanup_run_error(run: ToolRegistryImageArtifactCleanupRun) -> str:
    for payload in (run.retention_controls, run.lifecycle_drift, run.version_reconciliation):
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, str) and error:
            return error[:1000]
    return ""


def _cleanup_schedule_backoff_seconds(failure_count: int) -> int:
    capped_failure_count = min(max(failure_count - 1, 0), 5)
    return int(min(3600, 60 * (2**capped_failure_count)))


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
