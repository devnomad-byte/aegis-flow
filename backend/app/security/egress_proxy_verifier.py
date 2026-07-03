import json
import shutil
import subprocess
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from backend.app.security.egress_proxy_profile import build_envoy_profile


@dataclass(frozen=True)
class EgressProxyCommandResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class EgressProxyAuditEvent:
    reason: str
    target_host: str
    target_port: int
    target_url: str = ""


@dataclass(frozen=True)
class EgressProxyVerificationReport:
    egress_network: str
    upstream_network: str
    allowed_via_proxy: EgressProxyCommandResult
    mcp_tools_list_via_proxy: EgressProxyCommandResult
    direct_without_proxy: EgressProxyCommandResult
    denied_host: EgressProxyCommandResult
    denied_port: EgressProxyCommandResult
    redirect_denied: EgressProxyCommandResult
    metrics: EgressProxyCommandResult
    admin_from_client: EgressProxyCommandResult
    proxy_unavailable: EgressProxyCommandResult
    audit_events: list[EgressProxyAuditEvent] = field(default_factory=list)


@dataclass(frozen=True)
class DockerEgressProxyVerifier:
    image_ref: str
    allowed_hosts: list[str]
    allowed_ports: list[int]
    proxy_kind: str = "python"
    proxy_image_ref: str = "envoyproxy/envoy:v1.35-latest"
    timeout_seconds: int = 30

    def run(self) -> EgressProxyVerificationReport:
        suffix = uuid4().hex[:10]
        egress_network = f"aegis-egress-verify-{suffix}"
        upstream_network = f"aegis-upstream-verify-{suffix}"
        target_name = f"aegis-target-{suffix}"
        proxy_name = f"aegis-proxy-{suffix}"
        script_dir = _create_script_dir()

        try:
            _write_verifier_scripts(script_dir)
            self._docker(["network", "create", egress_network])
            self._docker(["network", "create", upstream_network])
            self._start_target(target_name, upstream_network, script_dir)
            self._start_proxy(proxy_name, egress_network, script_dir)
            self._docker(["network", "connect", upstream_network, proxy_name])
            time.sleep(1)

            allowed_via_proxy = self._run_client(
                egress_network,
                _curl_script(
                    "curl -sS --max-time 5 -x http://aegis-egress-proxy:8888 "
                    "http://allowed.internal:8080/ok"
                ),
            )
            mcp_tools_list_via_proxy = self._run_client(
                egress_network,
                _curl_script(
                    "curl -sS --max-time 5 -x http://aegis-egress-proxy:8888 "
                    "-H 'content-type: application/json' "
                    '-d \'{"jsonrpc":"2.0","id":"1",'
                    '"method":"tools/list","params":{}}\' '
                    "http://allowed.internal:8080/mcp"
                ),
            )
            direct_without_proxy = self._run_client(
                egress_network,
                "curl -sS --max-time 3 http://allowed.internal:8080/ok",
            )
            denied_host = self._run_client(
                egress_network,
                "curl -sS --max-time 5 -x http://aegis-egress-proxy:8888 "
                "http://blocked.internal:8080/ok",
            )
            denied_port = self._run_client(
                egress_network,
                "curl -sS --max-time 5 -x http://aegis-egress-proxy:8888 "
                "http://allowed.internal:9090/ok",
            )
            redirect_denied = self._run_client(
                egress_network,
                "curl -i -sS --max-time 5 -x http://aegis-egress-proxy:8888 "
                "http://allowed.internal:8080/redirect",
            )
            metrics = self._run_metrics(proxy_name)
            admin_from_client = self._run_client(
                egress_network,
                "curl -sS --max-time 5 http://aegis-egress-proxy:9901/stats/prometheus",
            )
            self._docker(["stop", proxy_name], check=False)
            proxy_logs = self._docker(["logs", proxy_name], check=False)
            proxy_unavailable = self._run_client(
                egress_network,
                "curl -sS --max-time 3 -x http://aegis-egress-proxy:8888 "
                "http://allowed.internal:8080/ok",
            )

            return EgressProxyVerificationReport(
                egress_network=egress_network,
                upstream_network=upstream_network,
                allowed_via_proxy=allowed_via_proxy,
                mcp_tools_list_via_proxy=mcp_tools_list_via_proxy,
                direct_without_proxy=direct_without_proxy,
                denied_host=denied_host,
                denied_port=denied_port,
                redirect_denied=redirect_denied,
                metrics=metrics,
                admin_from_client=admin_from_client,
                proxy_unavailable=proxy_unavailable,
                audit_events=parse_proxy_audit_events(f"{proxy_logs.stdout}\n{proxy_logs.stderr}"),
            )
        finally:
            self._docker(["rm", "-f", target_name, proxy_name], check=False)
            self._docker(["network", "rm", egress_network, upstream_network], check=False)
            shutil.rmtree(script_dir, ignore_errors=True)

    def _start_target(self, name: str, network: str, script_dir: Path) -> None:
        self._docker(
            [
                "run",
                "-d",
                "--name",
                name,
                "--network",
                network,
                "--network-alias",
                "allowed.internal",
                "--mount",
                f"type=bind,source={script_dir},target=/workspace,readonly",
                "--entrypoint",
                "python3",
                self.image_ref,
                "/workspace/target_server.py",
            ]
        )

    def _start_proxy(self, name: str, network: str, script_dir: Path) -> None:
        if self.proxy_kind == "envoy":
            profile = build_envoy_profile(
                allowed_hosts=self.allowed_hosts,
                allowed_ports=self.allowed_ports,
                image_ref=self.proxy_image_ref,
            )
            profile.write_to_directory(script_dir)
            self._docker(
                [
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--network",
                    network,
                    "--network-alias",
                    "aegis-egress-proxy",
                    "--mount",
                    (
                        f"type=bind,source={script_dir / 'envoy.yaml'},"
                        "target=/etc/envoy/envoy.yaml,readonly"
                    ),
                    "--mount",
                    (
                        f"type=bind,source={script_dir / 'policy.lua'},"
                        "target=/etc/envoy/policy.lua,readonly"
                    ),
                    self.proxy_image_ref,
                    "envoy",
                    "-c",
                    "/etc/envoy/envoy.yaml",
                ]
            )
            return

        if self.proxy_kind != "python":
            raise ValueError(f"Unsupported egress proxy verifier kind: {self.proxy_kind}")

        self._docker(
            [
                "run",
                "-d",
                "--name",
                name,
                "--network",
                network,
                "--network-alias",
                "aegis-egress-proxy",
                "--env",
                f"ALLOWED_HOSTS={','.join(self.allowed_hosts)}",
                "--env",
                f"ALLOWED_PORTS={','.join(str(port) for port in self.allowed_ports)}",
                "--mount",
                f"type=bind,source={script_dir},target=/workspace,readonly",
                "--entrypoint",
                "python3",
                self.image_ref,
                "/workspace/proxy_server.py",
            ]
        )

    def _run_client(self, network: str, script: str) -> EgressProxyCommandResult:
        return self._docker(
            [
                "run",
                "--rm",
                "--network",
                network,
                "--entrypoint",
                "/bin/sh",
                self.image_ref,
                "-lc",
                script,
            ],
            check=False,
        )

    def _run_metrics(self, proxy_name: str) -> EgressProxyCommandResult:
        if self.proxy_kind != "envoy":
            return EgressProxyCommandResult(exit_code=0, stdout="", stderr="")
        return self._docker(
            [
                "exec",
                proxy_name,
                "/bin/bash",
                "-lc",
                (
                    "exec 3<>/dev/tcp/127.0.0.1/9901; "
                    "printf 'GET /stats/prometheus HTTP/1.1\\r\\nHost: localhost\\r\\n"
                    "Connection: close\\r\\n\\r\\n' >&3; "
                    "cat <&3"
                ),
            ],
            check=False,
        )

    def _docker(self, args: list[str], *, check: bool = True) -> EgressProxyCommandResult:
        completed = subprocess.run(
            ["docker", *args],
            capture_output=True,
            check=False,
            text=True,
            timeout=self.timeout_seconds,
        )
        result = EgressProxyCommandResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and completed.returncode != 0:
            raise RuntimeError(
                f"Docker command failed: docker {' '.join(args)}\n"
                f"stdout={completed.stdout}\nstderr={completed.stderr}"
            )
        return result


def parse_proxy_audit_events(log_text: str) -> list[EgressProxyAuditEvent]:
    events: list[EgressProxyAuditEvent] = []
    for line in log_text.splitlines():
        line = line.strip()
        json_start = line.find("{")
        if json_start < 0:
            continue
        json_text = line[json_start:]
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError:
            continue
        reason = str(payload.get("reason") or "")
        target_host = str(payload.get("target_host") or "")
        target_port = int(payload.get("target_port") or 0)
        if reason:
            events.append(
                EgressProxyAuditEvent(
                    reason=reason,
                    target_host=target_host,
                    target_port=target_port,
                )
            )
    return events


def _create_script_dir() -> Path:
    root = Path("D:/agent-platform-cache/egress-proxy-verifier")
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="run-", dir=root))


def _write_verifier_scripts(script_dir: Path) -> None:
    (script_dir / "target_server.py").write_text(_TARGET_SERVER, encoding="utf-8")
    (script_dir / "proxy_server.py").write_text(_PROXY_SERVER, encoding="utf-8")


def _curl_script(command: str) -> str:
    return f"for attempt in 1 2 3 4 5; do {command} && exit 0; sleep 1; done; exit 1"


_TARGET_SERVER = textwrap.dedent(
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/redirect"):
                self.send_response(302)
                self.send_header("Location", "http://blocked.internal:8080/ok")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"target=ok")

        def do_POST(self):
            if self.path.startswith("/mcp"):
                content_length = int(self.headers.get("content-length") or 0)
                if content_length:
                    self.rfile.read(content_length)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    b'{"jsonrpc":"2.0","id":"1","result":{"tools":[{"name":"ping"}]}}'
                )
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, format, *args):
            return


    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
    """
).strip()


_PROXY_SERVER = textwrap.dedent(
    """
    import http.client
    import json
    import os
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlsplit, urlunsplit

    ALLOWED_HOSTS = {
        host.strip().lower()
        for host in os.environ["ALLOWED_HOSTS"].split(",")
        if host.strip()
    }
    ALLOWED_PORTS = {
        int(port)
        for port in os.environ["ALLOWED_PORTS"].split(",")
        if port.strip()
    }


    def audit(reason, host, port):
        print(
            json.dumps(
                {
                    "reason": reason,
                    "target_host": host,
                    "target_port": port,
                },
                sort_keys=True,
            ),
            flush=True,
        )


    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._proxy("GET")

        def do_POST(self):
            self._proxy("POST")

        def _proxy(self, method):
            target = urlsplit(self.path)
            host = (target.hostname or "").lower()
            port = target.port or (443 if target.scheme == "https" else 80)
            if target.scheme != "http" or not host:
                return self._deny(400, "invalid_target", host, port)
            if host not in ALLOWED_HOSTS:
                return self._deny(403, "host_not_allowlisted", host, port)
            if ALLOWED_PORTS and port not in ALLOWED_PORTS:
                return self._deny(403, "port_not_allowlisted", host, port)

            path = urlunsplit(("", "", target.path or "/", target.query, ""))
            content_length = int(self.headers.get("content-length") or 0)
            body_in = self.rfile.read(content_length) if content_length else None
            headers = {"Host": host}
            content_type = self.headers.get("content-type")
            if content_type:
                headers["Content-Type"] = content_type
            try:
                connection = http.client.HTTPConnection(host, port, timeout=3)
                connection.request(method, path, body=body_in, headers=headers)
                response = connection.getresponse()
                body = response.read()
            except OSError:
                return self._deny(502, "upstream_unreachable", host, port)

            if 300 <= response.status < 400 and response.getheader("Location"):
                return self._deny(502, "redirect_denied", host, port)

            audit("allowed", host, port)
            self.send_response(response.status)
            self.send_header("Content-Type", response.getheader("Content-Type") or "text/plain")
            self.end_headers()
            self.wfile.write(body)

        def _deny(self, status, reason, host, port):
            audit(reason, host, port)
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(reason.encode("utf-8"))

        def log_message(self, format, *args):
            return


    ThreadingHTTPServer(("0.0.0.0", 8888), Handler).serve_forever()
    """
).strip()
