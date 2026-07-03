from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import yaml

from backend.app.security.egress_policy import normalize_allowed_hosts

ENVOY_HTTP_CONNECTION_MANAGER_TYPE = (
    "type.googleapis.com/envoy.extensions.filters.network."
    "http_connection_manager.v3.HttpConnectionManager"
)
ENVOY_LUA_FILTER_TYPE = "type.googleapis.com/envoy.extensions.filters.http.lua.v3.Lua"
ENVOY_DYNAMIC_FORWARD_PROXY_FILTER_TYPE = (
    "type.googleapis.com/envoy.extensions.filters.http.dynamic_forward_proxy.v3.FilterConfig"
)
ENVOY_ROUTER_FILTER_TYPE = "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"
ENVOY_DYNAMIC_FORWARD_PROXY_CLUSTER_TYPE = (
    "type.googleapis.com/envoy.extensions.clusters.dynamic_forward_proxy.v3.ClusterConfig"
)
ENVOY_DYNAMIC_FORWARD_PROXY_CLUSTER = "dynamic_forward_proxy_cluster"
ENVOY_DNS_CACHE_CONFIG = "dynamic_forward_proxy_cache_config"
SQUID_UNSAFE_DST_RANGES = " ".join(
    [
        "10.0.0.0/8",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "224.0.0.0/4",
        "240.0.0.0/4",
    ]
)


@dataclass(frozen=True)
class EgressProxyDeploymentProfile:
    kind: str
    image_ref: str
    files: dict[str, str]

    def write_to_directory(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for relative_path, content in self.files.items():
            target = directory / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")


def build_envoy_profile(
    *,
    allowed_hosts: list[str],
    allowed_ports: list[int],
    image_ref: str = "envoyproxy/envoy:v1.35-latest",
) -> EgressProxyDeploymentProfile:
    normalized_hosts = _normalize_hosts(allowed_hosts)
    normalized_ports = _normalize_ports(allowed_ports)
    files = {
        "envoy.yaml": _build_envoy_bootstrap(),
        "policy.lua": _build_envoy_policy_lua(
            allowed_hosts=normalized_hosts,
            allowed_ports=normalized_ports,
        ),
        "docker-compose.yml": _build_envoy_compose(image_ref=image_ref),
    }
    return EgressProxyDeploymentProfile(kind="envoy", image_ref=image_ref, files=files)


def build_squid_profile(
    *,
    allowed_hosts: list[str],
    allowed_ports: list[int],
    image_ref: str = "ubuntu/squid:6.6-24.04_beta",
) -> EgressProxyDeploymentProfile:
    normalized_hosts = _normalize_hosts(allowed_hosts)
    normalized_ports = _normalize_ports(allowed_ports)
    host_acl = " ".join(normalized_hosts)
    port_acl = " ".join(str(port) for port in normalized_ports)
    config = (
        dedent(
            f"""
        http_port 8888
        acl aegis_allowed_hosts dstdomain {host_acl}
        acl aegis_allowed_ports port {port_acl}
        acl aegis_unsafe_dst dst {SQUID_UNSAFE_DST_RANGES}
        http_access deny aegis_unsafe_dst
        http_access allow aegis_allowed_hosts aegis_allowed_ports
        http_access deny all
        logformat aegis_audit %ts.%03tu %>Hs %rm aegis_redacted_url %<st
        access_log stdio:/var/log/squid/access.log aegis_audit
        via off
        forwarded_for delete
        reply_header_access Location deny all
        request_header_access Authorization deny all
        request_header_access Cookie deny all
        """
        ).strip()
        + "\n"
    )
    compose = _build_squid_compose(image_ref=image_ref)
    return EgressProxyDeploymentProfile(
        kind="squid",
        image_ref=image_ref,
        files={"squid.conf": config, "docker-compose.yml": compose},
    )


def _build_envoy_bootstrap() -> str:
    bootstrap = {
        "admin": {
            "address": {
                "socket_address": {
                    "address": "127.0.0.1",
                    "port_value": 9901,
                }
            }
        },
        "static_resources": {
            "listeners": [
                {
                    "name": "aegis_egress_listener",
                    "address": {
                        "socket_address": {
                            "address": "0.0.0.0",
                            "port_value": 8888,
                        }
                    },
                    "filter_chains": [
                        {
                            "filters": [
                                {
                                    "name": "envoy.filters.network.http_connection_manager",
                                    "typed_config": {
                                        "@type": ENVOY_HTTP_CONNECTION_MANAGER_TYPE,
                                        "stat_prefix": "aegis_egress",
                                        "codec_type": "AUTO",
                                        "route_config": {
                                            "name": "aegis_egress_route",
                                            "virtual_hosts": [
                                                {
                                                    "name": "dynamic_forward_proxy",
                                                    "domains": ["*"],
                                                    "routes": [
                                                        {
                                                            "match": {"prefix": "/"},
                                                            "route": {
                                                                "cluster": (
                                                                    ENVOY_DYNAMIC_FORWARD_PROXY_CLUSTER
                                                                )
                                                            },
                                                        }
                                                    ],
                                                }
                                            ],
                                        },
                                        "http_filters": [
                                            {
                                                "name": "envoy.filters.http.lua",
                                                "typed_config": {
                                                    "@type": ENVOY_LUA_FILTER_TYPE,
                                                    "default_source_code": {
                                                        "filename": "/etc/envoy/policy.lua"
                                                    },
                                                },
                                            },
                                            {
                                                "name": "envoy.filters.http.dynamic_forward_proxy",
                                                "typed_config": {
                                                    "@type": (
                                                        ENVOY_DYNAMIC_FORWARD_PROXY_FILTER_TYPE
                                                    ),
                                                    "dns_cache_config": _envoy_dns_cache_config(),
                                                },
                                            },
                                            {
                                                "name": "envoy.filters.http.router",
                                                "typed_config": {"@type": ENVOY_ROUTER_FILTER_TYPE},
                                            },
                                        ],
                                    },
                                }
                            ]
                        }
                    ],
                }
            ],
            "clusters": [
                {
                    "name": ENVOY_DYNAMIC_FORWARD_PROXY_CLUSTER,
                    "lb_policy": "CLUSTER_PROVIDED",
                    "cluster_type": {
                        "name": "envoy.clusters.dynamic_forward_proxy",
                        "typed_config": {
                            "@type": ENVOY_DYNAMIC_FORWARD_PROXY_CLUSTER_TYPE,
                            "dns_cache_config": _envoy_dns_cache_config(),
                        },
                    },
                }
            ],
        },
    }
    return yaml.safe_dump(bootstrap, sort_keys=False)


def _build_envoy_policy_lua(*, allowed_hosts: list[str], allowed_ports: list[int]) -> str:
    exact_hosts = [host for host in allowed_hosts if not host.startswith("*.")]
    wildcard_hosts = [host[2:] for host in allowed_hosts if host.startswith("*.")]
    exact_host_entries = "\n".join(f'  ["{host}"] = true,' for host in exact_hosts)
    wildcard_host_entries = "\n".join(f'  ["{host}"] = true,' for host in wildcard_hosts)
    port_entries = "\n".join(f"  [{port}] = true," for port in allowed_ports)
    return (
        dedent(
            f"""
        local exact_hosts = {{
        {exact_host_entries}
        }}

        local wildcard_hosts = {{
        {wildcard_host_entries}
        }}

        local allowed_ports = {{
        {port_entries}
        }}

        local function json_escape(value)
          return string.gsub(value or "", '"', '\\"')
        end

        local function host_matches(host)
          if exact_hosts[host] == true then
            return true
          end
          for suffix, _ in pairs(wildcard_hosts) do
            local dotted_suffix = "." .. suffix
            if host ~= suffix and string.sub(host, -string.len(dotted_suffix)) == dotted_suffix then
              return true
            end
          end
          return false
        end

        local function audit(handle, reason, host, port)
          local method = json_escape(handle:headers():get(":method") or "")
          local message = '{{"reason":"' .. json_escape(reason) ..
            '","target_host":"' .. json_escape(host) ..
            '","target_port":' .. tostring(port) ..
            ',"method":"' .. method .. '"}}'
          handle:logInfo(message)
        end

        local function deny(handle, status, reason, host, port)
          audit(handle, reason, host, port)
          local headers = {{[":status"] = tostring(status), ["content-type"] = "text/plain"}}
          handle:respond(headers, reason)
        end

        function envoy_on_request(handle)
          local authority = handle:headers():get(":authority") or ""
          local host = string.lower(string.gsub(authority, ":.*$", ""))
          local port = tonumber(string.match(authority, ":(%d+)$") or "80")
          if host_matches(host) ~= true then
            return deny(handle, 403, "host_not_allowlisted", host, port)
          end
          if next(allowed_ports) ~= nil and allowed_ports[port] ~= true then
            return deny(handle, 403, "port_not_allowlisted", host, port)
          end
          handle:streamInfo():dynamicMetadata():set("envoy.filters.http.lua", "target_host", host)
          handle:streamInfo():dynamicMetadata():set("envoy.filters.http.lua", "target_port", port)
          audit(handle, "allowed", host, port)
        end

        function envoy_on_response(handle)
          local status = tonumber(handle:headers():get(":status") or "0")
          local location = handle:headers():get("location")
          if status >= 300 and status < 400 and location ~= nil then
            local metadata = handle:streamInfo():dynamicMetadata():get("envoy.filters.http.lua")
            local host = metadata["target_host"] or ""
            local port = metadata["target_port"] or 0
            handle:headers():replace(":status", "502")
            handle:headers():replace("content-type", "text/plain")
            handle:headers():remove("location")
            handle:body():setBytes("redirect_denied")
            audit(handle, "redirect_denied", host, port)
          end
        end
        """
        ).strip()
        + "\n"
    )


def _build_envoy_compose(*, image_ref: str) -> str:
    compose = {
        "services": {
            "aegis-egress-envoy": {
                "image": image_ref,
                "command": ["envoy", "-c", "/etc/envoy/envoy.yaml"],
                "networks": ["aegis-egress", "aegis-upstream"],
                "volumes": [
                    "./envoy.yaml:/etc/envoy/envoy.yaml:ro",
                    "./policy.lua:/etc/envoy/policy.lua:ro",
                ],
            }
        },
        "networks": {
            "aegis-egress": {"name": "aegis-egress-dev"},
            "aegis-upstream": {"name": "aegis-upstream-dev"},
        },
    }
    return yaml.safe_dump(compose, sort_keys=False)


def _build_squid_compose(*, image_ref: str) -> str:
    compose = {
        "services": {
            "aegis-egress-squid": {
                "image": image_ref,
                "networks": ["aegis-egress", "aegis-upstream"],
                "volumes": ["./squid.conf:/etc/squid/squid.conf:ro"],
            }
        },
        "networks": {
            "aegis-egress": {"name": "aegis-egress-dev"},
            "aegis-upstream": {"name": "aegis-upstream-dev"},
        },
    }
    return yaml.safe_dump(compose, sort_keys=False)


def _normalize_hosts(hosts: list[str]) -> list[str]:
    return normalize_allowed_hosts(hosts)


def _normalize_ports(ports: list[int]) -> list[int]:
    return sorted({int(port) for port in ports})


def _envoy_dns_cache_config() -> dict[str, object]:
    return {
        "name": ENVOY_DNS_CACHE_CONFIG,
        "dns_lookup_family": "V4_ONLY",
        "dns_min_refresh_rate": "60s",
        "host_ttl": "300s",
    }
