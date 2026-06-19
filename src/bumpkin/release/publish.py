from __future__ import annotations

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
from bumpkin.release.models import ReleaseExecutionResult, ReleasePlan


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


def _build_publishers(*, github_token: str) -> tuple[TagPublisher, ReleasePublisher]:
    normalized_token = github_token.strip()
    if not normalized_token:
        raise ValueError("github token is required.")
    return (
        GitHubTagPublisher(token=normalized_token),
        GitHubReleasePublisher(token=normalized_token),
    )


__all__ = ["_build_publishers", "publish_release_plan"]
