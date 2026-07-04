from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any

import yaml

from backend.app.security.egress_proxy_profile import build_envoy_profile

KUBERNETES_UNSAFE_CIDRS = [
    "10.0.0.0/8",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "100.64.0.0/10",
    "224.0.0.0/4",
    "240.0.0.0/4",
]


@dataclass(frozen=True)
class EgressProxyKubernetesProfile:
    kind: str
    namespace: str
    release_name: str
    image_ref: str
    files: dict[str, str]

    def write_to_directory(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for relative_path, content in self.files.items():
            target = directory / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")


def build_egress_proxy_kubernetes_profile(
    *,
    project_ref: str,
    namespace: str,
    allowed_hosts: list[str],
    allowed_ports: list[int],
    release_name: str = "aegis-egress-proxy",
    image_ref: str = "envoyproxy/envoy:v1.35-latest",
    replicas: int = 2,
    secret_name: str = "aegis-egress-proxy-secrets",
) -> EgressProxyKubernetesProfile:
    envoy_profile = build_envoy_profile(
        allowed_hosts=allowed_hosts,
        allowed_ports=allowed_ports,
        image_ref=image_ref,
    )
    envoy_bootstrap = yaml.safe_load(envoy_profile.files["envoy.yaml"])
    envoy_bootstrap["admin"]["address"]["socket_address"]["address"] = "0.0.0.0"
    envoy_yaml = yaml.safe_dump(envoy_bootstrap, sort_keys=False)
    policy_lua = envoy_profile.files["policy.lua"]
    normalized_ports = sorted({int(port) for port in allowed_ports})

    manifest = yaml.safe_dump_all(
        _build_manifest_documents(
            project_ref=project_ref,
            namespace=namespace,
            release_name=release_name,
            image_ref=image_ref,
            replicas=replicas,
            secret_name=secret_name,
            envoy_yaml=envoy_yaml,
            policy_lua=policy_lua,
            allowed_ports=normalized_ports,
        ),
        sort_keys=False,
        explicit_start=True,
    )
    files = {
        "manifests/aegis-egress-proxy.yaml": manifest,
        "helm/aegis-egress-proxy/Chart.yaml": _build_chart_yaml(),
        "helm/aegis-egress-proxy/values.yaml": _build_values_yaml(
            project_ref=project_ref,
            namespace=namespace,
            image_ref=image_ref,
            replicas=replicas,
            secret_name=secret_name,
            allowed_hosts=allowed_hosts,
            allowed_ports=normalized_ports,
        ),
        "helm/aegis-egress-proxy/templates/_helpers.tpl": _build_helpers_template(),
        "helm/aegis-egress-proxy/templates/namespace.yaml": _build_namespace_template(),
        "helm/aegis-egress-proxy/templates/serviceaccount.yaml": _build_service_account_template(),
        "helm/aegis-egress-proxy/templates/configmap.yaml": _build_config_map_template(),
        "helm/aegis-egress-proxy/templates/deployment.yaml": _build_deployment_template(),
        "helm/aegis-egress-proxy/templates/service.yaml": _build_service_template(),
        "helm/aegis-egress-proxy/templates/networkpolicy.yaml": _build_network_policy_template(),
        "helm/aegis-egress-proxy/templates/servicemonitor.yaml": _build_service_monitor_template(),
    }
    return EgressProxyKubernetesProfile(
        kind="kubernetes-envoy",
        namespace=namespace,
        release_name=release_name,
        image_ref=image_ref,
        files=files,
    )


def _build_manifest_documents(
    *,
    project_ref: str,
    namespace: str,
    release_name: str,
    image_ref: str,
    replicas: int,
    secret_name: str,
    envoy_yaml: str,
    policy_lua: str,
    allowed_ports: list[int],
) -> list[dict[str, Any]]:
    labels = _common_labels(project_ref=project_ref, release_name=release_name)
    selector_labels = _selector_labels(project_ref=project_ref, release_name=release_name)
    client_labels = {
        "aegis.flow/egress-client": "true",
        "aegis.flow/project": project_ref,
    }

    return [
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": namespace,
                "labels": {
                    "aegis.flow/project": project_ref,
                    "aegis.flow/egress-namespace": "true",
                },
            },
        },
        {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {"name": release_name, "namespace": namespace, "labels": labels},
            "automountServiceAccountToken": False,
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": f"{release_name}-config",
                "namespace": namespace,
                "labels": labels,
            },
            "data": {
                "envoy.yaml": envoy_yaml,
                "policy.lua": policy_lua,
            },
        },
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": release_name, "namespace": namespace, "labels": labels},
            "spec": {
                "replicas": replicas,
                "strategy": {
                    "type": "RollingUpdate",
                    "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1},
                },
                "selector": {"matchLabels": selector_labels},
                "template": {
                    "metadata": {"labels": {**labels, **selector_labels}},
                    "spec": {
                        "serviceAccountName": release_name,
                        "automountServiceAccountToken": False,
                        "securityContext": {
                            "runAsNonRoot": True,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "containers": [
                            {
                                "name": "envoy",
                                "image": image_ref,
                                "imagePullPolicy": "IfNotPresent",
                                "command": ["envoy", "-c", "/etc/envoy/envoy.yaml"],
                                "ports": [
                                    {"name": "proxy", "containerPort": 8888, "protocol": "TCP"},
                                    {
                                        "name": "admin-metrics",
                                        "containerPort": 9901,
                                        "protocol": "TCP",
                                    },
                                ],
                                "env": [
                                    {
                                        "name": "AEGIS_EGRESS_AUDIT_SHARED_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": secret_name,
                                                "key": "audit-shared-key",
                                                "optional": True,
                                            }
                                        },
                                    }
                                ],
                                "readinessProbe": {
                                    "httpGet": {"path": "/ready", "port": "admin-metrics"},
                                    "initialDelaySeconds": 3,
                                    "periodSeconds": 10,
                                },
                                "livenessProbe": {
                                    "httpGet": {"path": "/ready", "port": "admin-metrics"},
                                    "initialDelaySeconds": 10,
                                    "periodSeconds": 20,
                                },
                                "resources": {
                                    "requests": {"cpu": "100m", "memory": "128Mi"},
                                    "limits": {"cpu": "500m", "memory": "512Mi"},
                                },
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "readOnlyRootFilesystem": True,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                                "volumeMounts": [
                                    {
                                        "name": "envoy-config",
                                        "mountPath": "/etc/envoy/envoy.yaml",
                                        "subPath": "envoy.yaml",
                                        "readOnly": True,
                                    },
                                    {
                                        "name": "envoy-config",
                                        "mountPath": "/etc/envoy/policy.lua",
                                        "subPath": "policy.lua",
                                        "readOnly": True,
                                    },
                                ],
                            }
                        ],
                        "volumes": [
                            {
                                "name": "envoy-config",
                                "configMap": {"name": f"{release_name}-config"},
                            }
                        ],
                    },
                },
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": release_name,
                "namespace": namespace,
                "labels": labels,
                "annotations": {
                    "prometheus.io/scrape": "true",
                    "prometheus.io/path": "/stats/prometheus",
                    "prometheus.io/port": "9901",
                },
            },
            "spec": {
                "type": "ClusterIP",
                "selector": selector_labels,
                "ports": [
                    {"name": "proxy", "port": 8888, "targetPort": "proxy", "protocol": "TCP"},
                    {
                        "name": "admin-metrics",
                        "port": 9901,
                        "targetPort": "admin-metrics",
                        "protocol": "TCP",
                    },
                ],
            },
        },
        _client_egress_policy(
            namespace=namespace,
            release_name=release_name,
            client_labels=client_labels,
        ),
        _proxy_ingress_policy(
            namespace=namespace,
            release_name=release_name,
            labels=labels,
            selector_labels=selector_labels,
            client_labels=client_labels,
        ),
        _proxy_egress_policy(
            namespace=namespace,
            release_name=release_name,
            labels=labels,
            selector_labels=selector_labels,
            allowed_ports=allowed_ports,
        ),
    ]


def _client_egress_policy(
    *,
    namespace: str,
    release_name: str,
    client_labels: dict[str, str],
) -> dict[str, Any]:
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": "aegis-egress-client-egress",
            "namespace": namespace,
        },
        "spec": {
            "podSelector": {"matchLabels": client_labels},
            "policyTypes": ["Egress"],
            "egress": [
                {
                    "to": [
                        {"podSelector": {"matchLabels": {"app.kubernetes.io/name": release_name}}}
                    ],
                    "ports": [{"protocol": "TCP", "port": 8888}],
                },
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                            }
                        }
                    ],
                    "ports": [
                        {"protocol": "UDP", "port": 53},
                        {"protocol": "TCP", "port": 53},
                    ],
                },
            ],
        },
    }


def _proxy_ingress_policy(
    *,
    namespace: str,
    release_name: str,
    labels: dict[str, str],
    selector_labels: dict[str, str],
    client_labels: dict[str, str],
) -> dict[str, Any]:
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": "aegis-egress-proxy-ingress",
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "podSelector": {"matchLabels": selector_labels},
            "policyTypes": ["Ingress"],
            "ingress": [
                {
                    "from": [{"podSelector": {"matchLabels": client_labels}}],
                    "ports": [{"protocol": "TCP", "port": 8888}],
                },
                {
                    "from": [
                        {"namespaceSelector": {"matchLabels": {"aegis.flow/observability": "true"}}}
                    ],
                    "ports": [{"protocol": "TCP", "port": 9901}],
                },
            ],
        },
    }


def _proxy_egress_policy(
    *,
    namespace: str,
    release_name: str,
    labels: dict[str, str],
    selector_labels: dict[str, str],
    allowed_ports: list[int],
) -> dict[str, Any]:
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": "aegis-egress-proxy-egress",
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "podSelector": {"matchLabels": selector_labels},
            "policyTypes": ["Egress"],
            "egress": [
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                            }
                        }
                    ],
                    "ports": [
                        {"protocol": "UDP", "port": 53},
                        {"protocol": "TCP", "port": 53},
                    ],
                },
                {
                    "to": [
                        {
                            "ipBlock": {
                                "cidr": "0.0.0.0/0",
                                "except": KUBERNETES_UNSAFE_CIDRS,
                            }
                        }
                    ],
                    "ports": [{"protocol": "TCP", "port": port} for port in allowed_ports],
                },
            ],
        },
    }


def _common_labels(*, project_ref: str, release_name: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": release_name,
        "app.kubernetes.io/part-of": "aegis-flow",
        "app.kubernetes.io/component": "egress-proxy",
        "aegis.flow/project": project_ref,
    }


def _selector_labels(*, project_ref: str, release_name: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": release_name,
        "aegis.flow/project": project_ref,
    }


def _build_chart_yaml() -> str:
    return yaml.safe_dump(
        {
            "apiVersion": "v2",
            "name": "aegis-egress-proxy",
            "description": "AegisFlow governed Envoy egress proxy profile.",
            "type": "application",
            "version": "0.1.0",
            "appVersion": "1.35",
        },
        sort_keys=False,
    )


def _build_values_yaml(
    *,
    project_ref: str,
    namespace: str,
    image_ref: str,
    replicas: int,
    secret_name: str,
    allowed_hosts: list[str],
    allowed_ports: list[int],
) -> str:
    image_repository, image_tag = image_ref.rsplit(":", 1)
    values = {
        "projectRef": project_ref,
        "namespaceOverride": namespace,
        "replicaCount": replicas,
        "image": {
            "repository": image_repository,
            "tag": image_tag,
            "pullPolicy": "IfNotPresent",
        },
        "secretRef": {"name": secret_name, "auditSharedKey": "audit-shared-key"},
        "egressPolicy": {
            "allowedHosts": allowed_hosts,
            "allowedPorts": allowed_ports,
        },
        "service": {
            "type": "ClusterIP",
            "proxyPort": 8888,
            "adminMetricsPort": 9901,
            "annotations": {
                "prometheus.io/scrape": "true",
                "prometheus.io/path": "/stats/prometheus",
                "prometheus.io/port": "9901",
            },
        },
        "networkPolicy": {
            "enabled": True,
            "clientSelector": {"aegis.flow/egress-client": "true"},
            "observabilityNamespaceSelector": {"aegis.flow/observability": "true"},
            "dnsNamespaceSelector": {"kubernetes.io/metadata.name": "kube-system"},
            "unsafeCidrs": KUBERNETES_UNSAFE_CIDRS,
        },
        "serviceMonitor": {"enabled": False, "interval": "30s"},
        "failureDrills": {
            "commands": [
                "verify-client-direct-egress-denied",
                "verify-denied-host",
                "verify-denied-port",
                "verify-proxy-unavailable",
            ]
        },
        "resources": {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "500m", "memory": "512Mi"},
        },
    }
    return yaml.safe_dump(values, sort_keys=False)


def _build_helpers_template() -> str:
    return dedent(
        """
        {{- define "aegis-egress-proxy.name" -}}
        {{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
        {{- end -}}

        {{- define "aegis-egress-proxy.fullname" -}}
        {{- $name := include "aegis-egress-proxy.name" . -}}
        {{- default $name .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
        {{- end -}}

        {{- define "aegis-egress-proxy.labels" -}}
        app.kubernetes.io/name: {{ include "aegis-egress-proxy.name" . }}
        helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
        app.kubernetes.io/managed-by: {{ .Release.Service }}
        app.kubernetes.io/part-of: aegis-flow
        app.kubernetes.io/component: egress-proxy
        aegis.flow/project: {{ .Values.projectRef | quote }}
        {{- end -}}

        {{- define "aegis-egress-proxy.selectorLabels" -}}
        app.kubernetes.io/name: {{ include "aegis-egress-proxy.name" . }}
        aegis.flow/project: {{ .Values.projectRef | quote }}
        {{- end -}}
        """
    ).lstrip()


def _build_namespace_template() -> str:
    return dedent(
        """
        apiVersion: v1
        kind: Namespace
        metadata:
          name: {{ .Values.namespaceOverride | default .Release.Namespace }}
          labels:
            aegis.flow/project: {{ .Values.projectRef | quote }}
            aegis.flow/egress-namespace: "true"
        """
    ).lstrip()


def _build_service_account_template() -> str:
    return dedent(
        """
        apiVersion: v1
        kind: ServiceAccount
        metadata:
          name: {{ include "aegis-egress-proxy.fullname" . }}
          namespace: {{ .Values.namespaceOverride | default .Release.Namespace }}
          labels:
            {{- include "aegis-egress-proxy.labels" . | nindent 4 }}
        automountServiceAccountToken: false
        """
    ).lstrip()


def _build_config_map_template() -> str:
    return dedent(
        """
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: {{ include "aegis-egress-proxy.fullname" . }}-config
          namespace: {{ .Values.namespaceOverride | default .Release.Namespace }}
          labels:
            {{- include "aegis-egress-proxy.labels" . | nindent 4 }}
        data:
          envoy.yaml: |
            # Render from generated manifest for production rollout.
          policy.lua: |
            # Render from generated manifest for production rollout.
        """
    ).lstrip()


def _build_deployment_template() -> str:
    return dedent(
        """
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: {{ include "aegis-egress-proxy.fullname" . }}
          namespace: {{ .Values.namespaceOverride | default .Release.Namespace }}
          labels:
            {{- include "aegis-egress-proxy.labels" . | nindent 4 }}
        spec:
          replicas: {{ .Values.replicaCount }}
          strategy:
            type: RollingUpdate
            rollingUpdate:
              maxUnavailable: 0
              maxSurge: 1
          selector:
            matchLabels:
              {{- include "aegis-egress-proxy.selectorLabels" . | nindent 6 }}
          template:
            metadata:
              labels:
                {{- include "aegis-egress-proxy.labels" . | nindent 8 }}
                {{- include "aegis-egress-proxy.selectorLabels" . | nindent 8 }}
            spec:
              serviceAccountName: {{ include "aegis-egress-proxy.fullname" . }}
              automountServiceAccountToken: false
              securityContext:
                runAsNonRoot: true
                seccompProfile:
                  type: RuntimeDefault
              containers:
                - name: envoy
                  image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
                  imagePullPolicy: {{ .Values.image.pullPolicy }}
                  command: ["envoy", "-c", "/etc/envoy/envoy.yaml"]
                  ports:
                    - name: proxy
                      containerPort: 8888
                      protocol: TCP
                    - name: admin-metrics
                      containerPort: 9901
                      protocol: TCP
                  env:
                    - name: AEGIS_EGRESS_AUDIT_SHARED_KEY
                      valueFrom:
                        secretKeyRef:
                          name: {{ .Values.secretRef.name }}
                          key: {{ .Values.secretRef.auditSharedKey }}
                          optional: true
                  readinessProbe:
                    httpGet:
                      path: /ready
                      port: admin-metrics
                  livenessProbe:
                    httpGet:
                      path: /ready
                      port: admin-metrics
                  resources:
                    {{- toYaml .Values.resources | nindent 20 }}
                  securityContext:
                    allowPrivilegeEscalation: false
                    readOnlyRootFilesystem: true
                    capabilities:
                      drop: ["ALL"]
                  volumeMounts:
                    - name: envoy-config
                      mountPath: /etc/envoy/envoy.yaml
                      subPath: envoy.yaml
                      readOnly: true
                    - name: envoy-config
                      mountPath: /etc/envoy/policy.lua
                      subPath: policy.lua
                      readOnly: true
              volumes:
                - name: envoy-config
                  configMap:
                    name: {{ include "aegis-egress-proxy.fullname" . }}-config
        """
    ).lstrip()


def _build_service_template() -> str:
    return dedent(
        """
        apiVersion: v1
        kind: Service
        metadata:
          name: {{ include "aegis-egress-proxy.fullname" . }}
          namespace: {{ .Values.namespaceOverride | default .Release.Namespace }}
          labels:
            {{- include "aegis-egress-proxy.labels" . | nindent 4 }}
          annotations:
            {{- toYaml .Values.service.annotations | nindent 4 }}
        spec:
          type: {{ .Values.service.type }}
          selector:
            {{- include "aegis-egress-proxy.selectorLabels" . | nindent 4 }}
          ports:
            - name: proxy
              port: {{ .Values.service.proxyPort }}
              targetPort: proxy
              protocol: TCP
            - name: admin-metrics
              port: {{ .Values.service.adminMetricsPort }}
              targetPort: admin-metrics
              protocol: TCP
        """
    ).lstrip()


def _build_network_policy_template() -> str:
    return dedent(
        """
        {{- if .Values.networkPolicy.enabled }}
        apiVersion: networking.k8s.io/v1
        kind: NetworkPolicy
        metadata:
          name: aegis-egress-proxy-egress
          namespace: {{ .Values.namespaceOverride | default .Release.Namespace }}
        spec:
          podSelector:
            matchLabels:
              {{- include "aegis-egress-proxy.selectorLabels" . | nindent 6 }}
          policyTypes: ["Egress"]
          egress:
            - to:
                - namespaceSelector:
                    matchLabels:
                      {{- toYaml .Values.networkPolicy.dnsNamespaceSelector | nindent 22 }}
              ports:
                - protocol: UDP
                  port: 53
                - protocol: TCP
                  port: 53
            - to:
                - ipBlock:
                    cidr: 0.0.0.0/0
                    except:
                      {{- toYaml .Values.networkPolicy.unsafeCidrs | nindent 22 }}
              ports:
                {{- range .Values.egressPolicy.allowedPorts }}
                - protocol: TCP
                  port: {{ . }}
                {{- end }}
        {{- end }}
        """
    ).lstrip()


def _build_service_monitor_template() -> str:
    return dedent(
        """
        {{- if .Values.serviceMonitor.enabled }}
        apiVersion: monitoring.coreos.com/v1
        kind: ServiceMonitor
        metadata:
          name: {{ include "aegis-egress-proxy.fullname" . }}
          namespace: {{ .Values.namespaceOverride | default .Release.Namespace }}
          labels:
            {{- include "aegis-egress-proxy.labels" . | nindent 4 }}
        spec:
          selector:
            matchLabels:
              {{- include "aegis-egress-proxy.selectorLabels" . | nindent 6 }}
          endpoints:
            - port: admin-metrics
              path: /stats/prometheus
              interval: {{ .Values.serviceMonitor.interval }}
        {{- end }}
        """
    ).lstrip()
