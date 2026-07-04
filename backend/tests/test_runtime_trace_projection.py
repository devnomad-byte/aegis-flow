from uuid import uuid4

from backend.app.execution.models import ShellRunnerInvocation
from backend.app.knowledge.models import RetrievalQueryLog
from backend.app.model_gateway.models import ModelGatewayInvocation, ModelGatewayPolicy
from backend.app.observability.projection import (
    model_invocation_to_span,
    policy_gate_event_to_span,
    retrieval_query_log_to_span,
    shell_invocation_to_span,
    tool_invocation_to_span,
)
from backend.app.policy_gate.models import PolicyGateEvent
from backend.app.tool_gateway.models import ToolGatewayInvocation


def test_model_invocation_projects_to_sanitized_runtime_span() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    policy_id = uuid4()
    invocation = ModelGatewayInvocation(
        project_id=project_id,
        actor_id=actor_id,
        policy_id=policy_id,
        policy_ref="default",
        invocation_ref="model-call-1",
        provider="openai-compatible",
        model_name="gpt-5.5",
        prompt_version="incident/v1",
        run_id="run-1",
        node_id="llm_1",
        trace_id="trace-1",
        status="success",
        request_hash="sha256:abc",
        output_summary="Authorization: Bearer raw-provider-token",
        usage={"total_tokens": 42, "prompt": "secret prompt"},
        latency_ms=123,
        created_by=actor_id,
        updated_by=actor_id,
    )

    span = model_invocation_to_span(invocation)

    assert span.project_id == project_id
    assert span.actor_id == actor_id
    assert span.trace_id == "trace-1"
    assert span.run_id == "run-1"
    assert span.node_id == "llm_1"
    assert span.span_id == "model:model-call-1"
    assert span.span_name == "llm.model_call"
    assert span.span_kind == "model"
    assert span.component == "model_gateway"
    assert span.status == "success"
    assert span.duration_ms == 123
    assert span.attributes["llm.provider"] == "openai-compatible"
    assert span.attributes["llm.usage.total_tokens"] == 42
    assert "[redacted]" in span.attributes["output_summary"]
    assert span.attributes["llm.usage.prompt"] == "[redacted]"
    assert "raw-provider-token" not in str(span)


def test_tool_invocation_projects_to_runtime_span_without_secret_lease() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    invocation = ToolGatewayInvocation(
        project_id=project_id,
        actor_id=actor_id,
        tool_ref="mcp.ops.restart",
        tool_name="restart",
        server_ref="mcp-ops",
        tool_group_refs=["ops"],
        workflow_ref="wf-ops",
        agent_ref="agent-ops",
        role_refs=["role:ops"],
        run_id="run-1",
        node_id="tool_1",
        trace_id="trace-1",
        tool_call_id="call-1",
        effective_risk_level="high",
        approval_required=True,
        policy_decision="approval_required",
        status="pending_approval",
        input_summary='{"password":"hunter2"}',
        output_summary="waiting for approval",
        error_type="",
        error_message="",
        duration_ms=9,
        credential_ref="vault://ops/k8s",
        secret_lease_ref="lease_should_not_leak",
        created_by=actor_id,
        updated_by=actor_id,
    )

    span = tool_invocation_to_span(invocation)

    assert span.span_id == "tool:call-1"
    assert span.span_name == "tool.call"
    assert span.span_kind == "tool"
    assert span.component == "tool_gateway"
    assert span.status == "pending"
    assert span.attributes["tool.ref"] == "mcp.ops.restart"
    assert span.attributes["tool.risk_level"] == "high"
    assert "[redacted]" in span.attributes["input_summary"]
    assert "vault://ops/k8s" not in str(span)
    assert "lease_should_not_leak" not in str(span)
    assert "hunter2" not in str(span)


def test_retrieval_query_log_projects_to_runtime_span() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    query_log = RetrievalQueryLog(
        project_id=project_id,
        actor_id=actor_id,
        query_hash="sha256:query",
        query_summary="sha256:query",
        retrieval_mode="hybrid",
        result_count=3,
        denied_count=1,
        latency_ms=18,
        trace_id="trace-1",
        filters={"environments": ["prod"], "query": "secret question"},
        result_chunk_refs=["child-1"],
        created_by=actor_id,
        updated_by=actor_id,
    )

    span = retrieval_query_log_to_span(query_log)

    assert span.span_id == "retrieval:sha256:query"
    assert span.span_name == "retrieval.query"
    assert span.span_kind == "internal"
    assert span.component == "retrieval_gateway"
    assert span.trace_id == "trace-1"
    assert span.attributes["retrieval.mode"] == "hybrid"
    assert span.attributes["retrieval.result_count"] == 3
    assert span.attributes["retrieval.denied_count"] == 1
    assert span.attributes["retrieval.filters"]["query"] == "[redacted]"
    assert "secret question" not in str(span)


def test_shell_invocation_projects_to_runtime_span_without_raw_command_or_output() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    invocation = ShellRunnerInvocation(
        project_id=project_id,
        actor_id=actor_id,
        invocation_ref="shell-call-1",
        template_ref="k8s-log-collector",
        template_version=3,
        command_hash="sha256:rendered-command",
        sandbox_image="capievo/runtime-sandbox-base:latest",
        sandbox_image_digest="sha256:image-digest",
        egress_profile_ref="egress-dev",
        egress_proxy_mode="envoy",
        network_mode="aegis-egress-dev",
        workflow_ref="incident-response",
        run_id="run-1",
        node_id="shell_1",
        trace_id="trace-1",
        status="failed",
        exit_code=2,
        duration_ms=211,
        resource_usage={"cpu_seconds": 0.32, "memory_peak_bytes": 12_345_678},
        stdout_summary="collected 10 lines; token=raw-provider-token",
        stderr_summary="kubectl failed password=hunter2",
        error_type="CommandFailed",
        error_message="Authorization: Bearer raw-shell-token",
        created_by=actor_id,
        updated_by=actor_id,
    )

    span = shell_invocation_to_span(invocation)

    assert span.project_id == project_id
    assert span.actor_id == actor_id
    assert span.trace_id == "trace-1"
    assert span.run_id == "run-1"
    assert span.node_id == "shell_1"
    assert span.span_id == "shell:shell-call-1"
    assert span.span_name == "shell.execute"
    assert span.span_kind == "tool"
    assert span.component == "shell_runner"
    assert span.status == "failed"
    assert span.duration_ms == 211
    assert span.attributes["shell.template_ref"] == "k8s-log-collector"
    assert span.attributes["shell.template_version"] == 3
    assert span.attributes["shell.command_hash"] == "sha256:rendered-command"
    assert span.attributes["shell.sandbox_image"] == "capievo/runtime-sandbox-base:latest"
    assert span.attributes["shell.exit_code"] == 2
    assert span.attributes["shell.resource.cpu_seconds"] == 0.32
    assert span.attributes["shell.resource.memory_peak_bytes"] == 12_345_678
    assert span.attributes["shell.egress_profile_ref"] == "egress-dev"
    assert span.attributes["shell.egress_proxy_mode"] == "envoy"
    assert span.attributes["shell.network_mode"] == "aegis-egress-dev"
    assert "[redacted]" in span.attributes["stdout_summary"]
    assert "[redacted]" in span.attributes["stderr_summary"]
    assert "[redacted]" in span.attributes["error.message"]
    assert "kubectl get secret" not in str(span)
    assert "raw-provider-token" not in str(span)
    assert "raw-shell-token" not in str(span)
    assert "hunter2" not in str(span)


def test_policy_gate_event_projects_to_runtime_span_without_policy_input_or_secret() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    event = PolicyGateEvent(
        project_id=project_id,
        actor_id=actor_id,
        event_ref="policy-event-1",
        gate_ref="tool-preflight",
        policy_ref="ops-prod-risk",
        rule_ref="require-approval-for-shell",
        target_type="shell_template",
        target_ref="k8s-log-collector@3",
        workflow_ref="incident-response",
        run_id="run-1",
        node_id="shell_1",
        trace_id="trace-1",
        decision="approval_required",
        risk_level="critical",
        approval_required=True,
        approval_task_ref="approval-123",
        reason_summary="requires approval because password=hunter2",
        duration_ms=17,
        created_by=actor_id,
        updated_by=actor_id,
    )

    span = policy_gate_event_to_span(event)

    assert span.project_id == project_id
    assert span.actor_id == actor_id
    assert span.trace_id == "trace-1"
    assert span.run_id == "run-1"
    assert span.node_id == "shell_1"
    assert span.span_id == "policy:policy-event-1"
    assert span.span_name == "policy.gate"
    assert span.span_kind == "internal"
    assert span.component == "policy_engine"
    assert span.status == "pending"
    assert span.duration_ms == 17
    assert span.attributes["policy.decision"] == "approval_required"
    assert span.attributes["policy.risk_level"] == "critical"
    assert span.attributes["policy.rule_ref"] == "require-approval-for-shell"
    assert span.attributes["policy.approval_required"] is True
    assert span.attributes["policy.approval_task_ref"] == "approval-123"
    assert span.attributes["policy.target_type"] == "shell_template"
    assert span.attributes["policy.target_ref"] == "k8s-log-collector@3"
    assert "[redacted]" in span.attributes["reason_summary"]
    assert "hunter2" not in str(span)
    assert "policy_input" not in str(span)


def test_model_projection_uses_created_at_when_available_for_timestamps() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    policy = ModelGatewayPolicy(
        project_id=project_id,
        policy_ref="default",
        provider="openai-compatible",
        model_name="gpt-5.5",
        created_by=actor_id,
        updated_by=actor_id,
    )
    invocation = ModelGatewayInvocation(
        project_id=project_id,
        actor_id=actor_id,
        policy_id=policy.id,
        policy_ref="default",
        invocation_ref="model-call-2",
        provider="openai-compatible",
        model_name="gpt-5.5",
        prompt_version="incident/v1",
        run_id="run-1",
        node_id="llm_1",
        trace_id="trace-1",
        status="failed",
        request_hash="sha256:abc",
        latency_ms=10,
        created_by=actor_id,
        updated_by=actor_id,
    )

    span = model_invocation_to_span(invocation)

    assert span.end_time_unix_nano >= span.start_time_unix_nano
