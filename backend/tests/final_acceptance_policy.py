from collections.abc import Mapping, Sequence

REAL_DEPENDENCY_MARKERS = {
    "real_ai_provider",
    "real_database",
    "real_docker",
    "real_mcp",
}

_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def is_final_acceptance_mode(environment: Mapping[str, str]) -> bool:
    return environment.get("AEGIS_FINAL_ACCEPTANCE", "").strip().lower() in _TRUTHY_VALUES


def build_final_acceptance_skip_message(skipped_node_ids: Sequence[str]) -> str:
    listed_tests = ", ".join(skipped_node_ids)
    return f"final acceptance cannot skip real dependency tests: {listed_tests}"
