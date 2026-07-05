import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from backend.app.core.settings import S3Settings

ShellImageArtifactKind = Literal["sbom", "scan_report", "notation_trust_certificate"]


@dataclass(frozen=True)
class StoredShellImageArtifact:
    body: bytes
    content_type: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class ShellImageArtifactMetadata:
    size_bytes: int
    content_type: str
    metadata: dict[str, str]


class ShellImageArtifactObjectStore(Protocol):
    async def put_artifact(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> str:
        raise NotImplementedError

    async def head_artifact(self, artifact_ref: str) -> ShellImageArtifactMetadata:
        raise NotImplementedError

    async def get_artifact(self, artifact_ref: str) -> StoredShellImageArtifact:
        raise NotImplementedError

    async def delete_artifact(self, artifact_ref: str) -> None:
        raise NotImplementedError


class InMemoryShellImageArtifactObjectStore:
    def __init__(self, *, bucket: str = "aegis-flow") -> None:
        self.bucket = bucket
        self.objects: dict[str, StoredShellImageArtifact] = {}

    async def put_artifact(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> str:
        artifact_ref = f"s3://{self.bucket}/{key}"
        self.objects[artifact_ref] = StoredShellImageArtifact(
            body=body,
            content_type=content_type,
            metadata=metadata,
        )
        return artifact_ref

    async def head_artifact(self, artifact_ref: str) -> ShellImageArtifactMetadata:
        stored = self.objects[artifact_ref]
        return ShellImageArtifactMetadata(
            size_bytes=len(stored.body),
            content_type=stored.content_type,
            metadata=stored.metadata,
        )

    async def get_artifact(self, artifact_ref: str) -> StoredShellImageArtifact:
        return self.objects[artifact_ref]

    async def delete_artifact(self, artifact_ref: str) -> None:
        self.objects.pop(artifact_ref, None)


class S3ShellImageArtifactObjectStore:
    def __init__(self, settings: S3Settings) -> None:
        self._settings = settings

    async def put_artifact(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> str:
        import aioboto3  # type: ignore[import-untyped]

        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self._settings.endpoint,
            region_name=self._settings.region,
            aws_access_key_id=self._settings.access_key.get_secret_value(),
            aws_secret_access_key=self._settings.secret_key.get_secret_value(),
        ) as client:
            await client.put_object(
                Bucket=self._settings.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                Metadata=metadata,
            )
        return f"s3://{self._settings.bucket}/{key}"

    async def head_artifact(self, artifact_ref: str) -> ShellImageArtifactMetadata:
        import aioboto3

        bucket, key = _parse_s3_ref(artifact_ref)
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self._settings.endpoint,
            region_name=self._settings.region,
            aws_access_key_id=self._settings.access_key.get_secret_value(),
            aws_secret_access_key=self._settings.secret_key.get_secret_value(),
        ) as client:
            response = await client.head_object(Bucket=bucket, Key=key)
        return ShellImageArtifactMetadata(
            size_bytes=int(response.get("ContentLength", 0)),
            content_type=str(response.get("ContentType", "")),
            metadata={
                str(key): str(value) for key, value in dict(response.get("Metadata", {})).items()
            },
        )

    async def get_artifact(self, artifact_ref: str) -> StoredShellImageArtifact:
        import aioboto3

        bucket, key = _parse_s3_ref(artifact_ref)
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self._settings.endpoint,
            region_name=self._settings.region,
            aws_access_key_id=self._settings.access_key.get_secret_value(),
            aws_secret_access_key=self._settings.secret_key.get_secret_value(),
        ) as client:
            response = await client.get_object(Bucket=bucket, Key=key)
            body = await response["Body"].read()
        return StoredShellImageArtifact(
            body=bytes(body),
            content_type=str(response.get("ContentType", "")),
            metadata={
                str(key): str(value) for key, value in dict(response.get("Metadata", {})).items()
            },
        )

    async def delete_artifact(self, artifact_ref: str) -> None:
        import aioboto3

        bucket, key = _parse_s3_ref(artifact_ref)
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self._settings.endpoint,
            region_name=self._settings.region,
            aws_access_key_id=self._settings.access_key.get_secret_value(),
            aws_secret_access_key=self._settings.secret_key.get_secret_value(),
        ) as client:
            await client.delete_object(Bucket=bucket, Key=key)


@dataclass(frozen=True)
class ShellImageArtifactWriter:
    project_id: UUID
    object_store: ShellImageArtifactObjectStore
    artifact_store_prefix: str = "shell-image-admissions"
    retention_days: int = 30
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def write_json_artifact(
        self,
        *,
        kind: ShellImageArtifactKind,
        image_ref: str,
        image_digest: str,
        payload: dict[str, Any],
    ) -> dict[str, object]:
        now = self.clock()
        retention_expires_at = now + timedelta(days=self.retention_days)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        artifact_sha256 = hashlib.sha256(body).hexdigest()
        key = self._build_object_key(kind=kind, image_digest=image_digest, now=now)
        content_type = _content_type_for_kind(kind)
        artifact_ref = await self.object_store.put_artifact(
            key,
            body,
            content_type=content_type,
            metadata={
                "artifact-kind": kind,
                "artifact-sha256": artifact_sha256,
                "image-digest": image_digest,
                "image-ref-sha256": hashlib.sha256(image_ref.encode("utf-8")).hexdigest(),
                "project-id": str(self.project_id),
                "retention-expires-at": retention_expires_at.isoformat(),
            },
        )
        return {
            "artifact_ref": artifact_ref,
            "artifact_sha256": artifact_sha256,
            "artifact_size_bytes": len(body),
            "artifact_content_type": content_type,
            "artifact_retention_days": self.retention_days,
            "artifact_retention_expires_at": retention_expires_at.isoformat(),
        }

    def _build_object_key(
        self,
        *,
        kind: ShellImageArtifactKind,
        image_digest: str,
        now: datetime,
    ) -> str:
        prefix = self.artifact_store_prefix.strip().strip("/")
        digest_prefix = _digest_prefix(image_digest)
        return (
            f"{prefix}/{self.project_id}/{now:%Y/%m/%d}/{digest_prefix}/{uuid4().hex}-{kind}.json"
        )


def build_shell_image_artifact_object_store(
    settings: S3Settings,
) -> ShellImageArtifactObjectStore:
    if settings.enabled:
        return S3ShellImageArtifactObjectStore(settings)
    return InMemoryShellImageArtifactObjectStore(bucket=settings.bucket)


def _digest_prefix(image_digest: str) -> str:
    if ":" in image_digest:
        image_digest = image_digest.split(":", maxsplit=1)[1]
    normalized = "".join(character for character in image_digest.lower() if character.isalnum())
    return (normalized or "unknown")[:12]


def _content_type_for_kind(kind: ShellImageArtifactKind) -> str:
    if kind == "sbom":
        return "application/vnd.cyclonedx+json"
    if kind == "notation_trust_certificate":
        return "application/x-pem-file"
    return "application/vnd.aegis.trivy.vulnerability-report+json"


def _parse_s3_ref(artifact_ref: str) -> tuple[str, str]:
    if not artifact_ref.startswith("s3://"):
        raise ValueError("artifact ref must use s3:// scheme")
    bucket_and_key = artifact_ref.removeprefix("s3://")
    bucket, separator, key = bucket_and_key.partition("/")
    if not bucket or not separator or not key:
        raise ValueError("artifact ref must include bucket and key")
    return bucket, key
