from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bumpkin.release_job import (
    ReleasePlan,
    ReleaseScopedPullRequest,
    _build_release_candidate,
    _serialize_release_candidate,
)


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "ci" / "verify_release_flow.py"
    spec = importlib.util.spec_from_file_location("verify_release_flow", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load verify_release_flow module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_flow_verifier_runs_from_repo_root_without_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "ci" / "verify_release_flow.py"
    env = {key: value for key, value in os.environ.items() if key.upper() != "PYTHONPATH"}

    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "Validate Bumpkin preview and publish release flow artifacts." in result.stdout


def _candidate_payload(
    *,
    repository: str = "acme/repo",
    status: str = "planned",
    release_label: str | None = "MINOR",
    next_tag: str | None = "v1.3.0",
    preview_notes: str = "# preview\n",
    published_release_body: str = "## Features\n- public change\n",
) -> dict[str, object]:
    pull_request = ReleaseScopedPullRequest(
        repository=repository,
        number=12,
        title="Add release-scoped aggregation",
        url=f"https://github.com/{repository}/pull/12",
        author_login="alice",
        merged_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        merge_commit_sha="merge-12",
        base_ref="main",
        base_sha="base-12",
        head_ref="feature-12",
        head_sha="head-12",
        labels=(),
    )
    plan = ReleasePlan(
        repository=repository,
        target_ref="main",
        target_sha="sha-main",
        previous_tag="v1.2.3",
        next_tag=next_tag,
        release_label=release_label,
        pull_requests=(pull_request,),
        recommendations=(),
        preview_notes=preview_notes,
        published_release_body=published_release_body,
        notes=(),
        status=status,
    )
    candidate = _build_release_candidate(
        plan=plan,
        base_tag_input="",
        source_operation="release_preview",
        source_run_id="12345",
    )
    return _serialize_release_candidate(candidate)


def test_release_flow_verifier_accepts_preview_artifacts(tmp_path, monkeypatch) -> None:
    module = _load_module()
    notes_path = tmp_path / "preview.md"
    candidate_path = tmp_path / "candidate.json"
    notes_path.write_text(
        (
            "# v1.3.0\n"
            "## Release rationale\n"
            "- A reason\n"
            "## Versioning context\n"
            "- A context line\n"
            "## Key evidence\n"
            "- A fact\n"
            "## Public release notes\n"
            "## Features\n"
            "- public change"
        ),
        encoding="utf-8",
    )
    candidate_path.write_text(json.dumps(_candidate_payload()), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_release_flow.py",
            "--mode",
            "preview",
            "--notes-path",
            str(notes_path),
            "--candidate-path",
            str(candidate_path),
            "--expected-repository",
            "acme/repo",
            "--expected-status",
            "planned",
        ],
    )

    assert module.main() == 0


def test_release_flow_verifier_accepts_publish_artifacts(tmp_path, monkeypatch) -> None:
    module = _load_module()
    notes_path = tmp_path / "publish.md"
    candidate_path = tmp_path / "candidate.json"
    published_body = "## Features\n- public change\n## Contributors\n@alice\n"
    notes_path.write_text(published_body, encoding="utf-8")
    payload = _candidate_payload(
        repository="trybumpkin/bumpkin-test",
        published_release_body=published_body,
    )
    candidate_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_release_flow.py",
            "--mode",
            "publish",
            "--notes-path",
            str(notes_path),
            "--candidate-path",
            str(candidate_path),
            "--expected-repository",
            "trybumpkin/bumpkin-test",
            "--expected-status",
            "published",
        ],
    )

    assert module.main() == 0


def test_release_flow_verifier_rejects_publish_body_with_maintainer_sections(
    tmp_path, monkeypatch
) -> None:
    module = _load_module()
    notes_path = tmp_path / "publish.md"
    candidate_path = tmp_path / "candidate.json"
    notes_path.write_text(
        "## Features\n- public change\n## Release rationale\n- should not leak\n",
        encoding="utf-8",
    )
    candidate_path.write_text(json.dumps(_candidate_payload()), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_release_flow.py",
            "--mode",
            "publish",
            "--notes-path",
            str(notes_path),
            "--candidate-path",
            str(candidate_path),
            "--expected-repository",
            "acme/repo",
            "--expected-status",
            "published",
        ],
    )

    with pytest.raises(SystemExit, match="Release rationale"):
        module.main()


def test_release_flow_verifier_rejects_publish_body_that_differs_from_candidate(
    tmp_path, monkeypatch
) -> None:
    module = _load_module()
    notes_path = tmp_path / "publish.md"
    candidate_path = tmp_path / "candidate.json"
    notes_path.write_text(
        "## Features\n- mutated after preview\n## Contributors\n@alice\n", encoding="utf-8"
    )
    candidate_path.write_text(json.dumps(_candidate_payload()), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_release_flow.py",
            "--mode",
            "publish",
            "--notes-path",
            str(notes_path),
            "--candidate-path",
            str(candidate_path),
            "--expected-repository",
            "acme/repo",
            "--expected-status",
            "published",
        ],
    )

    with pytest.raises(SystemExit, match="saved release candidate body"):
        module.main()


def test_release_flow_verifier_rejects_candidate_with_bad_fingerprint(
    tmp_path, monkeypatch
) -> None:
    module = _load_module()
    notes_path = tmp_path / "preview.md"
    candidate_path = tmp_path / "candidate.json"
    notes_path.write_text(
        (
            "# v1.3.0\n"
            "## Release rationale\n"
            "- A reason\n"
            "## Versioning context\n"
            "- A context line\n"
            "## Key evidence\n"
            "- A fact\n"
            "## Public release notes\n"
            "## Features\n"
            "- public change"
        ),
        encoding="utf-8",
    )
    payload = _candidate_payload()
    payload["fingerprint"] = "bad-fingerprint"
    candidate_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_release_flow.py",
            "--mode",
            "preview",
            "--notes-path",
            str(notes_path),
            "--candidate-path",
            str(candidate_path),
            "--expected-repository",
            "acme/repo",
            "--expected-status",
            "planned",
        ],
    )

    with pytest.raises(SystemExit, match="fingerprint is invalid"):
        module.main()


def test_release_flow_verifier_accepts_skipped_preview_artifacts(tmp_path, monkeypatch) -> None:
    module = _load_module()
    notes_path = tmp_path / "preview.md"
    candidate_path = tmp_path / "candidate.json"
    notes_path.write_text(
        (
            "# Release Preview\n"
            "Previous tag: v1.2.3\n"
            "Release type: NO_BUMP\n"
            "Included PRs: 1\n\n"
            "No new release will be published for this batch.\n"
            "All included pull requests were classified as NO_BUMP.\n"
        ),
        encoding="utf-8",
    )
    payload = _candidate_payload(
        status="skipped",
        release_label="NO_BUMP",
        next_tag=None,
    )
    candidate_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_release_flow.py",
            "--mode",
            "preview",
            "--notes-path",
            str(notes_path),
            "--candidate-path",
            str(candidate_path),
            "--expected-repository",
            "acme/repo",
            "--expected-status",
            "skipped",
        ],
    )

    assert module.main() == 0


def test_release_flow_verifier_accepts_needs_review_preview_artifacts(
    tmp_path, monkeypatch
) -> None:
    module = _load_module()
    notes_path = tmp_path / "preview.md"
    candidate_path = tmp_path / "candidate.json"
    notes_path.write_text(
        (
            "# Release Preview\n"
            "Included PRs: 1\n\n"
            "## Public release notes\n"
            "### Needs Review\n"
            "- unresolved change\n"
        ),
        encoding="utf-8",
    )
    payload = _candidate_payload(
        status="needs_review",
        release_label=None,
        next_tag=None,
    )
    candidate_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_release_flow.py",
            "--mode",
            "preview",
            "--notes-path",
            str(notes_path),
            "--candidate-path",
            str(candidate_path),
            "--expected-repository",
            "acme/repo",
            "--expected-status",
            "needs_review",
        ],
    )

    assert module.main() == 0
