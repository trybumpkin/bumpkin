from __future__ import annotations

from typing import Any


def select_batch_cases(
    cases: list[Any], *, batch_size: int | None, batch_index: int
) -> tuple[list[Any], dict[str, Any]]:
    ordered = sorted(cases, key=lambda case: case.name)
    total_case_count = len(ordered)
    if not batch_size or batch_size <= 0:
        return ordered, _batch_metadata(0, total_case_count, ordered, total_case_count)
    if batch_index < 0:
        raise ValueError("batch_index must be >= 0")
    start = batch_index * batch_size
    if start >= total_case_count:
        return [], _batch_metadata(batch_index, batch_size, [], total_case_count, empty=True)
    selected = ordered[start : start + batch_size]
    return selected, _batch_metadata(batch_index, batch_size, selected, total_case_count)


def _batch_metadata(
    batch_index: int, batch_size: int, selected: list[Any], total: int, *, empty: bool = False
) -> dict[str, Any]:
    return {
        "batch_index": batch_index,
        "batch_size": batch_size,
        "batch_case_count": len(selected),
        "total_case_count": total,
        "is_subset_run": len(selected) != total,
        "is_empty_batch": empty or len(selected) == 0,
    }
