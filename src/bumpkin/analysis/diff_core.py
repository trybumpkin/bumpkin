from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass

DEFAULT_IGNORES = [
    "docs/**",
    "tests/**",
    "coverage/**",
    "dist/**",
    "node_modules/**",
    ".wrangler/**",
    "**/.wrangler/**",
    "*.md",
    "*.lock",
    "**/*.md",
    "**/*.lock",
    "pnpm-lock.yaml",
    "**/pnpm-lock.yaml",
    "package-lock.json",
    "**/package-lock.json",
    "npm-shrinkwrap.json",
    "**/npm-shrinkwrap.json",
    "bun.lockb",
    "**/bun.lockb",
]
PER_FILE_CHAR_CAP = 6000


@dataclass
class DiffUnit:
    path: str
    text: str
    approx_tokens: int


@dataclass
class DiffResult:
    from_ref: str
    to_ref: str
    repo_root: str | None
    diff_text: str
    full_diff_text: str
    truncated: bool
    analyzed_files: list[str]
    file_units: list[DiffUnit]
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
                "No previous tags found — comparing against the initial commit. "
                "This appears to be your first release."
            )

    return resolved_from, resolved_to, notes


def is_ignored(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.strip("/")
    for raw in patterns:
        pattern = raw.strip().strip("/")
        if not pattern:
            continue
        if fnmatch.fnmatch(normalized, pattern) or normalized.startswith(pattern):
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


def build_diff(
    from_ref: str,
    to_ref: str,
    ignore_patterns: Iterable[str] | None = None,
    allowed_files: Iterable[str] | None = None,
    token_cap: int = 6000,
    use_difftastic: bool = False,
    chunking_enabled: bool = True,
    *,
    changed_files_fn: Callable[[str, str], list[str]] = changed_files,
    normalize_path_fn: Callable[[str], str] = normalize_path,
    is_ignored_fn: Callable[[str, Iterable[str]], bool] = is_ignored,
    build_diff_text_fn: Callable[
        [str, str, list[str], bool], tuple[str, list[str]]
    ] = build_diff_text,
    cap_diff_per_file_fn: Callable[[str, int], tuple[str, int]] = cap_diff_per_file,
    estimate_tokens_fn: Callable[[str], int] = estimate_tokens,
    truncate_fn: Callable[[str, int], tuple[str, bool]] = truncate,
    dedupe_preserve_order_fn: Callable[[list[str]], list[str]] = dedupe_preserve_order,
    repository_root_fn: Callable[[], str] = repository_root,
) -> DiffResult:
    ignores = list(ignore_patterns or DEFAULT_IGNORES)
    notes: list[str] = []
    repo_root = repository_root_fn()

    changed = changed_files_fn(from_ref, to_ref)
    allowlist = {
        normalize_path_fn(path) for path in (allowed_files or []) if normalize_path_fn(path)
    }
    changed_pairs = [(normalize_path_fn(path), path) for path in changed]
    overlap_paths = {normalized for normalized, _ in changed_pairs if normalized in allowlist}
    unexpected_paths = [
        path for normalized, path in changed_pairs if allowlist and normalized not in allowlist
    ]
    scope_missing_files = max(0, len(allowlist) - len(overlap_paths)) if allowlist else 0

    if allowlist:
        scoped_changed = [path for normalized, path in changed_pairs if normalized in allowlist]
        notes.append(
            "Scope guard: "
            f"matched {len(scoped_changed)}/{len(changed)} git-changed file(s) against PR allowlist "
            f"(unexpected={len(unexpected_paths)}, missing={scope_missing_files})."
        )
    else:
        scoped_changed = [path for _, path in changed_pairs]

    kept = [path for path in scoped_changed if not is_ignored_fn(path, ignores)]
    ignored_count = max(0, len(scoped_changed) - len(kept))

    if not kept:
        notes.append("Only ignored files changed; defaulting to NO_BUMP recommendation.")
        return DiffResult(
            from_ref=from_ref,
            to_ref=to_ref,
            repo_root=repo_root,
            diff_text="",
            full_diff_text="",
            truncated=False,
            analyzed_files=[],
            file_units=[],
            changed_files_total=len(changed),
            ignored_files_total=ignored_count,
            approx_prompt_tokens=0,
            approx_full_tokens=0,
            capped_files=0,
            scope_allowlist_files_total=len(allowlist),
            scope_overlap_files=len(overlap_paths),
            scope_unexpected_files=len(unexpected_paths),
            scope_missing_files=scope_missing_files,
            notes=notes,
        )

    preprocessor_notes: list[str] = []
    file_units: list[DiffUnit] = []
    capped_files = 0
    for path in kept:
        unit_text, unit_notes = build_diff_text_fn(
            from_ref,
            to_ref,
            [path],
            use_difftastic,
        )
        preprocessor_notes.extend(unit_notes)
        if not unit_text.strip():
            continue
        capped_text, capped_count = cap_diff_per_file_fn(unit_text, PER_FILE_CHAR_CAP)
        if capped_count > 0:
            capped_files += 1
        file_units.append(
            DiffUnit(
                path=path,
                text=capped_text,
                approx_tokens=estimate_tokens_fn(capped_text),
            )
        )

    notes.extend(dedupe_preserve_order_fn(preprocessor_notes))
    if capped_files > 0:
        notes.append(
            f"Per-file diff cap applied to {capped_files} file(s) to reduce prompt dominance."
        )

    # Keep each per-file patch on its own boundary so downstream parsers
    # can reliably detect every `diff --git` header.
    full_diff_text = "\n".join(unit.text.rstrip("\n") for unit in file_units)
    if full_diff_text:
        full_diff_text += "\n"
    approx_full_tokens = estimate_tokens_fn(full_diff_text)
    model_diff_text = full_diff_text
    truncated = False
    approx_prompt_tokens = approx_full_tokens

    if not chunking_enabled:
        model_diff_text, truncated = truncate_fn(full_diff_text, token_cap)
        approx_prompt_tokens = estimate_tokens_fn(model_diff_text)
        if truncated:
            notes.append(
                f"Diff exceeded token cap (~{token_cap}) and was truncated. Review manually."
            )
    elif token_cap > 0 and approx_full_tokens > token_cap:
        notes.append(
            f"Diff exceeded token cap (~{token_cap}), but chunking is enabled so full per-file coverage was kept."
        )

    notes.append(f"Analyzed {len(kept)} file(s) after filtering.")
    notes.append(f"Approx. prompt tokens: {approx_prompt_tokens}")

    return DiffResult(
        from_ref=from_ref,
        to_ref=to_ref,
        repo_root=repo_root,
        diff_text=model_diff_text,
        full_diff_text=full_diff_text,
        truncated=truncated,
        analyzed_files=kept,
        file_units=file_units,
        changed_files_total=len(changed),
        ignored_files_total=ignored_count,
        approx_prompt_tokens=approx_prompt_tokens,
        approx_full_tokens=approx_full_tokens,
        capped_files=capped_files,
        scope_allowlist_files_total=len(allowlist),
        scope_overlap_files=len(overlap_paths),
        scope_unexpected_files=len(unexpected_paths),
        scope_missing_files=scope_missing_files,
        notes=notes,
    )
