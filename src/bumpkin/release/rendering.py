from __future__ import annotations

import urllib.parse

from bumpkin.release.analysis import _normalize_label
from bumpkin.release.models import ReleaseRecommendationRecord
from bumpkin.release.rationale import _build_release_why_lines

_SECTION_BY_LABEL = {
    "MAJOR": "Breaking Changes",
    "MINOR": "Features",
    "PATCH": "Fixes",
    "NO_BUMP": "Maintenance",
}
_SECTION_ORDER = ("Breaking Changes", "Features", "Fixes", "Maintenance")


def _versioning_context_notes(notes: tuple[str, ...] | list[str]) -> list[str]:
    relevant_prefixes = (
        "Detected versioning scheme:",
        "Zero-based policy:",
        "CalVer detected:",
        "Detected mixed tag prefixes",
        "Tag source order was non-monotonic;",
    )
    return [note for note in notes if note.startswith(relevant_prefixes)]


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


def _release_label_headline(
    release_label: str, matching_records: list[ReleaseRecommendationRecord]
) -> str:
    count = len(matching_records)
    if release_label == "MAJOR":
        return f"Breaking public API evidence was detected in {count} merged PR(s)."
    if release_label == "MINOR":
        return f"User-facing additive changes were detected in {count} merged PR(s)."
    if release_label == "PATCH":
        return f"Backward-compatible runtime changes were detected in {count} merged PR(s)."
    if release_label == "NO_BUMP":
        return f"All {count} merged PR(s) resolved to NO_BUMP."
    return f"{count} merged PR(s) contributed to this release decision."


def _format_preview_file_link(*, repository: str, target_sha: str, path: str) -> str:
    normalized_path = path.strip().lstrip("/")
    if not repository.strip() or not target_sha.strip() or not normalized_path:
        return path
    encoded_path = urllib.parse.quote(normalized_path, safe="/")
    return (
        f"[`{normalized_path}`](https://github.com/{repository}/blob/{target_sha}/{encoded_path})"
    )


def _humanize_evidence_line(
    line: str,
    *,
    repository: str,
    target_sha: str,
) -> str:
    parts = [part.strip() for part in line.split("|") if part.strip()]
    if not parts:
        return line.strip()
    path = _format_preview_file_link(
        repository=repository,
        target_sha=target_sha,
        path=parts[0],
    )
    details: list[str] = []
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        if not sep:
            continue
        normalized_key = key.strip().lower()
        normalized_value = " ".join(value.split()).strip()
        if not normalized_value:
            continue
        if normalized_key in {"suggested", "severity"}:
            continue
        if normalized_key == "scope" and normalized_value.lower() == "non_runtime":
            continue
        if normalized_key == "rule":
            details.append(normalized_value.replace("_", " "))
            continue
        if normalized_key == "scope":
            details.append(normalized_value.replace("_", " "))
            continue
        if normalized_key == "symbol":
            details.append(f"`{normalized_value}`")
            continue
        details.append(normalized_value)
    if not details:
        return path
    return f"{path} - {'; '.join(details)}"


def _build_release_evidence_lines(
    *,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
    target_sha: str,
    max_items: int | None = None,
) -> list[str]:
    evidence: list[str] = []
    seen: set[str] = set()
    has_detailed_evidence = False
    for record in _top_label_records(recommendations, release_label):
        for raw_line in record.evidence_lines:
            detail = _humanize_evidence_line(
                raw_line,
                repository=record.pull_request.repository,
                target_sha=target_sha,
            )
            line = f"PR #{record.pull_request.number}: {detail}"
            if line in seen:
                continue
            seen.add(line)
            evidence.append(line)
            has_detailed_evidence = True
            if max_items is not None and len(evidence) >= max_items:
                return evidence
        if record.summary and not has_detailed_evidence:
            line = f"PR #{record.pull_request.number}: {record.summary}"
            if line not in seen:
                seen.add(line)
                evidence.append(line)
                if max_items is not None and len(evidence) >= max_items:
                    return evidence
    return evidence


def _group_release_records(
    recommendations: list[ReleaseRecommendationRecord],
) -> tuple[
    dict[str, list[ReleaseRecommendationRecord]], list[ReleaseRecommendationRecord], list[str]
]:
    grouped: dict[str, list[ReleaseRecommendationRecord]] = {
        section: [] for section in _SECTION_ORDER
    }
    unresolved: list[ReleaseRecommendationRecord] = []
    contributors: list[str] = []
    seen_contributors: set[str] = set()
    for record in recommendations:
        if record.status != "classified" or not record.label:
            unresolved.append(record)
            continue
        section = _SECTION_BY_LABEL.get(record.label, "Maintenance")
        grouped.setdefault(section, []).append(record)
        author = (record.pull_request.author_login or "").strip()
        if author and author not in seen_contributors:
            seen_contributors.add(author)
            contributors.append(author)
    return grouped, unresolved, contributors


def _render_public_release_body(
    recommendations: list[ReleaseRecommendationRecord],
) -> str:
    grouped, unresolved, contributors = _group_release_records(recommendations)
    lines: list[str] = []
    for section in _SECTION_ORDER:
        section_records = grouped.get(section, [])
        if not section_records:
            continue
        if lines:
            lines.append("")
        lines.append(f"## {section}")
        for record in section_records:
            pull_request = record.pull_request
            author = (
                f"@{pull_request.author_login}" if pull_request.author_login else "unknown author"
            )
            lines.append(
                f"- [PR #{pull_request.number}]({pull_request.url}) by {author}: {pull_request.title.rstrip('.')}"
            )

    if unresolved:
        if lines:
            lines.append("")
        lines.append("## Needs Review")
        for record in unresolved:
            pull_request = record.pull_request
            author = (
                f"@{pull_request.author_login}" if pull_request.author_login else "unknown author"
            )
            reason = (record.reason or record.status).rstrip(".")
            lines.append(
                f"- [PR #{pull_request.number}]({pull_request.url}) by {author}: {pull_request.title.rstrip('.')} ({reason})"
            )

    if contributors:
        if lines:
            lines.append("")
        lines.extend(["## Contributors", ", ".join(f"@{author}" for author in contributors)])

    return "\n".join(lines).strip() + ("\n" if lines else "")


def _shift_markdown_headings(markdown: str, *, offset: int = 1) -> str:
    shifted_lines: list[str] = []
    for raw_line in markdown.splitlines():
        if raw_line.startswith("#"):
            marker, sep, rest = raw_line.partition(" ")
            if sep:
                shifted_lines.append(f"{'#' * (len(marker) + offset)} {rest}")
                continue
        shifted_lines.append(raw_line)
    return "\n".join(shifted_lines).rstrip()


def _render_preview_notes(
    *,
    target_sha: str,
    previous_tag: str | None,
    next_tag: str | None,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
    notes: tuple[str, ...] | list[str] = (),
    published_release_body: str,
    rationale_lines: list[str] | None = None,
) -> str:
    heading = next_tag or "Release Preview"
    lines: list[str] = [f"# {heading}", ""]
    if previous_tag:
        lines.append(f"Previous tag: {previous_tag}")
    if next_tag:
        lines.append(f"Next tag: {next_tag}")
    if release_label:
        lines.append(f"Release type: {release_label}")
    lines.append(f"Included PRs: {len(recommendations)}")

    why_lines = rationale_lines
    if why_lines is None:
        why_lines = _build_release_why_lines(
            release_label=release_label,
            recommendations=recommendations,
            target_sha=target_sha,
        )
    if why_lines:
        lines.extend(["", "## Release rationale"])
        lines.extend(f"- {line}" for line in why_lines)

    versioning_notes = _versioning_context_notes(notes)
    if versioning_notes:
        lines.extend(["", "## Versioning context"])
        lines.extend(f"- {note}" for note in versioning_notes)

    evidence_lines = _build_release_evidence_lines(
        release_label=release_label,
        recommendations=recommendations,
        target_sha=target_sha,
    )
    if evidence_lines:
        lines.extend(["", "## Key evidence"])
        lines.extend(f"- {line}" for line in evidence_lines)

    if published_release_body:
        lines.extend(
            [
                "",
                "## Public release notes",
                _shift_markdown_headings(published_release_body),
            ]
        )

    return "\n".join(lines).strip() + "\n"


def _render_no_release_preview_notes(
    *,
    previous_tag: str | None,
    release_label: str,
    recommendations: list[ReleaseRecommendationRecord],
    notes: tuple[str, ...] | list[str] = (),
) -> str:
    lines = ["# Release Preview", ""]
    if previous_tag:
        lines.append(f"Previous tag: {previous_tag}")
    lines.append(f"Release type: {release_label}")
    lines.append(f"Included PRs: {len(recommendations)}")
    lines.extend(
        [
            "",
            "No new release will be published for this batch.",
            "All included pull requests were classified as NO_BUMP.",
        ]
    )

    versioning_notes = _versioning_context_notes(notes)
    if versioning_notes:
        lines.extend(["", "## Versioning context"])
        lines.extend(f"- {note}" for note in versioning_notes)

    maintenance_records = [
        record
        for record in recommendations
        if record.label is not None and _SECTION_BY_LABEL.get(record.label) == "Maintenance"
    ]
    if maintenance_records:
        lines.extend(["", "## Included PRs"])
        for record in maintenance_records:
            pull_request = record.pull_request
            author = (
                f"@{pull_request.author_login}" if pull_request.author_login else "unknown author"
            )
            lines.append(
                f"- [PR #{pull_request.number}]({pull_request.url}) by {author}: {pull_request.title.rstrip('.')}"
            )

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "_render_no_release_preview_notes",
    "_render_preview_notes",
    "_render_public_release_body",
]
