from __future__ import annotations

import argparse
import json
import os
import re

from bumpkin.integrations.github.recommendations import (
    PipelineRecommendationRunner,
    RecommendationRunner,
)
from bumpkin.integrations.github.releases import GitHubReleasePublisher, ReleasePublisher
from bumpkin.integrations.github.tags import GitHubTagPublisher, TagPublisher
from bumpkin.release.analysis import (
    _analyze_pull_requests,
    _discover_pull_requests,
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
from bumpkin.release.output_writers import (
    _append_step_summary,
    _build_summary_payload,
    _render_publish_step_summary,
    _write_github_output,
    _write_json_file,
    _write_text_file,
)
from bumpkin.release.planning import (
    aggregate_release_label as _aggregate_release_label_impl,
)
from bumpkin.release.planning import (
    prepare_release_plan as _prepare_release_plan_impl,
)
from bumpkin.release.planning import (
    resolve_target_ref as _resolve_target_ref_impl,
)
from bumpkin.release.planning import (
    run_git as _run_git_impl,
)
from bumpkin.release.planning import (
    verify_release_candidate as _verify_release_candidate_impl,
)
from bumpkin.release.publish import publish_release_plan
from bumpkin.release.rendering import (
    _render_no_release_preview_notes,
    _render_preview_notes,
    _render_public_release_body,
)
from bumpkin.release.repository_client import (
    GitHubRepositoryClient,
    GitHubRepositoryClientProtocol,
)
from bumpkin.release.workflow_discovery import _resolve_release_candidate
from bumpkin.versioning.tags import detect_next_version, list_tags, resolve_current_tag

_LABEL_PRECEDENCE = {"NO_BUMP": 0, "PATCH": 1, "MINOR": 2, "MAJOR": 3}
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
    return _run_git_impl(args)


def _resolve_target_ref(input_target_ref: str) -> tuple[str, str]:
    return _resolve_target_ref_impl(input_target_ref, run_git_fn=_run_git)


def _verify_release_candidate(
    *,
    candidate: ReleaseCandidate,
    repository: str,
    target_ref: str,
    base_tag: str,
    client: GitHubRepositoryClientProtocol,
) -> ReleasePlan:
    return _verify_release_candidate_impl(
        candidate=candidate,
        repository=repository,
        target_ref=target_ref,
        base_tag=base_tag,
        client=client,
        resolve_target_ref_fn=_resolve_target_ref,
        list_tags_fn=list_tags,
        resolve_current_tag_fn=lambda latest_tag, tags: resolve_current_tag(
            latest_tag=latest_tag,
            tags=tags,
        ),
        discover_pull_requests_fn=_discover_pull_requests,
        candidate_fingerprint_fn=_candidate_fingerprint,
        candidate_fingerprint_payload_fn=_candidate_fingerprint_payload,
    )


def _aggregate_release_label(recommendations: list[ReleaseRecommendationRecord]) -> str | None:
    return _aggregate_release_label_impl(
        recommendations,
        label_precedence=_LABEL_PRECEDENCE,
    )


def prepare_release_plan(
    *,
    repository: str,
    github_token: str,
    target_ref: str,
    base_tag: str,
    client: GitHubRepositoryClientProtocol,
    recommendation_runner: RecommendationRunner | None = None,
) -> ReleasePlan:
    return _prepare_release_plan_impl(
        repository=repository,
        github_token=github_token,
        target_ref=target_ref,
        base_tag=base_tag,
        client=client,
        recommendation_runner=recommendation_runner,
        resolve_target_ref_fn=_resolve_target_ref,
        list_tags_fn=list_tags,
        resolve_current_tag_fn=lambda latest_tag, tags: resolve_current_tag(
            latest_tag=latest_tag,
            tags=tags,
        ),
        discover_pull_requests_fn=_discover_pull_requests,
        analyze_pull_requests_fn=_analyze_pull_requests,
        aggregate_release_label_fn=_aggregate_release_label,
        detect_next_version_fn=lambda release_label, latest_tag: detect_next_version(
            release_label,
            latest_tag=latest_tag,
        ),
        render_public_release_body_fn=_render_public_release_body,
        render_preview_notes_fn=_render_preview_notes,
        render_no_release_preview_notes_fn=_render_no_release_preview_notes,
        recommendation_runner_factory=PipelineRecommendationRunner,
        summary_line_re=_SUMMARY_LINE_RE,
        reasoning_line_re=_REASONING_LINE_RE,
    )


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
                release_candidate_artifact_name=_RELEASE_CANDIDATE_ARTIFACT_NAME,
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
            release_candidate_artifact_name=_RELEASE_CANDIDATE_ARTIFACT_NAME,
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
