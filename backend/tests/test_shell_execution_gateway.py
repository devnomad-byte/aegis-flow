import subprocess
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from backend.app.execution.gateway import (
    ShellExecutionGatewayError,
    ShellExecutionGatewayService,
    ShellExecutionRequest,
)
from backend.app.execution.schemas import ShellInvocationCreate
from backend.app.tool_registry.schemas import ShellImageAdmissionPolicyRead, ShellTemplateRead


@pytest.mark.asyncio
async def test_shell_execution_gateway_renders_template_runs_docker_and_records_ledger() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    template_store = InMemoryShellTemplateStore(
        template=shell_template(project_id=project_id, actor_id=actor_id)
    )
    invocation_store = RecordingShellInvocationStore()
    command_executor = RecordingCommandExecutor(
        result=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="hello gateway\n",
            stderr="",
        )
    )
    gateway = ShellExecutionGatewayService(
        template_store=template_store,
        invocation_store=invocation_store,
        command_executor=command_executor,
    )

    result = await gateway.run_shell(
        ShellExecutionRequest(
            project_id=project_id,
            actor_id=actor_id,
            workflow_ref="shell_flow:1",
            run_id="run-shell-gateway",
            node_id="shell_1",
            trace_id="trace-shell-gateway",
            template_ref="echo-shell",
            template_version=1,
            environment="test",
            parameters={"message": "hello gateway"},
        )
    )

    assert result.status == "success"
    assert result.exit_code == 0
    assert result.stdout_summary == "hello gateway"
    assert result.stderr_summary == ""
    assert result.sandbox_image == "redis:7-alpine"
    assert result.network_mode == "none"
    assert command_executor.timeout_seconds == 7
    assert command_executor.command is not None
    assert command_executor.command[:3] == ["docker", "run", "--rm"]
    assert "--network=none" in command_executor.command
    assert "--read-only" in command_executor.command
    assert "--cap-drop=ALL" in command_executor.command
    assert "no-new-privileges=true" in command_executor.command
    assert command_executor.command[-3:] == ["redis:7-alpine", "-lc", "echo hello gateway"]

    assert len(invocation_store.invocations) == 1
    invocation = invocation_store.invocations[0]
    assert invocation.project_id == project_id
    assert invocation.actor_id == actor_id
    assert invocation.template_ref == "echo-shell"
    assert invocation.template_version == 1
    assert invocation.workflow_ref == "shell_flow:1"
    assert invocation.run_id == "run-shell-gateway"
    assert invocation.node_id == "shell_1"
    assert invocation.trace_id == "trace-shell-gateway"
    assert invocation.status == "success"
    assert invocation.exit_code == 0
    assert invocation.stdout_summary == "hello gateway"
    assert invocation.command_hash.startswith("sha256:")


@pytest.mark.asyncio
async def test_shell_execution_gateway_rejects_wrong_environment_before_docker() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    invocation_store = RecordingShellInvocationStore()
    command_executor = RecordingCommandExecutor(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    )
    gateway = ShellExecutionGatewayService(
        template_store=InMemoryShellTemplateStore(
            template=shell_template(project_id=project_id, actor_id=actor_id)
        ),
        invocation_store=invocation_store,
        command_executor=command_executor,
    )

    with pytest.raises(ShellExecutionGatewayError, match="environment"):
        await gateway.run_shell(
            ShellExecutionRequest(
                project_id=project_id,
                actor_id=actor_id,
                template_ref="echo-shell",
                template_version=1,
                environment="prod",
                parameters={"message": "hello"},
            )
        )

    assert command_executor.command is None
    assert invocation_store.invocations == []


@pytest.mark.asyncio
async def test_shell_execution_gateway_rejects_invalid_parameters_before_docker() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    invocation_store = RecordingShellInvocationStore()
    command_executor = RecordingCommandExecutor(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    )
    gateway = ShellExecutionGatewayService(
        template_store=InMemoryShellTemplateStore(
            template=shell_template(project_id=project_id, actor_id=actor_id)
        ),
        invocation_store=invocation_store,
        command_executor=command_executor,
    )

    with pytest.raises(ShellExecutionGatewayError, match="parameters"):
        await gateway.run_shell(
            ShellExecutionRequest(
                project_id=project_id,
                actor_id=actor_id,
                template_ref="echo-shell",
                template_version=1,
                environment="test",
                parameters={"message": 123},
            )
        )

    assert command_executor.command is None
    assert invocation_store.invocations == []


@pytest.mark.asyncio
async def test_shell_execution_gateway_rejects_unpinned_image_before_docker() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    invocation_store = RecordingShellInvocationStore()
    command_executor = RecordingCommandExecutor(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    )
    template = shell_template(project_id=project_id, actor_id=actor_id).model_copy(
        update={"image_digest": ""}
    )
    gateway = ShellExecutionGatewayService(
        template_store=InMemoryShellTemplateStore(template=template),
        invocation_store=invocation_store,
        command_executor=command_executor,
    )

    with pytest.raises(ShellExecutionGatewayError, match="digest"):
        await gateway.run_shell(
            ShellExecutionRequest(
                project_id=project_id,
                actor_id=actor_id,
                template_ref="echo-shell",
                template_version=1,
                environment="test",
                parameters={"message": "hello"},
            )
        )

    assert command_executor.command is None
    assert invocation_store.invocations == []


@pytest.mark.asyncio
async def test_shell_execution_gateway_blocks_would_reject_template_when_policy_enforces() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    digest = "sha256:" + ("d" * 64)
    invocation_store = RecordingShellInvocationStore()
    command_executor = RecordingCommandExecutor(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    )
    template = shell_template(project_id=project_id, actor_id=actor_id).model_copy(
        update={
            "risk_level": "high",
            "environment_key": "prod",
            "image_ref": "registry.example/aegis/runtime:7-alpine",
            "image_digest": digest,
            "image_registry_digest": digest,
            "image_admission_status": "would_reject",
            "image_admission_reason": "dry-run would reject: cosign evidence missing",
        }
    )
    gateway = ShellExecutionGatewayService(
        template_store=InMemoryShellTemplateStore(
            policy=shell_image_policy(project_id=project_id, actor_id=actor_id),
            template=template,
        ),
        invocation_store=invocation_store,
        command_executor=command_executor,
    )

    with pytest.raises(ShellExecutionGatewayError, match="approved shell image admission"):
        await gateway.run_shell(
            ShellExecutionRequest(
                project_id=project_id,
                actor_id=actor_id,
                template_ref="echo-shell",
                template_version=1,
                environment="prod",
                parameters={"message": "hello"},
            )
        )

    assert command_executor.command is None
    assert invocation_store.invocations == []


@pytest.mark.asyncio
async def test_shell_execution_gateway_records_sanitized_failure_summary() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    invocation_store = RecordingShellInvocationStore()
    gateway = ShellExecutionGatewayService(
        template_store=InMemoryShellTemplateStore(
            template=shell_template(project_id=project_id, actor_id=actor_id)
        ),
        invocation_store=invocation_store,
        command_executor=RecordingCommandExecutor(
            result=subprocess.CompletedProcess(
                args=[],
                returncode=2,
                stdout="",
                stderr="Authorization: Bearer raw-token",
            )
        ),
    )

    result = await gateway.run_shell(
        ShellExecutionRequest(
            project_id=project_id,
            actor_id=actor_id,
            template_ref="echo-shell",
            template_version=1,
            environment="test",
            parameters={"message": "hello"},
        )
    )

    assert result.status == "failed"
    assert result.exit_code == 2
    assert result.error_type == "ShellCommandFailed"
    assert "raw-token" not in result.stderr_summary
    assert "raw-token" not in str(invocation_store.invocations[0])


class InMemoryShellTemplateStore:
    def __init__(
        self,
        *,
        policy: ShellImageAdmissionPolicyRead | None = None,
        template: ShellTemplateRead | None,
    ) -> None:
        self.policy = policy
        self.template = template

    async def get_shell_image_admission_policy(
        self,
        project_id: UUID,
    ) -> ShellImageAdmissionPolicyRead:
        if self.policy is not None:
            return self.policy
        return ShellImageAdmissionPolicyRead(
            id=None,
            configured=False,
            project_id=project_id,
            enforcement_mode="dry_run",
            cosign_required=False,
            notation_enabled=False,
            notation_trust_policy={"version": "1.0", "trustPolicies": []},
            sbom_artifact_retention_enabled=False,
            scan_report_retention_enabled=False,
            artifact_store_prefix="shell-image-admissions",
            artifact_retention_days=30,
            blocked_severities=["HIGH", "CRITICAL"],
        )

    async def get_active_shell_template(
        self,
        *,
        project_id: UUID,
        template_ref: str,
        template_version: int,
    ) -> ShellTemplateRead | None:
        if self.template is None:
            return None
        if (
            self.template.project_id == project_id
            and self.template.template_ref == template_ref
            and self.template.template_version == template_version
        ):
            return self.template
        return None


class RecordingShellInvocationStore:
    def __init__(self) -> None:
        self.invocations: list[ShellInvocationCreate] = []

    async def record_invocation(self, request: ShellInvocationCreate) -> ShellInvocationCreate:
        self.invocations.append(request)
        return request


class RecordingCommandExecutor:
    def __init__(self, *, result: subprocess.CompletedProcess[str]) -> None:
        self.result = result
        self.command: list[str] | None = None
        self.timeout_seconds: int | None = None

    def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        self.command = command
        self.timeout_seconds = timeout_seconds
        return self.result


def shell_template(*, project_id: UUID, actor_id: UUID) -> ShellTemplateRead:
    now = datetime.now(UTC)
    return ShellTemplateRead(
        id=uuid4(),
        project_id=project_id,
        name="Echo Shell",
        status="active",
        description="Echo a message in Docker",
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
        template_ref="echo-shell",
        template_version=1,
        risk_level="low",
        environment_key="test",
        credential_ref="",
        image_ref="redis:7-alpine",
        image_digest="sha256:" + ("c" * 64),
        entrypoint="/bin/sh",
        argv_template=["-lc", "echo {{message}}"],
        parameter_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
            "additionalProperties": False,
        },
        timeout_seconds=7,
    )


def shell_image_policy(
    *,
    project_id: UUID,
    actor_id: UUID,
) -> ShellImageAdmissionPolicyRead:
    now = datetime.now(UTC)
    return ShellImageAdmissionPolicyRead(
        id=uuid4(),
        configured=True,
        project_id=project_id,
        enforcement_mode="enforce",
        cosign_required=True,
        notation_enabled=False,
        notation_trust_policy={"version": "1.0", "trustPolicies": []},
        sbom_artifact_retention_enabled=False,
        scan_report_retention_enabled=False,
        artifact_store_prefix="shell-image-admissions",
        artifact_retention_days=30,
        blocked_severities=["HIGH", "CRITICAL"],
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
