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
)
from backend.app.model_gateway.sqlalchemy_store import SqlAlchemyModelGatewayStore

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
