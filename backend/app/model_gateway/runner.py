import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as validate_json_schema
from pydantic import BaseModel, ConfigDict, Field

from backend.app.model_gateway.openai_compatible import (
    ModelGatewayError,
    OpenAICompatibleChatCompletion,
    OpenAICompatibleChatMessage,
    redact_sensitive_text,
)
from backend.app.model_gateway.schemas import (
    DEFAULT_PROMPT_RELEASE_ENVIRONMENT,
    ModelGatewayInvocationCreate,
    ModelGatewayInvocationRead,
    ModelGatewayPolicyRead,
    PromptTemplateVersionRead,
)
from backend.app.policy_center.runtime import (
    ApprovalPolicyDecisionRequest,
    ApprovalPolicyRuntimeEvaluator,
)
from backend.app.runtime_approvals.schemas import (
    RuntimeApprovalTaskCreate,
    RuntimeApprovalTaskRead,
)
from backend.app.runtime_approvals.store import RuntimeApprovalTaskStore
from backend.app.workflows.dsl import LlmNodeData, WorkflowDefinition

_TEMPLATE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


class LlmNodePolicyNotFound(ModelGatewayError):
    """Raised when an LLM node references a missing project model policy."""


class LlmNodeBudgetExceeded(ModelGatewayError):
    """Raised when an LLM node call would exceed its configured token budget."""


class LlmNodePromptNotFound(ModelGatewayError):
    """Raised when an LLM node references a missing prompt template version."""


class LlmNodePolicyDenied(ModelGatewayError):
    """Raised when a runtime approval policy blocks an LLM node call."""


class LlmNodeApprovalRequired(ModelGatewayError):
    """Raised when a runtime approval task must be decided before model invocation."""

    def __init__(
        self,
        *,
        approval_task: RuntimeApprovalTaskRead,
        invocation: ModelGatewayInvocationRead,
    ) -> None:
        super().__init__("model invocation requires approval")
        self.approval_task = approval_task
        self.invocation = invocation


class LlmNodeStructuredOutputInvalid(ModelGatewayError):
    """Raised when an LLM node response fails JSON Schema validation."""


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

    async def update_invocation_by_ref(
        self,
        request: ModelGatewayInvocationCreate,
    ) -> ModelGatewayInvocationRead: ...


class PromptTemplateVersionStore(Protocol):
    async def get_prompt_template_version(
        self,
        *,
        project_id: UUID,
        template_ref: str,
        version: str,
    ) -> PromptTemplateVersionRead | None: ...

    async def get_prompt_template_version_by_label(
        self,
        *,
        project_id: UUID,
        template_ref: str,
        label: str,
        environment: str,
    ) -> PromptTemplateVersionRead | None: ...


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
    approved_approval_task_id: UUID | None = None


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
    prompt_store: PromptTemplateVersionStore | None = None
    approval_evaluator: ApprovalPolicyRuntimeEvaluator | None = None
    runtime_approval_store: RuntimeApprovalTaskStore | None = None

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

        invocation_ref = _build_invocation_ref(request.run_id, request.node_id)
        prompt_version_for_policy = node_data.prompt_version or policy.prompt_version
        if request.approved_approval_task_id is not None:
            approval_task = await _validate_runtime_approval_for_model(
                approval_store=self.runtime_approval_store,
                request=request,
                policy=policy,
            )
            invocation_ref = approval_task.invocation_ref
        policy_decision = await _evaluate_model_approval_policy(
            approval_evaluator=self.approval_evaluator,
            request=request,
            policy=policy,
        )
        if policy_decision == "approval_required" and request.approved_approval_task_id is None:
            invocation = await self._record_invocation(
                request=request,
                policy=policy,
                invocation_ref=invocation_ref,
                prompt_version=prompt_version_for_policy,
                request_hash=_hash_model_request(
                    policy_ref=policy.policy_ref,
                    node_id=request.node_id,
                    prompt_version=prompt_version_for_policy,
                    system_prompt="",
                    user_prompt="",
                ),
                status="pending_approval",
                output_summary="",
                usage={},
                error_type="approval_policy_approval_required",
                error_message="Model invocation requires approval",
                output_schema_ref=node_data.output_schema_ref,
                schema_validation_status="not_applicable",
                schema_validation_error="",
                latency_ms=0,
            )
            approval_task = await self._create_pending_approval_task(
                request=request,
                policy=policy,
                node_data=node_data,
                invocation_ref=invocation_ref,
                prompt_version=prompt_version_for_policy,
            )
            raise LlmNodeApprovalRequired(
                approval_task=approval_task,
                invocation=invocation,
            )
        if policy_decision == "denied":
            message = "Model invocation denied by approval policy"
            await self._record_invocation(
                request=request,
                policy=policy,
                invocation_ref=invocation_ref,
                prompt_version=prompt_version_for_policy,
                request_hash=_hash_model_request(
                    policy_ref=policy.policy_ref,
                    node_id=request.node_id,
                    prompt_version=prompt_version_for_policy,
                    system_prompt="",
                    user_prompt="",
                ),
                status="denied",
                output_summary="",
                usage={},
                error_type="approval_policy_denied",
                error_message=message,
                output_schema_ref=node_data.output_schema_ref,
                schema_validation_status="not_applicable",
                schema_validation_error="",
                latency_ms=0,
            )
            raise LlmNodePolicyDenied(message)

        prompt_source = await self._load_prompt_source(request, node_data)
        system_prompt = _render_template(prompt_source.system_prompt, request.inputs)
        user_prompt = _render_template(prompt_source.user_prompt, request.inputs)
        output_schema = prompt_source.output_schema or node_data.output_schema
        max_tokens = node_data.max_tokens or policy.max_tokens
        temperature = (
            node_data.temperature if node_data.temperature is not None else policy.temperature
        )
        prompt_version = (
            prompt_source.prompt_version or node_data.prompt_version or policy.prompt_version
        )
        output_schema_ref = node_data.output_schema_ref or prompt_source.output_schema_ref
        request_hash = _hash_model_request(
            policy_ref=policy.policy_ref,
            node_id=request.node_id,
            prompt_version=prompt_version,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
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
                output_schema_ref=output_schema_ref,
                schema_validation_status="not_applicable",
                schema_validation_error="",
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
                output_schema_ref=output_schema_ref,
                schema_validation_status="not_applicable",
                schema_validation_error="",
                latency_ms=0,
            )
            raise ModelGatewayError(sanitized_error) from exc

        schema_validation_status = "not_applicable"
        schema_validation_error = ""
        if output_schema:
            try:
                _validate_structured_output(response.content, output_schema)
                schema_validation_status = "passed"
            except LlmNodeStructuredOutputInvalid as exc:
                schema_validation_status = "failed"
                schema_validation_error = redact_sensitive_text(str(exc))
                await self._record_invocation(
                    request=request,
                    policy=policy,
                    invocation_ref=invocation_ref,
                    prompt_version=prompt_version,
                    request_hash=request_hash,
                    status="schema_validation_failed",
                    output_summary=_summarize_output(response.content),
                    usage=response.usage,
                    error_type=exc.__class__.__name__,
                    error_message=schema_validation_error,
                    output_schema_ref=output_schema_ref,
                    schema_validation_status=schema_validation_status,
                    schema_validation_error=schema_validation_error,
                    latency_ms=response.latency_ms,
                )
                raise

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
            output_schema_ref=output_schema_ref,
            schema_validation_status=schema_validation_status,
            schema_validation_error=schema_validation_error,
            latency_ms=response.latency_ms,
        )
        if (
            request.approved_approval_task_id is not None
            and self.runtime_approval_store is not None
        ):
            await self.runtime_approval_store.mark_approval_task_resumed(
                project_id=request.project_id,
                approval_task_id=request.approved_approval_task_id,
                actor_id=request.actor_id,
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
        output_schema_ref: str,
        schema_validation_status: str,
        schema_validation_error: str,
        latency_ms: int,
    ) -> ModelGatewayInvocationRead:
        invocation_create = ModelGatewayInvocationCreate(
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
            output_schema_ref=output_schema_ref,
            schema_validation_status=schema_validation_status,
            schema_validation_error=redact_sensitive_text(schema_validation_error),
            latency_ms=latency_ms,
            created_by=request.actor_id,
            updated_by=request.actor_id,
        )
        if request.approved_approval_task_id is not None:
            return await self.invocation_store.update_invocation_by_ref(invocation_create)
        return await self.invocation_store.record_invocation(invocation_create)

    async def _create_pending_approval_task(
        self,
        *,
        request: LlmNodeRunRequest,
        policy: ModelGatewayPolicyRead,
        node_data: LlmNodeData,
        invocation_ref: str,
        prompt_version: str,
    ) -> RuntimeApprovalTaskRead:
        if self.runtime_approval_store is None:
            raise LlmNodePolicyDenied("runtime approval store is not configured")
        return await self.runtime_approval_store.create_approval_task(
            RuntimeApprovalTaskCreate(
                project_id=request.project_id,
                actor_id=request.actor_id,
                target_kind="model_invocation",
                target_ref=policy.policy_ref,
                invocation_ref=invocation_ref,
                workflow_ref=f"{request.workflow.workflow.id}:{request.workflow.workflow.version}",
                run_id=request.run_id,
                node_id=request.node_id,
                trace_id=request.trace_id,
                risk_level="medium",
                request_payload=request.model_dump(mode="json"),
                public_payload={
                    "policy_ref": policy.policy_ref,
                    "model_name": policy.model_name,
                    "prompt_version": prompt_version,
                    "input_keys": sorted(request.inputs.keys()),
                },
                target_snapshot={
                    "policy_ref": policy.policy_ref,
                    "provider": policy.provider,
                    "model_name": policy.model_name,
                    "prompt_version": prompt_version,
                    "output_schema_ref": node_data.output_schema_ref,
                },
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
                created_by=request.actor_id,
                updated_by=request.actor_id,
            )
        )

    async def _load_prompt_source(
        self,
        request: LlmNodeRunRequest,
        node_data: LlmNodeData,
    ) -> "_PromptSource":
        if not node_data.prompt_template_ref:
            return _PromptSource(
                system_prompt=node_data.system_prompt,
                user_prompt=node_data.user_prompt,
                prompt_version=node_data.prompt_version,
                output_schema=node_data.output_schema,
                output_schema_ref=node_data.output_schema_ref,
            )

        if self.prompt_store is None:
            raise LlmNodePromptNotFound(
                f"prompt store is not configured for: {node_data.prompt_template_ref}",
            )

        if node_data.prompt_label:
            prompt_environment = node_data.prompt_environment or DEFAULT_PROMPT_RELEASE_ENVIRONMENT
            prompt_version = await self.prompt_store.get_prompt_template_version_by_label(
                project_id=request.project_id,
                template_ref=node_data.prompt_template_ref,
                label=node_data.prompt_label,
                environment=prompt_environment,
            )
            prompt_ref = (
                f"{node_data.prompt_template_ref}#{node_data.prompt_label}@{prompt_environment}"
            )
        else:
            prompt_version = await self.prompt_store.get_prompt_template_version(
                project_id=request.project_id,
                template_ref=node_data.prompt_template_ref,
                version=node_data.prompt_version,
            )
            prompt_ref = f"{node_data.prompt_template_ref}/{node_data.prompt_version}"
        if prompt_version is None:
            raise LlmNodePromptNotFound(
                f"prompt version not found: {prompt_ref}",
            )

        return _PromptSource(
            system_prompt=prompt_version.system_prompt,
            user_prompt=prompt_version.user_prompt,
            prompt_version=prompt_version.version,
            output_schema=prompt_version.output_schema,
            output_schema_ref=node_data.output_schema_ref or prompt_version.template_ref,
        )


@dataclass(frozen=True)
class _PromptSource:
    system_prompt: str
    user_prompt: str
    prompt_version: str
    output_schema: dict[str, object]
    output_schema_ref: str


async def _evaluate_model_approval_policy(
    *,
    approval_evaluator: ApprovalPolicyRuntimeEvaluator | None,
    request: LlmNodeRunRequest,
    policy: ModelGatewayPolicyRead,
) -> str:
    if approval_evaluator is None:
        return "allowed"

    result = await approval_evaluator.evaluate_and_record(
        ApprovalPolicyDecisionRequest(
            project_id=request.project_id,
            actor_id=request.actor_id,
            target_kind="model_invocation",
            target_ref=policy.policy_ref,
            risk_level="medium",
            workflow_ref=f"{request.workflow.workflow.id}:{request.workflow.workflow.version}",
            run_id=request.run_id,
            node_id=request.node_id,
            trace_id=request.trace_id,
            model_policy_ref=policy.policy_ref,
        )
    )
    return result.decision


async def _validate_runtime_approval_for_model(
    *,
    approval_store: RuntimeApprovalTaskStore | None,
    request: LlmNodeRunRequest,
    policy: ModelGatewayPolicyRead,
) -> RuntimeApprovalTaskRead:
    if approval_store is None or request.approved_approval_task_id is None:
        raise LlmNodePolicyDenied("runtime approval store is not configured")
    approval_task = await approval_store.get_approval_task(
        project_id=request.project_id,
        approval_task_id=request.approved_approval_task_id,
    )
    if approval_task is None:
        raise LlmNodePolicyDenied("approval task not found")
    if approval_task.status == "resumed":
        raise LlmNodePolicyDenied("approval task has already been resumed")
    if approval_task.status != "approved":
        raise LlmNodePolicyDenied("approval task is not approved")
    if approval_task.expires_at <= datetime.now(UTC):
        raise LlmNodePolicyDenied("approval task expired before resume")
    if approval_task.target_kind != "model_invocation":
        raise LlmNodePolicyDenied("approval task target kind mismatch")
    if approval_task.target_ref != policy.policy_ref:
        raise LlmNodePolicyDenied("approval task target ref mismatch")
    if approval_task.run_id and approval_task.run_id != request.run_id:
        raise LlmNodePolicyDenied("approval task run mismatch")
    if approval_task.node_id and approval_task.node_id != request.node_id:
        raise LlmNodePolicyDenied("approval task node mismatch")
    return approval_task


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


def _validate_structured_output(content: str, schema: dict[str, object]) -> None:
    try:
        parsed_output = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LlmNodeStructuredOutputInvalid("structured output is not valid JSON") from exc

    try:
        validate_json_schema(instance=parsed_output, schema=schema)
    except JsonSchemaValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path)
        prefix = f"{path}: " if path else ""
        raise LlmNodeStructuredOutputInvalid(f"{prefix}{exc.message}") from exc


def _build_invocation_ref(run_id: str, node_id: str) -> str:
    return f"model_call_{run_id}_{node_id}_{uuid4().hex[:12]}"[:160]
