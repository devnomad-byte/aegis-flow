import pytest
from backend.app.core.settings import AppSettings
from backend.app.model_gateway.openai_compatible import (
    OpenAICompatibleChatMessage,
    OpenAICompatibleModelGatewayClient,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_ai_provider,
]


def require_real_provider_settings() -> AppSettings:
    settings = AppSettings()
    if not settings.model_gateway.openai_compatible.has_auth_token:
        pytest.skip("OpenAI-compatible auth token is not configured")

    return settings


@pytest.mark.asyncio
async def test_real_openai_compatible_provider_returns_chat_completion() -> None:
    settings = require_real_provider_settings()
    client = OpenAICompatibleModelGatewayClient(settings.model_gateway.openai_compatible)

    response = await client.create_chat_completion(
        model=settings.model_gateway.default_model,
        messages=[
            OpenAICompatibleChatMessage(
                role="system",
                content="You are a terse integration-test assistant.",
            ),
            OpenAICompatibleChatMessage(
                role="user",
                content="Reply with exactly: aegis-flow-ok",
            ),
        ],
        temperature=0,
        max_tokens=16,
    )

    assert response.provider == "openai-compatible"
    assert response.model
    assert response.content.strip()
    assert "aegis-flow-ok" in response.content.lower()
    assert response.latency_ms >= 0
