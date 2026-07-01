import shutil
import subprocess

import pytest
from backend.app.execution.shell_runner import (
    DockerSandboxPolicy,
    ScriptTemplateInvocation,
    build_docker_run_command,
)

pytestmark = pytest.mark.integration

DOCKER_IMAGE = "redis:7-alpine"


def require_docker() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is not installed")

    result = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        pytest.skip("Docker daemon is not available")


def run_sandboxed_shell(script: str, *, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    require_docker()
    command = build_docker_run_command(
        ScriptTemplateInvocation(
            image_ref=DOCKER_IMAGE,
            entrypoint="/bin/sh",
            argv=["-lc", script],
        ),
        DockerSandboxPolicy(),
    )
    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )


def test_sandbox_runs_as_non_root_user() -> None:
    result = run_sandboxed_shell("id -u")

    assert result.returncode == 0
    assert result.stdout.strip() == "10000"


def test_sandbox_root_filesystem_is_read_only_but_tmp_is_writable() -> None:
    result = run_sandboxed_shell(
        "touch /blocked 2>/tmp/root.err; root_status=$?; "
        "touch /tmp/allowed; tmp_status=$?; "
        "echo root=$root_status tmp=$tmp_status"
    )

    assert result.returncode == 0
    assert "root=1 tmp=0" in result.stdout


def test_sandbox_has_no_default_network_access() -> None:
    result = run_sandboxed_shell(
        "wget -T 1 -q -O - http://1.1.1.1 >/tmp/net.out 2>&1 || echo network=blocked"
    )

    assert result.returncode == 0
    assert "network=blocked" in result.stdout


def test_sandbox_does_not_mount_docker_socket() -> None:
    result = run_sandboxed_shell("test ! -S /var/run/docker.sock && echo docker_socket=absent")

    assert result.returncode == 0
    assert "docker_socket=absent" in result.stdout
