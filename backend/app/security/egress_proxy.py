from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlsplit

from backend.app.security.egress_policy import (
    EgressPolicy,
    ValidatedEgressTarget,
    normalize_allowed_hosts,
    validate_egress_url,
)


class EgressProxyMode(StrEnum):
    DIRECT = "direct"
    HTTP_PROXY = "http_proxy"
    DOCKER_NETWORK = "docker_network"


class EgressProxyPolicyViolation(ValueError):
    def __init__(self, reason_code: str, public_message: str) -> None:
        super().__init__(f"{public_message} ({reason_code})")
        self.reason_code = reason_code
        self.public_message = f"{public_message} ({reason_code})"


@dataclass(frozen=True)
class EgressProxyPolicy:
    mode: EgressProxyMode = EgressProxyMode.DIRECT
    proxy_url: str = ""
    docker_network: str = ""
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_ports: list[int] = field(default_factory=list)
    dns_pinning_required: bool = False


@dataclass(frozen=True)
class EgressProxyPlan:
    mode: EgressProxyMode
    target: ValidatedEgressTarget
    httpx_proxy_url: str
    docker_network: str
    dns_pinning_required: bool
    audit_metadata: dict[str, object]


def build_egress_proxy_plan(
    target_url: str,
    *,
    proxy_policy: EgressProxyPolicy | None = None,
    egress_policy: EgressPolicy | None = None,
) -> EgressProxyPlan:
    resolved_policy = proxy_policy or EgressProxyPolicy()
    allowed_hosts = normalize_allowed_hosts(resolved_policy.allowed_hosts)
    target = validate_egress_url(
        target_url,
        policy=egress_policy,
        allowed_hosts=allowed_hosts,
    )
    _validate_target_port(target.port, resolved_policy.allowed_ports)
    proxy_url = ""
    docker_network = ""

    if resolved_policy.mode == EgressProxyMode.HTTP_PROXY:
        proxy_url = _validate_proxy_url(resolved_policy.proxy_url)
    elif resolved_policy.mode == EgressProxyMode.DOCKER_NETWORK:
        docker_network = _validate_docker_network(resolved_policy.docker_network)
    elif resolved_policy.mode != EgressProxyMode.DIRECT:
        raise _violation("invalid_proxy_mode", "Egress proxy mode is invalid")

    proxy_host, proxy_port = _proxy_metadata(proxy_url)
    return EgressProxyPlan(
        mode=resolved_policy.mode,
        target=target,
        httpx_proxy_url=proxy_url,
        docker_network=docker_network,
        dns_pinning_required=resolved_policy.dns_pinning_required,
        audit_metadata={
            "egress_mode": resolved_policy.mode.value,
            "target_host": target.hostname,
            "target_port": target.port,
            "proxy_host": proxy_host,
            "proxy_port": proxy_port,
            "docker_network": docker_network,
            "dns_pinning_required": resolved_policy.dns_pinning_required,
            "resolved_ip_count": len(target.resolved_addresses),
        },
    )


def _validate_target_port(port: int, allowed_ports: list[int]) -> None:
    if allowed_ports and port not in allowed_ports:
        raise _violation("port_not_allowlisted", "Egress target port is not allowed")


def _validate_proxy_url(proxy_url: str) -> str:
    if not proxy_url:
        raise _violation("proxy_url_required", "Egress proxy URL is required")
    parts = urlsplit(proxy_url)
    if parts.scheme.lower() not in {"http", "https"}:
        raise _violation("proxy_scheme_not_allowed", "Egress proxy URL scheme is not allowed")
    if not parts.hostname:
        raise _violation("proxy_hostname_required", "Egress proxy URL hostname is required")
    if parts.username or parts.password:
        raise _violation(
            "proxy_credentials_not_allowed",
            "Egress proxy URL credentials are not allowed",
        )
    port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    netloc = f"{parts.hostname.lower()}:{port}"
    return f"{parts.scheme.lower()}://{netloc}"


def _validate_docker_network(network: str) -> str:
    if not network or not network.startswith("aegis-egress-"):
        raise _violation(
            "invalid_docker_network",
            "Docker egress network must be managed by AegisFlow",
        )
    return network


def _proxy_metadata(proxy_url: str) -> tuple[str, int]:
    if not proxy_url:
        return "", 0
    parts = urlsplit(proxy_url)
    return parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)


def _violation(reason_code: str, public_message: str) -> EgressProxyPolicyViolation:
    return EgressProxyPolicyViolation(reason_code, public_message)
