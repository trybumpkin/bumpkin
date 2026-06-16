from __future__ import annotations

import os
import subprocess

from bumpkin.integrations.github.recommendations import (
    MergeRecommendationRequest,
    PipelineRecommendationRunner,
    _ensure_event_refs_available,
    _extract_label,
)
from bumpkin.integrations.github.types import AppEvent
from bumpkin.orchestrator import pipeline as orchestrator_pipeline


def test_extract_label_accepts_canonical_patch_label() -> None:
    body = "Proposed bump (court): PATCH (high confidence)"
    assert _extract_label(body) == "PATCH"


def test_extract_label_normalizes_no_bump_variants() -> None:
    body = "Proposed bump (court): NO BUMP (medium confidence)"
    assert _extract_label(body) == "NO_BUMP"


def test_extract_label_accepts_current_comment_recommendation_line_with_emoji() -> None:
    body = "Recommendation : 🟢 PATCH"
    assert _extract_label(body) == "PATCH"


def test_extract_label_accepts_current_comment_recommendation_line_no_bump() -> None:
    body = "Recommendation : ⚪ NO_BUMP"
    assert _extract_label(body) == "NO_BUMP"


def test_extract_label_rejects_non_canonical_na_token() -> None:
    body = "Proposed bump (court): N/A (manual review)"
    assert _extract_label(body) is None


def test_ensure_event_refs_available_fetches_base_ref_before_head_ref(monkeypatch) -> None:
    event = AppEvent(
        event="pull_request",
        action="closed",
        installation_id=1,
        delivery_id="delivery-1",
        repository="acme/repo",
        pull_request_number=63,
        sender_login="octocat",
        merged=True,
        merge_commit_sha="merge-sha",
        base_ref="main",
        base_sha="base-sha",
        head_ref="feature",
        head_sha="head-sha",
    )
    commands: list[tuple[str, ...]] = []
    existing = {"base-sha", "head-sha"}

    def fake_run_git(*args: str) -> str:
        commands.append(args)
        if args[:2] == ("rev-parse", "--verify"):
            target = args[2]
            if target not in existing:
                raise RuntimeError(f"missing {target}")
            return target
        if args[:4] == ("fetch", "--no-tags", "origin", "main"):
            existing.add("merge-sha")
            return ""
        if args[:4] == ("fetch", "--no-tags", "origin", "feature"):
            raise AssertionError(
                "deleted head ref should not be fetched once merge sha is available"
            )
        raise AssertionError(args)

    monkeypatch.setattr("bumpkin.integrations.github.recommendations._run_git", fake_run_git)

    _ensure_event_refs_available(event)

    assert commands == [
        ("rev-parse", "--verify", "merge-sha"),
        ("fetch", "--no-tags", "origin", "main"),
        ("rev-parse", "--verify", "merge-sha"),
    ]


def test_ensure_event_refs_available_skips_fetch_when_merge_sha_exists(monkeypatch) -> None:
    event = AppEvent(
        event="pull_request",
        action="closed",
        installation_id=1,
        delivery_id="delivery-1",
        repository="acme/repo",
        pull_request_number=63,
        sender_login="octocat",
        merged=True,
        merge_commit_sha="merge-sha",
        base_ref="main",
        base_sha="base-sha",
        head_ref="feature",
        head_sha="head-sha",
    )
    commands: list[tuple[str, ...]] = []

    def fake_run_git(*args: str) -> str:
        commands.append(args)
        if args[:2] == ("rev-parse", "--verify"):
            return args[2]
        raise AssertionError(args)

    monkeypatch.setattr("bumpkin.integrations.github.recommendations._run_git", fake_run_git)

    _ensure_event_refs_available(event)

    assert commands == [("rev-parse", "--verify", "merge-sha")]


def test_ensure_event_refs_available_raises_when_non_merged_head_ref_fetch_fails(
    monkeypatch,
) -> None:
    event = AppEvent(
        event="pull_request",
        action="synchronize",
        installation_id=1,
        delivery_id="delivery-1",
        repository="acme/repo",
        pull_request_number=63,
        sender_login="octocat",
        merged=False,
        merge_commit_sha=None,
        base_ref="main",
        base_sha="base-sha",
        head_ref="feature",
        head_sha="head-sha",
    )
    commands: list[tuple[str, ...]] = []
    existing = {"base-sha"}

    def fake_run_git(*args: str) -> str:
        commands.append(args)
        if args[:2] == ("rev-parse", "--verify"):
            target = args[2]
            if target not in existing:
                raise RuntimeError(f"missing {target}")
            return target
        if args[:4] == ("fetch", "--no-tags", "origin", "main"):
            return ""
        if args[:4] == ("fetch", "--no-tags", "origin", "feature"):
            raise subprocess.CalledProcessError(
                returncode=128, cmd=["git", *args], stderr="not found"
            )
        raise AssertionError(args)

    monkeypatch.setattr("bumpkin.integrations.github.recommendations._run_git", fake_run_git)

    try:
        _ensure_event_refs_available(event)
    except RuntimeError as err:
        message = str(err)
    else:
        raise AssertionError("expected RuntimeError for non-merged head ref fetch failure")

    assert "fetch failed" in message
    assert commands == [
        ("rev-parse", "--verify", "head-sha"),
        ("fetch", "--no-tags", "origin", "main"),
        ("rev-parse", "--verify", "head-sha"),
        ("fetch", "--no-tags", "origin", "feature"),
    ]


def test_pipeline_runner_uses_github_api_diff_fallback_when_git_refs_unavailable(
    monkeypatch,
) -> None:
    event = AppEvent(
        event="pull_request",
        action="closed",
        installation_id=1,
        delivery_id="delivery-1",
        repository="acme/repo",
        pull_request_number=68,
        sender_login="octocat",
        merged=True,
        merge_commit_sha="merge-sha",
        base_ref="main",
        base_sha="base-sha",
        head_ref="feature",
        head_sha="head-sha",
    )
    payload = {
        "pull_request": {"number": 68, "merged": True},
        "repository": {"full_name": "acme/repo"},
    }
    runner = PipelineRecommendationRunner(
        model="gemini-2.5-flash",
        models_endpoint="https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    def fake_ensure(_: AppEvent) -> None:
        raise RuntimeError("git unavailable")

    monkeypatch.setattr(
        "bumpkin.integrations.github.recommendations._ensure_event_refs_available", fake_ensure
    )
    monkeypatch.setattr(
        "bumpkin.integrations.github.recommendations._fetch_pull_request_files",
        lambda **_: [
            {
                "filename": "src/example.py",
                "status": "modified",
                "patch": "@@ -1 +1 @@\n-old\n+new\n",
            }
        ],
    )

    observed: dict[str, object] = {}

    def fake_run(_: object, *, comment_poster=None) -> int:
        diff_result = orchestrator_pipeline.build_diff(
            from_ref="base",
            to_ref="merge",
            ignore_patterns=[],
            allowed_files=None,
            token_cap=6000,
            use_difftastic=False,
            chunking_enabled=True,
        )
        observed["files"] = diff_result.analyzed_files
        observed["diff"] = diff_result.full_diff_text
        observed["notes"] = diff_result.notes
        assert comment_poster is not None
        comment_poster(
            token="",
            repo="acme/repo",
            pr_number=68,
            body=(
                "<!-- bumpkin:recommendation -->\n"
                "Proposed bump (court): PATCH (low confidence)\n"
                "Next version   : v1.2.3 -> v1.2.4\n"
            ),
        )
        return 0

    monkeypatch.setattr(
        "bumpkin.integrations.github.recommendations.orchestrator_pipeline.run", fake_run
    )

    recommendation = runner.generate(
        MergeRecommendationRequest(
            event=event,
            payload=payload,
            provider_token="token-123",
        )
    )

    assert recommendation.label == "PATCH"
    assert recommendation.current_version == "1.2.3"
    assert observed["files"] == ["src/example.py"]
    assert "diff --git a/src/example.py b/src/example.py" in str(observed["diff"])
    assert "Using GitHub API PR files fallback" in str(observed["notes"])


def test_pipeline_runner_uses_capture_only_mode_for_release_scope(monkeypatch) -> None:
    event = AppEvent(
        event="pull_request",
        action="closed",
        installation_id=1,
        delivery_id="delivery-1",
        repository="acme/repo",
        pull_request_number=69,
        sender_login="octocat",
        merged=True,
        merge_commit_sha="merge-sha",
        base_ref="main",
        base_sha="base-sha",
        head_ref="feature",
        head_sha="head-sha",
    )
    payload = {
        "pull_request": {"number": 69, "merged": True},
        "repository": {"full_name": "acme/repo"},
    }
    runner = PipelineRecommendationRunner(
        model="gemini-2.5-flash",
        models_endpoint="https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    monkeypatch.setattr(
        "bumpkin.integrations.github.recommendations._ensure_event_refs_available",
        lambda _event: None,
    )

    observed: dict[str, object] = {}

    def fake_run(_: object, *, comment_poster=None) -> int:
        observed["capture_only"] = os.environ.get("BUMPKIN_CAPTURE_PR_COMMENT_ONLY")
        assert comment_poster is not None
        comment_poster(
            token="",
            repo="acme/repo",
            pr_number=69,
            body=(
                "<!-- bumpkin:recommendation -->\n"
                "Proposed bump (court): PATCH (low confidence)\n"
                "Next version   : v1.2.3 -> v1.2.4\n"
            ),
        )
        return 0

    monkeypatch.setattr(
        "bumpkin.integrations.github.recommendations.orchestrator_pipeline.run", fake_run
    )

    recommendation = runner.generate(
        MergeRecommendationRequest(
            event=event,
            payload=payload,
            provider_token="token-123",
        )
    )

    assert recommendation.label == "PATCH"
    assert observed["capture_only"] == "1"


def test_pipeline_runner_requires_provider_token_for_api_fallback(monkeypatch) -> None:
    event = AppEvent(
        event="pull_request",
        action="closed",
        installation_id=1,
        delivery_id="delivery-1",
        repository="acme/repo",
        pull_request_number=68,
        sender_login="octocat",
        merged=True,
        merge_commit_sha="merge-sha",
        base_ref="main",
        base_sha="base-sha",
        head_ref="feature",
        head_sha="head-sha",
    )
    runner = PipelineRecommendationRunner(
        model="gemini-2.5-flash",
        models_endpoint="https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    def fake_ensure(_: AppEvent) -> None:
        raise RuntimeError("git unavailable")

    monkeypatch.setattr(
        "bumpkin.integrations.github.recommendations._ensure_event_refs_available", fake_ensure
    )

    try:
        runner.generate(
            MergeRecommendationRequest(
                event=event,
                payload={"pull_request": {"number": 68}},
                provider_token=None,
            )
        )
    except RuntimeError as err:
        message = str(err)
    else:
        raise AssertionError("expected RuntimeError when fallback token is missing")

    assert "provider token" in message
