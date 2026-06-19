from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bumpkin.integrations.github.recommendations import MergeRecommendation
from bumpkin.integrations.github.releases import ReleasePublishResult
from bumpkin.integrations.github.tags import TagPublishResult


@dataclass(frozen=True, slots=True)
class ReleaseScopedPullRequest:
    repository: str
    number: int
    title: str
    url: str
    author_login: str | None
    merged_at: datetime
    merge_commit_sha: str
    base_ref: str | None
    base_sha: str | None
    head_ref: str | None
    head_sha: str | None
    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReleaseRecommendationRecord:
    pull_request: ReleaseScopedPullRequest
    recommendation: MergeRecommendation | None
    status: str
    label: str | None
    reason: str | None = None
    summary: str | None = None
    reasoning: str | None = None
    evidence_lines: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReleasePlan:
    repository: str
    target_ref: str
    target_sha: str
    previous_tag: str | None
    next_tag: str | None
    release_label: str | None
    pull_requests: tuple[ReleaseScopedPullRequest, ...]
    recommendations: tuple[ReleaseRecommendationRecord, ...]
    preview_notes: str
    published_release_body: str
    notes: tuple[str, ...]
    status: str = "planned"


@dataclass(frozen=True, slots=True)
class ReleaseExecutionResult:
    status: str
    plan: ReleasePlan
    tag_result: TagPublishResult | None = None
    release_result: ReleasePublishResult | None = None


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    format_version: int
    source_operation: str
    source_run_id: str | None
    repository: str
    target_ref: str
    target_sha: str
    base_tag_input: str
    previous_tag: str | None
    next_tag: str | None
    release_label: str | None
    status: str
    preview_notes: str
    published_release_body: str
    notes: tuple[str, ...]
    pull_requests: tuple[ReleaseScopedPullRequest, ...]
    fingerprint: str


__all__ = [
    "ReleaseCandidate",
    "ReleaseExecutionResult",
    "ReleasePlan",
    "ReleaseRecommendationRecord",
    "ReleaseScopedPullRequest",
]
