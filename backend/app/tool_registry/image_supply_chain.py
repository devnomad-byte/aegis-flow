import hashlib
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel

from backend.app.tool_registry.schemas import (
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

    async def resolve_and_record(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageAdmissionResolveRequest,
    ) -> ShellImageAdmissionRead:
        digest_result = await self.digest_resolver.resolve(request.image_ref)
        digest_match = (
            digest_result.digest_match and digest_result.registry_digest == request.image_digest
        )
        if digest_match:
            policy_decision = "approved"
            reason = (
                "registry digest matches requested digest; signature, SBOM, and vulnerability "
                "evidence not checked"
            )
        else:
            policy_decision = "rejected"
            reason = "registry digest does not match requested digest"
        return await self.store.record_shell_image_admission(
            project_id=project_id,
            actor_id=actor_id,
            request=request,
            digest_result=digest_result,
            digest_match=digest_match,
            policy_decision=policy_decision,
            decision_reason=reason,
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
    ) -> ShellImageAdmissionRead:
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


def _split_registry_and_repo(image_ref_without_reference: str) -> tuple[str, str]:
    parts = image_ref_without_reference.split("/", maxsplit=1)
    if len(parts) != 2:
        raise OciManifestDigestError("OCI image ref must include a registry host and repository")
    registry_host, repository = parts
    if not registry_host or not repository:
        raise OciManifestDigestError("OCI image ref is missing registry host or repository")
    return registry_host, repository
