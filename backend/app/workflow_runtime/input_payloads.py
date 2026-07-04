import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr


class WorkflowInputPayloadError(ValueError):
    pass


class WorkflowInputEncryptor:
    def __init__(self, *, secret: SecretStr, key_ref: str) -> None:
        raw_secret = secret.get_secret_value().strip()
        if not raw_secret:
            raise WorkflowInputPayloadError("workflow queue encryption secret is required")
        key = base64.urlsafe_b64encode(hashlib.sha256(raw_secret.encode("utf-8")).digest())
        self._fernet = Fernet(key)
        self.key_ref = key_ref

    def encrypt(self, payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return self._fernet.encrypt(encoded).decode("ascii")

    def decrypt(self, ciphertext: str, *, key_ref: str) -> dict[str, Any]:
        if key_ref != self.key_ref:
            raise WorkflowInputPayloadError(
                "workflow queue encryption key reference is unsupported"
            )
        try:
            decoded = self._fernet.decrypt(ciphertext.encode("ascii"))
        except (InvalidToken, UnicodeEncodeError) as exc:
            raise WorkflowInputPayloadError(
                "workflow queue input payload cannot be decrypted"
            ) from exc
        value = json.loads(decoded.decode("utf-8"))
        if not isinstance(value, dict):
            raise WorkflowInputPayloadError(
                "workflow queue input payload must decrypt to an object"
            )
        return value


def redact_sensitive_runtime_inputs(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            str(key): redact_sensitive_runtime_inputs(item, parent_key=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_runtime_inputs(item, parent_key=parent_key) for item in value]
    if isinstance(value, str) and _is_sensitive_input_key(parent_key):
        return "[redacted]"
    return value


def runtime_safe_inputs(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = redact_sensitive_runtime_inputs(payload)
    return sanitized if isinstance(sanitized, dict) else {}


def _is_sensitive_input_key(key: str) -> bool:
    normalized = key.lower()
    return any(
        token in normalized
        for token in {
            "api_key",
            "apikey",
            "auth_token",
            "authorization",
            "bearer",
            "password",
            "secret",
            "token",
        }
    )
