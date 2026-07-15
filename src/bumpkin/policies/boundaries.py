from __future__ import annotations

import fnmatch
import re

from bumpkin.analysis.findings import Finding

from .guards import is_docs_or_config_path


def dedupe_preserving_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def path_matches_hints(path: str, hints: list[str]) -> bool:
    normalized = path.strip().strip("/")
    if not normalized:
        return False
    return any(_path_matches_hint(normalized, hint) for hint in hints)


def _path_matches_hint(path: str, hint: str) -> bool:
    pattern = hint.strip().strip("/")
    if not pattern:
        return False
    if fnmatch.fnmatch(path, pattern):
        return True
    prefix = pattern.replace("**", "").rstrip("/")
    return bool(prefix and path.startswith(prefix))


def _classify_python_floor_boundary(path: str) -> str:
    normalized = path.strip().replace("\\", "/").strip("/").lower()
    parts = [part for part in normalized.split("/") if part]
    internal_dirs = {
        "bench",
        "benches",
        "benchmark",
        "benchmarks",
        "build",
        "builds",
        "ci",
        "docs",
        "doc",
        "example",
        "examples",
        "internal",
        "internals",
        "scripts",
        "test",
        "tests",
        "testing",
        "tool",
        "tools",
    }
    if is_docs_or_config_path(path) and len(parts) > 1:
        return "internal"
    if any(_is_internal_path_part(part, internal_dirs) for part in parts[:-1]):
        return "internal"
    return "public"


def _classify_public_hint_boundary(path: str, public_hints: list[str]) -> str:
    if is_docs_or_config_path(path):
        return "internal"
    if not public_hints:
        return "unknown"
    return "public" if path_matches_hints(path, public_hints) else "internal"


def classify_finding_boundary(finding: Finding, *, public_hints: list[str]) -> str:
    evidence = finding.evidence
    if not evidence:
        return "unknown"
    path = str(evidence[0].get("path", "")).strip()
    if not path:
        return "unknown"
    if finding.rule == "python_requires_floor_raised":
        return _classify_python_floor_boundary(path)
    return _classify_public_hint_boundary(path, public_hints)


def _is_internal_path_part(part: str, internal_dirs: set[str]) -> bool:
    normalized = part.strip().lower()
    if normalized in internal_dirs or normalized.startswith("_"):
        return True
    tokens = [token for token in re.split(r"[-_.]+", normalized) if token]
    return any(token in internal_dirs for token in tokens)


def summarize_boundary(findings: list[Finding], *, public_hints: list[str]) -> dict[str, int]:
    summary = {"public": 0, "internal": 0, "unknown": 0}
    for finding in findings:
        boundary = classify_finding_boundary(finding, public_hints=public_hints)
        summary[boundary] = summary.get(boundary, 0) + 1
    return summary


def finding_severity_counts(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        key = finding.severity.upper()
        counts[key] = counts.get(key, 0) + 1
    return counts
