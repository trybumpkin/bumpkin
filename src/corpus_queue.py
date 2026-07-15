from __future__ import annotations

import json
import random
from dataclasses import asdict
from pathlib import Path

from corpus_models import CommitCandidate

DEFAULT_DISTRIBUTION = {"MAJOR": 6, "MINOR": 8, "PATCH": 10, "NO_BUMP": 6}


def build_balanced_queue(
    candidates: list[CommitCandidate], *, target_count: int, seed: int, distribution: dict[str, int]
) -> list[CommitCandidate]:
    randomizer = random.Random(seed)
    by_label: dict[str, list[CommitCandidate]] = {label: [] for label in distribution}
    for candidate in candidates:
        if candidate.expected_label in by_label:
            by_label[candidate.expected_label].append(candidate)
    for rows in by_label.values():
        randomizer.shuffle(rows)
    selected = [
        candidate
        for label, target in distribution.items()
        for candidate in by_label[label][:target]
    ]
    if len(selected) < target_count:
        selected_shas = {row.sha for row in selected}
        remainder = [row for row in candidates if row.sha not in selected_shas]
        randomizer.shuffle(remainder)
        selected.extend(remainder[: max(0, target_count - len(selected))])
    selected = selected[:target_count]
    selected.sort(key=lambda row: row.sha)
    return selected


def write_queue(
    path: Path,
    rows: list[CommitCandidate],
    *,
    source_repo: Path,
    rev_range: str,
    resolved_rev_range: str,
) -> None:
    payload = {
        "source_repo": str(source_repo),
        "rev_range": rev_range,
        "resolved_rev_range": resolved_rev_range,
        "count": len(rows),
        "items": [asdict(row) for row in rows],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def load_queue(path: Path) -> list[CommitCandidate]:
    payload = json.loads(path.read_text())
    return [
        CommitCandidate(
            sha=str(row["sha"]),
            subject=str(row["subject"]),
            files=[str(item) for item in row.get("files", [])],
            expected_label=str(row["expected_label"]).upper(),
            category=str(row["category"]),
        )
        for row in payload.get("items", [])
    ]
