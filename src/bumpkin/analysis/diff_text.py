from __future__ import annotations

import fnmatch
import shutil
from collections.abc import Callable, Iterable

from .diff_git import run_command, run_git


def is_ignored(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.strip("/")
    for raw in patterns:
        pattern = raw.strip().strip("/")
        if not pattern:
            continue
        if fnmatch.fnmatch(normalized, pattern):
            return True
    return False


def changed_files(
    from_ref: str,
    to_ref: str,
    *,
    run_git_fn: Callable[[list[str]], str] = run_git,
) -> list[str]:
    output = run_git_fn(["diff", "--name-only", from_ref, to_ref])
    return [line.strip() for line in output.splitlines() if line.strip()]


def normalize_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    normalized = normalized.removeprefix("./")
    return normalized.lstrip("/")


def difftastic_available() -> bool:
    return shutil.which("difft") is not None


def build_diff_text(
    from_ref: str,
    to_ref: str,
    files: list[str],
    use_difftastic: bool,
    *,
    run_git_fn: Callable[[list[str]], str] = run_git,
    run_command_fn: Callable[[list[str]], str] = run_command,
    difftastic_available_fn: Callable[[], bool] = difftastic_available,
) -> tuple[str, list[str]]:
    notes: list[str] = []
    if not use_difftastic:
        return run_git_fn(["diff", from_ref, to_ref, "--", *files]), notes

    if not difftastic_available_fn():
        notes.append(
            "Configured difftastic preprocessing, but `difft` is not installed. Falling back to git diff."
        )
        return run_git_fn(["diff", from_ref, to_ref, "--", *files]), notes

    try:
        diff_text = run_command_fn(
            ["difft", "--color=never", "--display=inline", from_ref, to_ref, "--", *files]
        )
        notes.append("Preprocessed diff using difftastic.")
        return diff_text, notes
    except RuntimeError as err:
        notes.append(f"Difftastic failed ({err}); falling back to git diff.")
        return run_git_fn(["diff", from_ref, to_ref, "--", *files]), notes


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def cap_diff_per_file(diff_text: str, max_chars_per_file: int) -> tuple[str, int]:
    if max_chars_per_file <= 0:
        return diff_text, 0
    if len(diff_text) <= max_chars_per_file:
        return diff_text, 0
    if "diff --git " not in diff_text:
        return diff_text, 0

    sections = diff_text.split("diff --git ")
    if len(sections) <= 1:
        return diff_text, 0

    prefix = sections[0]
    rebuilt = [prefix]
    capped = 0
    marker = "\n...[Bumpkin: per-file diff capped]...\n"

    for section in sections[1:]:
        block = "diff --git " + section
        if len(block) > max_chars_per_file:
            trimmed = block[:max_chars_per_file]
            if not trimmed.endswith("\n"):
                trimmed += "\n"
            block = trimmed + marker
            capped += 1
        rebuilt.append(block)
    return "".join(rebuilt), capped


def truncate(text: str, token_cap: int) -> tuple[str, bool]:
    if token_cap <= 0:
        return text, False
    max_chars = token_cap * 4
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped
