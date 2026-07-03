import json
from pathlib import Path
from typing import Any

import yaml
from backend.app.security.egress_proxy_profile import (
    EgressProxyDeploymentProfile,
    build_envoy_profile,
    build_squid_profile,
)
from backend.app.security.egress_proxy_verifier import parse_proxy_audit_events

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_envoy_profile_contains_dynamic_forward_proxy_lua_policy_and_metrics() -> None:
    profile = build_envoy_profile(
        allowed_hosts=["Allowed.Internal", "api.example.com"],
        allowed_ports=[8080, 443],
    )

    bootstrap = yaml.safe_load(profile.files["envoy.yaml"])
    listener = bootstrap["static_resources"]["listeners"][0]
    http_filters = listener["filter_chains"][0]["filters"][0]["typed_config"]["http_filters"]
    filter_names = [filter_config["name"] for filter_config in http_filters]

    assert profile.kind == "envoy"
    assert profile.image_ref == "envoyproxy/envoy:v1.35-latest"
    assert "envoy.filters.http.lua" in filter_names
    assert "envoy.filters.http.dynamic_forward_proxy" in filter_names
    assert "envoy.filters.http.router" in filter_names
    assert "dynamic_forward_proxy_cluster" in profile.files["envoy.yaml"]
    assert "dynamic_forward_proxy_cache_config" in profile.files["envoy.yaml"]
    dns_cache_config = http_filters[1]["typed_config"]["dns_cache_config"]
    assert bootstrap["admin"]["address"]["socket_address"]["port_value"] == 9901
    assert bootstrap["admin"]["address"]["socket_address"]["address"] == "127.0.0.1"
    assert dns_cache_config["dns_min_refresh_rate"] == "60s"
    assert dns_cache_config["host_ttl"] == "300s"
    assert '["allowed.internal"] = true' in profile.files["policy.lua"]
    assert "[8080] = true" in profile.files["policy.lua"]
    assert "redirect_denied" in profile.files["policy.lua"]
    assert 'headers():remove("location")' in profile.files["policy.lua"]
    assert "password" not in profile.files["policy.lua"].lower()
    assert "token" not in profile.files["policy.lua"].lower()


def test_envoy_compose_profile_uses_aegis_network_and_mounts_generated_config() -> None:
    profile = build_envoy_profile(allowed_hosts=["allowed.internal"], allowed_ports=[8080])
    compose = yaml.safe_load(profile.files["docker-compose.yml"])

    service = compose["services"]["aegis-egress-envoy"]
    assert service["image"] == profile.image_ref
    assert "aegis-egress" in service["networks"]
    assert "aegis-upstream" in service["networks"]
    assert "8888:8888" not in service.get("ports", [])
    assert "9901:9901" not in service.get("ports", [])
    assert "./envoy.yaml:/etc/envoy/envoy.yaml:ro" in service["volumes"]
    assert "./policy.lua:/etc/envoy/policy.lua:ro" in service["volumes"]


def test_squid_profile_contains_host_port_acl_and_sanitized_logformat() -> None:
    profile = build_squid_profile(allowed_hosts=["allowed.internal"], allowed_ports=[8080])
    config = profile.files["squid.conf"]

    assert profile.kind == "squid"
    assert "acl aegis_allowed_hosts dstdomain allowed.internal" in config
    assert "acl aegis_allowed_ports port 8080" in config
    assert "http_access allow aegis_allowed_hosts aegis_allowed_ports" in config
    assert "acl aegis_unsafe_dst dst 10.0.0.0/8 127.0.0.0/8 169.254.0.0/16" in config
    assert "http_access deny aegis_unsafe_dst" in config
    assert "http_access deny all" in config
    assert "logformat aegis_audit" in config
    assert "aegis_redacted_url" in config
    assert "%ru" not in config
    assert "%>a" not in config
    assert "reply_header_access Location deny all" in config
    assert "request_header_access Authorization deny all" in config
    assert "request_header_access Cookie deny all" in config


def test_envoy_profile_matches_wildcard_hosts_with_platform_allowlist_semantics() -> None:
    profile = build_envoy_profile(allowed_hosts=["*.Trusted.Example"], allowed_ports=[443])
    policy = profile.files["policy.lua"]

    assert '["trusted.example"] = true' in policy
    assert "wildcard_hosts" in policy
    assert "host_matches" in policy


def test_profile_write_to_directory_creates_expected_files(tmp_path: Path) -> None:
    profile = EgressProxyDeploymentProfile(
        kind="envoy",
        image_ref="envoyproxy/envoy:v1.35-latest",
        files={
            "envoy.yaml": "static_resources: {}\n",
            "policy.lua": "-- policy\n",
        },
    )

    profile.write_to_directory(tmp_path)

    assert (tmp_path / "envoy.yaml").read_text(encoding="utf-8") == "static_resources: {}\n"
    assert (tmp_path / "policy.lua").read_text(encoding="utf-8") == "-- policy\n"


def test_checked_in_deploy_profiles_match_generated_defaults() -> None:
    envoy = build_envoy_profile(allowed_hosts=["allowed.internal"], allowed_ports=[8080])
    squid = build_squid_profile(allowed_hosts=["allowed.internal"], allowed_ports=[8080])

    for relative_path, content in envoy.files.items():
        assert (REPO_ROOT / "deploy" / "egress-proxy" / "envoy" / relative_path).read_text(
            encoding="utf-8"
        ) == content
    for relative_path, content in squid.files.items():
        assert (REPO_ROOT / "deploy" / "egress-proxy" / "squid" / relative_path).read_text(
            encoding="utf-8"
        ) == content


def test_envoy_json_audit_logs_parse_without_raw_url_or_secret() -> None:
    prefixed_log = (
        '[2026-07-04][info][lua] [source] script log: {"reason":"allowed",'
        '"target_host":"allowed.internal","target_port":8080,"method":"GET"}'
    )
    audit_log: dict[str, Any] = {
        "reason": "allowed",
        "target_host": "allowed.internal",
        "target_port": 8080,
        "method": "GET",
    }
    rejected_log: dict[str, Any] = {
        "reason": "host_not_allowlisted",
        "target_host": "blocked.internal",
        "target_port": 8080,
        "path": "/secret?token=raw",
    }
    events = parse_proxy_audit_events(
        "\n".join(
            [
                prefixed_log,
                json.dumps(audit_log, separators=(",", ":")),
                json.dumps(rejected_log, separators=(",", ":")),
            ]
        )
    )

    assert [event.reason for event in events] == [
        "allowed",
        "allowed",
        "host_not_allowlisted",
    ]
    assert all(event.target_url == "" for event in events)
    assert "raw" not in str(events)
