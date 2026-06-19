from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

from bumpkin.integrations.github.recommendations import RecommendationRunner
from bumpkin.release.models import (
    ReleaseCandidate,
    ReleasePlan,
    ReleaseRecommendationRecord,
    ReleaseScopedPullRequest,
)
from bumpkin.release.repository_client import GitHubRepositoryClientProtocol

ResolveTargetRefFn = Callable[[str], tuple[str, str]]
ListTagsFn = Callable[[], list[str]]
ResolveCurrentTagFn = Callable[[str | None, list[str]], tuple[str | None, list[str]]]
DiscoverPullRequestsFn = Callable[..., list[ReleaseScopedPullRequest]]
AnalyzePullRequestsFn = Callable[..., list[ReleaseRecommendationRecord]]
AggregateReleaseLabelFn = Callable[[list[ReleaseRecommendationRecord]], str | None]
RenderPublicReleaseBodyFn = Callable[[list[ReleaseRecommendationRecord]], str]
RenderPreviewNotesFn = Callable[..., str]
RenderNoReleasePreviewNotesFn = Callable[..., str]
DetectNextVersionFn = Callable[[str, str | None], tuple[str | None, str | None, list[str]]]
RunGitFn = Callable[[list[str]], str]


def run_git(args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def resolve_target_ref(input_target_ref: str, *, run_git_fn: RunGitFn = run_git) -> tuple[str, str]:
    target_ref = input_target_ref.strip()
    if target_ref:
        try:
            target_sha = run_git_fn(["rev-parse", target_ref])
        except (RuntimeError, subprocess.CalledProcessError):
            target_sha = target_ref
        return target_ref, target_sha
    try:
        target_sha = run_git_fn(["rev-parse", "HEAD"])
    except (RuntimeError, subprocess.CalledProcessError) as err:
        raise RuntimeError("Unable to resolve HEAD for release target.") from err
    return target_sha, target_sha


def aggregate_release_label(
    recommendations: list[ReleaseRecommendationRecord],
    *,
    label_precedence: dict[str, int],
) -> str | None:
    best_label: str | None = None
    best_rank = -1
    for record in recommendations:
        if record.status != "classified" or not record.label:
            continue
        rank = label_precedence.get(record.label, -1)
        if rank > best_rank:
            best_rank = rank
            best_label = record.label
    return best_label


def verify_release_candidate(
    *,
    candidate: ReleaseCandidate,
    repository: str,
    target_ref: str,
    base_tag: str,
    client: GitHubRepositoryClientProtocol,
    resolve_target_ref_fn: ResolveTargetRefFn,
    list_tags_fn: ListTagsFn,
    resolve_current_tag_fn: ResolveCurrentTagFn,
    discover_pull_requests_fn: DiscoverPullRequestsFn,
    candidate_fingerprint_fn: Callable[[dict[str, object]], str],
    candidate_fingerprint_payload_fn: Callable[..., dict[str, object]],
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

    resolved_target_ref, target_sha = resolve_target_ref_fn(target_ref)
    if candidate.target_sha != target_sha:
        raise RuntimeError(
            "Release candidate is stale because the target commit changed since preview."
        )

    candidate_tags = list_tags_fn()
    if not candidate_tags:
        candidate_tags = client.list_tags()
    previous_tag, _ = resolve_current_tag_fn(
        normalized_base_tag or None,
        candidate_tags,
    )
    if previous_tag != candidate.previous_tag:
        raise RuntimeError(
            "Release candidate is stale because the previous tag changed since preview."
        )
    if previous_tag is None:
        raise RuntimeError(
            "No previous tag found for this publish run. Create an initial release tag or run release_preview again."
        )

    current_pull_requests = discover_pull_requests_fn(
        client=client,
        base_ref=previous_tag,
        head_ref=resolved_target_ref,
    )
    current_fingerprint = candidate_fingerprint_fn(
        candidate_fingerprint_payload_fn(
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


def prepare_release_plan(
    *,
    repository: str,
    github_token: str,
    target_ref: str,
    base_tag: str,
    client: GitHubRepositoryClientProtocol,
    recommendation_runner: RecommendationRunner | None,
    resolve_target_ref_fn: ResolveTargetRefFn,
    list_tags_fn: ListTagsFn,
    resolve_current_tag_fn: ResolveCurrentTagFn,
    discover_pull_requests_fn: DiscoverPullRequestsFn,
    analyze_pull_requests_fn: AnalyzePullRequestsFn,
    aggregate_release_label_fn: AggregateReleaseLabelFn,
    detect_next_version_fn: DetectNextVersionFn,
    render_public_release_body_fn: RenderPublicReleaseBodyFn,
    render_preview_notes_fn: RenderPreviewNotesFn,
    render_no_release_preview_notes_fn: RenderNoReleasePreviewNotesFn,
    recommendation_runner_factory: Callable[[], RecommendationRunner],
    summary_line_re: re.Pattern[str],
    reasoning_line_re: re.Pattern[str],
) -> ReleasePlan:
    normalized_repository = repository.strip()
    if not normalized_repository:
        raise ValueError("repository is required.")
    normalized_token = github_token.strip()
    if not normalized_token:
        raise ValueError("github token is required.")
    resolved_target_ref, target_sha = resolve_target_ref_fn(target_ref)
    notes: list[str] = []
    candidate_tags = list_tags_fn()
    if not candidate_tags:
        candidate_tags = client.list_tags()
    previous_tag, current_tag_notes = resolve_current_tag_fn(
        base_tag.strip() or None,
        candidate_tags,
    )
    notes.extend(current_tag_notes)
    if previous_tag is None:
        raise RuntimeError(
            "No previous tag found. Create an initial release tag or pass --base-tag."
        )

    pull_requests = discover_pull_requests_fn(
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

    runner = recommendation_runner or recommendation_runner_factory()
    recommendations = analyze_pull_requests_fn(
        pull_requests=pull_requests,
        recommendation_runner=runner,
        github_token=normalized_token,
        summary_line_re=summary_line_re,
        reasoning_line_re=reasoning_line_re,
    )
    unresolved_records = [record for record in recommendations if record.status != "classified"]
    release_label = aggregate_release_label_fn(recommendations)
    if release_label is None and unresolved_records:
        notes.append(
            "Release scope contains unresolved pull requests that need review before publish."
        )
        published_release_body = render_public_release_body_fn(recommendations)
        preview_notes = render_preview_notes_fn(
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
    _, next_tag, version_notes = detect_next_version_fn(release_label, previous_tag)
    notes.extend(version_notes)
    if release_label == "NO_BUMP":
        notes.append(
            "Release scope resolved to NO_BUMP; no tag or GitHub Release will be published."
        )
        preview_notes = render_no_release_preview_notes_fn(
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
    published_release_body = render_public_release_body_fn(recommendations)
    preview_notes = render_preview_notes_fn(
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


__all__ = [
    "aggregate_release_label",
    "prepare_release_plan",
    "resolve_target_ref",
    "run_git",
    "verify_release_candidate",
]
