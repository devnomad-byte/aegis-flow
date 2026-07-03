import shutil
import subprocess

import pytest
from backend.app.security.egress_proxy_verifier import DockerEgressProxyVerifier

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_docker,
]


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


def test_real_egress_proxy_enforces_network_and_allowlist() -> None:
    require_docker()

    report = DockerEgressProxyVerifier(
        image_ref="capievo/runtime-sandbox-base:latest",
        allowed_hosts=["allowed.internal"],
        allowed_ports=[8080],
    ).run()

    assert report.allowed_via_proxy.exit_code == 0
    assert "target=ok" in report.allowed_via_proxy.stdout
    assert report.mcp_tools_list_via_proxy.exit_code == 0
    assert '"tools"' in report.mcp_tools_list_via_proxy.stdout
    assert report.direct_without_proxy.exit_code != 0
    assert report.denied_host.exit_code == 0
    assert "host_not_allowlisted" in report.denied_host.stdout
    assert report.denied_port.exit_code == 0
    assert "port_not_allowlisted" in report.denied_port.stdout
    assert report.redirect_denied.exit_code == 0
    assert "redirect_denied" in report.redirect_denied.stdout
    assert report.proxy_unavailable.exit_code != 0

    reasons = {event.reason for event in report.audit_events}
    assert {
        "allowed",
        "host_not_allowlisted",
        "port_not_allowlisted",
        "redirect_denied",
    }.issubset(reasons)
    assert all(event.target_url == "" for event in report.audit_events)
