from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, cast

from bumpkin.github.recommendations import (
    MergeRecommendation,
    MergeRecommendationRequest,
    PipelineRecommendationRunner,
    RecommendationRunner,
)
from bumpkin.github.releases import (
    GitHubReleasePublisher,
    ReleasePublisher,
    ReleasePublishRequest,
    ReleasePublishResult,
)
from bumpkin.github.tags import (
    GitHubTagPublisher,
    TagPublisher,
    TagPublishRequest,
    TagPublishResult,
)
from bumpkin.github.types import AppEvent
from bumpkin.versioning.tags import detect_next_version, list_tags, resolve_current_tag

_LABEL_PRECEDENCE = {"NO_BUMP": 0, "PATCH": 1, "MINOR": 2, "MAJOR": 3}
_SECTION_BY_LABEL = {
    "MAJOR": "Breaking Changes",
    "MINOR": "Features",
    "PATCH": "Fixes",
    "NO_BUMP": "Maintenance",
}
_SECTION_ORDER = ("Breaking Changes", "Features", "Fixes", "Maintenance")
_SUMMARY_LINE_RE = re.compile(r"(?im)^summary\s*:\s*(?P<value>.+)$")
_REASONING_LINE_RE = re.compile(r"(?im)^reasoning\s*:\s*(?P<value>.+)$")
_RELEASE_CANDIDATE_FORMAT_VERSION = 1
_RELEASE_CANDIDATE_ARTIFACT_NAME = "bumpkin-release-candidate"
_RELEASE_CANDIDATE_DISCOVERY_LIMIT = 20


def _coerce_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise RuntimeError(f"Release candidate field '{field_name}' must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            try:
                return int(normalized)
            except ValueError as exc:
                raise RuntimeError(
                    f"Release candidate field '{field_name}' must be an integer."
                ) from exc
    raise RuntimeError(f"Release candidate field '{field_name}' must be an integer.")


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


class GitHubRepositoryClientProtocol(Protocol):
    def list_tags(self) -> list[str]: ...

    def compare_commits(self, *, base_ref: str, head_ref: str) -> list[str]: ...

    def list_pull_requests_for_commit(self, commit_sha: str) -> list[int]: ...

    def get_pull_request(self, number: int) -> ReleaseScopedPullRequest: ...


def _normalize_label(label: str | None) -> str | None:
    normalized = (label or "").strip().upper().replace("-", "_").replace(" ", "_")
    if normalized == "NOBUMP":
        normalized = "NO_BUMP"
    return normalized if normalized in _LABEL_PRECEDENCE else None


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
    completed = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _resolve_target_ref(input_target_ref: str) -> tuple[str, str]:
    target_ref = input_target_ref.strip()
    if target_ref:
        try:
            target_sha = _run_git(["rev-parse", target_ref])
        except (RuntimeError, subprocess.CalledProcessError):
            target_sha = target_ref
        return target_ref, target_sha
    try:
        target_sha = _run_git(["rev-parse", "HEAD"])
    except (RuntimeError, subprocess.CalledProcessError) as err:
        raise RuntimeError("Unable to resolve HEAD for release target.") from err
    return target_sha, target_sha


def _parse_iso8601(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)  # noqa: UP017
    return parsed.astimezone(timezone.utc)  # noqa: UP017


def _serialize_pull_request(pull_request: ReleaseScopedPullRequest) -> dict[str, object]:
    return {
        "repository": pull_request.repository,
        "number": pull_request.number,
        "title": pull_request.title,
        "url": pull_request.url,
        "author_login": pull_request.author_login,
        "merged_at": pull_request.merged_at.isoformat(),
        "merge_commit_sha": pull_request.merge_commit_sha,
        "base_ref": pull_request.base_ref,
        "base_sha": pull_request.base_sha,
        "head_ref": pull_request.head_ref,
        "head_sha": pull_request.head_sha,
        "labels": list(pull_request.labels),
    }


def _deserialize_pull_request(payload: object) -> ReleaseScopedPullRequest:
    if not isinstance(payload, dict):
        raise RuntimeError("Release candidate payload contains an invalid pull request entry.")
    payload_map = cast("dict[str, object]", payload)
    return ReleaseScopedPullRequest(
        repository=str(payload_map.get("repository", "")).strip(),
        number=_coerce_int(payload_map.get("number", 0), field_name="number"),
        title=str(payload_map.get("title", "")).strip(),
        url=str(payload_map.get("url", "")).strip(),
        author_login=str(payload_map.get("author_login", "")).strip() or None,
        merged_at=_parse_iso8601(str(payload_map.get("merged_at", "")).strip()),
        merge_commit_sha=str(payload_map.get("merge_commit_sha", "")).strip(),
        base_ref=str(payload_map.get("base_ref", "")).strip() or None,
        base_sha=str(payload_map.get("base_sha", "")).strip() or None,
        head_ref=str(payload_map.get("head_ref", "")).strip() or None,
        head_sha=str(payload_map.get("head_sha", "")).strip() or None,
        labels=tuple(
            str(item).strip()
            for item in cast("list[object]", payload_map.get("labels", []))
            if str(item).strip()
        ),
    )


def _candidate_fingerprint_payload(
    *,
    repository: str,
    target_ref: str,
    target_sha: str,
    base_tag_input: str,
    previous_tag: str | None,
    next_tag: str | None,
    release_label: str | None,
    status: str,
    pull_requests: tuple[ReleaseScopedPullRequest, ...] | list[ReleaseScopedPullRequest],
    preview_notes: str,
    published_release_body: str,
) -> dict[str, object]:
    return {
        "repository": repository,
        "target_ref": target_ref,
        "target_sha": target_sha,
        "base_tag_input": base_tag_input,
        "previous_tag": previous_tag,
        "next_tag": next_tag,
        "release_label": release_label,
        "status": status,
        "preview_notes": preview_notes,
        "published_release_body": published_release_body,
        "pull_requests": [
            {
                "number": pull_request.number,
                "merge_commit_sha": pull_request.merge_commit_sha,
            }
            for pull_request in pull_requests
        ],
    }


def _candidate_fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_release_candidate(
    *,
    plan: ReleasePlan,
    base_tag_input: str,
    source_operation: str,
    source_run_id: str | None,
) -> ReleaseCandidate:
    fingerprint = _candidate_fingerprint(
        _candidate_fingerprint_payload(
            repository=plan.repository,
            target_ref=plan.target_ref,
            target_sha=plan.target_sha,
            base_tag_input=base_tag_input,
            previous_tag=plan.previous_tag,
            next_tag=plan.next_tag,
            release_label=plan.release_label,
            status=plan.status,
            pull_requests=plan.pull_requests,
            preview_notes=plan.preview_notes,
            published_release_body=plan.published_release_body,
        )
    )
    return ReleaseCandidate(
        format_version=_RELEASE_CANDIDATE_FORMAT_VERSION,
        source_operation=source_operation,
        source_run_id=source_run_id,
        repository=plan.repository,
        target_ref=plan.target_ref,
        target_sha=plan.target_sha,
        base_tag_input=base_tag_input,
        previous_tag=plan.previous_tag,
        next_tag=plan.next_tag,
        release_label=plan.release_label,
        status=plan.status,
        preview_notes=plan.preview_notes,
        published_release_body=plan.published_release_body,
        notes=tuple(plan.notes),
        pull_requests=tuple(plan.pull_requests),
        fingerprint=fingerprint,
    )


def _serialize_release_candidate(candidate: ReleaseCandidate) -> dict[str, object]:
    return {
        "format_version": candidate.format_version,
        "source_operation": candidate.source_operation,
        "source_run_id": candidate.source_run_id,
        "repository": candidate.repository,
        "target_ref": candidate.target_ref,
        "target_sha": candidate.target_sha,
        "base_tag_input": candidate.base_tag_input,
        "previous_tag": candidate.previous_tag,
        "next_tag": candidate.next_tag,
        "release_label": candidate.release_label,
        "status": candidate.status,
        "preview_notes": candidate.preview_notes,
        "published_release_body": candidate.published_release_body,
        "notes": list(candidate.notes),
        "pull_requests": [
            _serialize_pull_request(pull_request) for pull_request in candidate.pull_requests
        ],
        "fingerprint": candidate.fingerprint,
    }


def _deserialize_release_candidate(payload: object) -> ReleaseCandidate:
    if not isinstance(payload, dict):
        raise RuntimeError("Release candidate artifact did not contain a JSON object.")
    payload_map = cast("dict[str, object]", payload)
    pull_requests_raw = payload_map.get("pull_requests", [])
    if not isinstance(pull_requests_raw, list):
        raise RuntimeError("Release candidate artifact is missing pull request data.")
    notes_raw = payload_map.get("notes", [])
    if not isinstance(notes_raw, list):
        raise RuntimeError("Release candidate artifact is missing notes data.")
    candidate = ReleaseCandidate(
        format_version=_coerce_int(
            payload_map.get("format_version", 0), field_name="format_version"
        ),
        source_operation=str(payload_map.get("source_operation", "")).strip(),
        source_run_id=str(payload_map.get("source_run_id", "")).strip() or None,
        repository=str(payload_map.get("repository", "")).strip(),
        target_ref=str(payload_map.get("target_ref", "")).strip(),
        target_sha=str(payload_map.get("target_sha", "")).strip(),
        base_tag_input=str(payload_map.get("base_tag_input", "")).strip(),
        previous_tag=str(payload_map.get("previous_tag", "")).strip() or None,
        next_tag=str(payload_map.get("next_tag", "")).strip() or None,
        release_label=str(payload_map.get("release_label", "")).strip() or None,
        status=str(payload_map.get("status", "")).strip(),
        preview_notes=str(payload_map.get("preview_notes", "")),
        published_release_body=str(payload_map.get("published_release_body", "")),
        notes=tuple(str(note).strip() for note in notes_raw if str(note).strip()),
        pull_requests=tuple(_deserialize_pull_request(item) for item in pull_requests_raw),
        fingerprint=str(payload_map.get("fingerprint", "")).strip(),
    )
    if candidate.format_version != _RELEASE_CANDIDATE_FORMAT_VERSION:
        raise RuntimeError(
            f"Unsupported release candidate format version: {candidate.format_version}."
        )
    expected_fingerprint = _candidate_fingerprint(
        _candidate_fingerprint_payload(
            repository=candidate.repository,
            target_ref=candidate.target_ref,
            target_sha=candidate.target_sha,
            base_tag_input=candidate.base_tag_input,
            previous_tag=candidate.previous_tag,
            next_tag=candidate.next_tag,
            release_label=candidate.release_label,
            status=candidate.status,
            pull_requests=candidate.pull_requests,
            preview_notes=candidate.preview_notes,
            published_release_body=candidate.published_release_body,
        )
    )
    if candidate.fingerprint != expected_fingerprint:
        raise RuntimeError("Release candidate fingerprint is invalid.")
    return candidate


def _release_candidate_to_plan(candidate: ReleaseCandidate) -> ReleasePlan:
    return ReleasePlan(
        repository=candidate.repository,
        target_ref=candidate.target_ref,
        target_sha=candidate.target_sha,
        previous_tag=candidate.previous_tag,
        next_tag=candidate.next_tag,
        release_label=candidate.release_label,
        pull_requests=candidate.pull_requests,
        recommendations=(),
        preview_notes=candidate.preview_notes,
        published_release_body=candidate.published_release_body,
        notes=candidate.notes,
        status=candidate.status,
    )


def _bytes_request(
    *,
    token: str,
    url: str,
    timeout_seconds: int,
) -> bytes:
    class _GitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
            redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
            if redirected is None:
                return None
            original_host = urllib.parse.urlparse(req.full_url).netloc
            redirected_host = urllib.parse.urlparse(newurl).netloc
            if original_host and redirected_host and original_host != redirected_host:
                redirected.headers.pop("Authorization", None)
            return redirected

    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bumpkin-release-job",
        },
    )
    opener = urllib.request.build_opener(_GitHubRedirectHandler)
    try:
        with opener.open(request, timeout=max(1, timeout_seconds)) as response:
            body = response.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"GitHub API error {err.code}: {detail or err.reason}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"GitHub API request failed: {err.reason}") from err
    return body


def _json_request(
    *,
    token: str,
    url: str,
    timeout_seconds: int,
) -> object:
    body = _bytes_request(token=token, url=url, timeout_seconds=timeout_seconds)
    text = body.decode("utf-8")
    return json.loads(text) if text else None


class GitHubRepositoryClient:
    def __init__(
        self,
        *,
        repository: str,
        token: str,
        timeout_seconds: int = 15,
    ) -> None:
        self._repository = repository.strip()
        self._token = token.strip()
        self._timeout_seconds = max(1, timeout_seconds)
        if not self._repository:
            raise ValueError("repository is required.")
        if not self._token:
            raise ValueError("github token is required.")

    def list_tags(self) -> list[str]:
        page = 1
        per_page = 100
        collected: list[str] = []
        while True:
            url = (
                f"https://api.github.com/repos/{self._repository}/tags"
                f"?per_page={per_page}&page={page}"
            )
            payload = _json_request(
                token=self._token, url=url, timeout_seconds=self._timeout_seconds
            )
            if not isinstance(payload, list):
                break
            items = cast("list[object]", payload)
            if not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(cast("dict[str, object]", item).get("name", "")).strip()
                if name:
                    collected.append(name)
            if len(items) < per_page:
                break
            page += 1
        return collected

    def compare_commits(self, *, base_ref: str, head_ref: str) -> list[str]:
        encoded_base = urllib.parse.quote(base_ref, safe="")
        encoded_head = urllib.parse.quote(head_ref, safe="")
        url = f"https://api.github.com/repos/{self._repository}/compare/{encoded_base}...{encoded_head}"
        payload = _json_request(token=self._token, url=url, timeout_seconds=self._timeout_seconds)
        if not isinstance(payload, dict):
            raise RuntimeError("GitHub compare API returned an unexpected payload.")
        payload_map = cast("dict[str, object]", payload)
        commits = payload_map.get("commits")
        if not isinstance(commits, list):
            raise RuntimeError("GitHub compare API did not include commit data.")
        commit_shas: list[str] = []
        for item in commits:
            if not isinstance(item, dict):
                continue
            sha = str(cast("dict[str, object]", item).get("sha", "")).strip()
            if sha:
                commit_shas.append(sha)
        return list(dict.fromkeys(commit_shas))

    def list_pull_requests_for_commit(self, commit_sha: str) -> list[int]:
        normalized_sha = commit_sha.strip()
        if not normalized_sha:
            return []
        url = f"https://api.github.com/repos/{self._repository}/commits/{normalized_sha}/pulls"
        payload = _json_request(token=self._token, url=url, timeout_seconds=self._timeout_seconds)
        if not isinstance(payload, list):
            return []
        pull_numbers: list[int] = []
        for item in cast("list[object]", payload):
            if not isinstance(item, dict):
                continue
            number = cast("dict[str, object]", item).get("number")
            if isinstance(number, int) and number > 0:
                pull_numbers.append(number)
        return list(dict.fromkeys(pull_numbers))

    def get_pull_request(self, number: int) -> ReleaseScopedPullRequest:
        url = f"https://api.github.com/repos/{self._repository}/pulls/{number}"
        payload = _json_request(token=self._token, url=url, timeout_seconds=self._timeout_seconds)
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"GitHub pull request API returned an unexpected payload for PR #{number}."
            )
        payload_map = cast("dict[str, object]", payload)
        title = str(payload_map.get("title", "")).strip()
        html_url = str(payload_map.get("html_url", "")).strip()
        merge_commit_sha = str(payload_map.get("merge_commit_sha", "")).strip()
        merged_at_raw = str(payload_map.get("merged_at", "")).strip()
        if not merge_commit_sha or not merged_at_raw:
            raise RuntimeError(
                f"PR #{number} is missing merged metadata required for a release batch."
            )
        user = payload_map.get("user")
        author_login = None
        if isinstance(user, dict):
            author_login = str(cast("dict[str, object]", user).get("login", "")).strip() or None
        base = payload_map.get("base")
        head = payload_map.get("head")
        base_ref = base_sha = head_ref = head_sha = None
        if isinstance(base, dict):
            base_map = cast("dict[str, object]", base)
            base_ref = str(base_map.get("ref", "")).strip() or None
            base_sha = str(base_map.get("sha", "")).strip() or None
        if isinstance(head, dict):
            head_map = cast("dict[str, object]", head)
            head_ref = str(head_map.get("ref", "")).strip() or None
            head_sha = str(head_map.get("sha", "")).strip() or None
        labels_raw = payload_map.get("labels")
        labels: list[str] = []
        if isinstance(labels_raw, list):
            for item in cast("list[object]", labels_raw):
                if not isinstance(item, dict):
                    continue
                label_name = str(cast("dict[str, object]", item).get("name", "")).strip()
                if label_name:
                    labels.append(label_name)
        return ReleaseScopedPullRequest(
            repository=self._repository,
            number=number,
            title=title or f"PR #{number}",
            url=html_url or f"https://github.com/{self._repository}/pull/{number}",
            author_login=author_login,
            merged_at=_parse_iso8601(merged_at_raw),
            merge_commit_sha=merge_commit_sha,
            base_ref=base_ref,
            base_sha=base_sha,
            head_ref=head_ref,
            head_sha=head_sha,
            labels=tuple(labels),
        )


def _workflow_file_path() -> str | None:
    workflow_ref = os.getenv("GITHUB_WORKFLOW_REF", "").strip()
    if not workflow_ref:
        return None
    workflow_path = workflow_ref.split("@", 1)[0]
    marker = "/.github/workflows/"
    marker_index = workflow_path.find(marker)
    if marker_index == -1:
        return None
    return workflow_path[marker_index + 1 :].strip() or None


def _current_branch_name() -> str | None:
    branch_name = os.getenv("GITHUB_REF_NAME", "").strip()
    return branch_name or None


def _current_run_id() -> str | None:
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    return run_id or None


def _list_workflow_runs(
    *,
    repository: str,
    token: str,
    workflow_file: str,
    branch: str | None,
    timeout_seconds: int,
    per_page: int = _RELEASE_CANDIDATE_DISCOVERY_LIMIT,
) -> list[dict[str, object]]:
    encoded_workflow_file = urllib.parse.quote(workflow_file, safe="")
    query: list[str] = ["status=success", f"per_page={max(1, per_page)}"]
    if branch:
        query.append(f"branch={urllib.parse.quote(branch, safe='')}")
    url = (
        f"https://api.github.com/repos/{repository}/actions/workflows/{encoded_workflow_file}/runs"
        f"?{'&'.join(query)}"
    )
    payload = _json_request(token=token, url=url, timeout_seconds=timeout_seconds)
    if not isinstance(payload, dict):
        return []
    workflow_runs = cast("dict[str, object]", payload).get("workflow_runs")
    if not isinstance(workflow_runs, list):
        return []
    return [cast("dict[str, object]", item) for item in workflow_runs if isinstance(item, dict)]


def _list_run_artifacts(
    *,
    repository: str,
    token: str,
    run_id: str,
    timeout_seconds: int,
) -> list[dict[str, object]]:
    encoded_run_id = urllib.parse.quote(run_id, safe="")
    url = f"https://api.github.com/repos/{repository}/actions/runs/{encoded_run_id}/artifacts?per_page=100"
    payload = _json_request(token=token, url=url, timeout_seconds=timeout_seconds)
    if not isinstance(payload, dict):
        return []
    artifacts = cast("dict[str, object]", payload).get("artifacts")
    if not isinstance(artifacts, list):
        return []
    return [cast("dict[str, object]", item) for item in artifacts if isinstance(item, dict)]


def _download_release_candidate_for_run(
    *,
    repository: str,
    token: str,
    run_id: str,
    artifact_name: str,
    timeout_seconds: int,
) -> ReleaseCandidate | None:
    artifacts = _list_run_artifacts(
        repository=repository,
        token=token,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
    )
    artifact_id: int | None = None
    for artifact in artifacts:
        if str(artifact.get("name", "")).strip() != artifact_name:
            continue
        if bool(artifact.get("expired", False)):
            continue
        artifact_id = _coerce_int(artifact.get("id", 0), field_name="id")
        break
    if artifact_id is None:
        return None

    url = f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip"
    archive_bytes = _bytes_request(token=token, url=url, timeout_seconds=timeout_seconds)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        json_entries = [name for name in archive.namelist() if name.endswith(".json")]
        if not json_entries:
            raise RuntimeError("Release candidate artifact did not contain a JSON payload.")
        with archive.open(json_entries[0]) as candidate_file:
            payload = json.load(candidate_file)
    return _deserialize_release_candidate(payload)


def _resolve_release_candidate(
    *,
    repository: str,
    token: str,
    preview_run_id: str,
    base_tag_input: str,
    artifact_name: str,
    timeout_seconds: int,
) -> ReleaseCandidate:
    normalized_run_id = preview_run_id.strip()
    if normalized_run_id:
        candidate = _download_release_candidate_for_run(
            repository=repository,
            token=token,
            run_id=normalized_run_id,
            artifact_name=artifact_name,
            timeout_seconds=timeout_seconds,
        )
        if candidate is None:
            raise RuntimeError(
                f"No release candidate artifact named '{artifact_name}' was found on run {normalized_run_id}."
            )
        return candidate

    workflow_file = _workflow_file_path()
    if workflow_file is None:
        raise RuntimeError(
            "Unable to discover prior preview candidates automatically. Pass preview_run_id."
        )
    branch = _current_branch_name()
    current_run_id = _current_run_id()
    for workflow_run in _list_workflow_runs(
        repository=repository,
        token=token,
        workflow_file=workflow_file,
        branch=branch,
        timeout_seconds=timeout_seconds,
    ):
        run_id = str(workflow_run.get("id", "")).strip()
        if not run_id or (current_run_id and run_id == current_run_id):
            continue
        candidate = _download_release_candidate_for_run(
            repository=repository,
            token=token,
            run_id=run_id,
            artifact_name=artifact_name,
            timeout_seconds=timeout_seconds,
        )
        if candidate is None:
            continue
        if candidate.source_operation != "release_preview":
            continue
        if candidate.repository != repository:
            continue
        if candidate.base_tag_input != base_tag_input:
            continue
        return candidate

    raise RuntimeError(
        "No matching release preview candidate was found. Run release_preview first or pass preview_run_id."
    )


def _build_app_event(pull_request: ReleaseScopedPullRequest) -> AppEvent:
    return AppEvent(
        event="pull_request",
        action="closed",
        installation_id=None,
        repository=pull_request.repository,
        pull_request_number=pull_request.number,
        sender_login=pull_request.author_login,
        delivery_id=f"release-scope-pr-{pull_request.number}",
        merged=True,
        merge_commit_sha=pull_request.merge_commit_sha,
        base_ref=pull_request.base_ref,
        base_sha=pull_request.base_sha,
        head_ref=pull_request.head_ref,
        head_sha=pull_request.head_sha,
    )


def _build_payload(pull_request: ReleaseScopedPullRequest) -> dict[str, object]:
    return {
        "action": "closed",
        "repository": {"full_name": pull_request.repository},
        "pull_request": {
            "number": pull_request.number,
            "merged": True,
            "merge_commit_sha": pull_request.merge_commit_sha,
            "title": pull_request.title,
            "html_url": pull_request.url,
            "user": {"login": pull_request.author_login or ""},
            "base": {"ref": pull_request.base_ref or "", "sha": pull_request.base_sha or ""},
            "head": {"ref": pull_request.head_ref or "", "sha": pull_request.head_sha or ""},
            "labels": [{"name": label} for label in pull_request.labels],
        },
    }


def _discover_pull_requests(
    *,
    client: GitHubRepositoryClientProtocol,
    base_ref: str,
    head_ref: str,
) -> list[ReleaseScopedPullRequest]:
    pull_numbers: list[int] = []
    for commit_sha in client.compare_commits(base_ref=base_ref, head_ref=head_ref):
        pull_numbers.extend(client.list_pull_requests_for_commit(commit_sha))
    unique_numbers = sorted({number for number in pull_numbers if number > 0})
    pull_requests = [client.get_pull_request(number) for number in unique_numbers]
    merged_pull_requests = [
        pull_request for pull_request in pull_requests if pull_request.merge_commit_sha.strip()
    ]
    merged_pull_requests.sort(key=lambda item: (item.merged_at, item.number))
    return merged_pull_requests


def _verify_release_candidate(
    *,
    candidate: ReleaseCandidate,
    repository: str,
    github_token: str,
    target_ref: str,
    base_tag: str,
    client: GitHubRepositoryClientProtocol | None = None,
    request_timeout: int = 15,
) -> ReleasePlan:
    normalized_repository = repository.strip()
    if candidate.repository != normalized_repository:
        raise RuntimeError(
            "Release candidate does not belong to this repository. Run release_preview again."
        )
    normalized_base_tag = base_tag.strip()
    if candidate.base_tag_input != normalized_base_tag:
        raise RuntimeError(
            "Release candidate was created with a different base_tag input. Run release_preview again."
        )

    resolved_target_ref, target_sha = _resolve_target_ref(target_ref)
    if candidate.target_sha != target_sha:
        raise RuntimeError(
            "Release candidate is stale because the target commit changed since preview."
        )

    api_client = client or GitHubRepositoryClient(
        repository=normalized_repository,
        token=github_token.strip(),
        timeout_seconds=request_timeout,
    )
    candidate_tags = list_tags()
    if not candidate_tags:
        candidate_tags = api_client.list_tags()
    previous_tag, _ = resolve_current_tag(
        latest_tag=normalized_base_tag or None,
        tags=candidate_tags,
    )
    if previous_tag != candidate.previous_tag:
        raise RuntimeError(
            "Release candidate is stale because the previous tag changed since preview."
        )
    if previous_tag is None:
        raise RuntimeError(
            "No previous tag found for this publish run. Create an initial release tag or run release_preview again."
        )

    current_pull_requests = _discover_pull_requests(
        client=api_client,
        base_ref=previous_tag,
        head_ref=resolved_target_ref,
    )
    current_fingerprint = _candidate_fingerprint(
        _candidate_fingerprint_payload(
            repository=normalized_repository,
            target_ref=resolved_target_ref,
            target_sha=target_sha,
            base_tag_input=normalized_base_tag,
            previous_tag=previous_tag,
            next_tag=candidate.next_tag,
            release_label=candidate.release_label,
            status=candidate.status,
            pull_requests=current_pull_requests,
            preview_notes=candidate.preview_notes,
            published_release_body=candidate.published_release_body,
        )
    )
    if current_fingerprint != candidate.fingerprint:
        raise RuntimeError(
            "Release candidate is stale because the release scope changed since preview."
        )

    return ReleasePlan(
        repository=candidate.repository,
        target_ref=resolved_target_ref,
        target_sha=target_sha,
        previous_tag=candidate.previous_tag,
        next_tag=candidate.next_tag,
        release_label=candidate.release_label,
        pull_requests=tuple(current_pull_requests),
        recommendations=(),
        preview_notes=candidate.preview_notes,
        published_release_body=candidate.published_release_body,
        notes=candidate.notes,
        status=candidate.status,
    )


def _analyze_pull_requests(
    *,
    pull_requests: list[ReleaseScopedPullRequest],
    recommendation_runner: RecommendationRunner,
    github_token: str,
) -> list[ReleaseRecommendationRecord]:
    recommendation_records: list[ReleaseRecommendationRecord] = []
    for pull_request in pull_requests:
        try:
            recommendation = recommendation_runner.generate(
                MergeRecommendationRequest(
                    event=_build_app_event(pull_request),
                    payload=_build_payload(pull_request),
                    provider_token=github_token,
                )
            )
        except RuntimeError as err:
            recommendation_records.append(
                ReleaseRecommendationRecord(
                    pull_request=pull_request,
                    recommendation=None,
                    status="unsupported",
                    label=None,
                    reason=str(err),
                )
            )
            continue
        summary, reasoning, evidence_lines = _extract_recommendation_insights(recommendation.body)
        label = _normalize_label(recommendation.label)
        if label is None:
            recommendation_records.append(
                ReleaseRecommendationRecord(
                    pull_request=pull_request,
                    recommendation=recommendation,
                    status="needs_review",
                    label=None,
                    reason="PR recommendation did not produce a normalized release label.",
                    summary=summary,
                    reasoning=reasoning,
                    evidence_lines=evidence_lines,
                )
            )
            continue
        recommendation_records.append(
            ReleaseRecommendationRecord(
                pull_request=pull_request,
                recommendation=recommendation,
                status="classified",
                label=label,
                summary=summary,
                reasoning=reasoning,
                evidence_lines=evidence_lines,
            )
        )
    return recommendation_records


def _extract_first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    value = " ".join(match.group("value").split()).strip()
    return value or None


def _extract_findings_block_lines(body: str) -> tuple[str, ...]:
    lines = body.splitlines()
    findings_started = False
    findings: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not findings_started:
            if stripped.lower() == "findings:":
                findings_started = True
            continue
        if not stripped:
            if findings:
                break
            continue
        if stripped.startswith("- "):
            findings.append(stripped[2:].strip())
            continue
        if findings:
            break
    return tuple(line for line in findings if line)


def _extract_recommendation_insights(body: str) -> tuple[str | None, str | None, tuple[str, ...]]:
    return (
        _extract_first_match(_SUMMARY_LINE_RE, body),
        _extract_first_match(_REASONING_LINE_RE, body),
        _extract_findings_block_lines(body),
    )


def _versioning_context_notes(notes: tuple[str, ...] | list[str]) -> list[str]:
    relevant_prefixes = (
        "Detected versioning scheme:",
        "Zero-based policy:",
        "CalVer detected:",
        "Detected mixed tag prefixes",
        "Tag source order was non-monotonic;",
    )
    return [note for note in notes if note.startswith(relevant_prefixes)]


def _top_label_records(
    recommendations: list[ReleaseRecommendationRecord],
    release_label: str | None,
) -> list[ReleaseRecommendationRecord]:
    normalized_label = _normalize_label(release_label)
    if normalized_label is None:
        return []
    return [
        record
        for record in recommendations
        if record.status == "classified" and record.label == normalized_label
    ]


def _release_label_headline(
    release_label: str, matching_records: list[ReleaseRecommendationRecord]
) -> str:
    count = len(matching_records)
    if release_label == "MAJOR":
        return f"Breaking public API evidence was detected in {count} merged PR(s)."
    if release_label == "MINOR":
        return f"User-facing additive changes were detected in {count} merged PR(s)."
    if release_label == "PATCH":
        return f"Backward-compatible runtime changes were detected in {count} merged PR(s)."
    if release_label == "NO_BUMP":
        return f"All {count} merged PR(s) resolved to NO_BUMP."
    return f"{count} merged PR(s) contributed to this release decision."


def _parse_evidence_line(raw_line: str) -> dict[str, str]:
    parts = [part.strip() for part in raw_line.split("|") if part.strip()]
    if not parts:
        return {}
    parsed: dict[str, str] = {"path": parts[0]}
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        if not sep:
            continue
        normalized_value = " ".join(value.split()).strip()
        if not normalized_value:
            continue
        parsed[key.strip().lower()] = normalized_value
    return parsed


def _format_preview_file_link(*, repository: str, target_sha: str, path: str) -> str:
    normalized_path = path.strip().lstrip("/")
    if not repository.strip() or not target_sha.strip() or not normalized_path:
        return path
    encoded_path = urllib.parse.quote(normalized_path, safe="/")
    return (
        f"[`{normalized_path}`](https://github.com/{repository}/blob/{target_sha}/{encoded_path})"
    )


def _format_rationale_sentence(
    *,
    record: ReleaseRecommendationRecord,
    evidence: dict[str, str],
    target_sha: str,
) -> str | None:
    path = evidence.get("path")
    rule = evidence.get("rule", "").lower()
    symbol = evidence.get("symbol", "").strip()
    scope = evidence.get("scope", "").lower()
    pr_number = record.pull_request.number

    if not path:
        return None
    linked_path = _format_preview_file_link(
        repository=record.pull_request.repository,
        target_sha=target_sha,
        path=path,
    )
    formatted_symbol = f"`{symbol}`" if symbol else ""

    if rule == "export_symbol_removed":
        if symbol:
            return f"PR #{pr_number} removed exported API {formatted_symbol} in {linked_path}."
        return f"PR #{pr_number} removed a public API surface in {linked_path}."
    if rule == "export_symbol_changed":
        if symbol:
            return f"PR #{pr_number} changed exported API {formatted_symbol} in {linked_path}."
        return f"PR #{pr_number} changed a public API surface in {linked_path}."
    if rule == "export_symbol_added":
        if symbol:
            return f"PR #{pr_number} added exported API {formatted_symbol} in {linked_path}."
        return f"PR #{pr_number} added a public API surface in {linked_path}."
    if scope == "public_api":
        return f"PR #{pr_number} changed public API behavior in {linked_path}."
    if scope == "runtime":
        return f"PR #{pr_number} changed runtime behavior in {linked_path}."
    return f"PR #{pr_number} changed code in {linked_path}."


def _fallback_rationale_sentence(record: ReleaseRecommendationRecord) -> str:
    summary = " ".join((record.summary or "").split()).strip()
    if summary:
        if summary.endswith("."):
            return f"PR #{record.pull_request.number}: {summary}"
        return f"PR #{record.pull_request.number}: {summary}."
    title = record.pull_request.title.rstrip(".")
    return f"PR #{record.pull_request.number} contributed to this release decision through {title}."


def _build_release_why_lines(
    *,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
    target_sha: str,
) -> list[str]:
    normalized_label = _normalize_label(release_label)
    if normalized_label is None:
        return []
    matching_records = _top_label_records(recommendations, normalized_label)
    if not matching_records:
        return []
    lines: list[str] = []
    seen: set[str] = set()
    for record in matching_records:
        sentence: str | None = None
        for raw_line in record.evidence_lines:
            sentence = _format_rationale_sentence(
                record=record,
                evidence=_parse_evidence_line(raw_line),
                target_sha=target_sha,
            )
            if sentence:
                break
        if sentence is None:
            sentence = _fallback_rationale_sentence(record)
        if sentence in seen:
            continue
        seen.add(sentence)
        lines.append(sentence)
        if len(lines) >= 3:
            break
    if normalized_label == "MAJOR":
        lines.append("Breaking public APIs were removed or changed in this release batch.")
    elif normalized_label == "MINOR":
        lines.append("No exported APIs were removed or narrowed in this release batch.")
    elif normalized_label == "PATCH":
        lines.append(
            "No public API additions or breaking removals were detected in this release batch."
        )
    elif normalized_label == "NO_BUMP":
        lines.append("All included pull requests resolved to NO_BUMP.")
    return lines


def _humanize_evidence_line(
    line: str,
    *,
    repository: str,
    target_sha: str,
) -> str:
    parts = [part.strip() for part in line.split("|") if part.strip()]
    if not parts:
        return line.strip()
    path = _format_preview_file_link(
        repository=repository,
        target_sha=target_sha,
        path=parts[0],
    )
    details: list[str] = []
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        if not sep:
            continue
        normalized_key = key.strip().lower()
        normalized_value = " ".join(value.split()).strip()
        if not normalized_value:
            continue
        if normalized_key in {"suggested", "severity"}:
            continue
        if normalized_key == "scope" and normalized_value.lower() == "non_runtime":
            continue
        if normalized_key == "rule":
            details.append(normalized_value.replace("_", " "))
            continue
        if normalized_key == "scope":
            details.append(normalized_value.replace("_", " "))
            continue
        if normalized_key == "symbol":
            details.append(f"`{normalized_value}`")
            continue
        details.append(normalized_value)
    if not details:
        return path
    return f"{path} - {'; '.join(details)}"


def _build_release_evidence_lines(
    *,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
    target_sha: str,
    max_items: int = 3,
) -> list[str]:
    evidence: list[str] = []
    seen: set[str] = set()
    has_detailed_evidence = False
    for record in _top_label_records(recommendations, release_label):
        for raw_line in record.evidence_lines:
            detail = _humanize_evidence_line(
                raw_line,
                repository=record.pull_request.repository,
                target_sha=target_sha,
            )
            line = f"PR #{record.pull_request.number}: {detail}"
            if line in seen:
                continue
            seen.add(line)
            evidence.append(line)
            has_detailed_evidence = True
            if len(evidence) >= max_items:
                return evidence
        if record.summary and not has_detailed_evidence:
            line = f"PR #{record.pull_request.number}: {record.summary}"
            if line not in seen:
                seen.add(line)
                evidence.append(line)
                if len(evidence) >= max_items:
                    return evidence
    return evidence


def _group_release_records(
    recommendations: list[ReleaseRecommendationRecord],
) -> tuple[
    dict[str, list[ReleaseRecommendationRecord]], list[ReleaseRecommendationRecord], list[str]
]:
    grouped: dict[str, list[ReleaseRecommendationRecord]] = {
        section: [] for section in _SECTION_ORDER
    }
    unresolved: list[ReleaseRecommendationRecord] = []
    contributors: list[str] = []
    seen_contributors: set[str] = set()
    for record in recommendations:
        if record.status != "classified" or not record.label:
            unresolved.append(record)
            continue
        section = _SECTION_BY_LABEL.get(record.label, "Maintenance")
        grouped.setdefault(section, []).append(record)
        author = (record.pull_request.author_login or "").strip()
        if author and author not in seen_contributors:
            seen_contributors.add(author)
            contributors.append(author)
    return grouped, unresolved, contributors


def _render_public_release_body(
    recommendations: list[ReleaseRecommendationRecord],
) -> str:
    grouped, unresolved, contributors = _group_release_records(recommendations)
    lines: list[str] = []
    for section in _SECTION_ORDER:
        section_records = grouped.get(section, [])
        if not section_records:
            continue
        if lines:
            lines.append("")
        lines.append(f"## {section}")
        for record in section_records:
            pull_request = record.pull_request
            author = (
                f"@{pull_request.author_login}" if pull_request.author_login else "unknown author"
            )
            lines.append(
                f"- [PR #{pull_request.number}]({pull_request.url}) by {author}: {pull_request.title.rstrip('.')}"
            )

    if unresolved:
        if lines:
            lines.append("")
        lines.append("## Needs Review")
        for record in unresolved:
            pull_request = record.pull_request
            author = (
                f"@{pull_request.author_login}" if pull_request.author_login else "unknown author"
            )
            reason = (record.reason or record.status).rstrip(".")
            lines.append(
                f"- [PR #{pull_request.number}]({pull_request.url}) by {author}: {pull_request.title.rstrip('.')} ({reason})"
            )

    if contributors:
        if lines:
            lines.append("")
        lines.extend(["## Contributors", ", ".join(f"@{author}" for author in contributors)])

    return "\n".join(lines).strip() + ("\n" if lines else "")


def _shift_markdown_headings(markdown: str, *, offset: int = 1) -> str:
    shifted_lines: list[str] = []
    for raw_line in markdown.splitlines():
        if raw_line.startswith("#"):
            marker, sep, rest = raw_line.partition(" ")
            if sep:
                shifted_lines.append(f"{'#' * (len(marker) + offset)} {rest}")
                continue
        shifted_lines.append(raw_line)
    return "\n".join(shifted_lines).rstrip()


def _aggregate_release_label(recommendations: list[ReleaseRecommendationRecord]) -> str | None:
    best_label: str | None = None
    best_rank = -1
    for record in recommendations:
        if record.status != "classified" or not record.label:
            continue
        rank = _LABEL_PRECEDENCE.get(record.label, -1)
        if rank > best_rank:
            best_rank = rank
            best_label = record.label
    return best_label


def _render_preview_notes(
    *,
    target_sha: str,
    previous_tag: str | None,
    next_tag: str | None,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
    notes: tuple[str, ...] | list[str] = (),
    published_release_body: str,
) -> str:
    heading = next_tag or "Release Preview"
    lines: list[str] = [f"# {heading}", ""]
    if previous_tag:
        lines.append(f"Previous tag: {previous_tag}")
    if next_tag:
        lines.append(f"Next tag: {next_tag}")
    if release_label:
        lines.append(f"Release type: {release_label}")
    lines.append(f"Included PRs: {len(recommendations)}")

    why_lines = _build_release_why_lines(
        release_label=release_label,
        recommendations=recommendations,
        target_sha=target_sha,
    )
    if why_lines:
        lines.extend(["", "## Release rationale"])
        lines.extend(f"- {line}" for line in why_lines)

    versioning_notes = _versioning_context_notes(notes)
    if versioning_notes:
        lines.extend(["", "## Versioning context"])
        lines.extend(f"- {note}" for note in versioning_notes)

    evidence_lines = _build_release_evidence_lines(
        release_label=release_label,
        recommendations=recommendations,
        target_sha=target_sha,
    )
    if evidence_lines:
        lines.extend(["", "## Key evidence"])
        lines.extend(f"- {line}" for line in evidence_lines)

    if published_release_body:
        lines.extend(
            [
                "",
                "## Public release notes",
                _shift_markdown_headings(published_release_body),
            ]
        )

    return "\n".join(lines).strip() + "\n"


def _render_no_release_preview_notes(
    *,
    previous_tag: str | None,
    release_label: str,
    recommendations: list[ReleaseRecommendationRecord],
    notes: tuple[str, ...] | list[str] = (),
) -> str:
    lines = ["# Release Preview", ""]
    if previous_tag:
        lines.append(f"Previous tag: {previous_tag}")
    lines.append(f"Release type: {release_label}")
    lines.append(f"Included PRs: {len(recommendations)}")
    lines.extend(
        [
            "",
            "No new release will be published for this batch.",
            "All included pull requests were classified as NO_BUMP.",
        ]
    )

    versioning_notes = _versioning_context_notes(notes)
    if versioning_notes:
        lines.extend(["", "## Versioning context"])
        lines.extend(f"- {note}" for note in versioning_notes)

    maintenance_records = [
        record
        for record in recommendations
        if record.label is not None and _SECTION_BY_LABEL.get(record.label) == "Maintenance"
    ]
    if maintenance_records:
        lines.extend(["", "## Included PRs"])
        for record in maintenance_records:
            pull_request = record.pull_request
            author = (
                f"@{pull_request.author_login}" if pull_request.author_login else "unknown author"
            )
            lines.append(
                f"- [PR #{pull_request.number}]({pull_request.url}) by {author}: {pull_request.title.rstrip('.')}"
            )

    return "\n".join(lines).strip() + "\n"


def _render_publish_step_summary(
    *,
    status: str,
    plan: ReleasePlan,
    release_candidate: ReleaseCandidate,
    release_url: str | None = None,
    tag_url: str | None = None,
) -> str:
    title = {
        "published": "# Release published",
        "skipped": "# Release publish skipped",
        "needs_review": "# Release publish blocked",
    }.get(status, "# Release publish result")
    lines = [title, ""]
    if plan.previous_tag:
        lines.append(f"Previous tag: {plan.previous_tag}")
    if plan.next_tag:
        lines.append(
            f"Published tag: {plan.next_tag}"
            if status == "published"
            else f"Candidate tag: {plan.next_tag}"
        )
    if plan.release_label:
        lines.append(f"Release type: {plan.release_label}")
    lines.append(f"Included PRs: {len(plan.pull_requests)}")
    if release_candidate.source_run_id:
        lines.append(f"Preview run id: {release_candidate.source_run_id}")
    if status == "published":
        lines.append("Release candidate verified and published.")
    elif status == "skipped":
        lines.append("No release was published for this candidate.")
    elif status == "needs_review":
        lines.append("Release candidate still needs maintainer review before publish.")
    if release_url:
        lines.append(f"Release URL: {release_url}")
    if tag_url:
        lines.append(f"Tag URL: {tag_url}")
    return "\n".join(lines).strip() + "\n"


def prepare_release_plan(
    *,
    repository: str,
    github_token: str,
    target_ref: str,
    base_tag: str,
    client: GitHubRepositoryClientProtocol | None = None,
    recommendation_runner: RecommendationRunner | None = None,
    request_timeout: int = 15,
) -> ReleasePlan:
    normalized_repository = repository.strip()
    if not normalized_repository:
        raise ValueError("repository is required.")
    normalized_token = github_token.strip()
    if not normalized_token:
        raise ValueError("github token is required.")
    resolved_target_ref, target_sha = _resolve_target_ref(target_ref)
    api_client = client or GitHubRepositoryClient(
        repository=normalized_repository,
        token=normalized_token,
        timeout_seconds=request_timeout,
    )
    notes: list[str] = []
    candidate_tags = list_tags()
    if not candidate_tags:
        candidate_tags = api_client.list_tags()
    previous_tag, current_tag_notes = resolve_current_tag(
        latest_tag=base_tag.strip() or None,
        tags=candidate_tags,
    )
    notes.extend(current_tag_notes)
    if previous_tag is None:
        raise RuntimeError(
            "No previous tag found. Create an initial release tag or pass --base-tag."
        )

    pull_requests = _discover_pull_requests(
        client=api_client,
        base_ref=previous_tag,
        head_ref=resolved_target_ref,
    )
    if not pull_requests:
        return ReleasePlan(
            status="skipped",
            repository=normalized_repository,
            target_ref=resolved_target_ref,
            target_sha=target_sha,
            previous_tag=previous_tag,
            next_tag=None,
            release_label=None,
            pull_requests=(),
            recommendations=(),
            preview_notes=(
                f"# Release Preview\n\nPrevious tag: {previous_tag}\nIncluded PRs: 0\n\n"
                "No merged pull requests were found in this release scope.\n"
            ),
            published_release_body="",
            notes=tuple(notes),
        )

    runner = recommendation_runner or PipelineRecommendationRunner()
    recommendations = _analyze_pull_requests(
        pull_requests=pull_requests,
        recommendation_runner=runner,
        github_token=normalized_token,
    )
    unresolved_records = [record for record in recommendations if record.status != "classified"]
    release_label = _aggregate_release_label(recommendations)
    if release_label is None and unresolved_records:
        notes.append(
            "Release scope contains unresolved pull requests that need review before publish."
        )
        published_release_body = _render_public_release_body(recommendations)
        preview_notes = _render_preview_notes(
            target_sha=target_sha,
            previous_tag=previous_tag,
            next_tag=None,
            release_label=None,
            recommendations=recommendations,
            notes=notes,
            published_release_body=published_release_body,
        )
        return ReleasePlan(
            status="needs_review",
            repository=normalized_repository,
            target_ref=resolved_target_ref,
            target_sha=target_sha,
            previous_tag=previous_tag,
            next_tag=None,
            release_label=None,
            pull_requests=tuple(pull_requests),
            recommendations=tuple(recommendations),
            preview_notes=preview_notes,
            published_release_body="",
            notes=tuple(notes),
        )
    if release_label is None:
        raise RuntimeError("Could not determine an aggregate release label.")
    _, next_tag, version_notes = detect_next_version(release_label, latest_tag=previous_tag)
    notes.extend(version_notes)
    if release_label == "NO_BUMP":
        notes.append(
            "Release scope resolved to NO_BUMP; no tag or GitHub Release will be published."
        )
        preview_notes = _render_no_release_preview_notes(
            previous_tag=previous_tag,
            release_label=release_label,
            recommendations=recommendations,
            notes=notes,
        )
        return ReleasePlan(
            status="skipped",
            repository=normalized_repository,
            target_ref=resolved_target_ref,
            target_sha=target_sha,
            previous_tag=previous_tag,
            next_tag=None,
            release_label=release_label,
            pull_requests=tuple(pull_requests),
            recommendations=tuple(recommendations),
            preview_notes=preview_notes,
            published_release_body="",
            notes=tuple(notes),
        )
    if not next_tag:
        raise RuntimeError("Could not compute the next release tag from the current scope.")
    published_release_body = _render_public_release_body(recommendations)
    preview_notes = _render_preview_notes(
        target_sha=target_sha,
        previous_tag=previous_tag,
        next_tag=next_tag,
        release_label=release_label,
        recommendations=recommendations,
        notes=notes,
        published_release_body=published_release_body,
    )
    return ReleasePlan(
        status="planned",
        repository=normalized_repository,
        target_ref=resolved_target_ref,
        target_sha=target_sha,
        previous_tag=previous_tag,
        next_tag=next_tag,
        release_label=release_label,
        pull_requests=tuple(pull_requests),
        recommendations=tuple(recommendations),
        preview_notes=preview_notes,
        published_release_body=published_release_body,
        notes=tuple(notes),
    )


def publish_release_plan(
    plan: ReleasePlan,
    *,
    github_token: str,
    tag_publisher: TagPublisher | None = None,
    release_publisher: ReleasePublisher | None = None,
) -> ReleaseExecutionResult:
    normalized_token = github_token.strip()
    if not normalized_token:
        raise ValueError("github token is required.")
    if plan.status == "needs_review":
        return ReleaseExecutionResult(status="needs_review", plan=plan)
    if not plan.next_tag:
        if plan.status == "skipped" or plan.release_label == "NO_BUMP":
            return ReleaseExecutionResult(status="skipped", plan=plan)
        raise RuntimeError("Cannot publish a release plan without a next tag.")
    tag_publisher_impl = tag_publisher or GitHubTagPublisher(token=normalized_token)
    release_publisher_impl = release_publisher or GitHubReleasePublisher(token=normalized_token)
    tag_result = tag_publisher_impl.publish(
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
    release_result = release_publisher_impl.publish(
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


def _write_text_file(path_value: str, content: str) -> str:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _write_json_file(path_value: str, payload: dict[str, object]) -> str:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def _write_github_output(values: dict[str, str]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    lines: list[str] = []
    for key, value in values.items():
        lines.append(f"{key}<<__BUMPKIN_EOF__")
        lines.append(value)
        lines.append("__BUMPKIN_EOF__")
    with Path(output_path).open("a", encoding="utf-8") as output_file:
        output_file.write("\n".join(lines) + "\n")


def _append_step_summary(markdown: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as summary_file:
        summary_file.write(markdown.rstrip() + "\n")


def _build_summary_payload(
    *,
    status: str,
    plan: ReleasePlan,
    release_candidate: ReleaseCandidate,
    candidate_path: str,
    release_url: str | None = None,
    tag_url: str | None = None,
    notes_path: str,
) -> dict[str, str]:
    return {
        "release_status": status,
        "release_previous_tag": plan.previous_tag or "",
        "release_next_tag": plan.next_tag or "",
        "release_label": plan.release_label or "",
        "release_pr_count": str(len(plan.pull_requests)),
        "release_notes_path": notes_path,
        "release_target_sha": plan.target_sha,
        "release_candidate_path": candidate_path,
        "release_candidate_fingerprint": release_candidate.fingerprint,
        "release_candidate_run_id": release_candidate.source_run_id or "",
        "release_candidate_artifact_name": _RELEASE_CANDIDATE_ARTIFACT_NAME,
        "release_url": release_url or "",
        "tag_url": tag_url or "",
    }


def run_release_job(args: argparse.Namespace | None = None) -> int:
    parsed = args or _parse_args()
    if parsed.operation == "publish":
        candidate = _resolve_release_candidate(
            repository=parsed.repository,
            token=parsed.github_token,
            preview_run_id=parsed.preview_run_id,
            base_tag_input=parsed.base_tag.strip(),
            artifact_name=_RELEASE_CANDIDATE_ARTIFACT_NAME,
            timeout_seconds=parsed.request_timeout,
        )
        plan = _verify_release_candidate(
            candidate=candidate,
            repository=parsed.repository,
            github_token=parsed.github_token,
            target_ref=parsed.target_ref,
            base_tag=parsed.base_tag,
            request_timeout=parsed.request_timeout,
        )
    else:
        plan = prepare_release_plan(
            repository=parsed.repository,
            github_token=parsed.github_token,
            target_ref=parsed.target_ref,
            base_tag=parsed.base_tag,
            request_timeout=parsed.request_timeout,
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
        execution = publish_release_plan(plan, github_token=parsed.github_token)
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
    "main",
    "prepare_release_plan",
    "publish_release_plan",
    "run_release_job",
]
