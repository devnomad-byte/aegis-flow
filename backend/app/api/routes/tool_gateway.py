from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_tool_gateway_service,
    get_tool_invocation_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.tool_gateway.schemas import (
    ToolApprovalDecisionRequest,
    ToolApprovalTaskRead,
    ToolInvocationListResponse,
    ToolInvocationRead,
    ToolInvocationRequest,
    ToolInvocationResponse,
    ToolInvocationTraceRead,
)
from backend.app.tool_gateway.service import ToolGatewayService, ToolGatewayServiceError
from backend.app.tool_gateway.store import ToolInvocationStore
from backend.app.tool_registry.mcp_client import sanitize_mcp_error_message

router = APIRouter(prefix="/projects/{project_id}/tool-gateway", tags=["tool-gateway"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
InvocationStore = Depends(get_tool_invocation_store)
AuditStore = Depends(get_audit_event_store)
ToolGatewayServiceDep = Depends(get_tool_gateway_service)


@router.get("/invocations", response_model=ToolInvocationListResponse)
async def list_tool_gateway_invocations(
    project_id: UUID,
    run_id: str | None = Query(default=None, min_length=1, max_length=160),
    node_id: str | None = Query(default=None, min_length=1, max_length=160),
    trace_id: str | None = Query(default=None, min_length=1, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    invocation_store: ToolInvocationStore = InvocationStore,
    audit_store: AuditEventStore = AuditStore,
) -> ToolInvocationListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:view",
    )
    invocations = await invocation_store.list_invocations(
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
        action="tool_gateway.invocation.list",
        target_type="tool_gateway_invocation",
        target_id=str(project_id),
        metadata={
            "invocation_count": len(sanitized_invocations),
            "run_id": run_id or "",
            "node_id": node_id or "",
            "trace_id": trace_id or "",
        },
    )
    return ToolInvocationListResponse(
        invocations=sanitized_invocations,
        count=len(sanitized_invocations),
    )


@router.post("/invoke", response_model=ToolInvocationResponse)
async def invoke_tool(
    project_id: UUID,
    request: ToolInvocationRequest,
    response: Response,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    tool_gateway_service: ToolGatewayService = ToolGatewayServiceDep,
) -> ToolInvocationResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:view",
    )
    try:
        invocation_response = await tool_gateway_service.invoke(
            project_id=project_id,
            actor_id=current_account.account_id,
            request=request,
        )
    except ToolGatewayServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if invocation_response.status == "pending_approval":
        response.status_code = status.HTTP_202_ACCEPTED
    return invocation_response


@router.post(
    "/approvals/{approval_task_id}/decide",
    response_model=ToolApprovalTaskRead,
)
async def decide_tool_approval(
    project_id: UUID,
    approval_task_id: UUID,
    request: ToolApprovalDecisionRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    invocation_store: ToolInvocationStore = InvocationStore,
    audit_store: AuditEventStore = AuditStore,
) -> ToolApprovalTaskRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-gateway:approve",
    )
    approval_task = await invocation_store.get_approval_task(
        project_id=project_id,
        approval_task_id=approval_task_id,
    )
    if approval_task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval task not found",
        )
    if approval_task.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approval task has already been decided",
        )

    decided_task = await invocation_store.decide_approval_task(
        project_id=project_id,
        approval_task_id=approval_task_id,
        actor_id=current_account.account_id,
        decision=request.decision,
        reason=request.reason,
    )
    if request.decision in {"rejected", "revoked"}:
        await invocation_store.update_invocation_status(
            project_id=project_id,
            invocation_id=approval_task.invocation_id,
            actor_id=current_account.account_id,
            status="denied" if request.decision == "rejected" else "cancelled",
            policy_decision="denied",
            output_summary=f"tool invocation approval {request.decision}",
            error_type=f"approval_{request.decision}",
            error_message=request.reason,
        )
    await _record_approval_audit_event(
        audit_store,
        approval_task=decided_task,
        actor_id=current_account.account_id,
        action=f"tool_gateway.approval.{request.decision}",
        result="success",
    )
    return decided_task


@router.post(
    "/approvals/{approval_task_id}/resume",
    response_model=ToolInvocationResponse,
)
async def resume_tool_approval(
    project_id: UUID,
    approval_task_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    tool_gateway_service: ToolGatewayService = ToolGatewayServiceDep,
) -> ToolInvocationResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:view",
    )
    try:
        return await tool_gateway_service.resume_approval(
            project_id=project_id,
            actor_id=current_account.account_id,
            approval_task_id=approval_task_id,
        )
    except ToolGatewayServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


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


async def _record_approval_audit_event(
    audit_store: AuditEventStore,
    *,
    approval_task: ToolApprovalTaskRead,
    actor_id: UUID,
    action: str,
    result: str,
    metadata: dict[str, object] | None = None,
) -> None:
    event_metadata: dict[str, object] = {
        "invocation_id": str(approval_task.invocation_id),
        "tool_ref": approval_task.tool_ref,
        "server_ref": approval_task.server_ref,
        "status": approval_task.status,
        "decision": approval_task.decision,
        "run_id": approval_task.run_id,
        "node_id": approval_task.node_id,
        "trace_id": approval_task.trace_id,
        "tool_call_id": approval_task.tool_call_id,
    }
    if metadata:
        event_metadata.update(metadata)
    await audit_store.record_project_event(
        project_id=approval_task.project_id,
        actor_id=actor_id,
        action=action,
        target_type="tool_gateway_approval_task",
        target_id=str(approval_task.id),
        result=result,
        risk_level=approval_task.effective_risk_level,
        metadata=event_metadata,
    )


def _sanitize_error_message(message: str) -> str:
    return sanitize_mcp_error_message(message)


def _sanitize_invocation(invocation: ToolInvocationRead) -> ToolInvocationTraceRead:
    return ToolInvocationTraceRead(
        id=invocation.id,
        project_id=invocation.project_id,
        tool_ref=invocation.tool_ref,
        tool_name=invocation.tool_name,
        server_ref=invocation.server_ref,
        tool_group_refs=invocation.tool_group_refs,
        workflow_ref=invocation.workflow_ref,
        agent_ref=invocation.agent_ref,
        role_refs=invocation.role_refs,
        run_id=invocation.run_id,
        node_id=invocation.node_id,
        trace_id=invocation.trace_id,
        tool_call_id=invocation.tool_call_id,
        effective_risk_level=invocation.effective_risk_level,
        approval_required=invocation.approval_required,
        policy_decision=invocation.policy_decision,
        status=invocation.status,
        input_summary=_sanitize_error_message(invocation.input_summary),
        output_summary=_sanitize_error_message(invocation.output_summary),
        error_type=invocation.error_type,
        error_message=_sanitize_error_message(invocation.error_message),
        duration_ms=invocation.duration_ms,
        created_at=invocation.created_at,
        updated_at=invocation.updated_at,
    )
