from __future__ import annotations

import os
import subprocess
from collections.abc import Callable


def run_git(args: list[str]) -> str:
    cmd = ["git", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git command failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def run_command(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def latest_tag(run_git_fn: Callable[[list[str]], str] = run_git) -> str | None:
    tags = run_git_fn(["tag", "--sort=-creatordate"]).splitlines()
    return tags[0].strip() if tags else None


def initial_commit(run_git_fn: Callable[[list[str]], str] = run_git) -> str:
    return run_git_fn(["rev-list", "--max-parents=0", "HEAD"]).splitlines()[0].strip()


def repository_root(run_git_fn: Callable[[list[str]], str] = run_git) -> str:
    return run_git_fn(["rev-parse", "--show-toplevel"]).strip()


def resolve_refs(
    from_ref: str | None,
    to_ref: str | None,
    *,
    latest_tag_fn: Callable[[], str | None] = latest_tag,
    initial_commit_fn: Callable[[], str] = initial_commit,
) -> tuple[str, str, list[str]]:
    notes: list[str] = []

    resolved_to = (to_ref or "").strip() or os.getenv("GITHUB_SHA") or "HEAD"
    resolved_from = (from_ref or "").strip()

    if not resolved_from:
        tag = latest_tag_fn()
        if tag:
            resolved_from = tag
        else:
            resolved_from = initial_commit_fn()
            notes.append(
                "No previous tags found â€” comparing against the initial commit. "
                "This appears to be your first release."
            )

    return resolved_from, resolved_to, notes
