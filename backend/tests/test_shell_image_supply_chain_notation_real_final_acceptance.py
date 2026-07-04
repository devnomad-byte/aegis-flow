import json
import os
import shutil

import pytest
from backend.app.tool_registry.image_evidence import NotationCliEvidenceProvider


@pytest.mark.final_acceptance
@pytest.mark.real_notation
@pytest.mark.asyncio
async def test_real_notation_cli_verifies_image_with_project_trust_policy() -> None:
    notation_command = os.environ.get("AEGIS_REAL_NOTATION_COMMAND", "notation")
    if shutil.which(notation_command) is None:
        pytest.fail("AEGIS_REAL_NOTATION=1 requires a real Notation CLI on PATH")

    image_ref = os.environ.get("AEGIS_REAL_NOTATION_IMAGE_REF", "").strip()
    image_digest = os.environ.get("AEGIS_REAL_NOTATION_IMAGE_DIGEST", "").strip()
    trust_policy_raw = os.environ.get("AEGIS_REAL_NOTATION_TRUST_POLICY_JSON", "").strip()
    missing_inputs = [
        name
        for name, value in {
            "AEGIS_REAL_NOTATION_IMAGE_REF": image_ref,
            "AEGIS_REAL_NOTATION_IMAGE_DIGEST": image_digest,
            "AEGIS_REAL_NOTATION_TRUST_POLICY_JSON": trust_policy_raw,
        }.items()
        if not value
    ]
    if missing_inputs:
        pytest.fail("AEGIS_REAL_NOTATION=1 missing inputs: " + ", ".join(missing_inputs))

    try:
        trust_policy = json.loads(trust_policy_raw)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"AEGIS_REAL_NOTATION_TRUST_POLICY_JSON must be valid JSON: {exc.__class__.__name__}"
        )

    provider = NotationCliEvidenceProvider(
        notation_command=notation_command,
        trust_policy=trust_policy,
        work_dir=os.environ.get(
            "AEGIS_REAL_NOTATION_WORK_DIR",
            r"D:\agent-platform-cache\notation-final-acceptance",
        ),
    )

    result = await provider.collect(image_ref=image_ref, image_digest=image_digest)

    assert result.signature_status == "passed"
    assert result.policy_decision == "approved"
    assert result.evidence["signature"] == {"tool": "notation", "status": "passed"}
