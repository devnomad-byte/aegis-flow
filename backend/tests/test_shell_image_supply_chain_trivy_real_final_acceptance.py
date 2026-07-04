import os
import shutil

import pytest
from backend.app.tool_registry.image_evidence import TrivyCliEvidenceProvider

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_trivy,
]


def require_real_trivy_final_acceptance() -> None:
    if os.environ.get("AEGIS_FINAL_ACCEPTANCE", "").lower() in {"1", "true", "yes"}:
        return
    if os.environ.get("AEGIS_REAL_TRIVY") == "1":
        return
    pytest.skip("real Trivy final acceptance is not enabled")


@pytest.mark.asyncio
async def test_real_trivy_provider_scans_image_for_sbom_and_vulnerabilities() -> None:
    require_real_trivy_final_acceptance()
    trivy_command = os.environ.get("TRIVY_COMMAND", "trivy")
    if shutil.which(trivy_command) is None:
        pytest.fail("AEGIS_REAL_TRIVY is enabled but Trivy executable is not available")

    image_ref = os.environ.get("AEGIS_REAL_TRIVY_IMAGE", "redis:7-alpine")
    provider = TrivyCliEvidenceProvider(trivy_command=trivy_command, timeout_seconds=180)

    result = await provider.collect(
        image_ref=image_ref,
        image_digest="sha256:" + ("f" * 64),
    )

    assert result.sbom_status == "passed"
    assert result.vulnerability_status in {"passed", "failed"}
    assert result.evidence["sbom"]["component_count"] > 0
    assert "vulnerabilities" in result.evidence
