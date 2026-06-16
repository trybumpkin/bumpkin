from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
from argparse import Namespace
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol

from bumpkin.integrations.github.types import AppEvent
from bumpkin.io.github_http import collect_paginated_github_json_list, github_request_json
from bumpkin.io.tokens import is_valid_models_endpoint
from bumpkin.orchestrator import pipeline as orchestrator_pipeline

_PROPOSED_BUMP_RE = re.compile(r"(?im)^proposed bump \(court\):\s*(?P<label>[^\n\r(]+)")
_RECOMMENDATION_LINE_RE = re.compile(
    r"(?im)^recommendation\s*:\s*[^\n\rA-Z]*(?P<label>NO[\s_-]?BUMP|MAJOR|MINOR|PATCH)\b"
)
_NEXT_VERSION_ARROW_RE = re.compile(
    r"(?im)^next version\s*:\s*(?P<current>v?\d+\.\d+\.\d+)\s*(?:→|->)\s*(?P<next>v?\d+\.\d+\.\d+)\s*$"
)
_NEXT_VERSION_CURRENT_ONLY_RE = re.compile(
    r"(?im)^next version\s*:\s*not computed\s*\(current=(?P<current>v?\d+\.\d+\.\d+)\)\s*$"
)
_VALID_RECOMMENDATION_LABELS = frozenset({"MAJOR", "MINOR", "PATCH", "NO_BUMP"})
_PER_FILE_CHAR_CAP = 6000


@dataclass(frozen=True, slots=True)
class MergeRecommendationRequest:
    event: AppEvent
    payload: Mapping[str, object]
    provider_token: str | None = None


@dataclass(frozen=True, slots=True)
class MergeRecommendation:
    body: str
    label: str | None
    current_version: str | None


class RecommendationRunner(Protocol):
    def generate(self, request: MergeRecommendationRequest) -> MergeRecommendation: ...


class RecommendationPublisher(Protocol):
    def publish(self, *, repository: str, issue_number: int, body: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class _ApiDiffUnit:
    path: str
    text: str
    approx_tokens: int


@dataclass(frozen=True, slots=True)
class _ApiDiffResult:
    from_ref: str
    to_ref: str
    diff_text: str
    full_diff_text: str
    truncated: bool
    analyzed_files: list[str]
    file_units: list[_ApiDiffUnit]
    changed_files_total: int
    ignored_files_total: int
    approx_prompt_tokens: int
    approx_full_tokens: int
    capped_files: int
    scope_allowlist_files_total: int
    scope_overlap_files: int
    scope_unexpected_files: int
    scope_missing_files: int
    notes: list[str]


def _run_git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_object_exists(ref: str | None) -> bool:
    candidate = (ref or "").strip()
    if not candidate:
        return False
    try:
        _run_git("rev-parse", "--verify", candidate)
    except (RuntimeError, subprocess.CalledProcessError):
        return False
    return True


def _is_merged_pr_close_event(event: AppEvent) -> bool:
    return event.event == "pull_request" and event.action == "closed" and bool(event.merged)


def _ordered_event_refs(event: AppEvent) -> list[str]:
    refs: list[str] = []
    for ref_name in (event.base_ref, event.head_ref):
        candidate = (ref_name or "").strip()
        if candidate and candidate not in refs:
            refs.append(candidate)
    return refs


def _fetch_event_refs(event: AppEvent, *, required_ref: str) -> bool:
    refs = _ordered_event_refs(event)
    if not refs:
        return False
    head_ref = (event.head_ref or "").strip()
    allow_missing_head_ref = _is_merged_pr_close_event(event)
    for ref in refs:
        try:
            _run_git("fetch", "--no-tags", "origin", ref)
        except (RuntimeError, subprocess.CalledProcessError) as err:
            if allow_missing_head_ref and head_ref and ref == head_ref:
                continue
            raise RuntimeError(f"git fetch failed for ref '{ref}': {err}") from err
        if _git_object_exists(required_ref):
            return True
    return False


def _ensure_event_refs_available(event: AppEvent) -> None:
    preferred_ref = event.merge_commit_sha or event.head_sha or event.base_sha
    if not preferred_ref:
        raise RuntimeError(
            "required git object is unavailable: missing merge/head/base sha in event."
        )
    if _git_object_exists(preferred_ref):
        return
    if _fetch_event_refs(event, required_ref=preferred_ref):
        return
    raise RuntimeError(f"required git object is unavailable after fetch: {preferred_ref}")


def _normalize_repo_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    normalized = normalized.removeprefix("./")
    return normalized.lstrip("/")


def _is_ignored_path(path: str, patterns: list[str]) -> bool:
    normalized = path.strip("/")
    for raw in patterns:
        pattern = raw.strip().strip("/")
        if not pattern:
            continue
        if fnmatch.fnmatch(normalized, pattern) or normalized.startswith(pattern):
            return True
    return False


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _truncate_for_model(text: str, token_cap: int) -> tuple[str, bool]:
    if token_cap <= 0:
        return text, False
    max_chars = token_cap * 4
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _cap_file_diff(block: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(block) <= max_chars:
        return block, False
    capped = block[:max_chars]
    if not capped.endswith("\n"):
        capped += "\n"
    capped += "...[Bumpkin: per-file diff capped]...\n"
    return capped, True


def _fetch_pull_request_files(
    *, repository: str, pr_number: int, token: str
) -> list[Mapping[str, object]]:
    if not token.strip():
        raise RuntimeError("github api fallback requires a provider token.")
    url = f"https://api.github.com/repos/{repository}/pulls/{pr_number}/files?per_page=100"
    payload = collect_paginated_github_json_list(
        url=url,
        token=token,
        user_agent="bumpkin-app",
        timeout_seconds=10,
    )
    return [item for item in payload if isinstance(item, Mapping)]


def _build_git_block_from_pr_file(file_item: Mapping[str, object]) -> tuple[str, str]:
    path = _normalize_repo_path(str(file_item.get("filename", "")).strip())
    if not path:
        raise RuntimeError("github api fallback encountered file entry without filename.")
    status = str(file_item.get("status", "modified")).strip().lower()
    previous_filename = _normalize_repo_path(str(file_item.get("previous_filename", "")).strip())
    source_path = previous_filename or path

    old_marker = f"a/{source_path}"
    new_marker = f"b/{path}"
    if status == "added":
        old_marker = "/dev/null"
    elif status == "removed":
        new_marker = "/dev/null"

    raw_patch = file_item.get("patch")
    patch_text = str(raw_patch) if raw_patch is not None else ""
    if patch_text and not patch_text.endswith("\n"):
        patch_text += "\n"

    block = (
        f"diff --git a/{source_path} b/{path}\n"
        "index 0000000..0000000 100644\n"
        f"--- {old_marker}\n"
        f"+++ {new_marker}\n"
        f"{patch_text}"
    )
    if not block.endswith("\n"):
        block += "\n"
    return path, block


def _build_api_diff_result(
    *,
    from_ref: str,
    to_ref: str,
    pr_files: list[Mapping[str, object]],
    ignore_patterns: list[str],
    allowed_files: list[str] | None,
    token_cap: int,
) -> _ApiDiffResult:
    notes = ["Using GitHub API PR files fallback because local git refs are unavailable."]
    normalized_allowlist = {
        _normalize_repo_path(path) for path in (allowed_files or []) if _normalize_repo_path(path)
    }
    changed_paths: list[str] = []
    file_blocks: dict[str, str] = {}

    for item in pr_files:
        path, block = _build_git_block_from_pr_file(item)
        changed_paths.append(path)
        file_blocks[path] = block

    overlap_paths = {path for path in changed_paths if path in normalized_allowlist}
    unexpected_paths = [
        path for path in changed_paths if normalized_allowlist and path not in normalized_allowlist
    ]
    scope_missing_files = (
        max(0, len(normalized_allowlist) - len(overlap_paths)) if normalized_allowlist else 0
    )

    if normalized_allowlist:
        scoped_changed = [path for path in changed_paths if path in normalized_allowlist]
        notes.append(
            "Scope guard: "
            f"matched {len(scoped_changed)}/{len(changed_paths)} api-changed file(s) against PR allowlist "
            f"(unexpected={len(unexpected_paths)}, missing={scope_missing_files})."
        )
    else:
        scoped_changed = list(changed_paths)

    kept = [path for path in scoped_changed if not _is_ignored_path(path, ignore_patterns)]
    ignored_count = max(0, len(scoped_changed) - len(kept))
    if not kept:
        notes.append("Only ignored files changed; defaulting to NO_BUMP recommendation.")
        return _ApiDiffResult(
            from_ref=from_ref,
            to_ref=to_ref,
            diff_text="",
            full_diff_text="",
            truncated=False,
            analyzed_files=[],
            file_units=[],
            changed_files_total=len(changed_paths),
            ignored_files_total=ignored_count,
            approx_prompt_tokens=0,
            approx_full_tokens=0,
            capped_files=0,
            scope_allowlist_files_total=len(normalized_allowlist),
            scope_overlap_files=len(overlap_paths),
            scope_unexpected_files=len(unexpected_paths),
            scope_missing_files=scope_missing_files,
            notes=notes,
        )

    file_units: list[_ApiDiffUnit] = []
    capped_files = 0
    for path in kept:
        block = file_blocks[path]
        capped_block, was_capped = _cap_file_diff(block, _PER_FILE_CHAR_CAP)
        if was_capped:
            capped_files += 1
        file_units.append(
            _ApiDiffUnit(
                path=path,
                text=capped_block,
                approx_tokens=_estimate_tokens(capped_block),
            )
        )

    full_diff_text = "\n".join(unit.text.rstrip("\n") for unit in file_units)
    if full_diff_text:
        full_diff_text += "\n"
    diff_text, truncated = _truncate_for_model(full_diff_text, token_cap)
    approx_full_tokens = _estimate_tokens(full_diff_text)
    approx_prompt_tokens = _estimate_tokens(diff_text)
    notes.append(f"Analyzed {len(kept)} file(s) after filtering.")

    return _ApiDiffResult(
        from_ref=from_ref,
        to_ref=to_ref,
        diff_text=diff_text,
        full_diff_text=full_diff_text,
        truncated=truncated,
        analyzed_files=kept,
        file_units=file_units,
        changed_files_total=len(changed_paths),
        ignored_files_total=ignored_count,
        approx_prompt_tokens=approx_prompt_tokens,
        approx_full_tokens=approx_full_tokens,
        capped_files=capped_files,
        scope_allowlist_files_total=len(normalized_allowlist),
        scope_overlap_files=len(overlap_paths),
        scope_unexpected_files=len(unexpected_paths),
        scope_missing_files=scope_missing_files,
        notes=notes,
    )


def _build_github_api_diff_fallback(
    *,
    pr_files: list[Mapping[str, object]],
) -> Any:
    def _build_diff(
        *,
        from_ref: str,
        to_ref: str,
        ignore_patterns: list[str] | None = None,
        allowed_files: list[str] | None = None,
        token_cap: int = 6000,
        use_difftastic: bool = False,
        chunking_enabled: bool = True,
    ) -> _ApiDiffResult:
        return _build_api_diff_result(
            from_ref=from_ref,
            to_ref=to_ref,
            pr_files=pr_files,
            ignore_patterns=list(ignore_patterns or []),
            allowed_files=list(allowed_files) if allowed_files is not None else None,
            token_cap=token_cap,
        )

    return _build_diff


def _normalize_semver_token(token: str) -> str | None:
    normalized = token.strip()
    if not re.match(r"^v?\d+\.\d+\.\d+$", normalized):
        return None
    normalized = normalized.removeprefix("v")
    major, minor, patch = normalized.split(".")
    return f"{int(major)}.{int(minor)}.{int(patch)}"


def _extract_label(comment_body: str) -> str | None:
    def _normalize(raw: str) -> str | None:
        cleaned = re.sub(r"[^A-Z_\-\s]", "", raw.strip().upper())
        normalized = re.sub(r"[\s\-]+", "_", cleaned).strip("_")
        if normalized == "NOBUMP":
            normalized = "NO_BUMP"
        if normalized in _VALID_RECOMMENDATION_LABELS:
            return normalized
        return None

    match = _PROPOSED_BUMP_RE.search(comment_body)
    if match:
        normalized = _normalize(match.group("label"))
        if normalized is not None:
            return normalized

    match = _RECOMMENDATION_LINE_RE.search(comment_body)
    if match:
        return _normalize(match.group("label"))
    return None


def _extract_current_version(comment_body: str) -> str | None:
    arrow_match = _NEXT_VERSION_ARROW_RE.search(comment_body)
    if arrow_match:
        return _normalize_semver_token(arrow_match.group("current"))

    current_only_match = _NEXT_VERSION_CURRENT_ONLY_RE.search(comment_body)
    if current_only_match:
        return _normalize_semver_token(current_only_match.group("current"))
    return None


class NoopRecommendationPublisher:
    def publish(self, *, repository: str, issue_number: int, body: str) -> str | None:  # noqa: ARG002
        return None


class GitHubRecommendationCommentPublisher:
    def __init__(
        self,
        *,
        token: str,
        user_agent: str = "bumpkin-app",
        timeout_seconds: int = 10,
    ) -> None:
        self._token = token.strip()
        self._user_agent = user_agent.strip() or "bumpkin-app"
        self._timeout_seconds = timeout_seconds

    def publish(self, *, repository: str, issue_number: int, body: str) -> str | None:
        if not self._token:
            return None
        url = f"https://api.github.com/repos/{repository}/issues/{issue_number}/comments"
        payload = {"body": body}
        response = self._api_request(url=url, method="POST", payload=payload)
        if not isinstance(response, dict):
            return None
        html_url = response.get("html_url")
        return str(html_url).strip() if html_url is not None else None

    def _api_request(
        self,
        *,
        url: str,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> object:
        response, _headers = github_request_json(
            url=url,
            method=method,
            timeout_seconds=self._timeout_seconds,
            token=self._token,
            user_agent=self._user_agent,
            payload=payload,
        )
        return response


class PipelineRecommendationRunner:
    def __init__(
        self,
        *,
        mode: str | None = None,
        model: str | None = None,
        fallback_model: str | None = None,
        models_endpoint: str | None = None,
        max_retries: int | None = None,
        request_timeout: int | None = None,
        token_cap: int | None = None,
        use_difftastic: str | None = None,
    ) -> None:
        self._mode = mode or os.getenv("BUMPKIN_PROVIDER", "auto")
        self._model = model or os.getenv("BUMPKIN_MODEL", "")
        self._fallback_model = fallback_model or os.getenv("BUMPKIN_FALLBACK_MODEL", "")
        self._models_endpoint = models_endpoint or os.getenv("BUMPKIN_MODELS_ENDPOINT", "")
        self._max_retries = max_retries if max_retries is not None else 3
        self._request_timeout = (
            request_timeout
            if request_timeout is not None
            else int(os.getenv("BUMPKIN_REQUEST_TIMEOUT", "45"))
        )
        self._token_cap = token_cap if token_cap is not None else 6000
        self._use_difftastic = use_difftastic or os.getenv("BUMPKIN_USE_DIFFTASTIC", "")

    def generate(self, request: MergeRecommendationRequest) -> MergeRecommendation:
        repository = (request.event.repository or "").strip()
        pr_number = request.event.pull_request_number
        if not repository or pr_number is None:
            raise ValueError("merge recommendation requires repository and pull request number.")
        if not self._model.strip():
            raise ValueError("BUMPKIN_MODEL is required for recommendation runs.")
        if not self._models_endpoint.strip():
            raise ValueError("BUMPKIN_MODELS_ENDPOINT is required for recommendation runs.")
        if not is_valid_models_endpoint(self._models_endpoint):
            raise ValueError(
                "BUMPKIN_MODELS_ENDPOINT must be a valid http(s) URL for recommendation runs."
            )
        token = (request.provider_token or "").strip()
        fallback_diff_builder: Any | None = None
        try:
            _ensure_event_refs_available(request.event)
        except RuntimeError as err:
            if not token:
                raise RuntimeError(
                    "local git refs unavailable and github api fallback requires provider token."
                ) from err
            pr_files = _fetch_pull_request_files(
                repository=repository,
                pr_number=pr_number,
                token=token,
            )
            fallback_diff_builder = _build_github_api_diff_fallback(pr_files=pr_files)

        payload = dict(request.payload)
        with NamedTemporaryFile("w", encoding="utf-8", delete=False) as event_file:
            event_file.write(json.dumps(payload))
            event_path = event_file.name

        capture: dict[str, str] = {}
        original_build_diff = orchestrator_pipeline.build_diff

        def _capture_post_pr_comment(
            *,
            token: str,
            repo: str,
            pr_number: int,
            body: str,
        ) -> None:
            _ = token, repo, pr_number
            capture["body"] = body

        if fallback_diff_builder is not None:
            orchestrator_pipeline.build_diff = fallback_diff_builder
        env_updates = {
            "GITHUB_REPOSITORY": repository,
            "GITHUB_EVENT_PATH": event_path,
            "BUMPKIN_CAPTURE_PR_COMMENT_ONLY": "1",
        }
        if token:
            env_updates["GITHUB_TOKEN"] = token

        args = Namespace(
            from_ref="",
            to_ref="",
            token_cap=self._token_cap,
            use_difftastic=self._use_difftastic,
            mode=self._mode,
            model=self._model,
            fallback_model=self._fallback_model,
            models_endpoint=self._models_endpoint,
            max_retries=self._max_retries,
            request_timeout=self._request_timeout,
        )
        previous_env: dict[str, str | None] = {key: os.environ.get(key) for key in env_updates}
        try:
            for key, value in env_updates.items():
                os.environ[key] = value
            exit_code = orchestrator_pipeline.run(args, comment_poster=_capture_post_pr_comment)
        finally:
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            orchestrator_pipeline.build_diff = original_build_diff
            with suppress(FileNotFoundError):
                Path(event_path).unlink()

        if exit_code != 0:
            raise RuntimeError(f"recommendation pipeline failed with exit code {exit_code}.")
        body = capture.get("body", "").strip()
        if not body:
            raise RuntimeError("recommendation pipeline did not produce a comment body.")
        return MergeRecommendation(
            body=body + "\n",
            label=_extract_label(body),
            current_version=_extract_current_version(body),
        )
