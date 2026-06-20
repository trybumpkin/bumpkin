from __future__ import annotations

import urllib.parse

from bumpkin.release.analysis import _normalize_label
from bumpkin.release.models import ReleaseRecommendationRecord

_GENERIC_REASONING_PATTERNS = (
    "public api additive evidence detected without breaking removal",
    "public api breaking evidence detected",
    "runtime-internal deltas detected; no public api evidence",
    "non-runtime-only evidence detected; runtime/public impact not observed",
    "automatic classification unavailable; manual review required",
    "evidence was detected from exported api analysis",
)


def _top_label_records(
    recommendations: list[ReleaseRecommendationRecord],
    release_label: str | None,
) -> list[ReleaseRecommendationRecord]:
    normalized_label = _normalize_label(release_label)
    if normalized_label is None:
        return []
    return [
        record
        for record in recommendations
        if record.status == "classified" and record.label == normalized_label
    ]


def _parse_evidence_line(raw_line: str) -> dict[str, str]:
    parts = [part.strip() for part in raw_line.split("|") if part.strip()]
    if not parts:
        return {}
    parsed: dict[str, str] = {"path": parts[0]}
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        if not sep:
            continue
        normalized_value = " ".join(value.split()).strip()
        if not normalized_value:
            continue
        parsed[key.strip().lower()] = normalized_value
    return parsed


def _format_preview_file_link(*, repository: str, target_sha: str, path: str) -> str:
    normalized_path = path.strip().lstrip("/")
    if not repository.strip() or not target_sha.strip() or not normalized_path:
        return path
    encoded_path = urllib.parse.quote(normalized_path, safe="/")
    return (
        f"[`{normalized_path}`](https://github.com/{repository}/blob/{target_sha}/{encoded_path})"
    )


def _linked_path(record: ReleaseRecommendationRecord, path: str, target_sha: str) -> str:
    return _format_preview_file_link(
        repository=record.pull_request.repository,
        target_sha=target_sha,
        path=path,
    )


def _parsed_public_evidence(record: ReleaseRecommendationRecord) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    for raw_line in record.evidence_lines:
        parsed = _parse_evidence_line(raw_line)
        if not parsed:
            continue
        if parsed.get("scope", "").lower() != "public_api":
            continue
        evidence.append(parsed)
    return evidence


def _evidence_score(evidence: dict[str, str]) -> tuple[int, int]:
    rule = evidence.get("rule", "").lower()
    path = evidence.get("path", "")
    symbol = evidence.get("symbol", "").strip()
    score = 0
    if rule in {"export_symbol_added", "export_symbol_removed", "export_symbol_changed"}:
        score += 4
    if symbol:
        score += 3
    if path.endswith("__init__.py"):
        score -= 1
    return score, len(path)


def _primary_public_evidence(record: ReleaseRecommendationRecord) -> dict[str, str] | None:
    evidence = _parsed_public_evidence(record)
    if not evidence:
        return None
    return sorted(evidence, key=_evidence_score, reverse=True)[0]


def _entrypoint_export_paths(record: ReleaseRecommendationRecord) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for evidence in _parsed_public_evidence(record):
        path = evidence.get("path", "")
        if not path.endswith("__init__.py") or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _clean_reasoning(reasoning: str | None) -> str | None:
    normalized = " ".join((reasoning or "").split()).strip().rstrip(".")
    if not normalized:
        return None
    lowered = normalized.lower()
    if any(pattern in lowered for pattern in _GENERIC_REASONING_PATTERNS):
        return None
    return normalized


def _label_reason_phrase(label: str | None) -> str:
    normalized = _normalize_label(label)
    if normalized == "MAJOR":
        return "breaking public API changes"
    if normalized == "MINOR":
        return "additive public API changes"
    if normalized == "PATCH":
        return "runtime-facing changes without expanding the public API"
    if normalized == "NO_BUMP":
        return "operational-only changes"
    return "release-significant changes"


def _format_addition_sentence(
    *,
    record: ReleaseRecommendationRecord,
    evidence: dict[str, str],
    target_sha: str,
) -> str:
    pr_number = record.pull_request.number
    symbol = evidence.get("symbol", "").strip()
    path = evidence.get("path", "")
    linked_path = _linked_path(record, path, target_sha)
    entrypoint_paths = [
        entrypoint_path
        for entrypoint_path in _entrypoint_export_paths(record)
        if entrypoint_path != path
    ]
    if symbol and entrypoint_paths:
        entrypoint = _linked_path(record, entrypoint_paths[0], target_sha)
        return (
            f"PR #{pr_number} introduced `{symbol}` in {linked_path} and exposed it through the "
            f"package entrypoint in {entrypoint}, expanding the public API."
        )
    if symbol:
        return f"PR #{pr_number} introduced `{symbol}` in {linked_path}, expanding the public API."
    if path.endswith("__init__.py"):
        return (
            f"PR #{pr_number} expanded the package entrypoint exports in {linked_path}, increasing "
            "the public API surface."
        )
    return f"PR #{pr_number} added a new public API surface in {linked_path}."


def _format_change_sentence(
    *,
    record: ReleaseRecommendationRecord,
    evidence: dict[str, str],
    target_sha: str,
) -> str:
    pr_number = record.pull_request.number
    symbol = evidence.get("symbol", "").strip()
    path = evidence.get("path", "")
    linked_path = _linked_path(record, path, target_sha)
    rule = evidence.get("rule", "").lower()
    if rule == "export_symbol_removed":
        if symbol:
            return (
                f"PR #{pr_number} removed `{symbol}` from {linked_path}, breaking the public API."
            )
        return f"PR #{pr_number} removed a public API surface in {linked_path}."
    if rule == "export_symbol_changed":
        if symbol:
            return (
                f"PR #{pr_number} changed the public contract for `{symbol}` in {linked_path}, "
                "which can break existing consumers."
            )
        return f"PR #{pr_number} changed a public API surface in {linked_path}."
    cleaned_reasoning = _clean_reasoning(record.reasoning)
    if cleaned_reasoning:
        return (
            f"PR #{pr_number} ({record.pull_request.title.rstrip('.')}) was classified "
            f"{record.label} because {cleaned_reasoning[0].lower() + cleaned_reasoning[1:]}."
        )
    return (
        f"PR #{pr_number} ({record.pull_request.title.rstrip('.')}) was classified {record.label} "
        f"after review found {_label_reason_phrase(record.label)}."
    )


def _format_patch_sentence(
    *,
    record: ReleaseRecommendationRecord,
    target_sha: str,
) -> str:
    pr_number = record.pull_request.number
    cleaned_reasoning = _clean_reasoning(record.reasoning)
    runtime_path: str | None = None
    for raw_line in record.evidence_lines:
        parsed = _parse_evidence_line(raw_line)
        if parsed.get("scope", "").lower().startswith("runtime"):
            runtime_path = parsed.get("path", "")
            break
    if cleaned_reasoning:
        return (
            f"PR #{pr_number} ({record.pull_request.title.rstrip('.')}) stayed patch-level because "
            f"{cleaned_reasoning[0].lower() + cleaned_reasoning[1:]}."
        )
    if runtime_path:
        linked_path = _linked_path(record, runtime_path, target_sha)
        return (
            f"PR #{pr_number} updated runtime behavior in {linked_path} without expanding the "
            "public API."
        )
    return (
        f"PR #{pr_number} ({record.pull_request.title.rstrip('.')}) updated runtime behavior without "
        "expanding the public API."
    )


def _format_no_bump_sentence(record: ReleaseRecommendationRecord) -> str:
    pr_number = record.pull_request.number
    cleaned_reasoning = _clean_reasoning(record.reasoning)
    if cleaned_reasoning:
        return (
            f"PR #{pr_number} ({record.pull_request.title.rstrip('.')}) stayed out of the release "
            f"because {cleaned_reasoning[0].lower() + cleaned_reasoning[1:]}."
        )
    return (
        f"PR #{pr_number} ({record.pull_request.title.rstrip('.')}) stayed out of the release "
        "because it did not change runtime or public API behavior."
    )


def _format_record_rationale(record: ReleaseRecommendationRecord, *, target_sha: str) -> str:
    normalized_label = _normalize_label(record.label)
    primary_evidence = _primary_public_evidence(record)
    if normalized_label == "MINOR" and primary_evidence is not None:
        return _format_addition_sentence(
            record=record,
            evidence=primary_evidence,
            target_sha=target_sha,
        )
    if normalized_label == "MAJOR" and primary_evidence is not None:
        return _format_change_sentence(
            record=record,
            evidence=primary_evidence,
            target_sha=target_sha,
        )
    if normalized_label == "PATCH":
        return _format_patch_sentence(record=record, target_sha=target_sha)
    if normalized_label == "NO_BUMP":
        return _format_no_bump_sentence(record)
    cleaned_reasoning = _clean_reasoning(record.reasoning)
    if cleaned_reasoning:
        return (
            f"PR #{record.pull_request.number} ({record.pull_request.title.rstrip('.')}) was "
            f"classified {record.label} because {cleaned_reasoning[0].lower() + cleaned_reasoning[1:]}."
        )
    return (
        f"PR #{record.pull_request.number} ({record.pull_request.title.rstrip('.')}) contributed "
        "to this release decision."
    )


def _other_classified_prs_line(
    *,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
) -> str | None:
    normalized_label = _normalize_label(release_label)
    other_records = [
        record
        for record in recommendations
        if record.status == "classified" and record.label and record.label != normalized_label
    ]
    if not other_records:
        return None
    pr_numbers = ", ".join(f"PR #{record.pull_request.number}" for record in other_records[:4])
    if normalized_label == "MAJOR":
        return (
            "Lower-severity changes are also included in this batch, but they do not reduce the "
            f"overall MAJOR outcome ({pr_numbers})."
        )
    if normalized_label == "MINOR":
        return (
            "Lower-severity fixes are also included in this batch, but they do not change the "
            f"overall MINOR outcome ({pr_numbers})."
        )
    if normalized_label == "PATCH":
        return (
            "This release also includes no-bump maintenance work, but none of it expands the "
            f"public API ({pr_numbers})."
        )
    return None


def _default_conclusion_line(
    *,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
) -> str | None:
    normalized_label = _normalize_label(release_label)
    if normalized_label == "MAJOR":
        base_line = (
            "Overall, this batch changes or removes public API contracts, so it warrants a "
            "MAJOR bump."
        )
    elif normalized_label == "MINOR":
        base_line = (
            "Overall, this batch adds public API without breaking existing consumers, so it "
            "warrants a MINOR bump."
        )
    elif normalized_label == "PATCH":
        base_line = (
            "Overall, this batch changes runtime behavior without expanding the public API, so "
            "it warrants a PATCH bump."
        )
    elif normalized_label == "NO_BUMP":
        base_line = "Overall, the included pull requests do not justify a new release."
    else:
        return None
    other_prs_line = _other_classified_prs_line(
        release_label=normalized_label,
        recommendations=recommendations,
    )
    if not other_prs_line:
        return base_line
    return f"{base_line} {other_prs_line}"


def _build_release_why_lines(
    *,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
    target_sha: str,
) -> list[str]:
    normalized_label = _normalize_label(release_label)
    if normalized_label is None:
        return []
    matching_records = _top_label_records(recommendations, normalized_label)
    if not matching_records:
        return []
    lines: list[str] = []
    seen: set[str] = set()
    for record in matching_records:
        sentence = _format_record_rationale(record, target_sha=target_sha)
        if sentence in seen:
            continue
        seen.add(sentence)
        lines.append(sentence)
    conclusion = _default_conclusion_line(
        release_label=normalized_label,
        recommendations=recommendations,
    )
    if conclusion:
        lines.append(conclusion)
    return lines


def resolve_preview_rationale_lines(
    *,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
    target_sha: str,
    model: str | None = None,
    fallback_model: str | None = None,
    models_endpoint: str | None = None,
    models_token: str | None = None,
    max_retries: int = 3,
    request_timeout: int = 45,
    post_json_request_fn: object | None = None,
    notes: list[str] | None = None,
) -> list[str]:
    _ = (
        model,
        fallback_model,
        models_endpoint,
        models_token,
        max_retries,
        request_timeout,
        post_json_request_fn,
        notes,
    )
    return _build_release_why_lines(
        release_label=release_label,
        recommendations=recommendations,
        target_sha=target_sha,
    )


__all__ = [
    "_build_release_why_lines",
    "resolve_preview_rationale_lines",
]
