import hashlib
import json
import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.app.model_gateway.openai_compatible import (
    ModelGatewayError,
    OpenAICompatibleChatCompletion,
    OpenAICompatibleChatMessage,
    redact_sensitive_text,
)
from backend.app.model_gateway.schemas import (
    ModelGatewayInvocationCreate,
    ModelGatewayInvocationRead,
    ModelGatewayPolicyRead,
)
from backend.app.workflows.dsl import LlmNodeData, WorkflowDefinition

_TEMPLATE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


class LlmNodePolicyNotFound(ModelGatewayError):
    """Raised when an LLM node references a missing project model policy."""


class LlmNodeBudgetExceeded(ModelGatewayError):
    """Raised when an LLM node call would exceed its configured token budget."""


class ModelPolicyStore(Protocol):
    async def get_policy(
        self,
        *,
        project_id: UUID,
        policy_ref: str,
    ) -> ModelGatewayPolicyRead | None: ...


class ModelInvocationStore(Protocol):
    async def record_invocation(
        self,
        request: ModelGatewayInvocationCreate,
    ) -> ModelGatewayInvocationRead: ...


class ChatCompletionClient(Protocol):
    async def create_chat_completion(
        self,
        *,
        model: str,
        messages: list[OpenAICompatibleChatMessage],
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> OpenAICompatibleChatCompletion: ...


class LlmNodeRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    actor_id: UUID
    workflow: WorkflowDefinition
    node_id: str
    run_id: str = Field(min_length=1, max_length=160)
    trace_id: str = Field(min_length=1, max_length=160)
    inputs: dict[str, object] = Field(default_factory=dict)


class LlmNodeRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    content: str
    finish_reason: str
    usage: dict[str, object]
    latency_ms: int
    invocation_id: UUID


@dataclass(frozen=True)
class LlmNodeRunner:
    policy_store: ModelPolicyStore
    invocation_store: ModelInvocationStore
    model_client: ChatCompletionClient

    async def run(self, request: LlmNodeRunRequest) -> LlmNodeRunResult:
        node_data = _load_llm_node_data(request.workflow, request.node_id, request.project_id)
        policy = await self.policy_store.get_policy(
            project_id=request.project_id,
            policy_ref=node_data.model_policy_ref,
        )
        if policy is None:
            raise LlmNodePolicyNotFound(
                f"model policy not found: {node_data.model_policy_ref}",
            )
        if policy.provider != "openai-compatible":
            raise ModelGatewayError(f"unsupported model provider: {policy.provider}")

        system_prompt = _render_template(node_data.system_prompt, request.inputs)
        user_prompt = _render_template(node_data.user_prompt, request.inputs)
        max_tokens = node_data.max_tokens or policy.max_tokens
        temperature = (
            node_data.temperature if node_data.temperature is not None else policy.temperature
        )
        prompt_version = node_data.prompt_version or policy.prompt_version
        request_hash = _hash_model_request(
            policy_ref=policy.policy_ref,
            node_id=request.node_id,
            prompt_version=prompt_version,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        invocation_ref = _build_invocation_ref(request.run_id, request.node_id)
        estimated_total_tokens = _estimate_tokens(system_prompt, user_prompt) + max_tokens

        if estimated_total_tokens > policy.max_total_tokens_per_call:
            message = (
                "LLM node token budget exceeded: "
                f"estimated={estimated_total_tokens}, limit={policy.max_total_tokens_per_call}"
            )
            await self._record_invocation(
                request=request,
                policy=policy,
                invocation_ref=invocation_ref,
                prompt_version=prompt_version,
                request_hash=request_hash,
                status="budget_exceeded",
                output_summary="",
                usage={"estimated_total_tokens": estimated_total_tokens},
                error_type="budget_exceeded",
                error_message=message,
                latency_ms=0,
            )
            raise LlmNodeBudgetExceeded(message)

        try:
            response = await self.model_client.create_chat_completion(
                model=policy.model_name,
                messages=[
                    OpenAICompatibleChatMessage(role="system", content=system_prompt),
                    OpenAICompatibleChatMessage(role="user", content=user_prompt),
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except ModelGatewayError as exc:
            sanitized_error = redact_sensitive_text(str(exc))
            await self._record_invocation(
                request=request,
                policy=policy,
                invocation_ref=invocation_ref,
                prompt_version=prompt_version,
                request_hash=request_hash,
                status="failed",
                output_summary="",
                usage={},
                error_type=exc.__class__.__name__,
                error_message=sanitized_error,
                latency_ms=0,
            )
            raise ModelGatewayError(sanitized_error) from exc

        invocation = await self._record_invocation(
            request=request,
            policy=policy,
            invocation_ref=invocation_ref,
            prompt_version=prompt_version,
            request_hash=request_hash,
            status="success",
            output_summary=_summarize_output(response.content),
            usage=response.usage,
            error_type="",
            error_message="",
            latency_ms=response.latency_ms,
        )
        return LlmNodeRunResult(
            provider=response.provider,
            model=response.model,
            content=response.content,
            finish_reason=response.finish_reason,
            usage=response.usage,
            latency_ms=response.latency_ms,
            invocation_id=invocation.id,
        )

    async def _record_invocation(
        self,
        *,
        request: LlmNodeRunRequest,
        policy: ModelGatewayPolicyRead,
        invocation_ref: str,
        prompt_version: str,
        request_hash: str,
        status: str,
        output_summary: str,
        usage: dict[str, object],
        error_type: str,
        error_message: str,
        latency_ms: int,
    ) -> ModelGatewayInvocationRead:
        return await self.invocation_store.record_invocation(
            ModelGatewayInvocationCreate(
                project_id=request.project_id,
                actor_id=request.actor_id,
                policy_id=policy.id,
                policy_ref=policy.policy_ref,
                invocation_ref=invocation_ref,
                provider=policy.provider,
                model_name=policy.model_name,
                prompt_version=prompt_version,
                run_id=request.run_id,
                node_id=request.node_id,
                trace_id=request.trace_id,
                status=status,
                request_hash=request_hash,
                output_summary=output_summary,
                usage=usage,
                error_type=error_type,
                error_message=redact_sensitive_text(error_message),
                latency_ms=latency_ms,
                created_by=request.actor_id,
                updated_by=request.actor_id,
            )
        )


def _load_llm_node_data(
    workflow: WorkflowDefinition,
    node_id: str,
    project_id: UUID,
) -> LlmNodeData:
    if workflow.workflow.project_id != str(project_id):
        raise ValueError("workflow project_id does not match run project_id")
    node = next((candidate for candidate in workflow.nodes if candidate.id == node_id), None)
    if node is None:
        raise ValueError(f"workflow node not found: {node_id}")
    if node.type != "llm" or not isinstance(node.data, LlmNodeData):
        raise ValueError(f"workflow node is not an LLM node: {node_id}")
    return node.data


def _render_template(template: str, inputs: dict[str, object]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = inputs.get(key, "")
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    return _TEMPLATE_PATTERN.sub(replace, template)


def _hash_model_request(
    *,
    policy_ref: str,
    node_id: str,
    prompt_version: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    payload = json.dumps(
        {
            "policy_ref": policy_ref,
            "node_id": node_id,
            "prompt_version": prompt_version,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _estimate_tokens(system_prompt: str, user_prompt: str) -> int:
    character_count = len(system_prompt) + len(user_prompt)
    return max(1, (character_count + 3) // 4)


def _summarize_output(content: str) -> str:
    return redact_sensitive_text(content).strip()[:2000]


def _build_invocation_ref(run_id: str, node_id: str) -> str:
    return f"model_call_{run_id}_{node_id}_{uuid4().hex[:12]}"[:160]
