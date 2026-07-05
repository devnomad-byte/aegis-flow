import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.app.execution.schemas import (
    HttpInvocationCreate,
    HttpInvocationStatus,
    ShellInvocationCreate,
    ShellInvocationStatus,
)
from backend.app.execution.shell_policy import (
    ShellTemplatePolicyError,
    ShellTemplatePolicyInput,
    hash_command,
    render_template_args,
    validate_shell_parameters,
    validate_shell_template_policy,
)
from backend.app.execution.shell_runner import (
    DockerSandboxPolicy,
    ScriptTemplateInvocation,
    build_docker_run_command,
)
from backend.app.policy_center.runtime import (
    ApprovalPolicyDecisionRequest,
    ApprovalPolicyRuntimeEvaluator,
)
from backend.app.security.egress_policy import EgressPolicy, EgressPolicyViolation
from backend.app.security.egress_proxy import (
    EgressProxyMode,
    EgressProxyPlan,
    EgressProxyPolicy,
    EgressProxyPolicyViolation,
    build_egress_proxy_plan,
)
from backend.app.security.redaction import redact_sensitive_text
from backend.app.tool_registry.schemas import (
    EnvironmentRead,
    ShellImageAdmissionPolicyRead,
    ShellTemplateRead,
)
from backend.app.tool_registry.store import (
    ToolRegistryEgressPolicyError,
    ToolRegistryResourceNotFoundError,
)

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class ShellExecutionGatewayError(RuntimeError):
    """Raised when the Execution Gateway cannot run a shell template safely."""


class HttpExecutionGatewayError(RuntimeError):
    """Raised when the Execution Gateway cannot run an HTTP action safely."""


class ShellExecutionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    actor_id: UUID
    workflow_ref: str = Field(default="", max_length=160)
    run_id: str = Field(default="", max_length=160)
    node_id: str = Field(default="", max_length=160)
    trace_id: str = Field(default="", max_length=160)
    template_ref: str = Field(min_length=1, max_length=160)
    template_version: int = Field(ge=1)
    environment: str = Field(min_length=1, max_length=80)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ShellExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ShellInvocationStatus
    exit_code: int | None = None
    duration_ms: int = Field(default=0, ge=0)
    stdout_summary: str = ""
    stderr_summary: str = ""
    invocation_id: str
    command_hash: str
    sandbox_image: str
    sandbox_image_digest: str = ""
    network_mode: str = "none"
    error_type: str = ""
    error_message: str = ""


class HttpExecutionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    actor_id: UUID
    workflow_ref: str = Field(default="", max_length=160)
    run_id: str = Field(default="", max_length=160)
    node_id: str = Field(default="", max_length=160)
    trace_id: str = Field(default="", max_length=160)
    action_ref: str = Field(min_length=1, max_length=160)
    method: HttpMethod
    url: str = Field(min_length=1, max_length=2048)
    tool_group_ref: str = Field(default="", max_length=160)
    environment: str = Field(min_length=1, max_length=80)
    egress_profile_ref: str = Field(default="", max_length=160)
    query: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, Any] = Field(default_factory=dict)
    body: Any = None
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class HttpExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: HttpInvocationStatus
    http_status_code: int | None = None
    duration_ms: int = Field(default=0, ge=0)
    response_summary: str = ""
    response_json: dict[str, Any] = Field(default_factory=dict)
    invocation_id: str
    target_host: str = ""
    target_port: int = 0
    egress_proxy_mode: str = ""
    error_type: str = ""
    error_message: str = ""


class ShellTemplateStore(Protocol):
    async def get_shell_image_admission_policy(
        self,
        project_id: UUID,
    ) -> ShellImageAdmissionPolicyRead:
        raise NotImplementedError

    async def get_active_shell_template(
        self,
        *,
        project_id: UUID,
        template_ref: str,
        template_version: int,
    ) -> ShellTemplateRead | None:
        raise NotImplementedError


class ShellInvocationStore(Protocol):
    async def record_invocation(self, request: ShellInvocationCreate) -> Any:
        raise NotImplementedError


class EnvironmentStore(Protocol):
    async def get_active_environment(
        self,
        *,
        project_id: UUID,
        environment_key: str,
    ) -> EnvironmentRead | None:
        raise NotImplementedError


class HttpInvocationStore(Protocol):
    async def record_http_invocation(self, request: HttpInvocationCreate) -> Any:
        raise NotImplementedError


class ShellCommandExecutor(Protocol):
    def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        raise NotImplementedError


class HttpRequestExecutor(Protocol):
    async def execute(
        self,
        request: httpx.Request,
        *,
        timeout_seconds: int,
        proxy_url: str,
    ) -> httpx.Response:
        raise NotImplementedError


@dataclass(frozen=True)
class DockerShellCommandExecutor:
    def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )


@dataclass(frozen=True)
class HttpxRequestExecutor:
    async def execute(
        self,
        request: httpx.Request,
        *,
        timeout_seconds: int,
        proxy_url: str,
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(timeout_seconds),
            proxy=proxy_url or None,
        ) as client:
            return await client.send(request)


@dataclass(frozen=True)
class ShellExecutionGatewayService:
    template_store: ShellTemplateStore
    invocation_store: ShellInvocationStore
    command_executor: ShellCommandExecutor = DockerShellCommandExecutor()
    sandbox_policy: DockerSandboxPolicy = DockerSandboxPolicy()
    approval_evaluator: ApprovalPolicyRuntimeEvaluator | None = None

    async def run_shell(self, request: ShellExecutionRequest) -> ShellExecutionResult:
        started = time.perf_counter()
        template = await self.template_store.get_active_shell_template(
            project_id=request.project_id,
            template_ref=request.template_ref,
            template_version=request.template_version,
        )
        if template is None:
            raise ToolRegistryResourceNotFoundError("shell template not found")
        admission_policy = await self.template_store.get_shell_image_admission_policy(
            request.project_id,
        )
        _validate_executable_template(template, request, admission_policy)
        _validate_parameters(template, request.parameters)

        invocation_id = f"shell_{uuid4().hex}"
        policy_decision = await _evaluate_shell_approval_policy(
            approval_evaluator=self.approval_evaluator,
            request=request,
            template=template,
        )
        if policy_decision in {"denied", "approval_required"}:
            error_type = (
                "approval_policy_denied"
                if policy_decision == "denied"
                else "approval_policy_approval_required"
            )
            error_message = (
                "Shell execution denied by approval policy"
                if policy_decision == "denied"
                else (
                    "Shell execution requires approval; "
                    "shell approval recovery is not available in v1"
                )
            )
            command_hash = hash_command(
                [
                    "approval-policy",
                    policy_decision,
                    template.template_ref,
                    str(template.template_version),
                ]
            )
            duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            await self.invocation_store.record_invocation(
                ShellInvocationCreate(
                    project_id=request.project_id,
                    actor_id=request.actor_id,
                    invocation_ref=invocation_id,
                    template_ref=template.template_ref,
                    template_version=template.template_version,
                    command_hash=command_hash,
                    sandbox_image=template.image_ref,
                    sandbox_image_digest=template.image_digest,
                    egress_profile_ref="",
                    egress_proxy_mode="",
                    network_mode=self.sandbox_policy.network_mode,
                    workflow_ref=request.workflow_ref,
                    run_id=request.run_id,
                    node_id=request.node_id,
                    trace_id=request.trace_id,
                    status="denied",
                    exit_code=None,
                    duration_ms=duration_ms,
                    resource_usage={},
                    stdout_summary="",
                    stderr_summary="",
                    error_type=error_type,
                    error_message=error_message,
                    created_by=request.actor_id,
                    updated_by=request.actor_id,
                )
            )
            return ShellExecutionResult(
                status="denied",
                exit_code=None,
                duration_ms=duration_ms,
                stdout_summary="",
                stderr_summary="",
                invocation_id=invocation_id,
                command_hash=command_hash,
                sandbox_image=template.image_ref,
                sandbox_image_digest=template.image_digest,
                network_mode=self.sandbox_policy.network_mode,
                error_type=error_type,
                error_message=error_message,
            )

        argv = render_template_args(template.argv_template, request.parameters)
        invocation = ScriptTemplateInvocation(
            image_ref=template.image_ref,
            entrypoint=template.entrypoint,
            argv=argv,
        )
        command = build_docker_run_command(invocation, self.sandbox_policy)
        command_hash = hash_command(command)
        status: ShellInvocationStatus = "success"
        exit_code: int | None = None
        stdout_summary = ""
        stderr_summary = ""
        error_type = ""
        error_message = ""

        try:
            completed = self.command_executor.execute(
                command,
                timeout_seconds=template.timeout_seconds,
            )
            exit_code = completed.returncode
            stdout_summary = _summarize_output(completed.stdout)
            stderr_summary = _summarize_output(completed.stderr)
            if completed.returncode != 0:
                status = "failed"
                error_type = "ShellCommandFailed"
                error_message = f"shell command exited with code {completed.returncode}"
        except subprocess.TimeoutExpired as exc:
            status = "timeout"
            error_type = exc.__class__.__name__
            error_message = "shell command timed out"
            stdout_summary = _summarize_output(_coerce_output(exc.stdout))
            stderr_summary = _summarize_output(_coerce_output(exc.stderr))
        except Exception as exc:
            status = "failed"
            error_type = exc.__class__.__name__
            error_message = redact_sensitive_text(str(exc))

        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        await self.invocation_store.record_invocation(
            ShellInvocationCreate(
                project_id=request.project_id,
                actor_id=request.actor_id,
                invocation_ref=invocation_id,
                template_ref=template.template_ref,
                template_version=template.template_version,
                command_hash=command_hash,
                sandbox_image=template.image_ref,
                sandbox_image_digest=template.image_digest,
                egress_profile_ref="",
                egress_proxy_mode="",
                network_mode=self.sandbox_policy.network_mode,
                workflow_ref=request.workflow_ref,
                run_id=request.run_id,
                node_id=request.node_id,
                trace_id=request.trace_id,
                status=status,
                exit_code=exit_code,
                duration_ms=duration_ms,
                resource_usage={},
                stdout_summary=stdout_summary,
                stderr_summary=stderr_summary,
                error_type=error_type,
                error_message=error_message,
                created_by=request.actor_id,
                updated_by=request.actor_id,
            )
        )
        return ShellExecutionResult(
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout_summary=stdout_summary,
            stderr_summary=stderr_summary,
            invocation_id=invocation_id,
            command_hash=command_hash,
            sandbox_image=template.image_ref,
            sandbox_image_digest=template.image_digest,
            network_mode=self.sandbox_policy.network_mode,
            error_type=error_type,
            error_message=error_message,
        )


async def _evaluate_shell_approval_policy(
    *,
    approval_evaluator: ApprovalPolicyRuntimeEvaluator | None,
    request: ShellExecutionRequest,
    template: ShellTemplateRead,
) -> str:
    if approval_evaluator is None:
        return "approval_required" if template.risk_level in {"high", "critical"} else "allowed"

    result = await approval_evaluator.evaluate_and_record(
        ApprovalPolicyDecisionRequest(
            project_id=request.project_id,
            actor_id=request.actor_id,
            target_kind="shell_execution",
            target_ref=template.template_ref,
            risk_level=template.risk_level,
            workflow_ref=request.workflow_ref,
            run_id=request.run_id,
            node_id=request.node_id,
            trace_id=request.trace_id,
            shell_template_ref=template.template_ref,
            environment_key=template.environment_key,
        )
    )
    return result.decision


@dataclass(frozen=True)
class HttpExecutionGatewayService:
    environment_store: EnvironmentStore
    invocation_store: HttpInvocationStore
    request_executor: HttpRequestExecutor = HttpxRequestExecutor()
    egress_policy: EgressPolicy = EgressPolicy()

    async def run_http(self, request: HttpExecutionRequest) -> HttpExecutionResult:
        environment = await self.environment_store.get_active_environment(
            project_id=request.project_id,
            environment_key=request.environment,
        )
        if environment is None:
            raise ToolRegistryResourceNotFoundError("environment not found")

        url = _apply_query(request.url, request.query)
        egress_plan = _build_http_egress_plan(url, environment, self.egress_policy)
        normalized_url = egress_plan.target.normalized_url
        invocation_id = f"http_{uuid4().hex}"
        request_summary = _summarize_json(
            {
                "method": request.method,
                "target_host": egress_plan.target.hostname,
                "target_port": egress_plan.target.port,
                "query_keys": sorted(request.query.keys()),
                "header_keys": sorted(request.headers.keys()),
                "has_body": request.body is not None,
            }
        )
        started = time.perf_counter()
        status: HttpInvocationStatus = "success"
        http_status_code: int | None = None
        response_summary = ""
        response_json: dict[str, Any] = {}
        error_type = ""
        error_message = ""

        try:
            http_request = _build_httpx_request(
                method=request.method,
                url=normalized_url,
                headers=request.headers,
                body=request.body,
            )
            response = await self.request_executor.execute(
                http_request,
                timeout_seconds=request.timeout_seconds,
                proxy_url=egress_plan.httpx_proxy_url,
            )
            http_status_code = response.status_code
            response_summary = _summarize_output(response.text)
            response_json = _parse_json_object(response)
            if response.status_code >= 400:
                status = "failed"
                error_type = "HttpStatusError"
                error_message = f"http request failed with status {response.status_code}"
        except TimeoutError as exc:
            status = "timeout"
            error_type = exc.__class__.__name__
            error_message = "http request timed out"
        except httpx.TimeoutException as exc:
            status = "timeout"
            error_type = exc.__class__.__name__
            error_message = "http request timed out"
        except Exception as exc:
            status = "failed"
            error_type = exc.__class__.__name__
            error_message = redact_sensitive_text(str(exc))

        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        await self.invocation_store.record_http_invocation(
            HttpInvocationCreate(
                project_id=request.project_id,
                actor_id=request.actor_id,
                invocation_ref=invocation_id,
                action_ref=request.action_ref,
                method=request.method,
                url_hash=_url_hash(normalized_url),
                target_host=egress_plan.target.hostname,
                target_port=egress_plan.target.port,
                egress_profile_ref=request.egress_profile_ref,
                egress_proxy_mode=egress_plan.mode.value,
                workflow_ref=request.workflow_ref,
                run_id=request.run_id,
                node_id=request.node_id,
                trace_id=request.trace_id,
                status=status,
                http_status_code=http_status_code,
                duration_ms=duration_ms,
                request_summary=request_summary,
                response_summary=response_summary,
                response_json=response_json,
                error_type=error_type,
                error_message=error_message,
                created_by=request.actor_id,
                updated_by=request.actor_id,
            )
        )
        return HttpExecutionResult(
            status=status,
            http_status_code=http_status_code,
            duration_ms=duration_ms,
            response_summary=response_summary,
            response_json=response_json,
            invocation_id=invocation_id,
            target_host=egress_plan.target.hostname,
            target_port=egress_plan.target.port,
            egress_proxy_mode=egress_plan.mode.value,
            error_type=error_type,
            error_message=error_message,
        )


def _validate_executable_template(
    template: ShellTemplateRead,
    request: ShellExecutionRequest,
    admission_policy: ShellImageAdmissionPolicyRead,
) -> None:
    if template.environment_key != request.environment:
        raise ShellExecutionGatewayError("shell template environment does not match node")
    if not template.image_ref or not template.entrypoint or not template.argv_template:
        raise ShellExecutionGatewayError("shell template is missing executable metadata")
    try:
        validate_shell_template_policy(
            ShellTemplatePolicyInput(
                project_id=template.project_id,
                template_ref=template.template_ref,
                template_version=template.template_version,
                risk_level=template.risk_level,
                environment_key=template.environment_key,
                image_ref=template.image_ref,
                image_digest=template.image_digest,
                entrypoint=template.entrypoint,
                argv_template=template.argv_template,
                parameter_schema=template.parameter_schema,
                timeout_seconds=template.timeout_seconds,
                image_registry_digest=template.image_registry_digest,
                image_admission_status=template.image_admission_status,
            ),
            admission_enforcement_mode=admission_policy.enforcement_mode,
        )
    except ShellTemplatePolicyError as exc:
        raise ShellExecutionGatewayError(str(exc)) from exc


def _validate_parameters(template: ShellTemplateRead, parameters: dict[str, Any]) -> None:
    try:
        validate_shell_parameters(template.parameter_schema, parameters)
    except ShellTemplatePolicyError as exc:
        raise ShellExecutionGatewayError(str(exc)) from exc


def _summarize_output(value: str, *, limit: int = 2000) -> str:
    sanitized = redact_sensitive_text(value).strip()
    if len(sanitized) > limit:
        return f"{sanitized[:limit]}..."
    return sanitized


def _summarize_json(value: Any, *, limit: int = 2000) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return _summarize_output(text, limit=limit)


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _build_http_egress_plan(
    url: str,
    environment: EnvironmentRead,
    egress_policy: EgressPolicy,
) -> EgressProxyPlan:
    try:
        return build_egress_proxy_plan(
            url,
            egress_policy=egress_policy,
            proxy_policy=EgressProxyPolicy(
                mode=EgressProxyMode(environment.egress_proxy_mode),
                proxy_url=environment.egress_proxy_url,
                docker_network=environment.egress_proxy_network,
                allowed_hosts=environment.egress_allowed_hosts,
                allowed_ports=environment.egress_allowed_ports,
                dns_pinning_required=environment.egress_dns_pinning_required,
            ),
        )
    except EgressProxyPolicyViolation as exc:
        raise HttpExecutionGatewayError(exc.public_message) from exc
    except EgressPolicyViolation as exc:
        raise HttpExecutionGatewayError(exc.public_message) from exc
    except ToolRegistryEgressPolicyError as exc:
        raise HttpExecutionGatewayError(str(exc)) from exc
    except ValueError as exc:
        raise HttpExecutionGatewayError("HTTP egress policy is invalid") from exc


def _apply_query(url: str, query: dict[str, Any]) -> str:
    if not query:
        return url
    parts = urlsplit(url)
    existing_query = parts.query
    encoded = urlencode(
        {key: _scalar_query_value(value) for key, value in query.items() if value is not None},
        doseq=True,
    )
    combined = "&".join(item for item in [existing_query, encoded] if item)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, combined, parts.fragment))


def _scalar_query_value(value: Any) -> str | list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, (dict, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _build_httpx_request(
    *,
    method: str,
    url: str,
    headers: dict[str, Any],
    body: Any,
) -> httpx.Request:
    sanitized_headers = {
        str(key): str(value)
        for key, value in headers.items()
        if value is not None and str(key).strip()
    }
    if body is None:
        return httpx.Request(method, url, headers=sanitized_headers)
    return httpx.Request(method, url, headers=sanitized_headers, json=body)


def _parse_json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    if isinstance(payload, dict):
        sanitized = _sanitize_json_value(payload)
        return sanitized if isinstance(sanitized, dict) else {}
    sanitized_value = _sanitize_json_value(payload)
    return {"value": sanitized_value}


def _url_hash(url: str) -> str:
    return f"sha256:{hashlib.sha256(url.encode('utf-8')).hexdigest()}"


def _sanitize_json_value(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_json_value(item, parent_key=str(key)) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_json_value(item, parent_key=parent_key) for item in value]
    if isinstance(value, str):
        if _is_sensitive_key(parent_key):
            return "[redacted]"
        return redact_sensitive_text(value)
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(".", "_")
    parts = {part for part in normalized.split("_") if part}
    return bool(
        parts
        & {
            "api_key",
            "apikey",
            "auth",
            "authorization",
            "bearer",
            "credential",
            "password",
            "secret",
            "token",
        }
    )
