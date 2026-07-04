from pathlib import Path
from typing import Any

import yaml
from backend.app.security.egress_proxy_kubernetes_profile import (
    KUBERNETES_UNSAFE_CIDRS,
    build_egress_proxy_kubernetes_profile,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _manifest_documents(profile_files: dict[str, str]) -> list[dict[str, Any]]:
    return [
        document
        for document in yaml.safe_load_all(profile_files["manifests/aegis-egress-proxy.yaml"])
        if document
    ]


def _by_kind_name(documents: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(document["kind"], document["metadata"]["name"]): document for document in documents}


def test_kubernetes_envoy_profile_contains_secure_workload_objects() -> None:
    profile = build_egress_proxy_kubernetes_profile(
        project_ref="project-123",
        namespace="aegis-project-123",
        allowed_hosts=["Allowed.Internal", "*.Trusted.Example"],
        allowed_ports=[443, 8080],
    )
    documents = _manifest_documents(profile.files)
    objects = _by_kind_name(documents)

    assert profile.kind == "kubernetes-envoy"
    assert profile.namespace == "aegis-project-123"
    assert profile.release_name == "aegis-egress-proxy"
    assert ("Namespace", "aegis-project-123") in objects
    assert ("ServiceAccount", "aegis-egress-proxy") in objects
    assert ("ConfigMap", "aegis-egress-proxy-config") in objects
    assert ("Deployment", "aegis-egress-proxy") in objects
    assert ("Service", "aegis-egress-proxy") in objects

    service_account = objects[("ServiceAccount", "aegis-egress-proxy")]
    assert service_account["automountServiceAccountToken"] is False

    config_map = objects[("ConfigMap", "aegis-egress-proxy-config")]
    envoy_bootstrap = yaml.safe_load(config_map["data"]["envoy.yaml"])
    assert envoy_bootstrap["admin"]["address"]["socket_address"]["address"] == "0.0.0.0"
    assert '["allowed.internal"] = true' in config_map["data"]["policy.lua"]
    assert '["trusted.example"] = true' in config_map["data"]["policy.lua"]
    assert "[8080] = true" in config_map["data"]["policy.lua"]

    deployment = objects[("Deployment", "aegis-egress-proxy")]
    pod_spec = deployment["spec"]["template"]["spec"]
    container = pod_spec["containers"][0]
    assert deployment["spec"]["strategy"] == {
        "type": "RollingUpdate",
        "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1},
    }
    assert pod_spec["serviceAccountName"] == "aegis-egress-proxy"
    assert pod_spec["automountServiceAccountToken"] is False
    assert pod_spec["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert {
        "name": "envoy-config",
        "mountPath": "/etc/envoy/envoy.yaml",
        "subPath": "envoy.yaml",
        "readOnly": True,
    } in container["volumeMounts"]
    assert any(env["valueFrom"]["secretKeyRef"]["optional"] is True for env in container["env"])
    assert all("raw-token" not in str(document) for document in documents)

    service = objects[("Service", "aegis-egress-proxy")]
    assert service["spec"]["type"] == "ClusterIP"
    assert {port["name"] for port in service["spec"]["ports"]} == {"proxy", "admin-metrics"}
    assert service["metadata"]["annotations"] == {
        "prometheus.io/scrape": "true",
        "prometheus.io/path": "/stats/prometheus",
        "prometheus.io/port": "9901",
    }


def test_kubernetes_network_policies_enforce_project_and_proxy_boundaries() -> None:
    profile = build_egress_proxy_kubernetes_profile(
        project_ref="project-123",
        namespace="aegis-project-123",
        allowed_hosts=["allowed.internal"],
        allowed_ports=[443, 8080],
    )
    objects = _by_kind_name(_manifest_documents(profile.files))

    client_policy = objects[("NetworkPolicy", "aegis-egress-client-egress")]
    assert client_policy["spec"]["podSelector"]["matchLabels"] == {
        "aegis.flow/egress-client": "true",
        "aegis.flow/project": "project-123",
    }
    client_egress = client_policy["spec"]["egress"]
    assert client_egress[0]["to"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/name"] == (
        "aegis-egress-proxy"
    )
    assert client_egress[0]["ports"] == [{"protocol": "TCP", "port": 8888}]
    assert client_egress[1]["ports"] == [
        {"protocol": "UDP", "port": 53},
        {"protocol": "TCP", "port": 53},
    ]

    ingress_policy = objects[("NetworkPolicy", "aegis-egress-proxy-ingress")]
    ingress_rules = ingress_policy["spec"]["ingress"]
    assert ingress_rules[0]["from"][0]["podSelector"]["matchLabels"] == {
        "aegis.flow/egress-client": "true",
        "aegis.flow/project": "project-123",
    }
    assert ingress_rules[0]["ports"] == [{"protocol": "TCP", "port": 8888}]
    assert ingress_rules[1]["from"][0]["namespaceSelector"]["matchLabels"] == {
        "aegis.flow/observability": "true"
    }
    assert ingress_rules[1]["ports"] == [{"protocol": "TCP", "port": 9901}]

    proxy_egress_policy = objects[("NetworkPolicy", "aegis-egress-proxy-egress")]
    external_rule = proxy_egress_policy["spec"]["egress"][1]
    assert external_rule["to"] == [
        {
            "ipBlock": {
                "cidr": "0.0.0.0/0",
                "except": KUBERNETES_UNSAFE_CIDRS,
            }
        }
    ]
    assert external_rule["ports"] == [
        {"protocol": "TCP", "port": 443},
        {"protocol": "TCP", "port": 8080},
    ]


def test_helm_profile_contains_operator_ready_templates_and_values() -> None:
    profile = build_egress_proxy_kubernetes_profile(
        project_ref="project-123",
        namespace="aegis-project-123",
        allowed_hosts=["allowed.internal"],
        allowed_ports=[443],
    )

    chart = yaml.safe_load(profile.files["helm/aegis-egress-proxy/Chart.yaml"])
    values = yaml.safe_load(profile.files["helm/aegis-egress-proxy/values.yaml"])

    assert chart["apiVersion"] == "v2"
    assert chart["name"] == "aegis-egress-proxy"
    assert values["projectRef"] == "project-123"
    assert values["namespaceOverride"] == "aegis-project-123"
    assert values["networkPolicy"]["enabled"] is True
    assert values["serviceMonitor"]["enabled"] is False
    assert values["failureDrills"]["commands"] == [
        "verify-client-direct-egress-denied",
        "verify-denied-host",
        "verify-denied-port",
        "verify-proxy-unavailable",
    ]

    helpers = profile.files["helm/aegis-egress-proxy/templates/_helpers.tpl"]
    network_policy_template = profile.files["helm/aegis-egress-proxy/templates/networkpolicy.yaml"]
    service_monitor_template = profile.files[
        "helm/aegis-egress-proxy/templates/servicemonitor.yaml"
    ]
    assert "app.kubernetes.io/name" in helpers
    assert "helm.sh/chart" in helpers
    assert "app.kubernetes.io/managed-by" in helpers
    assert "namespaceSelector" in network_policy_template
    assert "ipBlock" in network_policy_template
    assert ".Values.networkPolicy.unsafeCidrs" in network_policy_template
    assert "kind: ServiceMonitor" in service_monitor_template
    assert "/stats/prometheus" in service_monitor_template


def test_checked_in_kubernetes_profile_matches_generated_defaults() -> None:
    profile = build_egress_proxy_kubernetes_profile(
        project_ref="project-123",
        namespace="aegis-project-123",
        allowed_hosts=["allowed.internal"],
        allowed_ports=[8080],
    )

    for relative_path, content in profile.files.items():
        checked_in = REPO_ROOT / "deploy" / "egress-proxy" / "kubernetes" / relative_path
        assert checked_in.read_text(encoding="utf-8") == content
