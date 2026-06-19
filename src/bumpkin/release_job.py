from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.parse
from pathlib import Path

from bumpkin.integrations.github.recommendations import (
    PipelineRecommendationRunner,
    RecommendationRunner,
)
from bumpkin.integrations.github.releases import (
    GitHubReleasePublisher,
    ReleasePublisher,
    ReleasePublishRequest,
)
from bumpkin.integrations.github.tags import (
    GitHubTagPublisher,
    TagPublisher,
    TagPublishRequest,
)
from bumpkin.release.analysis import (
    _analyze_pull_requests,
    _discover_pull_requests,
    _normalize_label,
)
from bumpkin.release.candidate import (
    _build_release_candidate,
    _candidate_fingerprint,
    _candidate_fingerprint_payload,
    _deserialize_release_candidate,
    _serialize_release_candidate,
)
from bumpkin.release.models import (
    ReleaseCandidate,
    ReleaseExecutionResult,
    ReleasePlan,
    ReleaseRecommendationRecord,
    ReleaseScopedPullRequest,
)
from bumpkin.release.repository_client import (
    GitHubRepositoryClient,
    GitHubRepositoryClientProtocol,
)
from bumpkin.release.workflow_discovery import _resolve_release_candidate
from bumpkin.versioning.tags import detect_next_version, list_tags, resolve_current_tag

_LABEL_PRECEDENCE = {"NO_BUMP": 0, "PATCH": 1, "MINOR": 2, "MAJOR": 3}
_SECTION_BY_LABEL = {
    "MAJOR": "Breaking Changes",
    "MINOR": "Features",
    "PATCH": "Fixes",
    "NO_BUMP": "Maintenance",
}
_SECTION_ORDER = ("Breaking Changes", "Features", "Fixes", "Maintenance")
_SUMMARY_LINE_RE = re.compile(r"(?im)^summary\s*:\s*(?P<value>.+)$")
_REASONING_LINE_RE = re.compile(r"(?im)^reasoning\s*:\s*(?P<value>.+)$")
_RELEASE_CANDIDATE_ARTIFACT_NAME = "bumpkin-release-candidate"
_RELEASE_CANDIDATE_DISCOVERY_LIMIT = 20


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bumpkin release-scoped workflow")
    parser.add_argument(
        "--operation",
        choices=("preview", "publish"),
        default="preview",
        help="Preview the release or publish the tag and GitHub Release.",
    )
    parser.add_argument(
        "--repository",
        default=os.getenv("GITHUB_REPOSITORY", ""),
        help="GitHub repository in owner/repo format.",
    )
    parser.add_argument(
        "--github-token",
        default=os.getenv("GITHUB_TOKEN", ""),
        help="GitHub token used for repository queries and release publishing.",
    )
    parser.add_argument(
        "--target-ref",
        default=os.getenv("GITHUB_SHA", ""),
        help="Target git ref or SHA for the release boundary head. Defaults to GITHUB_SHA or HEAD.",
    )
    parser.add_argument(
        "--base-tag",
        default="",
        help="Optional explicit previous tag override. Defaults to the latest parseable tag.",
    )
    parser.add_argument(
        "--output-markdown",
        default="artifacts/release/bumpkin-release-notes.md",
        help="Where to write the rendered release notes markdown artifact.",
    )
    parser.add_argument(
        "--candidate-output",
        default="artifacts/release/bumpkin-release-candidate.json",
        help="Where to write the release candidate JSON artifact.",
    )
    parser.add_argument(
        "--preview-run-id",
        default="",
        help="Optional preview workflow run id to publish from. Publish auto-discovers the latest matching preview when omitted.",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=15,
        help="GitHub API request timeout in seconds.",
    )
    return parser.parse_args()


def _run_git(args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _resolve_target_ref(input_target_ref: str) -> tuple[str, str]:
    target_ref = input_target_ref.strip()
    if target_ref:
        try:
            target_sha = _run_git(["rev-parse", target_ref])
        except (RuntimeError, subprocess.CalledProcessError):
            target_sha = target_ref
        return target_ref, target_sha
    try:
        target_sha = _run_git(["rev-parse", "HEAD"])
    except (RuntimeError, subprocess.CalledProcessError) as err:
        raise RuntimeError("Unable to resolve HEAD for release target.") from err
    return target_sha, target_sha


def _verify_release_candidate(
    *,
    candidate: ReleaseCandidate,
    repository: str,
    target_ref: str,
    base_tag: str,
    client: GitHubRepositoryClientProtocol,
) -> ReleasePlan:
    normalized_repository = repository.strip()
    if candidate.repository != normalized_repository:
        raise RuntimeError(
            "Release candidate does not belong to this repository. Run release_preview again."
        )
    normalized_base_tag = base_tag.strip()
    if candidate.base_tag_input != normalized_base_tag:
        raise RuntimeError(
            "Release candidate was created with a different base_tag input. Run release_preview again."
        )

    resolved_target_ref, target_sha = _resolve_target_ref(target_ref)
    if candidate.target_sha != target_sha:
        raise RuntimeError(
            "Release candidate is stale because the target commit changed since preview."
        )

    candidate_tags = list_tags()
    if not candidate_tags:
        candidate_tags = client.list_tags()
    previous_tag, _ = resolve_current_tag(
        latest_tag=normalized_base_tag or None,
        tags=candidate_tags,
    )
    if previous_tag != candidate.previous_tag:
        raise RuntimeError(
            "Release candidate is stale because the previous tag changed since preview."
        )
    if previous_tag is None:
        raise RuntimeError(
            "No previous tag found for this publish run. Create an initial release tag or run release_preview again."
        )

    current_pull_requests = _discover_pull_requests(
        client=client,
        base_ref=previous_tag,
        head_ref=resolved_target_ref,
    )
    current_fingerprint = _candidate_fingerprint(
        _candidate_fingerprint_payload(
            repository=normalized_repository,
            target_ref=resolved_target_ref,
            target_sha=target_sha,
            base_tag_input=normalized_base_tag,
            previous_tag=previous_tag,
            next_tag=candidate.next_tag,
            release_label=candidate.release_label,
            status=candidate.status,
            pull_requests=current_pull_requests,
            preview_notes=candidate.preview_notes,
            published_release_body=candidate.published_release_body,
        )
    )
    if current_fingerprint != candidate.fingerprint:
        raise RuntimeError(
            "Release candidate is stale because the release scope changed since preview."
        )

    return ReleasePlan(
        repository=candidate.repository,
        target_ref=resolved_target_ref,
        target_sha=target_sha,
        previous_tag=candidate.previous_tag,
        next_tag=candidate.next_tag,
        release_label=candidate.release_label,
        pull_requests=tuple(current_pull_requests),
        recommendations=(),
        preview_notes=candidate.preview_notes,
        published_release_body=candidate.published_release_body,
        notes=candidate.notes,
        status=candidate.status,
    )


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


def _format_rationale_sentence(
    *,
    record: ReleaseRecommendationRecord,
    evidence: dict[str, str],
    target_sha: str,
) -> str | None:
    path = evidence.get("path")
    rule = evidence.get("rule", "").lower()
    symbol = evidence.get("symbol", "").strip()
    scope = evidence.get("scope", "").lower()
    pr_number = record.pull_request.number

    if not path:
        return None
    linked_path = _format_preview_file_link(
        repository=record.pull_request.repository,
        target_sha=target_sha,
        path=path,
    )
    formatted_symbol = f"`{symbol}`" if symbol else ""

    if rule == "export_symbol_removed":
        if symbol:
            return f"PR #{pr_number} removed exported API {formatted_symbol} in {linked_path}."
        return f"PR #{pr_number} removed a public API surface in {linked_path}."
    if rule == "export_symbol_changed":
        if symbol:
            return f"PR #{pr_number} changed exported API {formatted_symbol} in {linked_path}."
        return f"PR #{pr_number} changed a public API surface in {linked_path}."
    if rule == "export_symbol_added":
        if symbol:
            return f"PR #{pr_number} added exported API {formatted_symbol} in {linked_path}."
        return f"PR #{pr_number} added a public API surface in {linked_path}."
    if scope == "public_api":
        return f"PR #{pr_number} changed public API behavior in {linked_path}."
    if scope == "runtime":
        return f"PR #{pr_number} changed runtime behavior in {linked_path}."
    return f"PR #{pr_number} changed code in {linked_path}."


def _fallback_rationale_sentence(record: ReleaseRecommendationRecord) -> str:
    summary = " ".join((record.summary or "").split()).strip()
    if summary:
        if summary.endswith("."):
            return f"PR #{record.pull_request.number}: {summary}"
        return f"PR #{record.pull_request.number}: {summary}."
    title = record.pull_request.title.rstrip(".")
    return f"PR #{record.pull_request.number} contributed to this release decision through {title}."


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
        sentence: str | None = None
        for raw_line in record.evidence_lines:
            sentence = _format_rationale_sentence(
                record=record,
                evidence=_parse_evidence_line(raw_line),
                target_sha=target_sha,
            )
            if sentence:
                break
        if sentence is None:
            sentence = _fallback_rationale_sentence(record)
        if sentence in seen:
            continue
        seen.add(sentence)
        lines.append(sentence)
        if len(lines) >= 3:
            break
    if normalized_label == "MAJOR":
        lines.append("Breaking public APIs were removed or changed in this release batch.")
    elif normalized_label == "MINOR":
        lines.append("No exported APIs were removed or narrowed in this release batch.")
    elif normalized_label == "PATCH":
        lines.append(
            "No public API additions or breaking removals were detected in this release batch."
        )
    elif normalized_label == "NO_BUMP":
        lines.append("All included pull requests resolved to NO_BUMP.")
    return lines


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
    max_items: int = 3,
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
            if len(evidence) >= max_items:
                return evidence
        if record.summary and not has_detailed_evidence:
            line = f"PR #{record.pull_request.number}: {record.summary}"
            if line not in seen:
                seen.add(line)
                evidence.append(line)
                if len(evidence) >= max_items:
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


def _aggregate_release_label(recommendations: list[ReleaseRecommendationRecord]) -> str | None:
    best_label: str | None = None
    best_rank = -1
    for record in recommendations:
        if record.status != "classified" or not record.label:
            continue
        rank = _LABEL_PRECEDENCE.get(record.label, -1)
        if rank > best_rank:
            best_rank = rank
            best_label = record.label
    return best_label


def _render_preview_notes(
    *,
    target_sha: str,
    previous_tag: str | None,
    next_tag: str | None,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
    notes: tuple[str, ...] | list[str] = (),
    published_release_body: str,
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


def _render_publish_step_summary(
    *,
    status: str,
    plan: ReleasePlan,
    release_candidate: ReleaseCandidate,
    release_url: str | None = None,
    tag_url: str | None = None,
) -> str:
    title = {
        "published": "# Release published",
        "skipped": "# Release publish skipped",
        "needs_review": "# Release publish blocked",
    }.get(status, "# Release publish result")
    lines = [title, ""]
    if plan.previous_tag:
        lines.append(f"Previous tag: {plan.previous_tag}")
    if plan.next_tag:
        lines.append(
            f"Published tag: {plan.next_tag}"
            if status == "published"
            else f"Candidate tag: {plan.next_tag}"
        )
    if plan.release_label:
        lines.append(f"Release type: {plan.release_label}")
    lines.append(f"Included PRs: {len(plan.pull_requests)}")
    if release_candidate.source_run_id:
        lines.append(f"Preview run id: {release_candidate.source_run_id}")
    if status == "published":
        lines.append("Release candidate verified and published.")
    elif status == "skipped":
        lines.append("No release was published for this candidate.")
    elif status == "needs_review":
        lines.append("Release candidate still needs maintainer review before publish.")
    if release_url:
        lines.append(f"Release URL: {release_url}")
    if tag_url:
        lines.append(f"Tag URL: {tag_url}")
    return "\n".join(lines).strip() + "\n"


def prepare_release_plan(
    *,
    repository: str,
    github_token: str,
    target_ref: str,
    base_tag: str,
    client: GitHubRepositoryClientProtocol,
    recommendation_runner: RecommendationRunner | None = None,
) -> ReleasePlan:
    normalized_repository = repository.strip()
    if not normalized_repository:
        raise ValueError("repository is required.")
    normalized_token = github_token.strip()
    if not normalized_token:
        raise ValueError("github token is required.")
    resolved_target_ref, target_sha = _resolve_target_ref(target_ref)
    notes: list[str] = []
    candidate_tags = list_tags()
    if not candidate_tags:
        candidate_tags = client.list_tags()
    previous_tag, current_tag_notes = resolve_current_tag(
        latest_tag=base_tag.strip() or None,
        tags=candidate_tags,
    )
    notes.extend(current_tag_notes)
    if previous_tag is None:
        raise RuntimeError(
            "No previous tag found. Create an initial release tag or pass --base-tag."
        )

    pull_requests = _discover_pull_requests(
        client=client,
        base_ref=previous_tag,
        head_ref=resolved_target_ref,
    )
    if not pull_requests:
        return ReleasePlan(
            status="skipped",
            repository=normalized_repository,
            target_ref=resolved_target_ref,
            target_sha=target_sha,
            previous_tag=previous_tag,
            next_tag=None,
            release_label=None,
            pull_requests=(),
            recommendations=(),
            preview_notes=(
                f"# Release Preview\n\nPrevious tag: {previous_tag}\nIncluded PRs: 0\n\n"
                "No merged pull requests were found in this release scope.\n"
            ),
            published_release_body="",
            notes=tuple(notes),
        )

    runner = recommendation_runner or PipelineRecommendationRunner()
    recommendations = _analyze_pull_requests(
        pull_requests=pull_requests,
        recommendation_runner=runner,
        github_token=normalized_token,
        summary_line_re=_SUMMARY_LINE_RE,
        reasoning_line_re=_REASONING_LINE_RE,
    )
    unresolved_records = [record for record in recommendations if record.status != "classified"]
    release_label = _aggregate_release_label(recommendations)
    if release_label is None and unresolved_records:
        notes.append(
            "Release scope contains unresolved pull requests that need review before publish."
        )
        published_release_body = _render_public_release_body(recommendations)
        preview_notes = _render_preview_notes(
            target_sha=target_sha,
            previous_tag=previous_tag,
            next_tag=None,
            release_label=None,
            recommendations=recommendations,
            notes=notes,
            published_release_body=published_release_body,
        )
        return ReleasePlan(
            status="needs_review",
            repository=normalized_repository,
            target_ref=resolved_target_ref,
            target_sha=target_sha,
            previous_tag=previous_tag,
            next_tag=None,
            release_label=None,
            pull_requests=tuple(pull_requests),
            recommendations=tuple(recommendations),
            preview_notes=preview_notes,
            published_release_body="",
            notes=tuple(notes),
        )
    if release_label is None:
        raise RuntimeError("Could not determine an aggregate release label.")
    _, next_tag, version_notes = detect_next_version(release_label, latest_tag=previous_tag)
    notes.extend(version_notes)
    if release_label == "NO_BUMP":
        notes.append(
            "Release scope resolved to NO_BUMP; no tag or GitHub Release will be published."
        )
        preview_notes = _render_no_release_preview_notes(
            previous_tag=previous_tag,
            release_label=release_label,
            recommendations=recommendations,
            notes=notes,
        )
        return ReleasePlan(
            status="skipped",
            repository=normalized_repository,
            target_ref=resolved_target_ref,
            target_sha=target_sha,
            previous_tag=previous_tag,
            next_tag=None,
            release_label=release_label,
            pull_requests=tuple(pull_requests),
            recommendations=tuple(recommendations),
            preview_notes=preview_notes,
            published_release_body="",
            notes=tuple(notes),
        )
    if not next_tag:
        raise RuntimeError("Could not compute the next release tag from the current scope.")
    published_release_body = _render_public_release_body(recommendations)
    preview_notes = _render_preview_notes(
        target_sha=target_sha,
        previous_tag=previous_tag,
        next_tag=next_tag,
        release_label=release_label,
        recommendations=recommendations,
        notes=notes,
        published_release_body=published_release_body,
    )
    return ReleasePlan(
        status="planned",
        repository=normalized_repository,
        target_ref=resolved_target_ref,
        target_sha=target_sha,
        previous_tag=previous_tag,
        next_tag=next_tag,
        release_label=release_label,
        pull_requests=tuple(pull_requests),
        recommendations=tuple(recommendations),
        preview_notes=preview_notes,
        published_release_body=published_release_body,
        notes=tuple(notes),
    )


def publish_release_plan(
    plan: ReleasePlan,
    *,
    tag_publisher: TagPublisher | None = None,
    release_publisher: ReleasePublisher | None = None,
) -> ReleaseExecutionResult:
    if plan.status == "needs_review":
        return ReleaseExecutionResult(status="needs_review", plan=plan)
    if not plan.next_tag:
        if plan.status == "skipped" or plan.release_label == "NO_BUMP":
            return ReleaseExecutionResult(status="skipped", plan=plan)
        raise RuntimeError("Cannot publish a release plan without a next tag.")
    if tag_publisher is None or release_publisher is None:
        raise ValueError(
            "tag_publisher and release_publisher are required for publishable release plans."
        )
    tag_result = tag_publisher.publish(
        TagPublishRequest(
            repository=plan.repository,
            tag_name=plan.next_tag,
            target_sha=plan.target_sha,
        )
    )
    if tag_result.status not in {"created", "exists"}:
        raise RuntimeError(
            tag_result.message or f"Tag publish failed with status {tag_result.status}."
        )
    release_result = release_publisher.publish(
        ReleasePublishRequest(
            repository=plan.repository,
            tag_name=plan.next_tag,
            target_sha=plan.target_sha,
            body=plan.published_release_body,
            name=plan.next_tag,
        )
    )
    if release_result.status not in {"created", "updated"}:
        raise RuntimeError(
            release_result.message or f"Release publish failed with status {release_result.status}."
        )
    return ReleaseExecutionResult(
        status="published",
        plan=plan,
        tag_result=tag_result,
        release_result=release_result,
    )


def _write_text_file(path_value: str, content: str) -> str:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _write_json_file(path_value: str, payload: dict[str, object]) -> str:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def _write_github_output(values: dict[str, str]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    lines: list[str] = []
    for key, value in values.items():
        lines.append(f"{key}<<__BUMPKIN_EOF__")
        lines.append(value)
        lines.append("__BUMPKIN_EOF__")
    with Path(output_path).open("a", encoding="utf-8") as output_file:
        output_file.write("\n".join(lines) + "\n")


def _append_step_summary(markdown: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as summary_file:
        summary_file.write(markdown.rstrip() + "\n")


def _build_summary_payload(
    *,
    status: str,
    plan: ReleasePlan,
    release_candidate: ReleaseCandidate,
    candidate_path: str,
    release_url: str | None = None,
    tag_url: str | None = None,
    notes_path: str,
) -> dict[str, str]:
    return {
        "release_status": status,
        "release_previous_tag": plan.previous_tag or "",
        "release_next_tag": plan.next_tag or "",
        "release_label": plan.release_label or "",
        "release_pr_count": str(len(plan.pull_requests)),
        "release_notes_path": notes_path,
        "release_target_sha": plan.target_sha,
        "release_candidate_path": candidate_path,
        "release_candidate_fingerprint": release_candidate.fingerprint,
        "release_candidate_run_id": release_candidate.source_run_id or "",
        "release_candidate_artifact_name": _RELEASE_CANDIDATE_ARTIFACT_NAME,
        "release_url": release_url or "",
        "tag_url": tag_url or "",
    }


def _build_repository_client(
    *,
    repository: str,
    github_token: str,
    request_timeout: int,
) -> GitHubRepositoryClientProtocol:
    return GitHubRepositoryClient(
        repository=repository.strip(),
        token=github_token.strip(),
        timeout_seconds=request_timeout,
    )


def _build_publishers(*, github_token: str) -> tuple[TagPublisher, ReleasePublisher]:
    normalized_token = github_token.strip()
    if not normalized_token:
        raise ValueError("github token is required.")
    return (
        GitHubTagPublisher(token=normalized_token),
        GitHubReleasePublisher(token=normalized_token),
    )


def run_release_job(args: argparse.Namespace | None = None) -> int:
    parsed = args or _parse_args()
    repository_client = _build_repository_client(
        repository=parsed.repository,
        github_token=parsed.github_token,
        request_timeout=parsed.request_timeout,
    )
    if parsed.operation == "publish":
        candidate = _resolve_release_candidate(
            repository=parsed.repository,
            token=parsed.github_token,
            preview_run_id=parsed.preview_run_id,
            base_tag_input=parsed.base_tag.strip(),
            artifact_name=_RELEASE_CANDIDATE_ARTIFACT_NAME,
            timeout_seconds=parsed.request_timeout,
            discovery_limit=_RELEASE_CANDIDATE_DISCOVERY_LIMIT,
        )
        plan = _verify_release_candidate(
            candidate=candidate,
            repository=parsed.repository,
            target_ref=parsed.target_ref,
            base_tag=parsed.base_tag,
            client=repository_client,
        )
    else:
        plan = prepare_release_plan(
            repository=parsed.repository,
            github_token=parsed.github_token,
            target_ref=parsed.target_ref,
            base_tag=parsed.base_tag,
            client=repository_client,
        )
        candidate = _build_release_candidate(
            plan=plan,
            base_tag_input=parsed.base_tag.strip(),
            source_operation="release_preview",
            source_run_id=os.getenv("GITHUB_RUN_ID", "").strip() or None,
        )

    output_body = (
        plan.preview_notes if parsed.operation != "publish" else plan.published_release_body
    )
    notes_path = _write_text_file(parsed.output_markdown, output_body)
    candidate_path = _write_json_file(
        parsed.candidate_output,
        _serialize_release_candidate(candidate),
    )
    if parsed.operation == "publish":
        tag_publisher, release_publisher = _build_publishers(github_token=parsed.github_token)
        execution = publish_release_plan(
            plan,
            tag_publisher=tag_publisher,
            release_publisher=release_publisher,
        )
        release_url = execution.release_result.url if execution.release_result else None
        tag_url = execution.tag_result.url if execution.tag_result else None
        _append_step_summary(
            _render_publish_step_summary(
                status=execution.status,
                plan=plan,
                release_candidate=candidate,
                release_url=release_url,
                tag_url=tag_url,
            )
        )
        _write_github_output(
            _build_summary_payload(
                status=execution.status,
                plan=plan,
                release_candidate=candidate,
                candidate_path=candidate_path,
                release_url=release_url,
                tag_url=tag_url,
                notes_path=notes_path,
            )
        )
        print(
            json.dumps(
                {
                    "status": execution.status,
                    "previous_tag": plan.previous_tag,
                    "next_tag": plan.next_tag,
                    "release_label": plan.release_label,
                    "pull_request_count": len(plan.pull_requests),
                    "release_candidate_path": candidate_path,
                    "release_candidate_run_id": candidate.source_run_id,
                    "release_url": release_url,
                    "tag_url": tag_url,
                    "release_notes_path": notes_path,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    _append_step_summary(plan.preview_notes)
    status = plan.status if plan.pull_requests else "skipped"
    _write_github_output(
        _build_summary_payload(
            status=status,
            plan=plan,
            release_candidate=candidate,
            candidate_path=candidate_path,
            notes_path=notes_path,
        )
    )
    print(
        json.dumps(
            {
                "status": status,
                "previous_tag": plan.previous_tag,
                "next_tag": plan.next_tag,
                "release_label": plan.release_label,
                "pull_request_count": len(plan.pull_requests),
                "release_candidate_path": candidate_path,
                "release_candidate_run_id": candidate.source_run_id,
                "release_notes_path": notes_path,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    return run_release_job()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GitHubRepositoryClient",
    "ReleaseExecutionResult",
    "ReleasePlan",
    "ReleaseRecommendationRecord",
    "ReleaseScopedPullRequest",
    "_build_release_candidate",
    "_deserialize_release_candidate",
    "_serialize_release_candidate",
    "main",
    "prepare_release_plan",
    "publish_release_plan",
    "run_release_job",
]
