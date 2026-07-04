import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, ValidationError
from pydantic import BaseModel, ConfigDict, Field

from backend.app.execution.schemas import ShellInvocationCreate, ShellInvocationStatus
from backend.app.execution.shell_runner import (
    DockerSandboxPolicy,
    ScriptTemplateInvocation,
    build_docker_run_command,
)
from backend.app.security.redaction import redact_sensitive_text
from backend.app.tool_registry.schemas import ShellTemplateRead
from backend.app.tool_registry.store import ToolRegistryResourceNotFoundError


class ShellExecutionGatewayError(RuntimeError):
    """Raised when the Execution Gateway cannot run a shell template safely."""


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


class ShellTemplateStore(Protocol):
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


class ShellCommandExecutor(Protocol):
    def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
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
class ShellExecutionGatewayService:
    template_store: ShellTemplateStore
    invocation_store: ShellInvocationStore
    command_executor: ShellCommandExecutor = DockerShellCommandExecutor()
    sandbox_policy: DockerSandboxPolicy = DockerSandboxPolicy()

    async def run_shell(self, request: ShellExecutionRequest) -> ShellExecutionResult:
        template = await self.template_store.get_active_shell_template(
            project_id=request.project_id,
            template_ref=request.template_ref,
            template_version=request.template_version,
        )
        if template is None:
            raise ToolRegistryResourceNotFoundError("shell template not found")
        _validate_executable_template(template, request)
        _validate_parameters(template, request.parameters)

        invocation_id = f"shell_{uuid4().hex}"
        argv = [_render_template_arg(item, request.parameters) for item in template.argv_template]
        invocation = ScriptTemplateInvocation(
            image_ref=template.image_ref,
            entrypoint=template.entrypoint,
            argv=argv,
        )
        command = build_docker_run_command(invocation, self.sandbox_policy)
        command_hash = _command_hash(command)
        started = time.perf_counter()
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


def _validate_executable_template(
    template: ShellTemplateRead,
    request: ShellExecutionRequest,
) -> None:
    if template.environment_key != request.environment:
        raise ShellExecutionGatewayError("shell template environment does not match node")
    if not template.image_ref or not template.entrypoint or not template.argv_template:
        raise ShellExecutionGatewayError("shell template is missing executable metadata")


def _validate_parameters(template: ShellTemplateRead, parameters: dict[str, Any]) -> None:
    if not template.parameter_schema:
        return
    try:
        Draft202012Validator(template.parameter_schema).validate(parameters)
    except ValidationError as exc:
        raise ShellExecutionGatewayError(
            f"shell template parameters are invalid: {exc.message}"
        ) from exc


def _render_template_arg(template: str, parameters: dict[str, Any]) -> str:
    rendered = template
    for key, value in parameters.items():
        if isinstance(value, (dict, list)):
            replacement = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            replacement = "" if value is None else str(value)
        rendered = rendered.replace(f"{{{{{key}}}}}", replacement)
    return rendered


def _command_hash(command: list[str]) -> str:
    payload = json.dumps(command, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _summarize_output(value: str, *, limit: int = 2000) -> str:
    sanitized = redact_sensitive_text(value).strip()
    if len(sanitized) > limit:
        return f"{sanitized[:limit]}..."
    return sanitized


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
