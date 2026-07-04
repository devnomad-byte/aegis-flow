from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_model_gateway_store,
    get_project_access_provider,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.model_gateway.openai_compatible import redact_sensitive_text
from backend.app.model_gateway.schemas import (
    ModelGatewayInvocationListResponse,
    ModelGatewayInvocationRead,
    ModelGatewayPolicyCreate,
    ModelGatewayPolicyListResponse,
    ModelGatewayPolicyRead,
    ModelGatewayPolicyUpsertRequest,
    PromptTemplateCreate,
    PromptTemplateCreateRequest,
    PromptTemplateListResponse,
    PromptTemplateRead,
    PromptTemplateReleaseListResponse,
    PromptTemplateReleasePublishRequest,
    PromptTemplateReleaseRead,
    PromptTemplateVersionCreate,
    PromptTemplateVersionCreateRequest,
    PromptTemplateVersionListResponse,
    PromptTemplateVersionRead,
)
from backend.app.model_gateway.sqlalchemy_store import (
    PromptReleaseConflict,
    PromptReleaseEvalGateFailed,
    PromptReleaseTargetInvalid,
    PromptTemplateVersionNotFound,
    SqlAlchemyModelGatewayStore,
)

router = APIRouter(prefix="/projects/{project_id}/model-gateway", tags=["model-gateway"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
ModelGatewayStore = Depends(get_model_gateway_store)
AuditStore = Depends(get_audit_event_store)


@router.get("/policies", response_model=ModelGatewayPolicyListResponse)
async def list_model_gateway_policies(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    model_gateway_store: SqlAlchemyModelGatewayStore = ModelGatewayStore,
    audit_store: AuditEventStore = AuditStore,
) -> ModelGatewayPolicyListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "model-gateway:view",
    )
    policies = await model_gateway_store.list_policies(project_id)
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="model_gateway.policy.list",
        target_type="model_gateway_policy",
        target_id=str(project_id),
        metadata={"policy_count": len(policies)},
    )
    return ModelGatewayPolicyListResponse(policies=policies, count=len(policies))


@router.put("/policies/{policy_ref}", response_model=ModelGatewayPolicyRead)
async def upsert_model_gateway_policy(
    project_id: UUID,
    policy_ref: str,
    request: ModelGatewayPolicyUpsertRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    model_gateway_store: SqlAlchemyModelGatewayStore = ModelGatewayStore,
    audit_store: AuditEventStore = AuditStore,
) -> ModelGatewayPolicyRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "model-gateway:write",
    )
    if request.policy_ref != policy_ref:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="policy_ref path and body must match",
        )
    policy = await model_gateway_store.upsert_policy(
        ModelGatewayPolicyCreate(
            project_id=project_id,
            created_by=current_account.account_id,
            updated_by=current_account.account_id,
            **request.model_dump(),
        )
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="model_gateway.policy.upsert",
        target_type="model_gateway_policy",
        target_id=str(policy.id),
        metadata={
            "policy_ref": policy.policy_ref,
            "provider": policy.provider,
            "model_name": policy.model_name,
            "status": policy.status,
        },
    )
    return policy


@router.get("/prompt-templates", response_model=PromptTemplateListResponse)
async def list_prompt_templates(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    model_gateway_store: SqlAlchemyModelGatewayStore = ModelGatewayStore,
    audit_store: AuditEventStore = AuditStore,
) -> PromptTemplateListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "model-gateway:view",
    )
    templates = await model_gateway_store.list_prompt_templates(project_id)
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="prompt_library.template.list",
        target_type="prompt_template",
        target_id=str(project_id),
        metadata={"template_count": len(templates)},
    )
    return PromptTemplateListResponse(templates=templates, count=len(templates))


@router.post("/prompt-templates", response_model=PromptTemplateRead)
async def create_prompt_template(
    project_id: UUID,
    request: PromptTemplateCreateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    model_gateway_store: SqlAlchemyModelGatewayStore = ModelGatewayStore,
    audit_store: AuditEventStore = AuditStore,
) -> PromptTemplateRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "model-gateway:write",
    )
    template = await model_gateway_store.create_prompt_template(
        PromptTemplateCreate(
            project_id=project_id,
            created_by=current_account.account_id,
            updated_by=current_account.account_id,
            **request.model_dump(),
        )
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="prompt_library.template.create",
        target_type="prompt_template",
        target_id=str(template.id),
        metadata={
            "template_ref": template.template_ref,
            "status": template.status,
        },
    )
    return template


@router.post(
    "/prompt-templates/{template_ref}/versions",
    response_model=PromptTemplateVersionRead,
)
async def create_prompt_template_version(
    project_id: UUID,
    template_ref: str,
    request: PromptTemplateVersionCreateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    model_gateway_store: SqlAlchemyModelGatewayStore = ModelGatewayStore,
    audit_store: AuditEventStore = AuditStore,
) -> PromptTemplateVersionRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "model-gateway:write",
    )
    template = await model_gateway_store.get_prompt_template(
        project_id=project_id,
        template_ref=template_ref,
    )
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt template not found",
        )
    version = await model_gateway_store.create_prompt_template_version(
        PromptTemplateVersionCreate(
            project_id=project_id,
            template_id=template.id,
            created_by=current_account.account_id,
            updated_by=current_account.account_id,
            **request.model_dump(),
        )
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="prompt_library.version.create",
        target_type="prompt_template_version",
        target_id=str(version.id),
        metadata={
            "template_ref": template_ref,
            "version": version.version,
            "status": version.status,
            "variables": version.variables,
        },
    )
    return version


@router.get(
    "/prompt-templates/{template_ref}/versions",
    response_model=PromptTemplateVersionListResponse,
)
async def list_prompt_template_versions(
    project_id: UUID,
    template_ref: str,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    model_gateway_store: SqlAlchemyModelGatewayStore = ModelGatewayStore,
    audit_store: AuditEventStore = AuditStore,
) -> PromptTemplateVersionListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "model-gateway:view",
    )
    versions = await model_gateway_store.list_prompt_template_versions(
        project_id=project_id,
        template_ref=template_ref,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="prompt_library.version.list",
        target_type="prompt_template_version",
        target_id=template_ref,
        metadata={
            "template_ref": template_ref,
            "version_count": len(versions),
        },
    )
    return PromptTemplateVersionListResponse(versions=versions, count=len(versions))


@router.post(
    "/prompt-templates/{template_ref}/releases",
    response_model=PromptTemplateReleaseRead,
)
async def publish_prompt_template_release(
    project_id: UUID,
    template_ref: str,
    request: PromptTemplateReleasePublishRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    model_gateway_store: SqlAlchemyModelGatewayStore = ModelGatewayStore,
    audit_store: AuditEventStore = AuditStore,
) -> PromptTemplateReleaseRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "model-gateway:write",
    )
    try:
        release = await model_gateway_store.publish_prompt_template_release(
            project_id=project_id,
            template_ref=template_ref,
            version=request.version,
            label=request.label,
            environment=request.environment,
            eval_run_id=request.eval_run_id,
            release_note=request.release_note,
            actor_id=current_account.account_id,
        )
    except PromptReleaseEvalGateFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except PromptReleaseTargetInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except PromptReleaseConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except PromptTemplateVersionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="prompt_library.release.publish",
        target_type="prompt_template_release",
        target_id=str(release.id),
        metadata={
            "template_ref": template_ref,
            "version": release.version,
            "label": release.label,
            "environment": release.environment,
            "eval_gate_status": release.eval_gate_status,
            "eval_run_id": str(release.eval_run_id) if release.eval_run_id else "",
        },
    )
    return release


@router.get(
    "/prompt-templates/{template_ref}/releases",
    response_model=PromptTemplateReleaseListResponse,
)
async def list_prompt_template_releases(
    project_id: UUID,
    template_ref: str,
    label: str | None = Query(default=None, min_length=1, max_length=80),
    environment: str | None = Query(default=None, min_length=1, max_length=80),
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    model_gateway_store: SqlAlchemyModelGatewayStore = ModelGatewayStore,
    audit_store: AuditEventStore = AuditStore,
) -> PromptTemplateReleaseListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "model-gateway:view",
    )
    releases = await model_gateway_store.list_prompt_template_releases(
        project_id=project_id,
        template_ref=template_ref,
        label=label,
        environment=environment,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="prompt_library.release.list",
        target_type="prompt_template_release",
        target_id=template_ref,
        metadata={
            "template_ref": template_ref,
            "label": label or "",
            "environment": environment or "",
            "release_count": len(releases),
        },
    )
    return PromptTemplateReleaseListResponse(releases=releases, count=len(releases))


@router.get("/invocations", response_model=ModelGatewayInvocationListResponse)
async def list_model_gateway_invocations(
    project_id: UUID,
    run_id: str | None = Query(default=None, min_length=1, max_length=160),
    node_id: str | None = Query(default=None, min_length=1, max_length=160),
    trace_id: str | None = Query(default=None, min_length=1, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    model_gateway_store: SqlAlchemyModelGatewayStore = ModelGatewayStore,
    audit_store: AuditEventStore = AuditStore,
) -> ModelGatewayInvocationListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "model-gateway:view",
    )
    invocations = await model_gateway_store.list_invocations(
        project_id=project_id,
        run_id=run_id,
        node_id=node_id,
        trace_id=trace_id,
        limit=limit,
    )
    sanitized_invocations = [_sanitize_invocation(invocation) for invocation in invocations]
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="model_gateway.invocation.list",
        target_type="model_gateway_invocation",
        target_id=str(project_id),
        metadata={
            "invocation_count": len(sanitized_invocations),
            "run_id": run_id or "",
            "node_id": node_id or "",
            "trace_id": trace_id or "",
        },
    )
    return ModelGatewayInvocationListResponse(
        invocations=sanitized_invocations,
        count=len(sanitized_invocations),
    )


def _require_project_permission(
    project_access: ProjectAccessProvider,
    current_account: AccountPrincipal,
    project_id: UUID,
    required_permission: str,
) -> None:
    try:
        project = project_access.get_project_for_account(
            current_account,
            project_id,
            required_permission,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required project permission",
        ) from exc

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )


def _sanitize_invocation(invocation: ModelGatewayInvocationRead) -> ModelGatewayInvocationRead:
    return invocation.model_copy(
        update={
            "output_summary": redact_sensitive_text(invocation.output_summary),
            "error_message": redact_sensitive_text(invocation.error_message),
        }
    )
