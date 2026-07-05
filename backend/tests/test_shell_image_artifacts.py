import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from backend.app.core.settings import S3Settings
from backend.app.tool_registry.image_artifacts import (
    InMemoryShellImageArtifactObjectStore,
    ShellImageArtifactWriter,
    build_shell_image_artifact_object_store,
)


@pytest.mark.asyncio
async def test_shell_image_artifact_writer_stores_json_and_returns_descriptor_only() -> None:
    project_id = uuid4()
    now = datetime(2026, 7, 5, 8, 30, tzinfo=UTC)
    object_store = InMemoryShellImageArtifactObjectStore(bucket="capievo")
    writer = ShellImageArtifactWriter(
        project_id=project_id,
        object_store=object_store,
        artifact_store_prefix="shell-image-admissions/prod",
        retention_days=7,
        clock=lambda: now,
    )
    raw_report = {
        "bomFormat": "CycloneDX",
        "components": [{"name": "openssl", "version": "3.0.0"}],
    }

    descriptor = await writer.write_json_artifact(
        kind="sbom",
        image_ref="registry.example/aegis/runtime:7-alpine",
        image_digest="sha256:" + ("a" * 64),
        payload=raw_report,
    )

    expected_payload = (
        b'{"bomFormat":"CycloneDX","components":[{"name":"openssl","version":"3.0.0"}]}'
    )
    assert descriptor == {
        "artifact_ref": descriptor["artifact_ref"],
        "artifact_sha256": hashlib.sha256(expected_payload).hexdigest(),
        "artifact_size_bytes": len(expected_payload),
        "artifact_content_type": "application/vnd.cyclonedx+json",
        "artifact_retention_days": 7,
        "artifact_retention_expires_at": (now + timedelta(days=7)).isoformat(),
    }
    artifact_ref = str(descriptor["artifact_ref"])
    assert artifact_ref.startswith(
        f"s3://capievo/shell-image-admissions/prod/{project_id}/2026/07/05/aaaaaaaaaaaa/"
    )
    stored = object_store.objects[artifact_ref]
    assert stored.body == expected_payload
    assert stored.metadata["artifact-kind"] == "sbom"
    assert stored.metadata["image-digest"] == "sha256:" + ("a" * 64)
    assert "openssl" not in str(descriptor)


def test_shell_image_artifact_object_store_uses_in_memory_when_s3_disabled() -> None:
    object_store = build_shell_image_artifact_object_store(
        S3Settings(enabled=False, bucket="capievo")
    )

    assert isinstance(object_store, InMemoryShellImageArtifactObjectStore)
