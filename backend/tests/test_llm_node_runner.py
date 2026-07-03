from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from backend.app.model_gateway.openai_compatible import (
    ModelGatewayError,
    OpenAICompatibleChatCompletion,
    OpenAICompatibleChatMessage,
)
from backend.app.model_gateway.runner import (
    LlmNodeBudgetExceeded,
    LlmNodeRunner,
    LlmNodeRunRequest,
)
from backend.app.model_gateway.schemas import (
    ModelGatewayInvocationCreate,
    ModelGatewayInvocationRead,
    ModelGatewayPolicyRead,
)
from backend.app.workflows.dsl import (
    EdgeDefinition,
    LlmNodeData,
    NodeDefinition,
    WorkflowDefinition,
    WorkflowMetadata,
)


class RecordingPolicyStore:
    def __init__(self, policy: ModelGatewayPolicyRead) -> None:
        self.policy = policy

    async def get_policy(
        self,
        *,
        project_id: UUID,
        policy_ref: str,
    ) -> ModelGatewayPolicyRead | None:
        if self.policy.project_id == project_id and self.policy.policy_ref == policy_ref:
            return self.policy
        return None


class RecordingInvocationStore:
    def __init__(self) -> None:
        self.records: list[ModelGatewayInvocationCreate] = []

    async def record_invocation(
        self,
        request: ModelGatewayInvocationCreate,
    ) -> ModelGatewayInvocationRead:
        self.records.append(request)
        now = datetime.now(UTC)
        return ModelGatewayInvocationRead(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            **request.model_dump(),
        )


class RecordingModelClient:
    def __init__(self, response: OpenAICompatibleChatCompletion | None = None) -> None:
        self.response = response or OpenAICompatibleChatCompletion(
            provider="openai-compatible",
            model="gpt-5.5",
            content="incident summarized",
            finish_reason="stop",
            usage={"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23},
            latency_ms=51,
        )
        self.calls: list[dict[str, object]] = []

    async def create_chat_completion(
        self,
        *,
        model: str,
        messages: list[OpenAICompatibleChatMessage],
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> OpenAICompatibleChatCompletion:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.response


class FailingModelClient:
    async def create_chat_completion(
        self,
        *,
        model: str,
        messages: list[OpenAICompatibleChatMessage],
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> OpenAICompatibleChatCompletion:
        raise ModelGatewayError("provider token=real-secret failed")


def make_policy(project_id: UUID, actor_id: UUID, *, budget: int = 600) -> ModelGatewayPolicyRead:
    now = datetime.now(UTC)
    return ModelGatewayPolicyRead(
        id=uuid4(),
        project_id=project_id,
        policy_ref="default",
        provider="openai-compatible",
        model_name="gpt-5.5",
        prompt_version="incident-summary/v1",
        temperature=0,
        max_tokens=128,
        max_total_tokens_per_call=budget,
        status="active",
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )


def make_workflow(project_id: UUID) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow=WorkflowMetadata(
            id="incident_summary",
            name="Incident summary",
            project_id=str(project_id),
            version=1,
        ),
        nodes=[
            NodeDefinition(id="start_1", name="Start", type="start"),
            NodeDefinition(
                id="llm_1",
                name="Summarize incident",
                type="llm",
                data=LlmNodeData(
                    model_policy_ref="default",
                    system_prompt="You summarize incidents for project {{project}}.",
                    user_prompt="Incident: {{incident}}",
                    prompt_version="incident-summary/v1",
                    max_tokens=64,
                ),
            ),
            NodeDefinition(id="end_1", name="End", type="end"),
        ],
        edges=[
            EdgeDefinition(source="start_1", target="llm_1"),
            EdgeDefinition(source="llm_1", target="end_1"),
        ],
    )


@pytest.mark.asyncio
async def test_llm_node_runner_calls_gateway_and_records_sanitized_usage() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    policy = make_policy(project_id, actor_id)
    invocation_store = RecordingInvocationStore()
    model_client = RecordingModelClient()
    runner = LlmNodeRunner(
        policy_store=RecordingPolicyStore(policy),
        invocation_store=invocation_store,
        model_client=model_client,
    )

    result = await runner.run(
        LlmNodeRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            workflow=make_workflow(project_id),
            node_id="llm_1",
            run_id="run-1",
            trace_id="trace-1",
            inputs={"project": "ops", "incident": "database password=secret was rotated"},
        )
    )

    assert result.content == "incident summarized"
    assert result.usage["total_tokens"] == 23
    assert model_client.calls[0]["max_tokens"] == 64
    assert invocation_store.records[0].request_hash.startswith("sha256:")
    assert invocation_store.records[0].status == "success"
    assert invocation_store.records[0].usage["total_tokens"] == 23
    assert "secret" not in invocation_store.records[0].model_dump_json().lower()


@pytest.mark.asyncio
async def test_llm_node_runner_blocks_before_provider_when_budget_is_exceeded() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    policy = make_policy(project_id, actor_id, budget=12)
    invocation_store = RecordingInvocationStore()
    model_client = RecordingModelClient()
    runner = LlmNodeRunner(
        policy_store=RecordingPolicyStore(policy),
        invocation_store=invocation_store,
        model_client=model_client,
    )

    with pytest.raises(LlmNodeBudgetExceeded):
        await runner.run(
            LlmNodeRunRequest(
                project_id=project_id,
                actor_id=actor_id,
                workflow=make_workflow(project_id),
                node_id="llm_1",
                run_id="run-budget",
                trace_id="trace-budget",
                inputs={"project": "ops", "incident": "x" * 200},
            )
        )

    assert model_client.calls == []
    assert invocation_store.records[0].status == "budget_exceeded"


@pytest.mark.asyncio
async def test_llm_node_runner_redacts_provider_errors_in_invocation_ledger() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    policy = make_policy(project_id, actor_id)
    invocation_store = RecordingInvocationStore()
    runner = LlmNodeRunner(
        policy_store=RecordingPolicyStore(policy),
        invocation_store=invocation_store,
        model_client=FailingModelClient(),
    )

    with pytest.raises(ModelGatewayError, match=r"\[redacted\]"):
        await runner.run(
            LlmNodeRunRequest(
                project_id=project_id,
                actor_id=actor_id,
                workflow=make_workflow(project_id),
                node_id="llm_1",
                run_id="run-fail",
                trace_id="trace-fail",
                inputs={"project": "ops", "incident": "provider outage"},
            )
        )

    assert invocation_store.records[0].status == "failed"
    assert "real-secret" not in invocation_store.records[0].error_message
