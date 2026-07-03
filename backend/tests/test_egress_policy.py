from collections.abc import Callable
from ipaddress import IPv4Address, IPv6Address, ip_address

import pytest
from backend.app.security.egress_policy import (
    EgressPolicy,
    EgressPolicyViolation,
    normalize_allowed_hosts,
    validate_egress_url,
)

IPAddress = IPv4Address | IPv6Address


def resolve_to(*addresses: str) -> Callable[[str, int], list[IPAddress]]:
    return lambda _host, _port: [ip_address(address) for address in addresses]


def test_egress_policy_normalizes_public_https_url_and_strips_fragment() -> None:
    target = validate_egress_url(
        "https://Example.COM:443/mcp?cursor=1#secret-fragment",
        resolver=resolve_to("93.184.216.34"),
    )

    assert target.normalized_url == "https://example.com/mcp?cursor=1"
    assert target.hostname == "example.com"
    assert target.port == 443
    assert [str(address) for address in target.resolved_addresses] == ["93.184.216.34"]


@pytest.mark.parametrize(
    ("url", "reason_code"),
    [
        ("http://example.com/mcp", "plain_http_not_allowed"),
        ("https://user:pass@example.com/mcp", "url_credentials_not_allowed"),
        ("ftp://example.com/mcp", "scheme_not_allowed"),
        ("https://127.0.0.1/mcp", "unsafe_ip_address"),
        ("https://10.1.2.3/mcp", "unsafe_ip_address"),
        ("https://169.254.169.254/latest/meta-data", "unsafe_ip_address"),
        ("https://[::1]/mcp", "unsafe_ip_address"),
    ],
)
def test_egress_policy_rejects_unsafe_targets(url: str, reason_code: str) -> None:
    with pytest.raises(EgressPolicyViolation) as exc_info:
        validate_egress_url(url)

    assert exc_info.value.reason_code == reason_code
    assert "pass" not in exc_info.value.public_message


def test_egress_policy_rejects_dns_rebinding_when_any_answer_is_private() -> None:
    with pytest.raises(EgressPolicyViolation) as exc_info:
        validate_egress_url(
            "https://mcp.example.com/mcp",
            resolver=resolve_to("93.184.216.34", "10.0.0.5"),
        )

    assert exc_info.value.reason_code == "unsafe_ip_address"


def test_egress_policy_requires_environment_allowlist_when_configured() -> None:
    with pytest.raises(EgressPolicyViolation) as exc_info:
        validate_egress_url(
            "https://other.example.com/mcp",
            allowed_hosts=["mcp.example.com", "*.trusted.example"],
            resolver=resolve_to("93.184.216.34"),
        )

    assert exc_info.value.reason_code == "host_not_allowlisted"

    assert (
        validate_egress_url(
            "https://ops.trusted.example/mcp",
            allowed_hosts=["mcp.example.com", "*.trusted.example"],
            resolver=resolve_to("93.184.216.34"),
        ).hostname
        == "ops.trusted.example"
    )


def test_egress_policy_can_explicitly_allow_local_final_acceptance_server() -> None:
    policy = EgressPolicy(allow_plain_http=True, allow_loopback=True)

    target = validate_egress_url("http://127.0.0.1:8765/mcp", policy=policy)

    assert target.normalized_url == "http://127.0.0.1:8765/mcp"
    assert target.port == 8765


def test_egress_policy_blocks_metadata_even_when_link_local_is_allowed() -> None:
    policy = EgressPolicy(allow_link_local=True)

    with pytest.raises(EgressPolicyViolation) as exc_info:
        validate_egress_url("https://169.254.169.254/latest/meta-data", policy=policy)

    assert exc_info.value.reason_code == "unsafe_ip_address"


def test_normalize_allowed_hosts_rejects_invalid_patterns() -> None:
    assert normalize_allowed_hosts([" MCP.Example.com ", "*.Trusted.Example"]) == [
        "mcp.example.com",
        "*.trusted.example",
    ]
    with pytest.raises(EgressPolicyViolation) as exc_info:
        normalize_allowed_hosts(["https://example.com"])

    assert exc_info.value.reason_code == "invalid_allowlist_host"
