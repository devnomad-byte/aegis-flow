import re
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.app.core.settings import OpenAICompatibleSettings

JsonObject = dict[str, Any]
ChatRole = Literal["system", "user", "assistant", "tool"]

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(\bbearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:token|password|secret|api[_-]?key|auth[_-]?token)\s*=\s*)[^&\s,;]+"),
    re.compile(r"(?i)((?:token|password|secret|api[_-]?key|auth[_-]?token)\s*:\s*)[^&\s,;]+"),
    re.compile(r"(https?://)([^/\s:@]+):([^/\s@]+)@"),
]


class ModelGatewayError(RuntimeError):
    """Raised when a model provider request fails."""


class OpenAICompatibleModelGatewaySettings(OpenAICompatibleSettings):
    """Settings alias kept with the Model Gateway adapter for tests and callers."""


class OpenAICompatibleChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: ChatRole
    content: str


class OpenAICompatibleChatCompletion(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "openai-compatible"
    model: str
    content: str
    finish_reason: str = ""
    usage: JsonObject = Field(default_factory=dict)
    latency_ms: int


@dataclass(frozen=True)
class OpenAICompatibleModelGatewayClient:
    settings: OpenAICompatibleSettings

    async def create_chat_completion(
        self,
        *,
        model: str,
        messages: list[OpenAICompatibleChatMessage],
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> OpenAICompatibleChatCompletion:
        if not self.settings.has_auth_token:
            raise ModelGatewayError("OpenAI-compatible auth token is not configured")

        payload: JsonObject = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "authorization": f"Bearer {self.settings.auth_token.get_secret_value()}",
            "content-type": "application/json",
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
                response = await client.post(
                    self.settings.chat_completions_url,
                    headers=headers,
                    json=payload,
                )
            response.raise_for_status()
            response_payload = response.json()
        except httpx.HTTPError as exc:
            raise ModelGatewayError(redact_sensitive_text(str(exc))) from exc
        except ValueError as exc:
            raise ModelGatewayError("Invalid OpenAI-compatible JSON response") from exc

        latency_ms = max(0, int((time.perf_counter() - started) * 1000))
        return parse_chat_completion_response(response_payload, latency_ms=latency_ms)


def parse_chat_completion_response(
    payload: JsonObject,
    *,
    latency_ms: int,
) -> OpenAICompatibleChatCompletion:
    error = payload.get("error")
    if isinstance(error, dict):
        error_message = str(error.get("message") or "OpenAI-compatible chat completion failed")
        raise ModelGatewayError(redact_sensitive_text(error_message))

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelGatewayError("OpenAI-compatible response missing choices")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ModelGatewayError("OpenAI-compatible choice must be an object")

    raw_message = first_choice.get("message")
    if not isinstance(raw_message, dict):
        raise ModelGatewayError("OpenAI-compatible choice missing message")
    response_message: JsonObject = raw_message

    raw_content = response_message.get("content")
    if not isinstance(raw_content, str):
        raise ModelGatewayError("OpenAI-compatible message content must be a string")
    content: str = raw_content

    model = payload.get("model")
    if not isinstance(model, str) or not model:
        model = "unknown"

    finish_reason = first_choice.get("finish_reason")
    if not isinstance(finish_reason, str):
        finish_reason = ""

    usage = payload.get("usage")
    if not isinstance(usage, dict):
        usage = {}

    return OpenAICompatibleChatCompletion(
        model=model,
        content=content,
        finish_reason=finish_reason,
        usage=dict(usage),
        latency_ms=latency_ms,
    )


def redact_sensitive_text(message: str) -> str:
    sanitized = message
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.startswith("(https?://)"):
            sanitized = pattern.sub(r"\1[redacted]@", sanitized)
        else:
            sanitized = pattern.sub(r"\1[redacted]", sanitized)
    return sanitized
