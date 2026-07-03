from datetime import UTC, datetime
from uuid import uuid4

from backend.app.tool_registry.schemas import CredentialAccessIntentRead, SecretLeaseRead


def test_credential_access_intent_read_model_never_contains_secret_value() -> None:
    now = datetime.now(UTC)

    intent = CredentialAccessIntentRead(
        id=uuid4(),
        project_id=uuid4(),
        credential_ref_id=uuid4(),
        credential_ref="vault://ops/k8s/readonly",
        actor_id=uuid4(),
        requester_type="tool_gateway",
        requester_ref="tool-call-123",
        purpose="sync k8s MCP tools",
        run_id="run-1",
        node_id="node-1",
        trace_id="trace-1",
        decision="recorded",
        denial_reason="",
        created_by=uuid4(),
        updated_by=uuid4(),
        created_at=now,
        updated_at=now,
    )

    payload = intent.model_dump(mode="json")

    assert payload["credential_ref"] == "vault://ops/k8s/readonly"
    assert "secret_value" not in payload
    assert "password" not in payload
    assert "api_key" not in payload


def test_secret_lease_read_model_never_contains_secret_value() -> None:
    now = datetime.now(UTC)

    lease = SecretLeaseRead(
        id=uuid4(),
        project_id=uuid4(),
        credential_ref_id=uuid4(),
        credential_ref="vault://ops/k8s/readonly",
        provider="external_vault",
        external_path="ops/k8s/readonly",
        lease_ref="lease_123",
        provider_lease_id="",
        requester_type="tool_gateway",
        requester_ref="mcp-k8s-test.kubectl_get_pods",
        purpose="invoke authorized MCP tool",
        run_id="run-1",
        node_id="node-1",
        trace_id="trace-1",
        ttl_seconds=900,
        expires_at=now,
        revoked_at=None,
        status="active",
        denial_reason="",
        created_by=uuid4(),
        updated_by=uuid4(),
        created_at=now,
        updated_at=now,
    )

    payload = lease.model_dump(mode="json")

    assert payload["lease_ref"] == "lease_123"
    assert "secret_value" not in payload
    assert "password" not in payload
    assert "api_key" not in payload
    assert "private_key" not in payload
