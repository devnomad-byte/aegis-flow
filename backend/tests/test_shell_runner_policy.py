import pytest
from backend.app.execution.shell_runner import (
    DockerMount,
    DockerResourceLimits,
    DockerSandboxPolicy,
    DockerSandboxPolicyError,
    ScriptTemplateInvocation,
    SecretReference,
    build_docker_run_command,
    build_shell_command_preview,
)


def make_invocation() -> ScriptTemplateInvocation:
    return ScriptTemplateInvocation(
        image_ref="registry.internal/aegis/shell-runner@sha256:abc123",
        entrypoint="/bin/sh",
        argv=["-lc", "echo hello"],
    )


def test_default_docker_command_includes_sandbox_baseline() -> None:
    command = build_docker_run_command(make_invocation(), DockerSandboxPolicy())

    assert command[:3] == ["docker", "run", "--rm"]
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--tmpfs" in command
    assert "/tmp:rw,nosuid,nodev,size=64m" in command
    assert "--user" in command
    assert "10000:10000" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt" in command
    assert "no-new-privileges=true" in command
    assert "--pids-limit=64" in command
    assert "--memory=256m" in command
    assert "--memory-swap=256m" in command
    assert "--cpus=0.5" in command
    assert "--ulimit" in command
    assert "nofile=256:256" in command
    assert "--privileged" not in command
    assert "/var/run/docker.sock" not in command


@pytest.mark.parametrize(
    "policy",
    [
        DockerSandboxPolicy(privileged=True),
        DockerSandboxPolicy(network_mode="host"),
        DockerSandboxPolicy(user="0:0"),
        DockerSandboxPolicy(cap_add=["NET_ADMIN"]),
        DockerSandboxPolicy(security_opt=[]),
        DockerSandboxPolicy(mounts=[DockerMount(source="/var/run/docker.sock", target="/sock")]),
        DockerSandboxPolicy(
            mounts=[
                DockerMount(
                    source="C:/Users/Administrator/.ssh",
                    target="/ssh",
                )
            ]
        ),
        DockerSandboxPolicy(resource_limits=DockerResourceLimits(memory="0", pids_limit=0)),
    ],
)
def test_dangerous_docker_policy_is_rejected(policy: DockerSandboxPolicy) -> None:
    with pytest.raises(DockerSandboxPolicyError):
        build_docker_run_command(make_invocation(), policy)


def test_allowed_mounts_are_read_only_and_inside_workspace() -> None:
    policy = DockerSandboxPolicy(
        mounts=[
            DockerMount(
                source="D:/projects/runtime/shell-runs/run-1/input",
                target="/workspace/input",
                readonly=True,
            )
        ]
    )

    command = build_docker_run_command(make_invocation(), policy)

    assert "--mount" in command
    assert (
        "type=bind,source=D:/projects/runtime/shell-runs/run-1/input,"
        "target=/workspace/input,readonly"
    ) in command


def test_secret_values_are_not_rendered_in_command_preview() -> None:
    invocation = ScriptTemplateInvocation(
        image_ref="registry.internal/aegis/shell-runner@sha256:abc123",
        entrypoint="/bin/sh",
        argv=["-lc", "curl -H 'Authorization: Bearer ${API_TOKEN}' https://internal.example"],
        secrets=[SecretReference(name="API_TOKEN", credential_ref="cred/project/api-token")],
    )

    preview = build_shell_command_preview(invocation)

    assert "cred/project/api-token" in preview
    assert "Bearer ${API_TOKEN}" not in preview
    assert "API_TOKEN" not in preview
