from __future__ import annotations

import re

from bumpkin.integrations.github.recommendations import (
    MergeRecommendationRequest,
    RecommendationRunner,
)
from bumpkin.integrations.github.types import AppEvent
from bumpkin.release.models import (
    ReleaseRecommendationRecord,
    ReleaseScopedPullRequest,
)
from bumpkin.release.repository_client import GitHubRepositoryClientProtocol


def _normalize_label(label: str | None) -> str | None:
    normalized = (label or "").strip().upper().replace("-", "_").replace(" ", "_")
    if normalized == "NOBUMP":
        normalized = "NO_BUMP"
    return normalized if normalized in {"NO_BUMP", "PATCH", "MINOR", "MAJOR"} else None


def _build_app_event(pull_request: ReleaseScopedPullRequest) -> AppEvent:
    return AppEvent(
        event="pull_request",
        action="closed",
        installation_id=None,
        repository=pull_request.repository,
        pull_request_number=pull_request.number,
        sender_login=pull_request.author_login,
        delivery_id=f"release-scope-pr-{pull_request.number}",
        merged=True,
        merge_commit_sha=pull_request.merge_commit_sha,
        base_ref=pull_request.base_ref,
        base_sha=pull_request.base_sha,
        head_ref=pull_request.head_ref,
        head_sha=pull_request.head_sha,
    )


def _build_payload(pull_request: ReleaseScopedPullRequest) -> dict[str, object]:
    return {
        "action": "closed",
        "repository": {"full_name": pull_request.repository},
        "pull_request": {
            "number": pull_request.number,
            "merged": True,
            "merge_commit_sha": pull_request.merge_commit_sha,
            "title": pull_request.title,
            "html_url": pull_request.url,
            "user": {"login": pull_request.author_login or ""},
            "base": {"ref": pull_request.base_ref or "", "sha": pull_request.base_sha or ""},
            "head": {"ref": pull_request.head_ref or "", "sha": pull_request.head_sha or ""},
            "labels": [{"name": label} for label in pull_request.labels],
        },
    }


def _discover_pull_requests(
    *,
    client: GitHubRepositoryClientProtocol,
    base_ref: str,
    head_ref: str,
) -> list[ReleaseScopedPullRequest]:
    pull_numbers: list[int] = []
    for commit_sha in client.compare_commits(base_ref=base_ref, head_ref=head_ref):
        pull_numbers.extend(client.list_pull_requests_for_commit(commit_sha))
    unique_numbers = sorted({number for number in pull_numbers if number > 0})
    pull_requests = [client.get_pull_request(number) for number in unique_numbers]
    merged_pull_requests = [
        pull_request for pull_request in pull_requests if pull_request.merge_commit_sha.strip()
    ]
    merged_pull_requests.sort(key=lambda item: (item.merged_at, item.number))
    return merged_pull_requests


def _extract_first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    value = " ".join(match.group("value").split()).strip()
    return value or None


def _extract_findings_block_lines(body: str) -> tuple[str, ...]:
    lines = body.splitlines()
    findings_started = False
    findings: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not findings_started:
            if stripped.lower() == "findings:":
                findings_started = True
            continue
        if not stripped:
            if findings:
                break
            continue
        if stripped.startswith("- "):
            findings.append(stripped[2:].strip())
            continue
        if findings:
            break
    return tuple(line for line in findings if line)


def _extract_recommendation_insights(
    body: str,
    *,
    summary_line_re: re.Pattern[str],
    reasoning_line_re: re.Pattern[str],
) -> tuple[str | None, str | None, tuple[str, ...]]:
    return (
        _extract_first_match(summary_line_re, body),
        _extract_first_match(reasoning_line_re, body),
        _extract_findings_block_lines(body),
    )


def _analyze_pull_requests(
    *,
    pull_requests: list[ReleaseScopedPullRequest],
    recommendation_runner: RecommendationRunner,
    github_token: str,
    summary_line_re: re.Pattern[str],
    reasoning_line_re: re.Pattern[str],
) -> list[ReleaseRecommendationRecord]:
    recommendation_records: list[ReleaseRecommendationRecord] = []
    for pull_request in pull_requests:
        try:
            recommendation = recommendation_runner.generate(
                MergeRecommendationRequest(
                    event=_build_app_event(pull_request),
                    payload=_build_payload(pull_request),
                    provider_token=github_token,
                )
            )
        except RuntimeError as err:
            recommendation_records.append(
                ReleaseRecommendationRecord(
                    pull_request=pull_request,
                    recommendation=None,
                    status="unsupported",
                    label=None,
                    reason=str(err),
                )
            )
            continue
        summary, reasoning, evidence_lines = _extract_recommendation_insights(
            recommendation.body,
            summary_line_re=summary_line_re,
            reasoning_line_re=reasoning_line_re,
        )
        label = _normalize_label(recommendation.label)
        if label is None:
            recommendation_records.append(
                ReleaseRecommendationRecord(
                    pull_request=pull_request,
                    recommendation=recommendation,
                    status="needs_review",
                    label=None,
                    reason="PR recommendation did not produce a normalized release label.",
                    summary=summary,
                    reasoning=reasoning,
                    evidence_lines=evidence_lines,
                )
            )
            continue
        recommendation_records.append(
            ReleaseRecommendationRecord(
                pull_request=pull_request,
                recommendation=recommendation,
                status="classified",
                label=label,
                summary=summary,
                reasoning=reasoning,
                evidence_lines=evidence_lines,
            )
        )
    return recommendation_records


__all__ = [
    "_analyze_pull_requests",
    "_build_app_event",
    "_build_payload",
    "_discover_pull_requests",
    "_extract_findings_block_lines",
    "_extract_first_match",
    "_extract_recommendation_insights",
    "_normalize_label",
]
