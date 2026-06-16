from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from bumpkin.integrations.github.recommendations import (
    MergeRecommendation,
    MergeRecommendationRequest,
)
from bumpkin.integrations.github.releases import ReleasePublishRequest, ReleasePublishResult
from bumpkin.integrations.github.tags import TagPublishRequest, TagPublishResult
from bumpkin.release_job import (
    ReleaseScopedPullRequest,
    _deserialize_release_candidate,
    run_release_job,
)


def _pull_request(
    *,
    number: int,
    title: str,
    author_login: str,
    merged_at: datetime,
) -> ReleaseScopedPullRequest:
    return ReleaseScopedPullRequest(
        repository="acme/repo",
        number=number,
        title=title,
        url=f"https://github.com/acme/repo/pull/{number}",
        author_login=author_login,
        merged_at=merged_at,
        merge_commit_sha=f"merge-{number}",
        base_ref="main",
        base_sha=f"base-{number}",
        head_ref=f"feature-{number}",
        head_sha=f"head-{number}",
        labels=(),
    )


class _FakeRepositoryClient:
    def __init__(
        self,
        *,
        tags: list[str],
        commits: list[str],
        pulls_by_commit: dict[str, list[int]],
        pull_requests: dict[int, ReleaseScopedPullRequest],
    ) -> None:
        self._tags = tags
        self._commits = commits
        self._pulls_by_commit = pulls_by_commit
        self._pull_requests = pull_requests

    def list_tags(self) -> list[str]:
        return list(self._tags)

    def compare_commits(self, *, base_ref: str, head_ref: str) -> list[str]:
        assert base_ref
        assert head_ref
        return list(self._commits)

    def list_pull_requests_for_commit(self, commit_sha: str) -> list[int]:
        return list(self._pulls_by_commit.get(commit_sha, []))

    def get_pull_request(self, number: int) -> ReleaseScopedPullRequest:
        return self._pull_requests[number]


class _FakeRecommendationRunner:
    def __init__(self, labels_by_pr: dict[int, str]) -> None:
        self._labels_by_pr = labels_by_pr

    def generate(self, request: MergeRecommendationRequest) -> MergeRecommendation:
        pr_payload = cast("dict[str, object]", request.payload["pull_request"])
        pr_number = int(cast("int | str", pr_payload["number"]))
        label = self._labels_by_pr[pr_number]
        return MergeRecommendation(
            body=(
                f"Recommendation : {label}\n"
                "Summary        : files affected: src/api.py, src/runtime.py; public=1, internal=1.\n\n"
                f"Reasoning      : {label.lower()} evidence was detected from exported API analysis.\n\n"
                "Findings:\n"
                f"- src/api.py | rule=export_symbol_{'removed' if label == 'MAJOR' else 'added'} | "
                f"scope=public_api | suggested={label} | symbol=publicThing\n"
                "- src/runtime.py | rule=changed_file_path | scope=runtime_internal | suggested=PATCH | target=retry flow\n\n"
                "Next version   : v1.2.3 -> v1.3.0\n"
            ),
            label=label,
            current_version="v1.2.3",
        )


class _FakeTagPublisher:
    def __init__(self) -> None:
        self.calls: list[TagPublishRequest] = []

    def publish(self, request: TagPublishRequest) -> TagPublishResult:
        self.calls.append(request)
        return TagPublishResult(
            status="created",
            tag_name=request.tag_name,
            url=f"https://github.com/{request.repository}/releases/tag/{request.tag_name}",
        )


class _FakeReleasePublisher:
    def __init__(self) -> None:
        self.calls: list[ReleasePublishRequest] = []

    def publish(self, request: ReleasePublishRequest) -> ReleasePublishResult:
        self.calls.append(request)
        return ReleasePublishResult(
            status="created",
            tag_name=request.tag_name,
            url=f"https://github.com/{request.repository}/releases/tag/{request.tag_name}",
            release_id=101,
        )


def _load_candidate(candidate_path: Path):
    return _deserialize_release_candidate(json.loads(candidate_path.read_text(encoding="utf-8")))


def test_run_release_job_preview_then_publish_reuses_saved_candidate(tmp_path, monkeypatch) -> None:
    pr_31 = _pull_request(
        number=31,
        title="Add release preview artifact upload",
        author_login="alice",
        merged_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
    )
    pr_32 = _pull_request(
        number=32,
        title="Fix release summary output",
        author_login="bob",
        merged_at=datetime(2026, 6, 2, 14, 0, tzinfo=UTC),
    )
    client = _FakeRepositoryClient(
        tags=["v1.2.3"],
        commits=["c1", "c2"],
        pulls_by_commit={"c1": [31], "c2": [32]},
        pull_requests={31: pr_31, 32: pr_32},
    )
    runner = _FakeRecommendationRunner({31: "MINOR", 32: "PATCH"})
    tag_publisher = _FakeTagPublisher()
    release_publisher = _FakeReleasePublisher()

    preview_notes_path = tmp_path / "preview-notes.md"
    preview_candidate_path = tmp_path / "preview-candidate.json"
    preview_output_path = tmp_path / "preview-output.txt"
    preview_summary_path = tmp_path / "preview-summary.md"

    publish_notes_path = tmp_path / "publish-notes.md"
    publish_candidate_path = tmp_path / "publish-candidate.json"
    publish_output_path = tmp_path / "publish-output.txt"
    publish_summary_path = tmp_path / "publish-summary.md"

    monkeypatch.setattr(
        "bumpkin.release_job._resolve_target_ref", lambda _target: ("main", "sha-main")
    )
    monkeypatch.setattr("bumpkin.release_job.list_tags", list)
    monkeypatch.setattr(
        "bumpkin.release_job.GitHubRepositoryClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        "bumpkin.release_job.PipelineRecommendationRunner",
        lambda: runner,
    )
    monkeypatch.setattr(
        "bumpkin.release_job.GitHubTagPublisher",
        lambda **_kwargs: tag_publisher,
    )
    monkeypatch.setattr(
        "bumpkin.release_job.GitHubReleasePublisher",
        lambda **_kwargs: release_publisher,
    )

    monkeypatch.setenv("GITHUB_RUN_ID", "777")
    monkeypatch.setenv("GITHUB_OUTPUT", str(preview_output_path))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(preview_summary_path))

    preview_exit_code = run_release_job(
        argparse.Namespace(
            operation="preview",
            repository="acme/repo",
            github_token="token-123",
            target_ref="main",
            base_tag="",
            output_markdown=str(preview_notes_path),
            candidate_output=str(preview_candidate_path),
            preview_run_id="",
            request_timeout=15,
        )
    )

    preview_candidate = _load_candidate(preview_candidate_path)
    preview_notes = preview_notes_path.read_text(encoding="utf-8")

    assert preview_exit_code == 0
    assert preview_candidate.source_run_id == "777"
    assert preview_candidate.source_operation == "release_preview"
    assert preview_candidate.next_tag == "v1.3.0"
    assert "## Release rationale" in preview_notes
    assert "## Key evidence" in preview_notes
    assert "## Public release notes" in preview_notes

    monkeypatch.setenv("GITHUB_OUTPUT", str(publish_output_path))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(publish_summary_path))
    monkeypatch.setattr(
        "bumpkin.release_job._resolve_release_candidate",
        lambda **_kwargs: _load_candidate(preview_candidate_path),
    )

    publish_exit_code = run_release_job(
        argparse.Namespace(
            operation="publish",
            repository="acme/repo",
            github_token="token-123",
            target_ref="main",
            base_tag="",
            output_markdown=str(publish_notes_path),
            candidate_output=str(publish_candidate_path),
            preview_run_id="777",
            request_timeout=15,
        )
    )

    publish_candidate = _load_candidate(publish_candidate_path)
    published_notes = publish_notes_path.read_text(encoding="utf-8")
    publish_summary = publish_summary_path.read_text(encoding="utf-8")

    assert publish_exit_code == 0
    assert publish_candidate.fingerprint == preview_candidate.fingerprint
    assert publish_candidate.published_release_body == preview_candidate.published_release_body
    assert published_notes == preview_candidate.published_release_body
    assert "## Features" in published_notes
    assert "## Fixes" in published_notes
    assert "## Contributors" in published_notes
    assert "## Release rationale" not in published_notes
    assert "## Versioning context" not in published_notes
    assert "## Key evidence" not in published_notes
    assert len(tag_publisher.calls) == 1
    assert len(release_publisher.calls) == 1
    assert release_publisher.calls[0].body == preview_candidate.published_release_body
    assert release_publisher.calls[0].tag_name == "v1.3.0"
    assert "Preview run id: 777" in publish_summary
    assert "Release candidate verified and published." in publish_summary
