import hashlib
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel

from backend.app.tool_registry.image_evidence import (
    NoopShellImageEvidenceProvider,
    ShellImageEvidenceProvider,
)
from backend.app.tool_registry.schemas import (
    ShellImageAdmissionPolicyRead,
    ShellImageAdmissionRead,
    ShellImageAdmissionResolveRequest,
)

OCI_MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    ]
)


class OciManifestDigestError(RuntimeError):
    """Raised when an OCI registry manifest digest cannot be resolved safely."""


class OciManifestDigestResult(BaseModel):
    image_ref: str
    registry_url: str
    registry_digest: str
    computed_digest: str
    digest_match: bool
    content_type: str
    manifest_size_bytes: int


class OciDigestResolver(Protocol):
    async def resolve(self, image_ref: str) -> OciManifestDigestResult:
        raise NotImplementedError


@dataclass
class OciManifestDigestResolver:
    timeout_seconds: float = 10.0
    transport: httpx.AsyncBaseTransport | None = None
    plain_http_hosts: tuple[str, ...] = ()

    async def resolve(self, image_ref: str) -> OciManifestDigestResult:
        registry_host, repository, reference = parse_image_ref(image_ref)
        scheme = "http" if registry_host in self.plain_http_hosts else "https"
        registry_url = (
            f"{scheme}://{registry_host}/v2/{quote(repository, safe='/')}/manifests/"
            f"{quote(reference, safe='')}"
        )
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            try:
                response = await client.get(registry_url, headers={"Accept": OCI_MANIFEST_ACCEPT})
            except httpx.HTTPError as exc:
                raise OciManifestDigestError("OCI registry manifest request failed") from exc
        if response.status_code >= 400:
            raise OciManifestDigestError("OCI registry manifest request was rejected")
        registry_digest = response.headers.get("Docker-Content-Digest", "").strip()
        if not registry_digest:
            raise OciManifestDigestError("OCI registry response omitted Docker-Content-Digest")
        payload = response.content
        computed_digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        return OciManifestDigestResult(
            image_ref=image_ref,
            registry_url=registry_url,
            registry_digest=registry_digest,
            computed_digest=computed_digest,
            digest_match=registry_digest == computed_digest,
            content_type=response.headers.get("Content-Type", "").split(";")[0],
            manifest_size_bytes=len(payload),
        )


@dataclass
class ShellImageAdmissionService:
    store: "ShellImageAdmissionStore"
    digest_resolver: OciDigestResolver
    evidence_provider: ShellImageEvidenceProvider = field(
        default_factory=NoopShellImageEvidenceProvider
    )

    async def resolve_and_record(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageAdmissionResolveRequest,
    ) -> ShellImageAdmissionRead:
        policy = await self.store.get_shell_image_admission_policy(project_id)
        digest_result = await self.digest_resolver.resolve(request.image_ref)
        digest_match = (
            digest_result.digest_match and digest_result.registry_digest == request.image_digest
        )
        signature_status = "not_checked"
        sbom_status = "not_checked"
        vulnerability_status = "not_checked"
        evidence: dict[str, object] = {}
        if not digest_match:
            policy_decision = "rejected"
            reason = "registry digest does not match requested digest"
        else:
            evidence_result = await self.evidence_provider.collect(
                image_ref=request.image_ref,
                image_digest=request.image_digest,
            )
            signature_status = evidence_result.signature_status
            sbom_status = evidence_result.sbom_status
            vulnerability_status = evidence_result.vulnerability_status
            policy_decision = evidence_result.policy_decision
            reason = evidence_result.decision_reason
            evidence = sanitize_image_evidence_summary(evidence_result.evidence)
        policy_decision, reason = apply_shell_image_admission_policy(
            policy=policy,
            policy_decision=policy_decision,
            decision_reason=reason,
            signature_status=signature_status,
        )
        return await self.store.record_shell_image_admission(
            project_id=project_id,
            actor_id=actor_id,
            request=request,
            digest_result=digest_result,
            digest_match=digest_match,
            policy_decision=policy_decision,
            decision_reason=reason,
            signature_status=signature_status,
            sbom_status=sbom_status,
            vulnerability_status=vulnerability_status,
            evidence_summary=evidence,
        )


class ShellImageAdmissionStore(Protocol):
    async def record_shell_image_admission(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageAdmissionResolveRequest,
        digest_result: OciManifestDigestResult,
        digest_match: bool,
        policy_decision: str,
        decision_reason: str,
        signature_status: str,
        sbom_status: str,
        vulnerability_status: str,
        evidence_summary: dict[str, object],
    ) -> ShellImageAdmissionRead:
        raise NotImplementedError

    async def get_shell_image_admission_policy(
        self,
        project_id: UUID,
    ) -> ShellImageAdmissionPolicyRead:
        raise NotImplementedError


def parse_image_ref(image_ref: str) -> tuple[str, str, str]:
    if "@sha256:" in image_ref:
        without_digest, digest = image_ref.rsplit("@", maxsplit=1)
        registry_host, repository = _split_registry_and_repo(without_digest)
        return registry_host, repository, digest
    without_tag, separator, tag = image_ref.rpartition(":")
    if separator and "/" in without_tag:
        registry_host, repository = _split_registry_and_repo(without_tag)
        return registry_host, repository, tag
    registry_host, repository = _split_registry_and_repo(image_ref)
    return registry_host, repository, "latest"


def sanitize_image_evidence_summary(evidence: dict[str, object]) -> dict[str, object]:
    artifact_keys = {
        "artifact_ref",
        "artifact_sha256",
        "artifact_size_bytes",
        "artifact_content_type",
        "artifact_retention_days",
        "artifact_retention_expires_at",
    }
    allowed_nested_keys = {
        "signature": {"tool", "verifier", "identity", "issuer", "status"},
        "sbom": {"tool", "format", "component_count", "status"} | artifact_keys,
        "vulnerabilities": {
            "tool",
            "severity_counts",
            "total_count",
            "blocked_severities",
            "blocked_count",
            "status",
        }
        | artifact_keys,
    }
    allowed_top_level = {
        "content_type",
        "manifest_size_bytes",
        "computed_digest",
    }
    sanitized: dict[str, object] = {}
    for key, value in evidence.items():
        if key in allowed_top_level:
            sanitized[key] = value
            continue
        if not isinstance(value, dict):
            continue
        allowed = allowed_nested_keys.get(key)
        if allowed is None:
            continue
        sanitized[key] = {
            nested_key: value[nested_key] for nested_key in allowed if nested_key in value
        }
    return sanitized


def apply_shell_image_admission_policy(
    *,
    policy: ShellImageAdmissionPolicyRead,
    policy_decision: str,
    decision_reason: str,
    signature_status: str,
) -> tuple[str, str]:
    would_reject_reasons: list[str] = []
    if policy_decision == "rejected":
        would_reject_reasons.append(decision_reason)
    if policy.cosign_required and signature_status != "passed":
        would_reject_reasons.append("Cosign signature evidence is required by project policy")

    if not would_reject_reasons:
        return "approved", decision_reason

    reason = "; ".join(reason for reason in would_reject_reasons if reason)
    if policy.enforcement_mode == "dry_run":
        return "would_reject", f"dry-run would reject: {reason}"
    return "rejected", reason


def _split_registry_and_repo(image_ref_without_reference: str) -> tuple[str, str]:
    parts = image_ref_without_reference.split("/", maxsplit=1)
    if len(parts) != 2:
        raise OciManifestDigestError("OCI image ref must include a registry host and repository")
    registry_host, repository = parts
    if not registry_host or not repository:
        raise OciManifestDigestError("OCI image ref is missing registry host or repository")
    return registry_host, repository
