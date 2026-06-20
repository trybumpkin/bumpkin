from __future__ import annotations

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
    *,
    number: int,
    label: str,
    title: str,
    reasoning: str = "public API additive evidence detected without breaking removal.",
    evidence_lines: tuple[str, ...] = (),
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
        summary="files affected: src/api.py; public=1, internal=0.",
        reasoning=reasoning,
        evidence_lines=evidence_lines,
    )


def test_build_release_why_lines_prefers_symbol_evidence_over_entrypoint_stub() -> None:
    records = [
        _record(
            number=12,
            label="MINOR",
            title="Add greet_pair API",
            evidence_lines=(
                "src/pkg/__init__.py | rule=export_symbol_added | scope=public_api",
                "src/pkg/api.py | rule=export_symbol_added | scope=public_api | symbol=greet_pair",
            ),
        ),
        _record(
            number=13,
            label="PATCH",
            title="Trim farewell inputs",
            reasoning="runtime-internal deltas detected; no public API evidence.",
            evidence_lines=("src/pkg/runtime.py | rule=changed_file_path | scope=runtime",),
        ),
    ]

    lines = _build_release_why_lines(
        release_label="MINOR",
        recommendations=records,
        target_sha="sha-main",
    )

    assert lines[0] == (
        "PR #12 introduced `greet_pair` in "
        "[`src/pkg/api.py`](https://github.com/acme/repo/blob/sha-main/src/pkg/api.py) and "
        "exposed it through the package entrypoint in "
        "[`src/pkg/__init__.py`](https://github.com/acme/repo/blob/sha-main/src/pkg/__init__.py), "
        "expanding the public API."
    )
    assert lines[1] == (
        "Overall, this batch adds public API without breaking existing consumers, so it warrants "
        "a MINOR bump. Lower-severity fixes are also included in this batch, but they do not "
        "change the overall MINOR outcome (PR #13)."
    )


def test_build_release_why_lines_uses_specific_reasoning_for_patch_records() -> None:
    records = [
        _record(
            number=21,
            label="PATCH",
            title="Normalize retry behavior",
            reasoning="retry handling changed without altering the exported API",
            evidence_lines=("src/pkg/runtime.py | rule=changed_file_path | scope=runtime",),
        ),
    ]

    lines = _build_release_why_lines(
        release_label="PATCH",
        recommendations=records,
        target_sha="sha-main",
    )

    assert lines[0] == (
        "PR #21 (Normalize retry behavior) stayed patch-level because retry handling changed "
        "without altering the exported API."
    )
    assert lines[1] == (
        "Overall, this batch changes runtime behavior without expanding the public API, so it "
        "warrants a PATCH bump."
    )


def test_resolve_preview_rationale_lines_uses_existing_pr_recommendation_outputs() -> None:
    records = [
        _record(
            number=31,
            label="MINOR",
            title="Add greeting catalog API",
            evidence_lines=(
                "src/python_test/__init__.py | rule=export_symbol_added | scope=public_api",
                "src/python_test/catalog.py | rule=export_symbol_added | scope=public_api | symbol=available_greetings",
            ),
        ),
    ]

    lines = resolve_preview_rationale_lines(
        release_label="MINOR",
        recommendations=records,
        target_sha="sha-main",
        model="ignored",
        models_endpoint="https://ignored.example/v1/chat/completions",
        models_token="ignored",
    )

    assert lines == [
        "PR #31 introduced `available_greetings` in "
        "[`src/python_test/catalog.py`](https://github.com/acme/repo/blob/sha-main/src/python_test/catalog.py) "
        "and exposed it through the package entrypoint in "
        "[`src/python_test/__init__.py`](https://github.com/acme/repo/blob/sha-main/src/python_test/__init__.py), "
        "expanding the public API.",
        "Overall, this batch adds public API without breaking existing consumers, so it warrants "
        "a MINOR bump.",
    ]
