from uuid import uuid4

from backend.app.knowledge.models import RetrievalQueryLog
from backend.app.model_gateway.models import ModelGatewayInvocation, ModelGatewayPolicy
from backend.app.observability.projection import (
    model_invocation_to_span,
    retrieval_query_log_to_span,
    tool_invocation_to_span,
)
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
