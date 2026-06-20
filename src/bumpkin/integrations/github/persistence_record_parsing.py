from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from bumpkin.integrations.github.guards import ApprovalRecord
from bumpkin.integrations.github.persistence_models import (
    AuditLogRecord,
    PublishDecisionRecord,
    RecommendationSnapshot,
    ReleaseBacklogItem,
    StoredEventRecord,
)
from bumpkin.integrations.github.persistence_recommendation_parsing import (
    extract_comment_body as _extract_comment_body,
)
from bumpkin.integrations.github.persistence_recommendation_parsing import (
    extract_recommended_current_version as _extract_recommended_current_version,
)
from bumpkin.integrations.github.persistence_recommendation_parsing import (
    extract_recommended_label as _extract_recommended_label,
)
from bumpkin.integrations.github.persistence_recommendation_parsing import (
    normalize_semver_token as _normalize_semver_token,
)
from bumpkin.integrations.github.persistence_serialization import (
    from_iso as _from_iso,
)


def _optional_text(row: Mapping[str, object], key: str) -> str | None:
    value = row[key]
    return str(value) if value is not None else None


def _optional_int(row: Mapping[str, object], key: str) -> int | None:
    value = row[key]
    return int(cast("Any", value)) if value is not None else None


def _required_int(row: Mapping[str, object], key: str) -> int:
    return int(cast("Any", row[key]))


def _optional_datetime(row: Mapping[str, object], key: str) -> object | None:
    value = row[key]
    return _from_iso(str(value)) if value is not None else None


def _load_json_value(row: Mapping[str, object], key: str) -> object:
    return json.loads(str(row[key]))


def build_stored_event_record(row: Mapping[str, object]) -> StoredEventRecord:
    payload = cast("dict[str, Any]", _load_json_value(row, "payload"))
    return StoredEventRecord(
        provider=str(row["provider"]),
        provider_event_id=str(row["provider_event_id"]),
        event_type=str(row["event_type"]),
        action=_optional_text(row, "action"),
        repository=_optional_text(row, "repository"),
        pull_request_number=_optional_int(row, "pull_request_number"),
        sender_login=_optional_text(row, "sender_login"),
        received_at=_from_iso(str(row["received_at"])),
        payload=payload,
        payload_hash=str(row["payload_hash"]),
        headers_hash=str(row["headers_hash"]),
        status=str(row["status"]),
    )


def build_recommendation_snapshot(
    *,
    label: str,
    current_version: str | None,
) -> RecommendationSnapshot:
    return RecommendationSnapshot(
        label=str(label).strip().upper(),
        current_version=_normalize_semver_token(current_version) if current_version else None,
    )


def build_recommendation_snapshot_from_row(
    row: Mapping[str, object],
) -> RecommendationSnapshot:
    current_version_value = row["current_version"]
    return build_recommendation_snapshot(
        label=str(row["label"]),
        current_version=(
            str(current_version_value) if current_version_value is not None else None
        ),
    )


def extract_recommendation_snapshot_from_payload(
    payload: object,
) -> RecommendationSnapshot | None:
    if not isinstance(payload, dict):
        return None
    body = _extract_comment_body(payload)
    if not body:
        return None
    label = _extract_recommended_label(body)
    if label is None:
        return None
    return build_recommendation_snapshot(
        label=label,
        current_version=_extract_recommended_current_version(body),
    )


def build_release_backlog_item(row: Mapping[str, object]) -> ReleaseBacklogItem:
    recommended_current_version = row["recommended_current_version"]
    return ReleaseBacklogItem(
        id=_required_int(row, "id"),
        repository=str(row["repository"]),
        pull_request_number=_required_int(row, "pull_request_number"),
        merge_commit_sha=str(row["merge_commit_sha"]),
        recommended_label=str(row["recommended_label"]),
        recommended_current_version=(
            _normalize_semver_token(str(recommended_current_version))
            if recommended_current_version is not None
            else None
        ),
        pull_request_title=_optional_text(row, "pull_request_title"),
        pull_request_author_login=_optional_text(row, "pull_request_author_login"),
        pull_request_url=_optional_text(row, "pull_request_url"),
        release_summary=_optional_text(row, "release_summary"),
        source_event_id=_optional_text(row, "source_event_id"),
        merged_at=_from_iso(str(row["merged_at"])),
        included_in_release_tag=_optional_text(row, "included_in_release_tag"),
        included_at=cast("Any", _optional_datetime(row, "included_at")),
    )


def build_approval_record(row: Mapping[str, object]) -> ApprovalRecord:
    return ApprovalRecord(
        repository=str(row["repository"]),
        pull_request_number=_required_int(row, "pull_request_number"),
        approved_label=str(row["approved_label"]),
        recommendation_hash=str(row["recommendation_hash"]),
        approved_by=str(row["approved_by"]),
        approved_at=_from_iso(str(row["approved_at"])),
    )


def build_publish_decision_record(
    row: Mapping[str, object],
) -> PublishDecisionRecord:
    guard_reasons_payload = _load_json_value(row, "guard_reasons")
    guard_reasons_raw = []
    if isinstance(guard_reasons_payload, dict):
        maybe_items = guard_reasons_payload.get("guard_reasons", [])
        if isinstance(maybe_items, list):
            guard_reasons_raw = maybe_items
    guard_reasons = tuple(
        item for item in guard_reasons_raw if isinstance(item, str) and item.strip()
    )
    policy_snapshot = cast("dict[str, Any]", _load_json_value(row, "policy_snapshot"))
    return PublishDecisionRecord(
        repository=str(row["repository"]),
        pull_request_number=_required_int(row, "pull_request_number"),
        commit_sha=str(row["commit_sha"]),
        allowed=bool(row["allowed"]),
        reason=str(row["reason"]),
        guard_reasons=guard_reasons,
        evaluated_at=_from_iso(str(row["evaluated_at"])),
        policy_snapshot=policy_snapshot,
    )


def build_audit_log_record(row: Mapping[str, object]) -> AuditLogRecord:
    details = cast("dict[str, Any]", _load_json_value(row, "details"))
    return AuditLogRecord(
        entity_type=str(row["entity_type"]),
        entity_id=str(row["entity_id"]),
        action=str(row["action"]),
        actor=str(row["actor"]),
        timestamp=_from_iso(str(row["timestamp"])),
        details=details,
    )
