import os
from typing import Any

import pytest
from backend.tests.final_acceptance_policy import (
    REAL_DEPENDENCY_MARKERS,
    build_final_acceptance_skip_message,
    build_final_acceptance_skip_reason,
    is_final_acceptance_mode,
    missing_real_dependency_flags,
    should_skip_final_acceptance_test,
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    missing_real_dependency_node_ids = []
    for item in items:
        marker_names = {marker.name for marker in item.iter_markers()}
        if "final_acceptance" not in marker_names:
            continue
        if REAL_DEPENDENCY_MARKERS.isdisjoint(marker_names):
            missing_real_dependency_node_ids.append(item.nodeid)
            continue
        if should_skip_final_acceptance_test(marker_names, os.environ):
            item.add_marker(
                pytest.mark.skip(
                    reason=build_final_acceptance_skip_reason(
                        missing_real_dependency_flags(marker_names, os.environ)
                    )
                )
            )

    if missing_real_dependency_node_ids:
        raise pytest.UsageError(
            "final_acceptance tests must declare a real dependency marker: "
            + ", ".join(missing_real_dependency_node_ids)
        )


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    if not is_final_acceptance_mode(os.environ):
        return

    skipped_final_acceptance_tests = [
        report.nodeid
        for report in terminalreporter.stats.get("skipped", [])
        if "final_acceptance" in getattr(report, "keywords", {})
    ]
    if skipped_final_acceptance_tests:
        raise pytest.UsageError(build_final_acceptance_skip_message(skipped_final_acceptance_tests))
