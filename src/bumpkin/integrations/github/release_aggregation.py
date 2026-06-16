from __future__ import annotations

from dataclasses import dataclass

from bumpkin.integrations.github.persistence import ReleaseBacklogItem

_LABEL_PRECEDENCE = {
    "NO_BUMP": 0,
    "PATCH": 1,
    "MINOR": 2,
    "MAJOR": 3,
}


@dataclass(frozen=True, slots=True)
class ReleaseBacklogAggregate:
    item_count: int
    considered_item_count: int
    considered_item_ids: tuple[int, ...]
    aggregated_label: str | None
    recommended_label: str | None
    baseline_version: str | None
    current_version: str | None
    next_version: str | None
    target_merge_commit_sha: str | None


def _normalize_label(label: str) -> str | None:
    normalized = label.strip().upper().replace("-", "_").replace(" ", "_")
    if normalized == "NOBUMP":
        normalized = "NO_BUMP"
    if normalized in _LABEL_PRECEDENCE:
        return normalized
    return None


def _version_parts(version: str) -> tuple[int, int, int] | None:
    normalized = version.strip().removeprefix("v")
    parts = normalized.split(".")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def _format_version(parts: tuple[int, int, int]) -> str:
    return f"{parts[0]}.{parts[1]}.{parts[2]}"


def _bump_parts(parts: tuple[int, int, int], label: str) -> tuple[int, int, int]:
    major, minor, patch = parts
    if label == "MAJOR":
        if major == 0:
            return (0, minor + 1, 0)
        return (major + 1, 0, 0)
    if label == "MINOR":
        return (major, minor + 1, 0)
    if label == "NO_BUMP":
        return (major, minor, patch)
    return (major, minor, patch + 1)


def aggregate_release_backlog(items: list[ReleaseBacklogItem]) -> ReleaseBacklogAggregate:
    if not items:
        return ReleaseBacklogAggregate(
            item_count=0,
            considered_item_count=0,
            considered_item_ids=(),
            aggregated_label=None,
            recommended_label=None,
            baseline_version=None,
            current_version=None,
            next_version=None,
            target_merge_commit_sha=None,
        )

    best_version_parts: tuple[int, int, int] | None = None

    for item in items:
        if item.recommended_current_version is None:
            continue
        parts = _version_parts(item.recommended_current_version)
        if parts is None:
            continue
        if best_version_parts is None or parts > best_version_parts:
            best_version_parts = parts

    if best_version_parts is None:
        return ReleaseBacklogAggregate(
            item_count=len(items),
            considered_item_count=0,
            considered_item_ids=(),
            aggregated_label=None,
            recommended_label=None,
            baseline_version=None,
            current_version=None,
            next_version=None,
            target_merge_commit_sha=None,
        )

    baseline_version = _format_version(best_version_parts)
    considered_items = [
        item
        for item in items
        if item.recommended_current_version is not None
        and _version_parts(item.recommended_current_version) == best_version_parts
    ]
    considered_items.sort(key=lambda item: (item.merged_at, item.id))

    aggregated_label: str | None = None
    best_rank = -1
    current_version = baseline_version
    recommended_label: str | None = None
    target_merge_commit_sha: str | None = None

    for item in considered_items:
        normalized_label = _normalize_label(item.recommended_label)
        if normalized_label is None:
            continue

        rank = _LABEL_PRECEDENCE[normalized_label]
        if rank > best_rank:
            best_rank = rank
            aggregated_label = normalized_label
            recommended_label = normalized_label
        target_merge_commit_sha = item.merge_commit_sha

    next_version = (
        _format_version(_bump_parts(best_version_parts, recommended_label))
        if recommended_label is not None
        else baseline_version
    )

    return ReleaseBacklogAggregate(
        item_count=len(items),
        considered_item_count=len(considered_items),
        considered_item_ids=tuple(item.id for item in considered_items),
        aggregated_label=aggregated_label,
        recommended_label=recommended_label,
        baseline_version=baseline_version,
        current_version=current_version,
        next_version=next_version,
        target_merge_commit_sha=target_merge_commit_sha,
    )


__all__ = ["ReleaseBacklogAggregate", "aggregate_release_backlog"]
