import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

from cryptography import x509

CERTIFICATE_CONTENT_TYPE = "application/x-pem-file"
CERTIFICATE_BLOCK_RE = re.compile(
    r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
    re.DOTALL,
)
PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CertificateBundleSummary:
    certificate_subject: str
    certificate_issuer: str
    certificate_not_before: datetime
    certificate_not_after: datetime
    certificate_count: int


def normalize_certificate_pem(certificate_pem: str) -> str:
    blocks = _certificate_blocks(certificate_pem)
    return "\n".join(block.strip() for block in blocks) + "\n"


def certificate_pem_sha256(certificate_pem: str) -> str:
    return hashlib.sha256(normalize_certificate_pem(certificate_pem).encode("utf-8")).hexdigest()


def summarize_certificate_bundle(certificate_pem: str) -> CertificateBundleSummary:
    certificates = [
        x509.load_pem_x509_certificate(block.encode("utf-8"))
        for block in _certificate_blocks(certificate_pem)
    ]
    first = certificates[0]
    not_before_values = [certificate.not_valid_before_utc for certificate in certificates]
    not_after_values = [certificate.not_valid_after_utc for certificate in certificates]
    return CertificateBundleSummary(
        certificate_subject=first.subject.rfc4514_string(),
        certificate_issuer=first.issuer.rfc4514_string(),
        certificate_not_before=max(not_before_values),
        certificate_not_after=min(not_after_values),
        certificate_count=len(certificates),
    )


def reject_private_key_material(certificate_pem: str) -> None:
    if PRIVATE_KEY_BLOCK_RE.search(certificate_pem) or "PRIVATE KEY" in certificate_pem.upper():
        raise ValueError("Private key material is not allowed in Notation trust certificates")


def _certificate_blocks(certificate_pem: str) -> list[str]:
    reject_private_key_material(certificate_pem)
    blocks = CERTIFICATE_BLOCK_RE.findall(certificate_pem)
    if not blocks:
        raise ValueError("Notation trust certificate bundle must contain PEM certificates")
    for block in blocks:
        try:
            x509.load_pem_x509_certificate(block.encode("utf-8"))
        except ValueError as exc:
            raise ValueError("Notation trust certificate bundle contains invalid PEM") from exc
    return blocks
