import asyncio
import json
import shutil
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ImageEvidenceStatus = Literal["not_checked", "passed", "failed"]
ImageAdmissionDecision = Literal["approved", "would_reject", "rejected"]

DEFAULT_BLOCKED_SEVERITIES = frozenset({"HIGH", "CRITICAL"})
KNOWN_SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")


class ShellImageEvidenceError(RuntimeError):
    """Raised when a configured shell image evidence tool cannot complete."""


@dataclass(frozen=True)
class ShellImageEvidenceCheck:
    status: ImageEvidenceStatus
    evidence: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass(frozen=True)
class ShellImageEvidenceResult:
    signature_status: ImageEvidenceStatus = "not_checked"
    sbom_status: ImageEvidenceStatus = "not_checked"
    vulnerability_status: ImageEvidenceStatus = "not_checked"
    policy_decision: ImageAdmissionDecision = "approved"
    decision_reason: str = "registry digest matches requested digest"
    evidence: dict[str, Any] = field(default_factory=dict)


class ShellImageEvidenceProvider(Protocol):
    async def collect(self, *, image_ref: str, image_digest: str) -> ShellImageEvidenceResult:
        raise NotImplementedError


class NoopShellImageEvidenceProvider:
    async def collect(self, *, image_ref: str, image_digest: str) -> ShellImageEvidenceResult:
        return ShellImageEvidenceResult(
            decision_reason=(
                "registry digest matches requested digest; signature, SBOM, and vulnerability "
                "evidence not checked"
            ),
            evidence={},
        )


class StaticShellImageEvidenceProvider:
    def __init__(self, result: ShellImageEvidenceResult) -> None:
        self._result = result

    async def collect(self, *, image_ref: str, image_digest: str) -> ShellImageEvidenceResult:
        return self._result


@dataclass(frozen=True)
class ShellImageToolCommand:
    argv: tuple[str, ...]
    timeout_seconds: float


class ShellImageCommandRunner(Protocol):
    async def run_json(self, command: ShellImageToolCommand) -> dict[str, Any]:
        raise NotImplementedError

    async def run_text(self, command: ShellImageToolCommand) -> str:
        raise NotImplementedError


class AsyncSubprocessJsonRunner:
    async def run_json(self, command: ShellImageToolCommand) -> dict[str, Any]:
        stdout = await self._run(command)
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ShellImageEvidenceError("supply chain tool returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise ShellImageEvidenceError("supply chain tool returned non-object JSON")
        return parsed

    async def run_text(self, command: ShellImageToolCommand) -> str:
        return await self._run(command)

    async def _run(self, command: ShellImageToolCommand) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                *command.argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=command.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ShellImageEvidenceError("supply chain tool timed out") from exc
        except OSError as exc:
            raise ShellImageEvidenceError("supply chain tool failed to start") from exc

        if process.returncode != 0:
            message = _sanitize_tool_error(stderr.decode("utf-8", errors="replace"))
            raise ShellImageEvidenceError(message or "supply chain tool failed")
        return stdout.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class CosignCliEvidenceProvider:
    cosign_command: str = "cosign"
    timeout_seconds: float = 120.0
    certificate_identity: str = ""
    certificate_oidc_issuer: str = ""
    key_ref: str = ""
    runner: ShellImageCommandRunner = field(default_factory=AsyncSubprocessJsonRunner)

    async def collect(self, *, image_ref: str, image_digest: str) -> ShellImageEvidenceResult:
        if not self.key_ref and not (self.certificate_identity and self.certificate_oidc_issuer):
            return ShellImageEvidenceResult(
                signature_status="failed",
                policy_decision="rejected",
                decision_reason="Cosign trust policy is not configured",
                evidence={"signature": {"tool": "cosign", "status": "failed"}},
            )
        if shutil.which(self.cosign_command) is None:
            return ShellImageEvidenceResult(
                signature_status="failed",
                policy_decision="rejected",
                decision_reason="Cosign executable is not available",
                evidence={"signature": {"tool": "cosign", "status": "failed"}},
            )
        command = self._build_verify_command(image_ref=image_ref, image_digest=image_digest)
        try:
            await self.runner.run_text(command)
        except ShellImageEvidenceError as exc:
            message = _sanitize_tool_error(str(exc))
            return ShellImageEvidenceResult(
                signature_status="failed",
                policy_decision="rejected",
                decision_reason=message or "Cosign signature verification failed",
                evidence={
                    "signature": {
                        "tool": "cosign",
                        "identity": self.certificate_identity,
                        "issuer": self.certificate_oidc_issuer,
                        "status": "failed",
                    }
                },
            )
        return ShellImageEvidenceResult(
            signature_status="passed",
            policy_decision="approved",
            decision_reason="Cosign signature verification passed",
            evidence={
                "signature": {
                    "tool": "cosign",
                    "identity": self.certificate_identity,
                    "issuer": self.certificate_oidc_issuer,
                    "status": "passed",
                }
            },
        )

    def _build_verify_command(self, *, image_ref: str, image_digest: str) -> ShellImageToolCommand:
        target = image_ref if "@sha256:" in image_ref else f"{image_ref}@{image_digest}"
        argv = [self.cosign_command, "verify"]
        if self.key_ref:
            argv.extend(["--key", self.key_ref])
        else:
            if self.certificate_identity:
                argv.extend(["--certificate-identity", self.certificate_identity])
            if self.certificate_oidc_issuer:
                argv.extend(["--certificate-oidc-issuer", self.certificate_oidc_issuer])
        argv.append(target)
        return ShellImageToolCommand(argv=tuple(argv), timeout_seconds=self.timeout_seconds)


@dataclass(frozen=True)
class TrivyCliEvidenceProvider:
    trivy_command: str = "trivy"
    timeout_seconds: float = 120.0
    blocked_severities: frozenset[str] = DEFAULT_BLOCKED_SEVERITIES
    cache_dir: str = ""
    runner: ShellImageCommandRunner = field(default_factory=AsyncSubprocessJsonRunner)

    async def collect(self, *, image_ref: str, image_digest: str) -> ShellImageEvidenceResult:
        if shutil.which(self.trivy_command) is None:
            return ShellImageEvidenceResult(
                sbom_status="failed",
                vulnerability_status="failed",
                policy_decision="rejected",
                decision_reason="Trivy executable is not available",
                evidence={
                    "sbom": {"tool": "trivy", "status": "failed"},
                    "vulnerabilities": {"tool": "trivy", "status": "failed"},
                },
            )

        sbom_report = await self.runner.run_json(
            ShellImageToolCommand(
                argv=(
                    self.trivy_command,
                    "image",
                    *self._cache_args(),
                    "--format",
                    "cyclonedx",
                    "--quiet",
                    image_ref,
                ),
                timeout_seconds=self.timeout_seconds,
            )
        )
        vulnerability_report = await self.runner.run_json(
            ShellImageToolCommand(
                argv=(
                    self.trivy_command,
                    "image",
                    *self._cache_args(),
                    "--scanners",
                    "vuln",
                    "--format",
                    "json",
                    "--quiet",
                    image_ref,
                ),
                timeout_seconds=self.timeout_seconds,
            )
        )
        sbom = summarize_trivy_sbom_report(sbom_report)
        vulnerabilities = summarize_trivy_vulnerability_report(
            vulnerability_report,
            blocked_severities=self.blocked_severities,
        )
        evidence_passed = sbom.status == "passed" and vulnerabilities.status == "passed"
        decision: ImageAdmissionDecision = "approved" if evidence_passed else "rejected"
        reason = (
            "registry digest, SBOM, and vulnerability evidence passed"
            if decision == "approved"
            else "vulnerability scan found blocked severities"
        )
        return ShellImageEvidenceResult(
            sbom_status=sbom.status,
            vulnerability_status=vulnerabilities.status,
            policy_decision=decision,
            decision_reason=reason,
            evidence={"sbom": sbom.evidence, "vulnerabilities": vulnerabilities.evidence},
        )

    def _cache_args(self) -> tuple[str, ...]:
        return ("--cache-dir", self.cache_dir) if self.cache_dir else ()


def summarize_trivy_sbom_report(report: dict[str, Any]) -> ShellImageEvidenceCheck:
    components = report.get("components", [])
    component_count = len(components) if isinstance(components, list) else 0
    format_name = str(report.get("bomFormat") or report.get("spdxVersion") or "unknown")
    return ShellImageEvidenceCheck(
        status="passed",
        evidence={"format": format_name, "component_count": component_count},
        reason="SBOM generated",
    )


def summarize_trivy_vulnerability_report(
    report: dict[str, Any],
    *,
    blocked_severities: set[str] | frozenset[str] = DEFAULT_BLOCKED_SEVERITIES,
) -> ShellImageEvidenceCheck:
    severity_counts: dict[str, int] = {}
    blocked = {severity.upper() for severity in blocked_severities}
    blocked_count = 0
    total_count = 0

    for vulnerability in _iter_trivy_vulnerabilities(report):
        severity = str(vulnerability.get("Severity", "UNKNOWN")).upper()
        if severity not in KNOWN_SEVERITIES:
            severity = "UNKNOWN"
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        total_count += 1
        if severity in blocked:
            blocked_count += 1

    status: ImageEvidenceStatus = "failed" if blocked_count else "passed"
    return ShellImageEvidenceCheck(
        status=status,
        evidence={
            "severity_counts": severity_counts,
            "total_count": total_count,
            "blocked_severities": sorted(blocked),
            "blocked_count": blocked_count,
        },
        reason="vulnerability scan passed" if status == "passed" else "blocked severities found",
    )


def merge_evidence_providers(*providers: ShellImageEvidenceProvider) -> ShellImageEvidenceProvider:
    return CompositeShellImageEvidenceProvider(providers=providers)


@dataclass(frozen=True)
class CompositeShellImageEvidenceProvider:
    providers: tuple[ShellImageEvidenceProvider, ...]

    async def collect(self, *, image_ref: str, image_digest: str) -> ShellImageEvidenceResult:
        result = ShellImageEvidenceResult()
        evidence: dict[str, Any] = {}
        decision: ImageAdmissionDecision = "approved"
        reasons: list[str] = []
        signature_status: ImageEvidenceStatus = "not_checked"
        sbom_status: ImageEvidenceStatus = "not_checked"
        vulnerability_status: ImageEvidenceStatus = "not_checked"

        for provider in self.providers:
            next_result = await provider.collect(image_ref=image_ref, image_digest=image_digest)
            evidence.update(next_result.evidence)
            reasons.append(next_result.decision_reason)
            signature_status = _merge_status(signature_status, next_result.signature_status)
            sbom_status = _merge_status(sbom_status, next_result.sbom_status)
            vulnerability_status = _merge_status(
                vulnerability_status,
                next_result.vulnerability_status,
            )
            if next_result.policy_decision == "rejected":
                decision = "rejected"
            result = next_result

        return ShellImageEvidenceResult(
            signature_status=signature_status,
            sbom_status=sbom_status,
            vulnerability_status=vulnerability_status,
            policy_decision=decision,
            decision_reason="; ".join(reason for reason in reasons if reason)
            or result.decision_reason,
            evidence=evidence,
        )


def _merge_status(
    current: ImageEvidenceStatus,
    next_status: ImageEvidenceStatus,
) -> ImageEvidenceStatus:
    if "failed" in {current, next_status}:
        return "failed"
    if "passed" in {current, next_status}:
        return "passed"
    return "not_checked"


def _iter_trivy_vulnerabilities(report: dict[str, Any]) -> list[dict[str, Any]]:
    vulnerabilities: list[dict[str, Any]] = []
    results = report.get("Results", [])
    if not isinstance(results, list):
        return vulnerabilities
    for result in results:
        if not isinstance(result, dict):
            continue
        items = result.get("Vulnerabilities", [])
        if not isinstance(items, list):
            continue
        vulnerabilities.extend(item for item in items if isinstance(item, dict))
    return vulnerabilities


def _sanitize_tool_error(message: str) -> str:
    lowered = message.lower()
    if any(secret_word in lowered for secret_word in ("token", "password", "secret", "api_key")):
        return "supply chain tool failed with sensitive output redacted"
    return message.strip()[:500]
