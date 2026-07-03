# AegisFlow Egress Proxy Profiles

These profiles provide controlled outbound proxy deployments for MCP, HTTP, and Shell Runner traffic.

## Envoy Profile

Primary profile:

```powershell
docker compose -f deploy/egress-proxy/envoy/docker-compose.yml up -d
```

The Envoy profile uses:

- Dynamic forward proxy with a shared DNS cache.
- Lua policy for exact/wildcard host and port allowlist enforcement.
- Redirect denial for upstream 3xx responses, with `Location` stripped before returning to clients.
- Admin Prometheus metrics bound to container loopback (`127.0.0.1:9901`), not to the client proxy network.

Do not publish proxy ports to the host in production. Platform clients must join an `aegis-egress-*` network and use the proxy URL from the project environment configuration.

Envoy `resolved_address_filter` can be used for DNS-rebinding CIDR filtering in Envoy versions that support it. The current verified profile keeps DNS cache refresh/TTL explicit and relies on the platform egress policy plus deployment-layer NetworkPolicy for unsafe CIDR blocking.

## Squid Profile

Fallback profile:

```powershell
docker compose -f deploy/egress-proxy/squid/docker-compose.yml up -d
```

Squid is kept as a simple ACL-based alternative for environments that standardize on Squid. It provides host/port ACLs, a basic unsafe destination ACL, stripped `Location` response headers, stripped `Authorization`/`Cookie` request headers, and access logs without full URLs. It is not a metrics-equivalent replacement for the Envoy profile.
