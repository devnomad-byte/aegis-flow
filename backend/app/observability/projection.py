from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.execution.models import HttpRunnerInvocation, ShellRunnerInvocation
from backend.app.knowledge.models import RetrievalQueryLog
from backend.app.model_gateway.models import ModelGatewayInvocation
from backend.app.observability.schemas import RuntimeSpanStatus, RuntimeTraceSpanCreate
from backend.app.observability.sqlalchemy_store import sanitize_trace_value
from backend.app.policy_gate.models import PolicyGateEvent
from backend.app.tool_gateway.models import ToolGatewayInvocation


def model_invocation_to_span(invocation: ModelGatewayInvocation) -> RuntimeTraceSpanCreate:
    start_nano, end_nano = _time_window_to_nanos(invocation.created_at, invocation.latency_ms)
    attributes = {
        "llm.provider": invocation.provider,
        "llm.model": invocation.model_name,
        "llm.policy_ref": invocation.policy_ref,
        "llm.prompt_version": invocation.prompt_version,
        "llm.request_hash": invocation.request_hash,
        "output_summary": invocation.output_summary,
        "error.type": invocation.error_type,
        "error.message": invocation.error_message,
        "schema.output_ref": invocation.output_schema_ref,
        "schema.validation_status": invocation.schema_validation_status,
        "schema.validation_error": invocation.schema_validation_error,
        **_flatten_usage(invocation.usage or {}),
    }
    return RuntimeTraceSpanCreate(
        project_id=invocation.project_id,
        actor_id=invocation.actor_id,
        trace_id=_trace_id_or_fallback(invocation.trace_id, invocation.invocation_ref),
        run_id=invocation.run_id,
        node_id=invocation.node_id,
        parent_span_id="",
        span_id=f"model:{invocation.invocation_ref}",
        span_name="llm.model_call",
        span_kind="model",
        component="model_gateway",
        status=_map_status(invocation.status),
        start_time_unix_nano=start_nano,
        end_time_unix_nano=end_nano,
        duration_ms=invocation.latency_ms,
        attributes=sanitize_trace_value(_drop_empty(attributes)),
        events=[],
        links=[],
        resource={"service.name": "aegis-flow-runtime"},
        source_type="model_gateway_invocation",
        source_id=str(invocation.id or invocation.invocation_ref),
        created_by=invocation.created_by,
        updated_by=invocation.updated_by,
    )


def tool_invocation_to_span(invocation: ToolGatewayInvocation) -> RuntimeTraceSpanCreate:
    start_nano, end_nano = _time_window_to_nanos(invocation.created_at, invocation.duration_ms)
    attributes = {
        "tool.ref": invocation.tool_ref,
        "tool.name": invocation.tool_name,
        "tool.server_ref": invocation.server_ref,
        "tool.group_refs": invocation.tool_group_refs,
        "tool.workflow_ref": invocation.workflow_ref,
        "tool.agent_ref": invocation.agent_ref,
        "tool.role_refs": invocation.role_refs,
        "tool.risk_level": invocation.effective_risk_level,
        "tool.approval_required": invocation.approval_required,
        "tool.policy_decision": invocation.policy_decision,
        "input_summary": invocation.input_summary,
        "output_summary": invocation.output_summary,
        "error.type": invocation.error_type,
        "error.message": invocation.error_message,
    }
    return RuntimeTraceSpanCreate(
        project_id=invocation.project_id,
        actor_id=invocation.actor_id,
        trace_id=_trace_id_or_fallback(invocation.trace_id, invocation.tool_call_id),
        run_id=invocation.run_id,
        workflow_ref=invocation.workflow_ref,
        node_id=invocation.node_id,
        parent_span_id="",
        span_id=f"tool:{invocation.tool_call_id}",
        span_name="tool.call",
        span_kind="tool",
        component="tool_gateway",
        status=_map_status(invocation.status),
        start_time_unix_nano=start_nano,
        end_time_unix_nano=end_nano,
        duration_ms=invocation.duration_ms,
        attributes=sanitize_trace_value(_drop_empty(attributes)),
        events=[],
        links=[],
        resource={"service.name": "aegis-flow-runtime"},
        source_type="tool_gateway_invocation",
        source_id=str(invocation.id or invocation.tool_call_id),
        created_by=invocation.created_by,
        updated_by=invocation.updated_by,
    )


def retrieval_query_log_to_span(query_log: RetrievalQueryLog) -> RuntimeTraceSpanCreate:
    start_nano, end_nano = _time_window_to_nanos(query_log.created_at, query_log.latency_ms)
    attributes = {
        "retrieval.query_hash": query_log.query_hash,
        "retrieval.mode": query_log.retrieval_mode,
        "retrieval.result_count": query_log.result_count,
        "retrieval.denied_count": query_log.denied_count,
        "retrieval.filters": query_log.filters,
        "retrieval.result_chunk_refs": query_log.result_chunk_refs,
    }
    span_source_id = str(query_log.id or query_log.query_hash)
    return RuntimeTraceSpanCreate(
        project_id=query_log.project_id,
        actor_id=query_log.actor_id,
        trace_id=_trace_id_or_fallback(query_log.trace_id, span_source_id),
        run_id="",
        node_id="",
        parent_span_id="",
        span_id=f"retrieval:{span_source_id}",
        span_name="retrieval.query",
        span_kind="internal",
        component="retrieval_gateway",
        status="success",
        start_time_unix_nano=start_nano,
        end_time_unix_nano=end_nano,
        duration_ms=query_log.latency_ms,
        attributes=sanitize_trace_value(attributes),
        events=[],
        links=[],
        resource={"service.name": "aegis-flow-runtime"},
        source_type="retrieval_query_log",
        source_id=span_source_id,
        created_by=query_log.created_by,
        updated_by=query_log.updated_by,
    )


def shell_invocation_to_span(invocation: ShellRunnerInvocation) -> RuntimeTraceSpanCreate:
    start_nano, end_nano = _time_window_to_nanos(invocation.created_at, invocation.duration_ms)
    attributes = {
        "shell.template_ref": invocation.template_ref,
        "shell.template_version": invocation.template_version,
        "shell.command_hash": invocation.command_hash,
        "shell.sandbox_image": invocation.sandbox_image,
        "shell.sandbox_image_digest": invocation.sandbox_image_digest,
        "shell.exit_code": invocation.exit_code,
        "shell.egress_profile_ref": invocation.egress_profile_ref,
        "shell.egress_proxy_mode": invocation.egress_proxy_mode,
        "shell.network_mode": invocation.network_mode,
        "stdout_summary": invocation.stdout_summary,
        "stderr_summary": invocation.stderr_summary,
        "error.type": invocation.error_type,
        "error.message": invocation.error_message,
        **_flatten_shell_resource_usage(invocation.resource_usage or {}),
    }
    return RuntimeTraceSpanCreate(
        project_id=invocation.project_id,
        actor_id=invocation.actor_id,
        trace_id=_trace_id_or_fallback(invocation.trace_id, invocation.invocation_ref),
        run_id=invocation.run_id,
        workflow_ref=invocation.workflow_ref,
        node_id=invocation.node_id,
        parent_span_id="",
        span_id=f"shell:{invocation.invocation_ref}",
        span_name="shell.execute",
        span_kind="tool",
        component="shell_runner",
        status=_map_shell_status(invocation.status),
        start_time_unix_nano=start_nano,
        end_time_unix_nano=end_nano,
        duration_ms=invocation.duration_ms,
        attributes=sanitize_trace_value(_drop_empty(attributes)),
        events=[],
        links=[],
        resource={"service.name": "aegis-flow-runtime"},
        source_type="shell_runner_invocation",
        source_id=str(invocation.id or invocation.invocation_ref),
        created_by=invocation.created_by,
        updated_by=invocation.updated_by,
    )


def http_invocation_to_span(invocation: HttpRunnerInvocation) -> RuntimeTraceSpanCreate:
    start_nano, end_nano = _time_window_to_nanos(invocation.created_at, invocation.duration_ms)
    attributes = {
        "http.action_ref": invocation.action_ref,
        "http.method": invocation.method,
        "http.status_code": invocation.http_status_code,
        "http.target_host": invocation.target_host,
        "http.target_port": invocation.target_port,
        "http.url_hash": invocation.url_hash,
        "http.egress_profile_ref": invocation.egress_profile_ref,
        "http.egress_proxy_mode": invocation.egress_proxy_mode,
        "request_summary": invocation.request_summary,
        "response_summary": invocation.response_summary,
        "error.type": invocation.error_type,
        "error.message": invocation.error_message,
    }
    return RuntimeTraceSpanCreate(
        project_id=invocation.project_id,
        actor_id=invocation.actor_id,
        trace_id=_trace_id_or_fallback(invocation.trace_id, invocation.invocation_ref),
        run_id=invocation.run_id,
        workflow_ref=invocation.workflow_ref,
        node_id=invocation.node_id,
        parent_span_id="",
        span_id=f"http:{invocation.invocation_ref}",
        span_name="http.client",
        span_kind="client",
        component="http_runner",
        status=_map_http_status(invocation.status),
        start_time_unix_nano=start_nano,
        end_time_unix_nano=end_nano,
        duration_ms=invocation.duration_ms,
        attributes=sanitize_trace_value(_drop_empty(attributes)),
        events=[],
        links=[],
        resource={"service.name": "aegis-flow-runtime"},
        source_type="http_runner_invocation",
        source_id=str(invocation.id or invocation.invocation_ref),
        created_by=invocation.created_by,
        updated_by=invocation.updated_by,
    )


def policy_gate_event_to_span(event: PolicyGateEvent) -> RuntimeTraceSpanCreate:
    start_nano, end_nano = _time_window_to_nanos(event.created_at, event.duration_ms)
    attributes = {
        "policy.gate_ref": event.gate_ref,
        "policy.policy_ref": event.policy_ref,
        "policy.rule_ref": event.rule_ref,
        "policy.target_type": event.target_type,
        "policy.target_ref": event.target_ref,
        "policy.decision": event.decision,
        "policy.risk_level": event.risk_level,
        "policy.approval_required": event.approval_required,
        "policy.approval_task_ref": event.approval_task_ref,
        "reason_summary": event.reason_summary,
    }
    return RuntimeTraceSpanCreate(
        project_id=event.project_id,
        actor_id=event.actor_id,
        trace_id=_trace_id_or_fallback(event.trace_id, event.event_ref),
        run_id=event.run_id,
        workflow_ref=event.workflow_ref,
        node_id=event.node_id,
        parent_span_id="",
        span_id=f"policy:{event.event_ref}",
        span_name="policy.gate",
        span_kind="internal",
        component="policy_engine",
        status=_map_policy_decision(event.decision),
        start_time_unix_nano=start_nano,
        end_time_unix_nano=end_nano,
        duration_ms=event.duration_ms,
        attributes=sanitize_trace_value(_drop_empty(attributes)),
        events=[],
        links=[],
        resource={"service.name": "aegis-flow-runtime"},
        source_type="policy_gate_event",
        source_id=str(event.id or event.event_ref),
        created_by=event.created_by,
        updated_by=event.updated_by,
    )


def _time_window_to_nanos(created_at: datetime | None, duration_ms: int) -> tuple[int, int]:
    end_at = created_at or datetime.now(UTC)
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=UTC)
    started_at = end_at - timedelta(milliseconds=max(duration_ms, 0))
    return int(started_at.timestamp() * 1_000_000_000), int(end_at.timestamp() * 1_000_000_000)


def _map_status(status: str) -> RuntimeSpanStatus:
    if status in {"success", "passed"}:
        return "success"
    if status in {"denied", "budget_exceeded", "schema_validation_failed"}:
        return "denied"
    if status in {"pending", "pending_approval"}:
        return "pending"
    if status in {"cancelled", "revoked"}:
        return "cancelled"
    return "failed"


def _map_shell_status(status: str) -> RuntimeSpanStatus:
    if status == "success":
        return "success"
    if status == "denied":
        return "denied"
    if status == "cancelled":
        return "cancelled"
    return "failed"


def _map_http_status(status: str) -> RuntimeSpanStatus:
    if status == "success":
        return "success"
    if status == "denied":
        return "denied"
    if status == "cancelled":
        return "cancelled"
    return "failed"


def _map_policy_decision(decision: str) -> RuntimeSpanStatus:
    if decision == "allowed":
        return "success"
    if decision == "approval_required":
        return "pending"
    return "denied"


def _flatten_usage(usage: dict[str, Any]) -> dict[str, Any]:
    return {f"llm.usage.{key}": value for key, value in usage.items()}


def _flatten_shell_resource_usage(resource_usage: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "cpu_seconds",
        "memory_peak_bytes",
        "pids_peak",
        "io_read_bytes",
        "io_write_bytes",
    }
    return {
        f"shell.resource.{key}": value
        for key, value in resource_usage.items()
        if key in allowed_keys
    }


def _drop_empty(attributes: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in attributes.items()
        if value is not None and value != "" and value != [] and value != {}
    }


def _trace_id_or_fallback(trace_id: str, fallback: str) -> str:
    return trace_id or f"trace:{fallback}"
