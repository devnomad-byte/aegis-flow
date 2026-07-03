from backend.app.core.settings import AppSettings
from backend.app.model_gateway.openai_compatible import (
    ModelGatewayError,
    OpenAICompatibleModelGatewaySettings,
    parse_chat_completion_response,
    redact_sensitive_text,
)
from pydantic import SecretStr
from pytest import MonkeyPatch


def test_openai_compatible_settings_read_local_ai_provider_environment(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://ai-provider.example.com")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-for-test")
    monkeypatch.setenv("MODEL_DEFAULT_MODEL", "gpt-5.5")

    settings = AppSettings()

    assert settings.model_gateway.default_provider == "openai-compatible"
    assert settings.model_gateway.default_model == "gpt-5.5"
    assert settings.model_gateway.openai_compatible.base_url == "https://ai-provider.example.com"
    assert isinstance(settings.model_gateway.openai_compatible.auth_token, SecretStr)

    rendered = repr(settings.model_gateway)
    assert "token-for-test" not in rendered
    assert "auth_token" not in rendered


def test_openai_compatible_settings_read_generic_provider_environment(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://provider.internal")
    monkeypatch.setenv("OPENAI_COMPATIBLE_AUTH_TOKEN", "generic-token-for-test")

    settings = AppSettings()

    assert settings.model_gateway.openai_compatible.base_url == "https://provider.internal"
    assert settings.model_gateway.openai_compatible.has_auth_token is True


def test_openai_compatible_settings_build_chat_completions_url() -> None:
    settings = OpenAICompatibleModelGatewaySettings(
        base_url="https://gateway.example.com/v1/",
        auth_token=SecretStr("token-for-test"),
    )

    assert settings.chat_completions_url == "https://gateway.example.com/v1/chat/completions"


def test_openai_compatible_settings_appends_v1_for_provider_root_url() -> None:
    settings = OpenAICompatibleModelGatewaySettings(
        base_url="https://ai-provider.example.com",
        auth_token=SecretStr("token-for-test"),
    )

    assert settings.chat_completions_url == "https://ai-provider.example.com/v1/chat/completions"


def test_redact_sensitive_text_removes_provider_tokens() -> None:
    message = (
        "upstream failed Authorization: Bearer secret-token-value "
        "api_key=abc123 password: hunter2 token=rawtoken"
    )

    redacted = redact_sensitive_text(message)

    assert "secret-token-value" not in redacted
    assert "abc123" not in redacted
    assert "hunter2" not in redacted
    assert "rawtoken" not in redacted
    assert "[redacted]" in redacted


def test_parse_chat_completion_response_rejects_sanitized_provider_error() -> None:
    try:
        parse_chat_completion_response(
            {
                "error": {
                    "message": "invalid api_key=abc123 for bearer secret-token-value",
                }
            },
            latency_ms=42,
        )
    except ModelGatewayError as exc:
        message = str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected ModelGatewayError")

    assert "abc123" not in message
    assert "secret-token-value" not in message
    assert "[redacted]" in message
