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


@dataclass(frozen=True)
class ShellImageArtifactRetentionControls:
    bucket: str
    versioning_status: str = "unknown"
    object_lock_enabled: bool = False
    worm_capable: bool = False
    default_retention_configured: bool = False
    default_retention_mode: str | None = None
    default_retention_days: int | None = None
    default_retention_years: int | None = None
    error: str = ""


@dataclass(frozen=True)
class ShellImageArtifactLifecycleControls:
    bucket: str
    checked_prefixes: list[str]
    lifecycle_configured: bool = False
    matched_rule_ids: list[str] | None = None
    noncurrent_version_expiration_configured: bool = False
    delete_marker_expiration_configured: bool = False
    error: str = ""


@dataclass(frozen=True)
class ShellImageArtifactVersionReconciliation:
    bucket: str
    checked_prefixes: list[str]
    current_version_count: int = 0
    noncurrent_version_count: int = 0
    delete_marker_count: int = 0
    error: str = ""


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

    async def inspect_retention_controls(self) -> ShellImageArtifactRetentionControls:
        raise NotImplementedError

    async def inspect_lifecycle_controls(
        self,
        prefixes: list[str],
    ) -> ShellImageArtifactLifecycleControls:
        raise NotImplementedError

    async def inspect_version_reconciliation(
        self,
        prefixes: list[str],
    ) -> ShellImageArtifactVersionReconciliation:
        raise NotImplementedError


class InMemoryShellImageArtifactObjectStore:
    def __init__(
        self,
        *,
        bucket: str = "aegis-flow",
        versioning_status: str = "Suspended",
        object_lock_enabled: bool = False,
        default_retention_mode: str | None = None,
        default_retention_days: int | None = None,
        default_retention_years: int | None = None,
        retention_error: str = "",
        lifecycle_rules: list[dict[str, Any]] | None = None,
        lifecycle_error: str = "",
        version_reconciliation: dict[str, dict[str, int]] | None = None,
        version_reconciliation_error: str = "",
    ) -> None:
        self.bucket = bucket
        self.versioning_status = versioning_status
        self.object_lock_enabled = object_lock_enabled
        self.default_retention_mode = default_retention_mode
        self.default_retention_days = default_retention_days
        self.default_retention_years = default_retention_years
        self.retention_error = retention_error
        self.lifecycle_rules = lifecycle_rules or []
        self.lifecycle_error = lifecycle_error
        self.version_reconciliation = version_reconciliation or {}
        self.version_reconciliation_error = version_reconciliation_error
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
        _validate_artifact_ref_bucket(artifact_ref, self.bucket)
        stored = self.objects[artifact_ref]
        return ShellImageArtifactMetadata(
            size_bytes=len(stored.body),
            content_type=stored.content_type,
            metadata=stored.metadata,
        )

    async def get_artifact(self, artifact_ref: str) -> StoredShellImageArtifact:
        _validate_artifact_ref_bucket(artifact_ref, self.bucket)
        return self.objects[artifact_ref]

    async def delete_artifact(self, artifact_ref: str) -> None:
        _validate_artifact_ref_bucket(artifact_ref, self.bucket)
        del self.objects[artifact_ref]

    async def inspect_retention_controls(self) -> ShellImageArtifactRetentionControls:
        default_retention_configured = _default_retention_configured(
            mode=self.default_retention_mode,
            days=self.default_retention_days,
            years=self.default_retention_years,
        )
        return ShellImageArtifactRetentionControls(
            bucket=self.bucket,
            versioning_status=self.versioning_status,
            object_lock_enabled=self.object_lock_enabled,
            worm_capable=self.object_lock_enabled and self.versioning_status == "Enabled",
            default_retention_configured=self.object_lock_enabled and default_retention_configured,
            default_retention_mode=self.default_retention_mode,
            default_retention_days=self.default_retention_days,
            default_retention_years=self.default_retention_years,
            error=self.retention_error,
        )

    async def inspect_lifecycle_controls(
        self,
        prefixes: list[str],
    ) -> ShellImageArtifactLifecycleControls:
        if self.lifecycle_error:
            return ShellImageArtifactLifecycleControls(
                bucket=self.bucket,
                checked_prefixes=prefixes,
                error=self.lifecycle_error,
            )
        matched_rule_ids: list[str] = []
        noncurrent_configured = False
        delete_marker_configured = False
        for rule in self.lifecycle_rules:
            rule_prefix = _lifecycle_rule_prefix(rule)
            if str(rule.get("Status") or "") != "Enabled":
                continue
            if not _lifecycle_rule_matches_prefixes(rule_prefix, prefixes):
                continue
            matched_rule_ids.append(str(rule.get("ID") or "unnamed"))
            noncurrent_configured = noncurrent_configured or isinstance(
                rule.get("NoncurrentVersionExpiration"),
                dict,
            )
            expiration = rule.get("Expiration")
            if isinstance(expiration, dict):
                delete_marker_configured = (
                    delete_marker_configured
                    or bool(expiration.get("ExpiredObjectDeleteMarker"))
                    or isinstance(expiration.get("Days"), int)
                )
        return ShellImageArtifactLifecycleControls(
            bucket=self.bucket,
            checked_prefixes=prefixes,
            lifecycle_configured=bool(matched_rule_ids),
            matched_rule_ids=matched_rule_ids,
            noncurrent_version_expiration_configured=noncurrent_configured,
            delete_marker_expiration_configured=delete_marker_configured,
        )

    async def inspect_version_reconciliation(
        self,
        prefixes: list[str],
    ) -> ShellImageArtifactVersionReconciliation:
        if self.version_reconciliation_error:
            return ShellImageArtifactVersionReconciliation(
                bucket=self.bucket,
                checked_prefixes=prefixes,
                error=self.version_reconciliation_error,
            )
        current = 0
        noncurrent = 0
        delete_markers = 0
        for prefix in prefixes:
            configured = self.version_reconciliation.get(prefix)
            if configured is None:
                matching_refs = [
                    artifact_ref
                    for artifact_ref in self.objects
                    if artifact_ref.startswith(f"s3://{self.bucket}/{prefix}")
                ]
                current += len(matching_refs)
                continue
            current += int(configured.get("current_version_count", 0))
            noncurrent += int(configured.get("noncurrent_version_count", 0))
            delete_markers += int(configured.get("delete_marker_count", 0))
        return ShellImageArtifactVersionReconciliation(
            bucket=self.bucket,
            checked_prefixes=prefixes,
            current_version_count=current,
            noncurrent_version_count=noncurrent,
            delete_marker_count=delete_markers,
        )


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

        bucket, key = _parse_expected_bucket_s3_ref(artifact_ref, self._settings.bucket)
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

        bucket, key = _parse_expected_bucket_s3_ref(artifact_ref, self._settings.bucket)
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

        bucket, key = _parse_expected_bucket_s3_ref(artifact_ref, self._settings.bucket)
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self._settings.endpoint,
            region_name=self._settings.region,
            aws_access_key_id=self._settings.access_key.get_secret_value(),
            aws_secret_access_key=self._settings.secret_key.get_secret_value(),
        ) as client:
            await client.delete_object(Bucket=bucket, Key=key)

    async def inspect_retention_controls(self) -> ShellImageArtifactRetentionControls:
        import aioboto3
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]

        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self._settings.endpoint,
            region_name=self._settings.region,
            aws_access_key_id=self._settings.access_key.get_secret_value(),
            aws_secret_access_key=self._settings.secret_key.get_secret_value(),
        ) as client:
            try:
                versioning_response = await client.get_bucket_versioning(
                    Bucket=self._settings.bucket
                )
                versioning_status = str(versioning_response.get("Status") or "Suspended")
            except ClientError as exc:
                return ShellImageArtifactRetentionControls(
                    bucket=self._settings.bucket,
                    error=_public_s3_error(exc),
                )
            try:
                lock_response = await client.get_object_lock_configuration(
                    Bucket=self._settings.bucket
                )
            except ClientError as exc:
                if _s3_error_code(exc) == "ObjectLockConfigurationNotFoundError":
                    return ShellImageArtifactRetentionControls(
                        bucket=self._settings.bucket,
                        versioning_status=versioning_status,
                    )
                return ShellImageArtifactRetentionControls(
                    bucket=self._settings.bucket,
                    versioning_status=versioning_status,
                    error=_public_s3_error(exc),
                )
        configuration = lock_response.get("ObjectLockConfiguration", {})
        enabled = configuration.get("ObjectLockEnabled") == "Enabled"
        default_retention = (
            configuration.get("Rule", {}).get("DefaultRetention", {})
            if isinstance(configuration.get("Rule"), dict)
            else {}
        )
        default_retention_configured = _default_retention_configured(
            mode=default_retention.get("Mode"),
            days=default_retention.get("Days"),
            years=default_retention.get("Years"),
        )
        return ShellImageArtifactRetentionControls(
            bucket=self._settings.bucket,
            versioning_status=versioning_status,
            object_lock_enabled=enabled,
            worm_capable=enabled and versioning_status == "Enabled",
            default_retention_configured=enabled and default_retention_configured,
            default_retention_mode=default_retention.get("Mode"),
            default_retention_days=default_retention.get("Days"),
            default_retention_years=default_retention.get("Years"),
        )

    async def inspect_lifecycle_controls(
        self,
        prefixes: list[str],
    ) -> ShellImageArtifactLifecycleControls:
        import aioboto3
        from botocore.exceptions import ClientError

        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self._settings.endpoint,
            region_name=self._settings.region,
            aws_access_key_id=self._settings.access_key.get_secret_value(),
            aws_secret_access_key=self._settings.secret_key.get_secret_value(),
        ) as client:
            try:
                response = await client.get_bucket_lifecycle_configuration(
                    Bucket=self._settings.bucket
                )
            except ClientError as exc:
                if _s3_error_code(exc) == "NoSuchLifecycleConfiguration":
                    return ShellImageArtifactLifecycleControls(
                        bucket=self._settings.bucket,
                        checked_prefixes=prefixes,
                    )
                return ShellImageArtifactLifecycleControls(
                    bucket=self._settings.bucket,
                    checked_prefixes=prefixes,
                    error=_public_s3_error(exc),
                )
        matched_rule_ids: list[str] = []
        noncurrent_configured = False
        delete_marker_configured = False
        for rule in response.get("Rules", []):
            if not isinstance(rule, dict) or rule.get("Status") != "Enabled":
                continue
            rule_prefix = _lifecycle_rule_prefix(rule)
            if not _lifecycle_rule_matches_prefixes(rule_prefix, prefixes):
                continue
            matched_rule_ids.append(str(rule.get("ID") or "unnamed"))
            noncurrent_configured = noncurrent_configured or isinstance(
                rule.get("NoncurrentVersionExpiration"),
                dict,
            )
            expiration = rule.get("Expiration")
            if isinstance(expiration, dict):
                delete_marker_configured = (
                    delete_marker_configured
                    or bool(expiration.get("ExpiredObjectDeleteMarker"))
                    or isinstance(expiration.get("Days"), int)
                )
        return ShellImageArtifactLifecycleControls(
            bucket=self._settings.bucket,
            checked_prefixes=prefixes,
            lifecycle_configured=bool(matched_rule_ids),
            matched_rule_ids=matched_rule_ids,
            noncurrent_version_expiration_configured=noncurrent_configured,
            delete_marker_expiration_configured=delete_marker_configured,
        )

    async def inspect_version_reconciliation(
        self,
        prefixes: list[str],
    ) -> ShellImageArtifactVersionReconciliation:
        import aioboto3
        from botocore.exceptions import ClientError

        current_count = 0
        noncurrent_count = 0
        delete_marker_count = 0
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=self._settings.endpoint,
            region_name=self._settings.region,
            aws_access_key_id=self._settings.access_key.get_secret_value(),
            aws_secret_access_key=self._settings.secret_key.get_secret_value(),
        ) as client:
            try:
                for prefix in prefixes:
                    key_marker: str | None = None
                    version_id_marker: str | None = None
                    while True:
                        kwargs: dict[str, object] = {
                            "Bucket": self._settings.bucket,
                            "Prefix": prefix,
                            "MaxKeys": 1000,
                        }
                        if key_marker:
                            kwargs["KeyMarker"] = key_marker
                        if version_id_marker:
                            kwargs["VersionIdMarker"] = version_id_marker
                        response = await client.list_object_versions(**kwargs)
                        for version in response.get("Versions", []):
                            if not isinstance(version, dict):
                                continue
                            if version.get("IsLatest") is True:
                                current_count += 1
                            else:
                                noncurrent_count += 1
                        delete_marker_count += sum(
                            1
                            for marker in response.get("DeleteMarkers", [])
                            if isinstance(marker, dict)
                        )
                        if not response.get("IsTruncated"):
                            break
                        key_marker = response.get("NextKeyMarker")
                        version_id_marker = response.get("NextVersionIdMarker")
                        if not isinstance(key_marker, str):
                            break
                        if version_id_marker is not None and not isinstance(
                            version_id_marker,
                            str,
                        ):
                            version_id_marker = None
            except ClientError as exc:
                return ShellImageArtifactVersionReconciliation(
                    bucket=self._settings.bucket,
                    checked_prefixes=prefixes,
                    error=_public_s3_error(exc),
                )
        return ShellImageArtifactVersionReconciliation(
            bucket=self._settings.bucket,
            checked_prefixes=prefixes,
            current_version_count=current_count,
            noncurrent_version_count=noncurrent_count,
            delete_marker_count=delete_marker_count,
        )


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


def _parse_expected_bucket_s3_ref(artifact_ref: str, expected_bucket: str) -> tuple[str, str]:
    bucket, key = _parse_s3_ref(artifact_ref)
    if bucket != expected_bucket:
        raise ValueError("artifact ref bucket is outside configured bucket")
    return bucket, key


def _validate_artifact_ref_bucket(artifact_ref: str, expected_bucket: str) -> None:
    _parse_expected_bucket_s3_ref(artifact_ref, expected_bucket)


def _default_retention_configured(
    *,
    mode: object,
    days: object,
    years: object,
) -> bool:
    return (
        isinstance(mode, str) and bool(mode) and (isinstance(days, int) or isinstance(years, int))
    )


def _lifecycle_rule_prefix(rule: dict[str, Any]) -> str:
    filter_value = rule.get("Filter")
    if isinstance(filter_value, dict):
        prefix = filter_value.get("Prefix")
        if isinstance(prefix, str):
            return prefix
        and_value = filter_value.get("And")
        if isinstance(and_value, dict) and isinstance(and_value.get("Prefix"), str):
            return str(and_value["Prefix"])
    prefix = rule.get("Prefix")
    if isinstance(prefix, str):
        return prefix
    return ""


def _lifecycle_rule_matches_prefixes(rule_prefix: str, prefixes: list[str]) -> bool:
    return any(
        prefix.startswith(rule_prefix) or rule_prefix.startswith(prefix) for prefix in prefixes
    )


def _public_s3_error(exc: Exception) -> str:
    code = _s3_error_code(exc)
    return code[:120]


def _s3_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", {})
    error = response.get("Error", {}) if isinstance(response, dict) else {}
    return str(error.get("Code") or exc.__class__.__name__)
