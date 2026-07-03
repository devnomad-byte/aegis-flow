import tomllib
from pathlib import Path

from backend.tests.final_acceptance_policy import (
    REAL_DEPENDENCY_MARKERS,
    build_final_acceptance_skip_message,
    is_final_acceptance_mode,
)


def test_final_acceptance_mode_requires_explicit_environment_flag() -> None:
    assert is_final_acceptance_mode({"AEGIS_FINAL_ACCEPTANCE": "1"}) is True
    assert is_final_acceptance_mode({"AEGIS_FINAL_ACCEPTANCE": "true"}) is True
    assert is_final_acceptance_mode({"AEGIS_FINAL_ACCEPTANCE": "yes"}) is True
    assert is_final_acceptance_mode({"AEGIS_FINAL_ACCEPTANCE": "0"}) is False
    assert is_final_acceptance_mode({}) is False


def test_final_acceptance_skip_message_names_skipped_real_tests() -> None:
    message = build_final_acceptance_skip_message(
        [
            "backend/tests/test_shell_runner_docker_integration.py::test_sandbox_runs",
            "backend/tests/test_model_gateway_real_provider_integration.py::test_real_provider",
        ]
    )

    assert "final acceptance cannot skip real dependency tests" in message
    assert "test_sandbox_runs" in message
    assert "test_real_provider" in message


def test_pytest_final_acceptance_markers_are_registered() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    markers = config["tool"]["pytest"]["ini_options"]["markers"]
    marker_names = {marker.split(":", maxsplit=1)[0] for marker in markers}

    assert "final_acceptance" in marker_names
    assert marker_names >= REAL_DEPENDENCY_MARKERS


def test_final_acceptance_tests_declare_real_dependency_marker() -> None:
    final_acceptance_files = []
    missing_real_marker = []

    for path in Path("backend/tests").glob("test_*.py"):
        if path.name == "test_final_acceptance_policy.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "pytest.mark.final_acceptance" not in text:
            continue
        final_acceptance_files.append(path.as_posix())
        if not any(f"pytest.mark.{marker}" in text for marker in REAL_DEPENDENCY_MARKERS):
            missing_real_marker.append(path.as_posix())

    assert final_acceptance_files
    assert missing_real_marker == []
