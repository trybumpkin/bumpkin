from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


def aggregate_results_from_json_dir(
    json_dir: Path, *, expected_cases: list[Any], result_factory: Callable[..., Any]
) -> tuple[list[Any], dict[str, Any]]:
    paths = sorted(json_dir.glob("*.json"))
    if not paths:
        raise ValueError(f"No JSON result files found in {json_dir}")
    aggregated = _read_result_files(paths, result_factory)
    aggregated.sort(key=lambda row: row.name)
    expected_names = {case.name for case in expected_cases}
    actual_names = {row.name for row in aggregated}
    missing_fixture_names = sorted(expected_names - actual_names)
    unexpected_fixture_names = sorted(actual_names - expected_names)
    return aggregated, {
        "baseline_coverage_complete": not missing_fixture_names and not unexpected_fixture_names,
        "missing_fixture_names": missing_fixture_names,
        "unexpected_fixture_names": unexpected_fixture_names,
    }


def _read_result_files(paths: list[Path], result_factory: Callable[..., Any]) -> list[Any]:
    aggregated: list[Any] = []
    seen_names: set[str] = set()
    duplicate_names: set[str] = set()
    for path in paths:
        payload = json.loads(path.read_text())
        for row in payload.get("results", []):
            name = str(row["name"])
            if name in seen_names:
                duplicate_names.add(name)
                continue
            seen_names.add(name)
            aggregated.append(
                result_factory(
                    name=name,
                    expected=row["expected"],
                    actual=row["actual"],
                    passed=bool(row["passed"]),
                    category=str(row["category"]),
                )
            )
    if duplicate_names:
        raise ValueError(
            f"Found duplicate fixture results in aggregate input: {', '.join(sorted(duplicate_names))}"
        )
    return aggregated
