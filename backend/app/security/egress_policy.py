import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from ipaddress import (
    IPv4Address,
    IPv4Network,
    IPv6Address,
    ip_address,
)
from urllib.parse import urlsplit, urlunsplit

IPAddress = IPv4Address | IPv6Address
EgressResolver = Callable[[str, int], Iterable[IPAddress]]

_SHARED_ADDRESS_SPACE = IPv4Network("100.64.0.0/10")
_METADATA_ADDRESSES = {
    ip_address("169.254.169.254"),
    ip_address("fd00:ec2::254"),
}


class EgressPolicyViolation(ValueError):
    """Raised when an outbound target violates the egress policy."""

    def __init__(
        self,
        reason_code: str,
        public_message: str,
        *,
        hostname: str = "",
        scheme: str = "",
    ) -> None:
        super().__init__(public_message)
        self.reason_code = reason_code
        self.public_message = public_message
        self.hostname = hostname
        self.scheme = scheme


@dataclass(frozen=True)
class EgressPolicy:
    allow_plain_http: bool = False
    allow_loopback: bool = False
    allow_private_networks: bool = False
    allow_link_local: bool = False
    allow_reserved: bool = False
    resolver: EgressResolver | None = None


@dataclass(frozen=True)
class ValidatedEgressTarget:
    normalized_url: str
    scheme: str
    hostname: str
    port: int
    resolved_addresses: tuple[IPAddress, ...]


def validate_egress_url(
    url: str,
    *,
    policy: EgressPolicy | None = None,
    allowed_hosts: Iterable[str] | None = None,
    resolver: EgressResolver | None = None,
) -> ValidatedEgressTarget:
    resolved_policy = policy or EgressPolicy()
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise _violation("scheme_not_allowed", "Egress URL scheme is not allowed", scheme=scheme)
    if scheme == "http" and not resolved_policy.allow_plain_http:
        raise _violation(
            "plain_http_not_allowed",
            "Plain HTTP egress is not allowed",
            scheme=scheme,
        )
    if parts.username or parts.password:
        raise _violation(
            "url_credentials_not_allowed",
            "URL credentials are not allowed in egress targets",
            scheme=scheme,
        )
    raw_hostname = parts.hostname
    if raw_hostname is None:
        raise _violation("missing_hostname", "Egress URL hostname is required", scheme=scheme)

    hostname = _normalize_hostname(raw_hostname)
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise _violation(
            "invalid_port",
            "Egress URL port is invalid",
            hostname=hostname,
            scheme=scheme,
        ) from exc

    normalized_allowed_hosts = normalize_allowed_hosts(allowed_hosts or [])
    if normalized_allowed_hosts and not _host_matches_allowlist(hostname, normalized_allowed_hosts):
        raise _violation(
            "host_not_allowlisted",
            "Egress target host is not allowed by environment policy",
            hostname=hostname,
            scheme=scheme,
        )

    selected_resolver = resolver or resolved_policy.resolver or resolve_hostname_addresses
    resolved_addresses = tuple(_resolve_hostname(hostname, port, selected_resolver))
    if not resolved_addresses:
        raise _violation(
            "dns_resolution_failed",
            "Egress target hostname did not resolve",
            hostname=hostname,
            scheme=scheme,
        )
    for address in resolved_addresses:
        if _is_unsafe_address(address, resolved_policy):
            raise _violation(
                "unsafe_ip_address",
                "Egress target resolves to an unsafe IP address",
                hostname=hostname,
                scheme=scheme,
            )

    normalized_netloc = _normalized_netloc(hostname, port, scheme)
    normalized_url = urlunsplit(
        (scheme, normalized_netloc, parts.path or "", parts.query or "", "")
    )
    return ValidatedEgressTarget(
        normalized_url=normalized_url,
        scheme=scheme,
        hostname=hostname,
        port=port,
        resolved_addresses=resolved_addresses,
    )


def normalize_allowed_hosts(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidate = str(value).strip().lower().rstrip(".")
        if not candidate:
            continue
        wildcard = candidate.startswith("*.")
        hostname = candidate[2:] if wildcard else candidate
        if "/" in hostname or ":" in hostname or "@" in hostname or "://" in hostname:
            raise _violation(
                "invalid_allowlist_host",
                "Environment egress allowlist host is invalid",
                hostname=hostname,
            )
        normalized_hostname = _normalize_hostname(hostname)
        if not normalized_hostname or "." not in normalized_hostname:
            raise _violation(
                "invalid_allowlist_host",
                "Environment egress allowlist host is invalid",
                hostname=hostname,
            )
        entry = f"*.{normalized_hostname}" if wildcard else normalized_hostname
        if entry not in seen:
            normalized.append(entry)
            seen.add(entry)
    return normalized


def resolve_hostname_addresses(hostname: str, port: int) -> list[IPAddress]:
    try:
        infos = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise _violation(
            "dns_resolution_failed",
            "Egress target hostname did not resolve",
            hostname=hostname,
        ) from exc

    addresses: list[IPAddress] = []
    seen: set[IPAddress] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        address = ip_address(sockaddr[0])
        if address not in seen:
            addresses.append(address)
            seen.add(address)
    return addresses


def _resolve_hostname(
    hostname: str,
    port: int,
    resolver: EgressResolver,
) -> Iterable[IPAddress]:
    try:
        literal_address = ip_address(hostname)
    except ValueError:
        return list(resolver(hostname, port))
    return [literal_address]


def _is_unsafe_address(address: IPAddress, policy: EgressPolicy) -> bool:
    if address in _METADATA_ADDRESSES:
        return True
    if address.is_unspecified or address.is_multicast:
        return True
    if address.is_loopback and not policy.allow_loopback:
        return True
    if address.is_link_local and not policy.allow_link_local:
        return True
    if address.is_loopback or address.is_link_local:
        return False
    if address.is_private and not policy.allow_private_networks:
        return True
    if address.is_reserved and not policy.allow_reserved:
        return True
    return isinstance(address, IPv4Address) and address in _SHARED_ADDRESS_SPACE


def _host_matches_allowlist(hostname: str, allowed_hosts: Iterable[str]) -> bool:
    for allowed_host in allowed_hosts:
        if allowed_host.startswith("*."):
            suffix = allowed_host[2:]
            if hostname.endswith(f".{suffix}") and hostname != suffix:
                return True
            continue
        if hostname == allowed_host:
            return True
    return False


def _normalize_hostname(hostname: str) -> str:
    return hostname.strip().lower().rstrip(".").encode("idna").decode("ascii")


def _normalized_netloc(hostname: str, port: int, scheme: str) -> str:
    host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    default_port = 443 if scheme == "https" else 80
    if port == default_port:
        return host
    return f"{host}:{port}"


def _violation(
    reason_code: str,
    public_message: str,
    *,
    hostname: str = "",
    scheme: str = "",
) -> EgressPolicyViolation:
    return EgressPolicyViolation(
        reason_code,
        f"{public_message} ({reason_code})",
        hostname=hostname,
        scheme=scheme,
    )
