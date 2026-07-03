import re

_SECRET_KEY = r"(?:token|password|secret|api[_-]?key|auth[_-]?token)"
_JSON_SECRET_PAIR_PATTERN = re.compile(rf"(?i)[\"'](?:{_SECRET_KEY})[\"']\s*:\s*[\"'][^\"']+[\"']")
_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(\bbearer\s+)[^\s,;]+"),
    re.compile(rf"(?i)((?:{_SECRET_KEY})\s*=\s*)[^&\s,;]+"),
    re.compile(rf"(?i)((?:{_SECRET_KEY})\s*:\s*)[^&\s,;]+"),
    re.compile(r"(https?://)([^/\s:@]+):([^/\s@]+)@"),
]


def redact_sensitive_text(message: str) -> str:
    sanitized = _JSON_SECRET_PAIR_PATTERN.sub("[redacted]", message)
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.startswith("(https?://)"):
            sanitized = pattern.sub(r"\1[redacted]@", sanitized)
        else:
            sanitized = pattern.sub(r"\1[redacted]", sanitized)
    return sanitized
