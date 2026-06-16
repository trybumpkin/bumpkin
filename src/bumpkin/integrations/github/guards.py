from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    repository: str
    pull_request_number: int
    approved_label: str
    recommendation_hash: str
    approved_by: str
    approved_at: datetime


@dataclass(frozen=True, slots=True)
class PublishGuardDecision:
    allowed: bool
    guard_reasons: tuple[str, ...] = ()


class ApprovalStore(Protocol):
    def get(self, repository: str, pull_request_number: int) -> ApprovalRecord | None: ...


def _normalize_dt(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def evaluate_publish_guard(
    *,
    approval: ApprovalRecord | None,
    current_recommendation_hash: str | None,
    required_checks_passed: bool,
    target_branch: str,
    allowed_branches: tuple[str, ...] = ("main",),
    actor_is_release_manager: bool,
    now: datetime | None = None,
    max_age_days: int = 7,
) -> PublishGuardDecision:
    reasons: list[str] = []
    evaluation_time = _normalize_dt(now or datetime.now(UTC))

    if approval is None:
        reasons.append("missing_approval")
        return PublishGuardDecision(allowed=False, guard_reasons=tuple(reasons))

    approval_time = _normalize_dt(approval.approved_at)
    if approval_time > evaluation_time:
        reasons.append("approval_timestamp_in_future")
    elif evaluation_time - approval_time > timedelta(days=max_age_days):
        reasons.append("stale_approval")

    normalized_hash = str(current_recommendation_hash or "").strip()
    if not normalized_hash:
        reasons.append("missing_recommendation_hash")
    elif normalized_hash != approval.recommendation_hash:
        reasons.append("recommendation_hash_mismatch")

    if not required_checks_passed:
        reasons.append("required_checks_not_green")

    normalized_target = str(target_branch or "").strip()
    normalized_allowed = {branch.strip() for branch in allowed_branches if branch.strip()}
    if normalized_target not in normalized_allowed:
        reasons.append(f"branch_not_allowed:{normalized_target or 'unknown'}")

    if not actor_is_release_manager:
        reasons.append("actor_not_authorized")

    return PublishGuardDecision(allowed=not reasons, guard_reasons=tuple(reasons))


def evaluate_publish_for_pr(
    *,
    approval_store: ApprovalStore,
    repository: str,
    pull_request_number: int,
    current_recommendation_hash: str | None,
    required_checks_passed: bool,
    target_branch: str,
    actor_is_release_manager: bool,
    now: datetime | None = None,
    allowed_branches: tuple[str, ...] = ("main",),
    max_age_days: int = 7,
) -> PublishGuardDecision:
    approval = approval_store.get(repository, pull_request_number)
    return evaluate_publish_guard(
        approval=approval,
        current_recommendation_hash=current_recommendation_hash,
        required_checks_passed=required_checks_passed,
        target_branch=target_branch,
        allowed_branches=allowed_branches,
        actor_is_release_manager=actor_is_release_manager,
        now=now,
        max_age_days=max_age_days,
    )
