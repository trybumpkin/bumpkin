from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from bumpkin.policies import guards as guard_policies

OVERRIDE_LABELS = {
    "bump:major": "MAJOR",
    "bump:minor": "MINOR",
    "bump:patch": "PATCH",
}
OVERRIDE_PRIORITY = {"MAJOR": 3, "MINOR": 2, "PATCH": 1}


@dataclass
class PREventContext:
    pr_number: int | None
    base_sha: str | None
    head_sha: str | None
    merge_sha: str | None
    labels: list[str]


@dataclass(frozen=True)
class OverrideResolution:
    label: str | None
    label_name: str | None
    warning: str | None
    status: str
    candidates: list[str]
    policy: str
    audit_note: str


def run_git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git command failed: {' '.join(['git', *args])}\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def resolve_merge_parent_sha(merge_sha: str) -> str | None:
    candidate = merge_sha.strip()
    if not candidate:
        return None
    try:
        return run_git(["rev-parse", f"{candidate}^1"])
    except RuntimeError:
        repository = os.getenv("GITHUB_REPOSITORY", "").strip()
        token = os.getenv("GITHUB_TOKEN", "").strip()
        if not repository or not token:
            return None
        url = f"https://api.github.com/repos/{repository}/commits/{candidate}"
        try:
            payload = github_api_request(token, url)
        except RuntimeError:
            return None
        if not isinstance(payload, dict):
            return None
        payload_map = cast("dict[str, object]", payload)
        parents = payload_map.get("parents")
        if not isinstance(parents, list) or not parents:
            return None
        parents_list = cast("list[object]", parents)
        first_parent = parents_list[0]
        if not isinstance(first_parent, dict):
            return None
        first_parent_map = cast("dict[str, object]", first_parent)
        parent_sha = str(first_parent_map.get("sha", "")).strip()
        return parent_sha or None


def read_event_context(event_path: str | None) -> PREventContext:
    if not event_path:
        return PREventContext(None, None, None, None, [])

    p = Path(event_path)
    if not p.exists():
        return PREventContext(None, None, None, None, [])

    payload = json.loads(p.read_text())
    pr = payload.get("pull_request")
    if not pr:
        return PREventContext(None, None, None, None, [])

    base_sha = pr.get("base", {}).get("sha")
    head_sha = pr.get("head", {}).get("sha")
    merge_sha = pr.get("merge_commit_sha")
    pr_number = int(pr["number"])
    labels = [str(label.get("name", "")).strip().lower() for label in pr.get("labels", [])]
    return PREventContext(pr_number, base_sha, head_sha, merge_sha, labels)


def select_diff_scope(
    from_ref_arg: str,
    to_ref_arg: str,
    event_context: PREventContext,
    *,
    merge_parent_resolver: Callable[[str], str | None] = resolve_merge_parent_sha,
) -> tuple[str, str, list[str]]:
    from_ref_input = from_ref_arg
    to_ref_input = to_ref_arg
    notes: list[str] = []

    if event_context.pr_number is not None:
        if not from_ref_input and not to_ref_input and event_context.merge_sha:
            merge_parent_sha = merge_parent_resolver(event_context.merge_sha)
            if merge_parent_sha:
                from_ref_input = merge_parent_sha
                to_ref_input = event_context.merge_sha
                notes.append("Using merged PR diff scope (merge parent SHA → merge SHA).")
            else:
                from_ref_input = event_context.base_sha or from_ref_input
                to_ref_input = event_context.merge_sha
                notes.append(
                    "Using merged PR diff scope fallback (base SHA → merge SHA); "
                    "merge parent SHA could not be resolved."
                )
        else:
            if not from_ref_input and event_context.base_sha:
                from_ref_input = event_context.base_sha
            if not to_ref_input:
                to_ref_input = event_context.merge_sha or event_context.head_sha or ""
            if from_ref_input and to_ref_input:
                notes.append("Using PR diff scope from event payload.")

    return from_ref_input, to_ref_input, notes


def normalize_repo_path(path: str) -> str:
    return guard_policies.normalize_repo_path(path)


def github_api_request(token: str, url: str) -> Any:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bumpkin",
        },
    )
    try:
        with urllib.request.urlopen(req) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        message = err.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {err.code}: {message.strip()}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(str(err.reason)) from err
    return json.loads(body) if body else None


def fetch_pr_changed_files(
    *,
    token: str,
    repo: str,
    pr_number: int,
    request_fn: Callable[[str, str], Any] = github_api_request,
) -> tuple[list[str] | None, str | None]:
    if not repo:
        return None, "Scope guard unavailable: missing GITHUB_REPOSITORY."
    if not token:
        return None, "Scope guard unavailable: missing GITHUB_TOKEN."

    page = 1
    per_page = 100
    collected: list[str] = []
    while True:
        url = (
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
            f"?per_page={per_page}&page={page}"
        )
        try:
            payload = request_fn(token, url)
        except RuntimeError as err:
            return None, f"Scope guard unavailable: failed fetching PR files ({err})."

        if not isinstance(payload, list):
            return None, "Scope guard unavailable: unexpected PR files API response shape."
        payload_items = cast("list[object]", payload)

        for item in payload_items:
            if not isinstance(item, dict):
                continue
            payload_item = cast("dict[str, object]", item)
            raw = str(payload_item.get("filename", "")).strip()
            normalized = normalize_repo_path(raw)
            if normalized:
                collected.append(normalized)

        if len(payload_items) < per_page:
            break
        page += 1

    deduped = list(dict.fromkeys(collected))
    return deduped, None


def evaluate_scope_mismatch(
    *,
    required: bool,
    fetch_error: str | None,
    git_files_count: int,
    overlap_count: int,
    unexpected_count: int,
    missing_count: int,
) -> tuple[bool, str | None]:
    if not required:
        return False, None
    if fetch_error:
        return True, fetch_error

    reasons: list[str] = []
    if git_files_count > 0 and overlap_count == 0:
        reasons.append("no overlap between git diff scope and PR files")
    if unexpected_count > 0:
        reasons.append(f"{unexpected_count} git-diff file(s) outside PR file allowlist")
    if missing_count > 0:
        reasons.append(f"{missing_count} PR file(s) missing from git diff scope")
    if not reasons:
        return False, None
    return True, "; ".join(reasons)


def resolve_override_governance(
    labels: list[str],
    *,
    policy: str,
) -> OverrideResolution:
    normalized_policy = policy.strip().lower()
    found = sorted({name for name in labels if name in OVERRIDE_LABELS})
    if not found:
        return OverrideResolution(
            label=None,
            label_name=None,
            warning=None,
            status="none",
            candidates=[],
            policy=normalized_policy,
            audit_note=f"override_governance_policy={normalized_policy}; no override labels detected.",
        )
    if len(found) == 1:
        label_name = found[0]
        return OverrideResolution(
            label=OVERRIDE_LABELS[label_name],
            label_name=label_name,
            warning=None,
            status="single",
            candidates=found,
            policy=normalized_policy,
            audit_note=(
                f"override_governance_policy={normalized_policy}; single override label "
                f"`{label_name}` accepted."
            ),
        )

    if normalized_policy == "severity_precedence":
        chosen = max(found, key=lambda name: OVERRIDE_PRIORITY.get(OVERRIDE_LABELS[name], 0))
        ordered = ", ".join(found)
        return OverrideResolution(
            label=OVERRIDE_LABELS[chosen],
            label_name=chosen,
            warning=f"Conflicting override labels found ({ordered}); resolved via severity precedence.",
            status="conflict_resolved",
            candidates=found,
            policy=normalized_policy,
            audit_note=(
                f"override_governance_policy={normalized_policy}; conflict resolved using precedence "
                f"(winner=`{chosen}` among [{ordered}])."
            ),
        )

    ordered = ", ".join(found)
    return OverrideResolution(
        label=None,
        label_name=None,
        warning=f"Conflicting override labels found ({ordered}); ignoring override.",
        status="conflict_ignored",
        candidates=found,
        policy=normalized_policy,
        audit_note=(
            f"override_governance_policy={normalized_policy}; conflict ignored "
            f"for labels [{ordered}]."
        ),
    )


def resolve_override_label(labels: list[str]) -> tuple[str | None, str | None, str | None]:
    resolved = resolve_override_governance(labels, policy="strict_audit")
    return resolved.label, resolved.label_name, resolved.warning
