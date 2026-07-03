import json
import time
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from jsonschema import ValidationError, validate

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_mcp_tool_call_client,
    get_project_access_provider,
    get_tool_invocation_store,
    get_tool_registry_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.tool_gateway.mcp_client import McpToolCallClient, McpToolCallError
from backend.app.tool_gateway.schemas import (
    ToolGatewayResult,
    ToolInvocationCreate,
    ToolInvocationPolicyDecision,
    ToolInvocationRead,
    ToolInvocationRequest,
    ToolInvocationResponse,
    ToolInvocationStatus,
)
from backend.app.tool_gateway.store import ToolInvocationStore
from backend.app.tool_registry.mcp_client import sanitize_mcp_error_message
from backend.app.tool_registry.schemas import (
    AuthorizedToolRead,
    AuthorizedToolsResolveRequest,
    SecretLeaseCreateRequest,
    ToolMcpServerCredentialRead,
)
from backend.app.tool_registry.store import ToolRegistryResourceNotFoundError, ToolRegistryStore

router = APIRouter(prefix="/projects/{project_id}/tool-gateway", tags=["tool-gateway"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
RegistryStore = Depends(get_tool_registry_store)
InvocationStore = Depends(get_tool_invocation_store)
AuditStore = Depends(get_audit_event_store)
McpToolCallClientDependency = Depends(get_mcp_tool_call_client)


@router.post("/invoke", response_model=ToolInvocationResponse)
async def invoke_tool(
    project_id: UUID,
    request: ToolInvocationRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    invocation_store: ToolInvocationStore = InvocationStore,
    audit_store: AuditEventStore = AuditStore,
    call_client: McpToolCallClient = McpToolCallClientDependency,
) -> ToolInvocationResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:view",
    )
    started = time.perf_counter()
    authorized_tool = await _resolve_authorized_tool(
        registry_store=registry_store,
        project_id=project_id,
        request=request,
    )
    if authorized_tool is None:
        invocation = await _record_invocation(
            invocation_store,
            project_id=project_id,
            actor_id=current_account.account_id,
            request=request,
            authorized_tool=None,
            server=None,
            status="denied",
            policy_decision="denied",
            started=started,
            output_summary="tool is not authorized for this runtime context",
            error_type="authorization_denied",
            error_message="Tool is not authorized for this runtime context",
        )
        await _record_audit_event(
            audit_store,
            invocation=invocation,
            result="failure",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tool is not authorized for this runtime context",
        )

    try:
        validate(instance=request.arguments, schema=authorized_tool.input_schema)
    except ValidationError as exc:
        invocation = await _record_invocation(
            invocation_store,
            project_id=project_id,
            actor_id=current_account.account_id,
            request=request,
            authorized_tool=authorized_tool,
            server=None,
            status="denied",
            policy_decision="denied",
            started=started,
            output_summary="arguments do not match tool input schema",
            error_type="schema_validation_failed",
            error_message=_sanitize_error_message(exc.message),
        )
        await _record_audit_event(
            audit_store,
            invocation=invocation,
            result="failure",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="arguments do not match tool input schema",
        ) from exc

    server = await registry_store.get_mcp_server_credential_for_tool(
        project_id=project_id,
        tool_ref=authorized_tool.tool_ref,
    )
    if server is None:
        invocation = await _record_invocation(
            invocation_store,
            project_id=project_id,
            actor_id=current_account.account_id,
            request=request,
            authorized_tool=authorized_tool,
            server=None,
            status="failed",
            policy_decision="allowed",
            started=started,
            output_summary="MCP server not found for authorized tool",
            error_type="mcp_server_not_found",
            error_message="MCP server not found for authorized tool",
        )
        await _record_audit_event(audit_store, invocation=invocation, result="failure")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP server not found for authorized tool",
        )

    lease_id: UUID | None = None
    lease_ref = ""
    if server.credential_ref:
        if server.credential_ref_id is None:
            invocation = await _record_invocation(
                invocation_store,
                project_id=project_id,
                actor_id=current_account.account_id,
                request=request,
                authorized_tool=authorized_tool,
                server=server,
                status="failed",
                policy_decision="allowed",
                started=started,
                output_summary="MCP server credential reference is inactive",
                error_type="credential_reference_inactive",
                error_message="MCP server credential reference is inactive",
                credential_ref=server.credential_ref,
            )
            await _record_audit_event(audit_store, invocation=invocation, result="failure")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="MCP server credential reference is inactive",
            )
        try:
            lease = await registry_store.create_secret_lease(
                project_id=project_id,
                credential_ref_id=server.credential_ref_id,
                actor_id=current_account.account_id,
                request=SecretLeaseCreateRequest(
                    requester_type="tool_gateway",
                    requester_ref=authorized_tool.tool_ref,
                    purpose="invoke authorized MCP tool",
                    run_id=request.run_id,
                    node_id=request.node_id,
                    trace_id=request.trace_id,
                    ttl_seconds=900,
                ),
            )
        except ToolRegistryResourceNotFoundError as exc:
            invocation = await _record_invocation(
                invocation_store,
                project_id=project_id,
                actor_id=current_account.account_id,
                request=request,
                authorized_tool=authorized_tool,
                server=server,
                status="failed",
                policy_decision="allowed",
                started=started,
                output_summary="MCP server credential reference is inactive",
                error_type="credential_reference_inactive",
                error_message="MCP server credential reference is inactive",
                credential_ref=server.credential_ref,
            )
            await _record_audit_event(audit_store, invocation=invocation, result="failure")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="MCP server credential reference is inactive",
            ) from exc
        lease_id = lease.id
        lease_ref = lease.lease_ref

    try:
        call_result = await call_client.call_tool(
            base_url=server.base_url,
            transport=server.transport,
            tool_name=authorized_tool.tool_name,
            arguments=request.arguments,
            lease_ref=lease_ref,
        )
    except McpToolCallError as exc:
        invocation = await _record_invocation(
            invocation_store,
            project_id=project_id,
            actor_id=current_account.account_id,
            request=request,
            authorized_tool=authorized_tool,
            server=server,
            status="failed",
            policy_decision="allowed",
            started=started,
            output_summary="MCP tool call failed",
            error_type=exc.__class__.__name__,
            error_message=_sanitize_error_message(str(exc)),
            credential_ref=server.credential_ref,
            secret_lease_id=lease_id,
            secret_lease_ref=lease_ref,
        )
        await _record_audit_event(audit_store, invocation=invocation, result="failure")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=invocation.error_message,
        ) from exc

    gateway_result = ToolGatewayResult(
        content=call_result.content,
        structured_content=call_result.structured_content,
        is_error=call_result.is_error,
    )
    invocation = await _record_invocation(
        invocation_store,
        project_id=project_id,
        actor_id=current_account.account_id,
        request=request,
        authorized_tool=authorized_tool,
        server=server,
        status="failed" if call_result.is_error else "success",
        policy_decision="allowed",
        started=started,
        output_summary=_summarize_payload(gateway_result.model_dump()),
        credential_ref=server.credential_ref,
        secret_lease_id=lease_id,
        secret_lease_ref=lease_ref,
    )
    await _record_audit_event(
        audit_store,
        invocation=invocation,
        result="failure" if call_result.is_error else "success",
    )
    return ToolInvocationResponse(
        invocation_id=invocation.id,
        project_id=invocation.project_id,
        tool_ref=invocation.tool_ref,
        tool_name=invocation.tool_name,
        server_ref=invocation.server_ref,
        status=invocation.status,
        policy_decision=invocation.policy_decision,
        effective_risk_level=invocation.effective_risk_level,
        approval_required=invocation.approval_required,
        input_summary=invocation.input_summary,
        output_summary=invocation.output_summary,
        error_type=invocation.error_type,
        error_message=invocation.error_message,
        duration_ms=invocation.duration_ms,
        credential_ref=invocation.credential_ref,
        secret_lease_ref=invocation.secret_lease_ref,
        run_id=invocation.run_id,
        node_id=invocation.node_id,
        trace_id=invocation.trace_id,
        tool_call_id=invocation.tool_call_id,
        result=gateway_result,
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


async def _resolve_authorized_tool(
    *,
    registry_store: ToolRegistryStore,
    project_id: UUID,
    request: ToolInvocationRequest,
) -> AuthorizedToolRead | None:
    resolved = await registry_store.resolve_authorized_tools(
        project_id=project_id,
        request=AuthorizedToolsResolveRequest(
            tool_group_refs=request.tool_group_refs,
            workflow_ref=request.workflow_ref,
            agent_ref=request.agent_ref,
            role_refs=request.role_refs,
        ),
    )
    for tool in resolved.tools:
        if tool.tool_ref == request.tool_ref:
            return tool
    return None


async def _record_invocation(
    invocation_store: ToolInvocationStore,
    *,
    project_id: UUID,
    actor_id: UUID,
    request: ToolInvocationRequest,
    authorized_tool: AuthorizedToolRead | None,
    server: ToolMcpServerCredentialRead | None,
    status: ToolInvocationStatus,
    policy_decision: ToolInvocationPolicyDecision,
    started: float,
    output_summary: str,
    error_type: str = "",
    error_message: str = "",
    credential_ref: str = "",
    secret_lease_id: UUID | None = None,
    secret_lease_ref: str = "",
) -> ToolInvocationRead:
    duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    server_ref = ""
    if server is not None:
        server_ref = server.server_ref
    elif authorized_tool is not None:
        server_ref = authorized_tool.server_ref

    return await invocation_store.record_invocation(
        ToolInvocationCreate(
            project_id=project_id,
            actor_id=actor_id,
            tool_ref=request.tool_ref,
            tool_name=authorized_tool.tool_name if authorized_tool else "",
            server_ref=server_ref,
            tool_group_refs=request.tool_group_refs,
            workflow_ref=request.workflow_ref,
            agent_ref=request.agent_ref,
            role_refs=request.role_refs,
            run_id=request.run_id,
            node_id=request.node_id,
            trace_id=request.trace_id,
            tool_call_id=request.tool_call_id or f"tool_call_{uuid4().hex}",
            effective_risk_level=authorized_tool.effective_risk_level
            if authorized_tool
            else "medium",
            approval_required=authorized_tool.approval_required if authorized_tool else False,
            policy_decision=policy_decision,
            status=status,
            input_summary=_summarize_payload(request.arguments),
            output_summary=output_summary,
            error_type=error_type,
            error_message=error_message,
            duration_ms=duration_ms,
            credential_ref=credential_ref,
            secret_lease_id=secret_lease_id,
            secret_lease_ref=secret_lease_ref,
            created_by=actor_id,
            updated_by=actor_id,
        )
    )


async def _record_audit_event(
    audit_store: AuditEventStore,
    *,
    invocation: Any,
    result: str,
) -> None:
    await audit_store.record_project_event(
        project_id=invocation.project_id,
        actor_id=invocation.actor_id,
        action="tool_gateway.invoke",
        target_type="tool_gateway_invocation",
        target_id=str(invocation.id),
        result=result,
        risk_level=invocation.effective_risk_level,
        metadata={
            "tool_ref": invocation.tool_ref,
            "server_ref": invocation.server_ref,
            "policy_decision": invocation.policy_decision,
            "status": invocation.status,
            "run_id": invocation.run_id,
            "node_id": invocation.node_id,
            "trace_id": invocation.trace_id,
            "tool_call_id": invocation.tool_call_id,
            "approval_required": invocation.approval_required,
            "secret_lease_ref": invocation.secret_lease_ref,
        },
    )


def _summarize_payload(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    sanitized = _sanitize_error_message(text)
    if len(sanitized) > 500:
        return f"{sanitized[:500]}..."
    return sanitized


def _sanitize_error_message(message: str) -> str:
    return sanitize_mcp_error_message(message)
