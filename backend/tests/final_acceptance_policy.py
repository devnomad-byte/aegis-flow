from collections.abc import Mapping, Sequence

REAL_DEPENDENCY_MARKERS = {
    "real_ai_provider",
    "real_database",
    "real_docker",
    "real_mcp",
}

REAL_DEPENDENCY_ENV_FLAGS = {
    "real_ai_provider": "AEGIS_REAL_AI_PROVIDER",
    "real_database": "AEGIS_REAL_DATABASE",
    "real_docker": "AEGIS_REAL_DOCKER",
    "real_mcp": "AEGIS_REAL_MCP",
}

_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def is_final_acceptance_mode(environment: Mapping[str, str]) -> bool:
    return environment.get("AEGIS_FINAL_ACCEPTANCE", "").strip().lower() in _TRUTHY_VALUES


def missing_real_dependency_flags(
    marker_names: set[str],
    environment: Mapping[str, str],
) -> dict[str, str]:
    missing = {}
    for marker_name in sorted(REAL_DEPENDENCY_MARKERS & marker_names):
        env_name = REAL_DEPENDENCY_ENV_FLAGS[marker_name]
        if environment.get(env_name, "").strip().lower() not in _TRUTHY_VALUES:
            missing[marker_name] = env_name
    return missing


def should_skip_final_acceptance_test(
    marker_names: set[str],
    environment: Mapping[str, str],
) -> bool:
    if "final_acceptance" not in marker_names:
        return False
    if is_final_acceptance_mode(environment):
        return False
    return bool(missing_real_dependency_flags(marker_names, environment))


def build_final_acceptance_skip_reason(missing_flags: Mapping[str, str]) -> str:
    required_flags = ", ".join(sorted(set(missing_flags.values())))
    return (
        "final acceptance test requires AEGIS_FINAL_ACCEPTANCE=1 "
        f"or explicit real dependency flags: {required_flags}"
    )


def build_final_acceptance_skip_message(skipped_node_ids: Sequence[str]) -> str:
    listed_tests = ", ".join(skipped_node_ids)
    return f"final acceptance cannot skip real dependency tests: {listed_tests}"
