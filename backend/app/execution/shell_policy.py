import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from jsonschema import Draft202012Validator, ValidationError

from backend.app.execution.shell_runner import (
    DockerSandboxPolicy,
    ScriptTemplateInvocation,
    build_docker_run_command,
    build_shell_command_preview,
)
from backend.app.security.redaction import redact_sensitive_text

DEFAULT_SHELL_IMAGE_ALLOWLIST = ("redis:7-alpine",)
_IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


class ShellTemplatePolicyError(ValueError):
    """Raised when a shell template violates execution policy."""


@dataclass(frozen=True)
class ShellImagePolicy:
    allowlist: tuple[str, ...] = DEFAULT_SHELL_IMAGE_ALLOWLIST
    require_digest: bool = True
    forbid_latest: bool = True


@dataclass(frozen=True)
class ShellTemplatePolicyDecision:
    approval_required: bool
    digest_required: bool
    allowlisted: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ShellTemplatePreview:
    rendered_argv: list[str]
    command_preview: str
    command_hash: str
    sandbox: dict[str, Any]
    policy: ShellTemplatePolicyDecision
    trace_link: str


@dataclass(frozen=True)
class ShellTemplatePolicyInput:
    project_id: UUID
    template_ref: str
    template_version: int
    risk_level: str
    environment_key: str
    image_ref: str
    image_digest: str
    entrypoint: str
    argv_template: list[str]
    parameter_schema: dict[str, Any]
    timeout_seconds: int
    image_registry_digest: str = ""
    image_admission_status: str = "not_required"


def validate_shell_template_policy(
    template: ShellTemplatePolicyInput,
    *,
    image_policy: ShellImagePolicy | None = None,
) -> ShellTemplatePolicyDecision:
    image_policy = image_policy or ShellImagePolicy()
    decision = evaluate_shell_template_policy(template, image_policy=image_policy)
    if not _has_executable_metadata(template):
        return decision
    if image_policy.forbid_latest and _uses_latest_or_missing_tag(template.image_ref):
        raise ShellTemplatePolicyError("Shell template image tag latest is forbidden")
    if not _image_is_allowlisted(template, image_policy):
        raise ShellTemplatePolicyError("Shell template image is not allowlisted")
    if image_policy.require_digest and not template.image_digest:
        raise ShellTemplatePolicyError("Shell template image digest is required")
    if template.image_digest and not _IMAGE_DIGEST_PATTERN.fullmatch(template.image_digest):
        raise ShellTemplatePolicyError("Shell template image digest is invalid")
    return decision


def evaluate_shell_template_policy(
    template: ShellTemplatePolicyInput,
    *,
    image_policy: ShellImagePolicy | None = None,
) -> ShellTemplatePolicyDecision:
    image_policy = image_policy or ShellImagePolicy()
    reasons: list[str] = []
    if template.environment_key.lower() in {"prod", "production"} or template.risk_level in {
        "high",
        "critical",
    }:
        reasons.append("Production or high risk shell templates require approval")
    if image_policy.require_digest:
        reasons.append("Shell images must carry a sha256 digest")
    return ShellTemplatePolicyDecision(
        approval_required=bool(
            template.environment_key.lower() in {"prod", "production"}
            or template.risk_level in {"high", "critical"}
        ),
        digest_required=image_policy.require_digest,
        allowlisted=_image_is_allowlisted(template, image_policy),
        reasons=reasons,
    )


def build_shell_template_preview(
    template: ShellTemplatePolicyInput,
    *,
    parameters: dict[str, Any],
    run_id: str = "",
    trace_id: str = "",
    image_policy: ShellImagePolicy | None = None,
    sandbox_policy: DockerSandboxPolicy | None = None,
) -> ShellTemplatePreview:
    image_policy = image_policy or ShellImagePolicy()
    sandbox_policy = sandbox_policy or DockerSandboxPolicy()
    validate_shell_template_policy(template, image_policy=image_policy)
    validate_shell_parameters(template.parameter_schema, parameters)
    rendered_argv = render_template_args(template.argv_template, parameters)
    invocation = ScriptTemplateInvocation(
        image_ref=template.image_ref,
        entrypoint=template.entrypoint,
        argv=rendered_argv,
    )
    command = build_docker_run_command(invocation, sandbox_policy)
    decision = evaluate_shell_template_policy(template, image_policy=image_policy)
    return ShellTemplatePreview(
        rendered_argv=[redact_sensitive_text(item) for item in rendered_argv],
        command_preview=redact_sensitive_text(build_shell_command_preview(invocation)),
        command_hash=hash_command(command),
        sandbox=sandbox_summary(sandbox_policy),
        policy=decision,
        trace_link=_trace_link(template.project_id, run_id=run_id, trace_id=trace_id),
    )


def validate_shell_parameters(schema: dict[str, Any], parameters: dict[str, Any]) -> None:
    if not schema:
        return
    try:
        Draft202012Validator(schema).validate(parameters)
    except ValidationError as exc:
        raise ShellTemplatePolicyError(
            f"shell template parameters are invalid: {exc.message}"
        ) from exc


def render_template_args(argv_template: list[str], parameters: dict[str, Any]) -> list[str]:
    return [_render_template_arg(item, parameters) for item in argv_template]


def hash_command(command: list[str]) -> str:
    payload = json.dumps(command, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def sandbox_summary(policy: DockerSandboxPolicy) -> dict[str, Any]:
    return {
        "network_mode": policy.network_mode,
        "read_only": policy.read_only,
        "tmpfs": policy.tmpfs,
        "user": policy.user,
        "cap_drop": policy.cap_drop,
        "no_new_privileges": "no-new-privileges=true" in policy.security_opt,
        "pids_limit": policy.resource_limits.pids_limit,
        "memory": policy.resource_limits.memory,
        "memory_swap": policy.resource_limits.memory_swap,
        "cpus": policy.resource_limits.cpus,
    }


def _render_template_arg(template: str, parameters: dict[str, Any]) -> str:
    rendered = template
    for key, value in parameters.items():
        if isinstance(value, (dict, list)):
            replacement = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            replacement = "" if value is None else str(value)
        rendered = rendered.replace(f"{{{{{key}}}}}", replacement)
    return rendered


def _has_executable_metadata(template: ShellTemplatePolicyInput) -> bool:
    return bool(template.image_ref or template.entrypoint or template.argv_template)


def _image_is_allowlisted(
    template: ShellTemplatePolicyInput,
    image_policy: ShellImagePolicy,
) -> bool:
    if template.image_ref in image_policy.allowlist:
        return True
    return (
        template.image_admission_status in {"approved", "would_reject"}
        and bool(template.image_registry_digest)
        and template.image_registry_digest == template.image_digest
    )


def _uses_latest_or_missing_tag(image_ref: str) -> bool:
    last_segment = image_ref.rsplit("/", maxsplit=1)[-1]
    if ":" not in last_segment:
        return True
    return last_segment.rsplit(":", maxsplit=1)[-1] == "latest"


def _trace_link(project_id: UUID, *, run_id: str, trace_id: str) -> str:
    query = urlencode(
        {key: value for key, value in {"run_id": run_id, "trace_id": trace_id}.items() if value}
    )
    suffix = f"?{query}" if query else ""
    return f"/projects/{project_id}/runs{suffix}"
