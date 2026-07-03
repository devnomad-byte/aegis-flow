from ipaddress import ip_address

import pytest
from backend.app.security.egress_policy import EgressPolicy
from backend.app.security.egress_proxy import (
    EgressProxyMode,
    EgressProxyPolicy,
    EgressProxyPolicyViolation,
    build_egress_proxy_plan,
)
from backend.app.security.egress_proxy_verifier import parse_proxy_audit_events


def test_egress_proxy_plan_requires_allowed_target_port() -> None:
    policy = EgressProxyPolicy(
        allowed_hosts=["api.example.com"],
        allowed_ports=[443],
    )

    with pytest.raises(EgressProxyPolicyViolation) as exc_info:
        build_egress_proxy_plan(
            "https://api.example.com:8443/v1",
            proxy_policy=policy,
            egress_policy=EgressPolicy(resolver=lambda _host, _port: [ip_address("93.184.216.34")]),
        )

    assert exc_info.value.reason_code == "port_not_allowlisted"


def test_egress_proxy_plan_builds_sanitized_http_proxy_metadata() -> None:
    plan = build_egress_proxy_plan(
        "https://api.example.com:443/v1?token=secret#fragment",
        proxy_policy=EgressProxyPolicy(
            mode=EgressProxyMode.HTTP_PROXY,
            proxy_url="http://egress-proxy.internal:8080",
            allowed_hosts=["api.example.com"],
            allowed_ports=[443],
            dns_pinning_required=True,
        ),
        egress_policy=EgressPolicy(resolver=lambda _host, _port: [ip_address("93.184.216.34")]),
    )

    assert plan.mode == EgressProxyMode.HTTP_PROXY
    assert plan.target.normalized_url == "https://api.example.com/v1?token=secret"
    assert plan.httpx_proxy_url == "http://egress-proxy.internal:8080"
    assert plan.audit_metadata == {
        "egress_mode": "http_proxy",
        "target_host": "api.example.com",
        "target_port": 443,
        "proxy_host": "egress-proxy.internal",
        "proxy_port": 8080,
        "docker_network": "",
        "dns_pinning_required": True,
        "resolved_ip_count": 1,
    }
    assert "secret" not in str(plan.audit_metadata)


def test_egress_proxy_plan_rejects_proxy_credentials() -> None:
    with pytest.raises(EgressProxyPolicyViolation) as exc_info:
        build_egress_proxy_plan(
            "https://api.example.com/v1",
            proxy_policy=EgressProxyPolicy(
                mode=EgressProxyMode.HTTP_PROXY,
                proxy_url="http://user:pass@egress-proxy.internal:8080",
                allowed_hosts=["api.example.com"],
            ),
            egress_policy=EgressPolicy(resolver=lambda _host, _port: [ip_address("93.184.216.34")]),
        )

    assert exc_info.value.reason_code == "proxy_credentials_not_allowed"


def test_egress_proxy_plan_accepts_aegis_docker_network_only() -> None:
    plan = build_egress_proxy_plan(
        "https://api.example.com/v1",
        proxy_policy=EgressProxyPolicy(
            mode=EgressProxyMode.DOCKER_NETWORK,
            docker_network="aegis-egress-prod",
            allowed_hosts=["api.example.com"],
        ),
        egress_policy=EgressPolicy(resolver=lambda _host, _port: [ip_address("93.184.216.34")]),
    )

    assert plan.docker_network == "aegis-egress-prod"

    with pytest.raises(EgressProxyPolicyViolation) as exc_info:
        build_egress_proxy_plan(
            "https://api.example.com/v1",
            proxy_policy=EgressProxyPolicy(
                mode=EgressProxyMode.DOCKER_NETWORK,
                docker_network="bridge",
                allowed_hosts=["api.example.com"],
            ),
            egress_policy=EgressPolicy(resolver=lambda _host, _port: [ip_address("93.184.216.34")]),
        )

    assert exc_info.value.reason_code == "invalid_docker_network"


def test_egress_proxy_verifier_parses_sanitized_audit_events() -> None:
    events = parse_proxy_audit_events(
        "\n".join(
            [
                '{"reason":"allowed","target_host":"api.example.com","target_port":443}',
                "not-json",
                '{"reason":"host_not_allowlisted","target_host":"blocked.example.com","target_port":8443}',
            ]
        )
    )

    assert [event.reason for event in events] == ["allowed", "host_not_allowlisted"]
    assert [event.target_url for event in events] == ["", ""]
    assert "token" not in str(events).lower()
