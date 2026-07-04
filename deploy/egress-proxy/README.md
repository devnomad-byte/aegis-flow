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

## Kubernetes / Helm Profile

Standard Kubernetes profile:

```powershell
kubectl apply -f deploy/egress-proxy/kubernetes/manifests/aegis-egress-proxy.yaml
```

Helm chart skeleton:

```powershell
helm upgrade --install aegis-egress-proxy deploy/egress-proxy/kubernetes/helm/aegis-egress-proxy --namespace aegis-project-123 --create-namespace
```

The Kubernetes profile includes:

- Namespace, ServiceAccount, ConfigMap, Deployment, Service, and NetworkPolicy resources.
- RollingUpdate deployment strategy with `maxUnavailable=0`.
- Envoy config mounted from ConfigMap and optional Secret reference for audit integration.
- ClusterIP service exposing proxy port `8888` and admin metrics port `9901` inside the cluster.
- Prometheus scrape annotations and an optional ServiceMonitor template.
- Client egress policy that only allows project egress clients to reach the proxy and DNS.
- Proxy ingress policy that only allows same-project clients on `8888` and observability namespaces on `9901`.
- Proxy egress policy that allows DNS and configured TCP ports while excluding unsafe private, loopback, link-local, CGNAT, multicast, and reserved ranges.

Kubernetes NetworkPolicy requires a CNI plugin that enforces NetworkPolicy. Treat `resolved_address_filter` as an Envoy upgrade option only after the target Envoy image accepts that field in validation; the current profile relies on platform egress policy, Envoy host/port policy, and Kubernetes NetworkPolicy as the deployable defense in depth.
