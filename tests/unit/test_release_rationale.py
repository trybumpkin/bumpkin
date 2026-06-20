from __future__ import annotations

import json
from datetime import UTC, datetime

from bumpkin.integrations.github.recommendations import MergeRecommendation
from bumpkin.release.models import ReleaseRecommendationRecord, ReleaseScopedPullRequest
from bumpkin.release.rationale import _build_release_why_lines, resolve_preview_rationale_lines


def _pull_request(*, number: int, title: str) -> ReleaseScopedPullRequest:
    return ReleaseScopedPullRequest(
        repository="acme/repo",
        number=number,
        title=title,
        url=f"https://github.com/acme/repo/pull/{number}",
        author_login="alice",
        merged_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        merge_commit_sha=f"merge-{number}",
        base_ref="main",
        base_sha=f"base-{number}",
        head_ref=f"feature-{number}",
        head_sha=f"head-{number}",
        labels=(),
    )


def _record(
    *, number: int, label: str, title: str, evidence_lines: tuple[str, ...]
) -> ReleaseRecommendationRecord:
    return ReleaseRecommendationRecord(
        pull_request=_pull_request(number=number, title=title),
        recommendation=MergeRecommendation(
            body=f"Recommendation : {label}\n",
            label=label,
            current_version="v1.2.3",
        ),
        status="classified",
        label=label,
        summary="public surface changed",
        reasoning="deterministic evidence detected from exported API analysis",
        evidence_lines=evidence_lines,
    )


def test_resolve_preview_rationale_lines_uses_model_rewrite_when_valid() -> None:
    records = [
        _record(
            number=12,
            label="MINOR",
            title="Add greet_pair API",
            evidence_lines=(
                "src/api.py | rule=export_symbol_added | scope=public_api | symbol=greet_pair",
            ),
        ),
        _record(
            number=13,
            label="PATCH",
            title="Trim farewell inputs",
            evidence_lines=("src/api.py | rule=changed_file_path | scope=runtime",),
        ),
    ]

    def fake_post_json_request(**_: object) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "lines": [
                                    "PR #12 introduced `greet_pair`, expanding the callable greeting API.",
                                    "This batch remains additive, with one lower-severity PATCH also included in the release notes.",
                                ]
                            }
                        )
                    }
                }
            ]
        }

    lines = resolve_preview_rationale_lines(
        release_label="MINOR",
        recommendations=records,
        target_sha="sha-main",
        model="deepseek/deepseek-chat",
        models_endpoint="https://example.com/v1/chat/completions",
        models_token="token-123",
        post_json_request_fn=fake_post_json_request,
    )

    assert lines == [
        "PR #12 introduced `greet_pair`, expanding the callable greeting API.",
        "This batch remains additive, with one lower-severity PATCH also included in the release notes.",
    ]


def test_resolve_preview_rationale_lines_accepts_plaintext_bullets() -> None:
    records = [
        _record(
            number=12,
            label="MINOR",
            title="Add greet_pair API",
            evidence_lines=(
                "src/api.py | rule=export_symbol_added | scope=public_api | symbol=greet_pair",
            ),
        ),
    ]

    def fake_post_json_request(**_: object) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": "- PR #12 introduced greet_pair for paired greetings.\n- This batch remains additive."
                    }
                }
            ]
        }

    lines = resolve_preview_rationale_lines(
        release_label="MINOR",
        recommendations=records,
        target_sha="sha-main",
        model="deepseek/deepseek-chat",
        models_endpoint="https://example.com/v1/chat/completions",
        models_token="token-123",
        post_json_request_fn=fake_post_json_request,
    )

    assert lines == [
        "PR #12 introduced greet_pair for paired greetings.",
        "This batch remains additive.",
    ]


def test_resolve_preview_rationale_lines_repairs_non_json_output() -> None:
    records = [
        _record(
            number=12,
            label="MINOR",
            title="Add greet_pair API",
            evidence_lines=(
                "src/api.py | rule=export_symbol_added | scope=public_api | symbol=greet_pair",
            ),
        ),
    ]
    calls = {"count": 0}
    notes: list[str] = []

    def fake_post_json_request(**_: object) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": ("- one\n- two\n- three\n- four\n- five\n- six\n- seven\n")
                        }
                    }
                ]
            }
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "lines": [
                                    "PR #12 introduced greet_pair for paired greetings.",
                                    "This batch remains additive.",
                                ]
                            }
                        )
                    }
                }
            ]
        }

    lines = resolve_preview_rationale_lines(
        release_label="MINOR",
        recommendations=records,
        target_sha="sha-main",
        model="deepseek/deepseek-chat",
        models_endpoint="https://example.com/v1/chat/completions",
        models_token="token-123",
        post_json_request_fn=fake_post_json_request,
        notes=notes,
    )

    assert calls["count"] == 2
    assert lines == [
        "PR #12 introduced greet_pair for paired greetings.",
        "This batch remains additive.",
    ]
    assert any("required repair before it could be used" in note for note in notes)


def test_resolve_preview_rationale_lines_falls_back_when_model_references_unknown_pr() -> None:
    records = [
        _record(
            number=12,
            label="MINOR",
            title="Add greet_pair API",
            evidence_lines=(
                "src/api.py | rule=export_symbol_added | scope=public_api | symbol=greet_pair",
            ),
        ),
    ]
    notes: list[str] = []

    def fake_post_json_request(**_: object) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "lines": [
                                    "PR #999 introduced a new API helper.",
                                    "This batch remains additive.",
                                ]
                            }
                        )
                    }
                }
            ]
        }

    lines = resolve_preview_rationale_lines(
        release_label="MINOR",
        recommendations=records,
        target_sha="sha-main",
        model="deepseek/deepseek-chat",
        models_endpoint="https://example.com/v1/chat/completions",
        models_token="token-123",
        post_json_request_fn=fake_post_json_request,
        notes=notes,
    )

    assert lines == _build_release_why_lines(
        release_label="MINOR",
        recommendations=records,
        target_sha="sha-main",
    )
    assert any("using deterministic rationale after rewrite fallback" in note for note in notes)
