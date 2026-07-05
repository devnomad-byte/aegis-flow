from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_backend_verification_script_uses_backend_app_coverage() -> None:
    script = ROOT / "scripts" / "verify-backend.ps1"

    assert script.exists()
    content = script.read_text(encoding="utf-8")

    assert "Invoke-Step" in content
    assert "if ($LASTEXITCODE -ne 0)" in content
    assert "uv run pytest --cov=backend.app --cov-report=term-missing" in content
    assert "--cov=app" not in content
    assert "DB_PASSWORD" not in content


def test_readme_points_developers_to_standard_verification_scripts() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "scripts/verify-backend.ps1" in readme
    assert "pnpm --dir web test:e2e" in readme
    assert "PLAYWRIGHT_BROWSERS_PATH" in readme
