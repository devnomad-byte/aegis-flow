from backend.app.core.settings import AppSettings
from pytest import MonkeyPatch
from sqlalchemy.engine import make_url


def test_settings_use_safe_defaults() -> None:
    settings = AppSettings()

    assert settings.app_name == "AegisFlow API"
    assert settings.app_version == "0.1.0"
    assert settings.database.host == "localhost"
    assert settings.redis.database == 0
    assert settings.s3.bucket == "aegis-flow"
    assert settings.milvus.uri == "http://localhost:19530"


def test_settings_read_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DB_HOST", "db.internal")
    monkeypatch.setenv("REDIS_DATABASE", "3")
    monkeypatch.setenv("S3_BUCKET", "private-bucket")

    settings = AppSettings()

    assert settings.database.host == "db.internal"
    assert settings.redis.database == 3
    assert settings.s3.bucket == "private-bucket"


def test_shell_image_supply_chain_settings_parse_blocked_severities(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHELL_IMAGE_SUPPLY_CHAIN_TRIVY_ENABLED", "true")
    monkeypatch.setenv(
        "SHELL_IMAGE_SUPPLY_CHAIN_TRIVY_CACHE_DIR",
        r"D:\agent-platform-cache\trivy-test",
    )
    monkeypatch.setenv("SHELL_IMAGE_SUPPLY_CHAIN_COSIGN_ENABLED", "true")
    monkeypatch.setenv(
        "SHELL_IMAGE_SUPPLY_CHAIN_COSIGN_CERTIFICATE_IDENTITY",
        "workflow@aegis-flow.internal",
    )
    monkeypatch.setenv(
        "SHELL_IMAGE_SUPPLY_CHAIN_COSIGN_CERTIFICATE_OIDC_ISSUER",
        "https://issuer.internal",
    )
    monkeypatch.setenv("SHELL_IMAGE_SUPPLY_CHAIN_BLOCKED_SEVERITIES", "critical, high")

    settings = AppSettings()

    assert settings.shell_image_supply_chain.trivy_enabled is True
    assert (
        settings.shell_image_supply_chain.trivy_cache_dir == r"D:\agent-platform-cache\trivy-test"
    )
    assert settings.shell_image_supply_chain.cosign_enabled is True
    assert (
        settings.shell_image_supply_chain.cosign_certificate_identity
        == "workflow@aegis-flow.internal"
    )
    assert (
        settings.shell_image_supply_chain.cosign_certificate_oidc_issuer
        == "https://issuer.internal"
    )
    assert settings.shell_image_supply_chain.blocked_severity_set == frozenset({"CRITICAL", "HIGH"})


def test_secret_values_are_not_shown_in_repr() -> None:
    settings = AppSettings()

    rendered = repr(settings)

    assert "change-me" not in rendered
    assert "password" not in rendered.lower()


def test_database_url_escapes_secret_characters(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PASSWORD", "not-a-secret@2026!")

    settings = AppSettings()
    url = make_url(settings.database.sqlalchemy_url)

    assert url.host == "localhost"
    assert url.password == "not-a-secret@2026!"


def test_database_settings_build_psycopg_url_for_langgraph_checkpointer(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("DB_PASSWORD", "not-a-secret@2026!")

    settings = AppSettings()
    url = make_url(settings.database.psycopg_url)

    assert url.drivername == "postgresql"
    assert url.host == "localhost"
    assert url.password == "not-a-secret@2026!"
