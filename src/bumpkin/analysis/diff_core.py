from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from . import diff_git
from .diff_git import repository_root
from .diff_text import (
    build_diff_text,
    cap_diff_per_file,
    changed_files,
    dedupe_preserve_order,
    estimate_tokens,
    is_ignored,
    normalize_path,
    truncate,
)

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

resolve_refs = diff_git.resolve_refs


@dataclass
class DiffUnit:
    path: str
    text: str
    approx_tokens: int


@dataclass
class DiffResult:
    from_ref: str
    to_ref: str
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
    repo_root: str | None = None


def _resolve_repo_root(
    repository_root_fn: Callable[[], str],
    *,
    notes: list[str],
) -> str | None:
    try:
        return repository_root_fn()
    except RuntimeError:
        notes.append("Repository root lookup was unavailable; continuing without repo_root.")
        return None


def _scope_changed_files(
    changed: list[str],
    allowed_files: Iterable[str] | None,
    *,
    normalize_path_fn: Callable[[str], str],
) -> tuple[list[str], set[str], list[str], int]:
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
    else:
        scoped_changed = [path for _, path in changed_pairs]
    return scoped_changed, overlap_paths, unexpected_paths, scope_missing_files


def _build_file_units(
    *,
    from_ref: str,
    to_ref: str,
    kept: list[str],
    use_difftastic: bool,
    build_diff_text_fn: Callable[[str, str, list[str], bool], tuple[str, list[str]]],
    cap_diff_per_file_fn: Callable[[str, int], tuple[str, int]],
    estimate_tokens_fn: Callable[[str], int],
) -> tuple[list[DiffUnit], list[str], int]:
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

    return file_units, preprocessor_notes, capped_files


def _assemble_diff_result(
    *,
    from_ref: str,
    to_ref: str,
    model_diff_text: str,
    full_diff_text: str,
    truncated: bool,
    kept: list[str],
    file_units: list[DiffUnit],
    changed: list[str],
    ignored_count: int,
    approx_prompt_tokens: int,
    approx_full_tokens: int,
    capped_files: int,
    allowlist: set[str],
    overlap_paths: set[str],
    unexpected_paths: list[str],
    scope_missing_files: int,
    notes: list[str],
    repository_root_fn: Callable[[], str],
) -> DiffResult:
    repo_root = _resolve_repo_root(repository_root_fn, notes=notes)
    return DiffResult(
        from_ref=from_ref,
        to_ref=to_ref,
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
        repo_root=repo_root,
    )


def _empty_diff_result(
    *,
    from_ref: str,
    to_ref: str,
    ignored_count: int,
    allowlist: set[str],
    overlap_paths: set[str],
    unexpected_paths: list[str],
    scope_missing_files: int,
    notes: list[str],
    repository_root_fn: Callable[[], str],
) -> DiffResult:
    repo_root = _resolve_repo_root(repository_root_fn, notes=notes)
    return DiffResult(
        from_ref=from_ref,
        to_ref=to_ref,
        diff_text="",
        full_diff_text="",
        truncated=False,
        analyzed_files=[],
        file_units=[],
        changed_files_total=0,
        ignored_files_total=ignored_count,
        approx_prompt_tokens=0,
        approx_full_tokens=0,
        capped_files=0,
        scope_allowlist_files_total=len(allowlist),
        scope_overlap_files=len(overlap_paths),
        scope_unexpected_files=len(unexpected_paths),
        scope_missing_files=scope_missing_files,
        notes=notes,
        repo_root=repo_root,
    )


def _apply_token_cap(
    *,
    full_diff_text: str,
    token_cap: int,
    chunking_enabled: bool,
    approx_full_tokens: int,
    estimate_tokens_fn: Callable[[str], int],
    truncate_fn: Callable[[str, int], tuple[str, bool]],
    notes: list[str],
) -> tuple[str, bool, int]:
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

    return model_diff_text, truncated, approx_prompt_tokens


def _materialize_diff_text(
    *,
    file_units: list[DiffUnit],
    token_cap: int,
    chunking_enabled: bool,
    estimate_tokens_fn: Callable[[str], int],
    truncate_fn: Callable[[str, int], tuple[str, bool]],
    notes: list[str],
) -> tuple[str, str, bool, int, int]:
    # Keep each per-file patch on its own boundary so downstream parsers
    # can reliably detect every `diff --git` header.
    full_diff_text = "\n".join(unit.text.rstrip("\n") for unit in file_units)
    if full_diff_text:
        full_diff_text += "\n"
    approx_full_tokens = estimate_tokens_fn(full_diff_text)
    model_diff_text, truncated, approx_prompt_tokens = _apply_token_cap(
        full_diff_text=full_diff_text,
        token_cap=token_cap,
        chunking_enabled=chunking_enabled,
        approx_full_tokens=approx_full_tokens,
        estimate_tokens_fn=estimate_tokens_fn,
        truncate_fn=truncate_fn,
        notes=notes,
    )
    return (
        full_diff_text,
        model_diff_text,
        truncated,
        approx_full_tokens,
        approx_prompt_tokens,
    )


def _prepare_diff_inputs(
    *,
    from_ref: str,
    to_ref: str,
    ignores: list[str],
    allowed_files: Iterable[str] | None,
    changed_files_fn: Callable[[str, str], list[str]],
    normalize_path_fn: Callable[[str], str],
    is_ignored_fn: Callable[[str, Iterable[str]], bool],
) -> tuple[
    list[str],
    set[str],
    set[str],
    list[str],
    int,
    list[str],
    int,
    list[str],
]:
    notes: list[str] = []
    changed = changed_files_fn(from_ref, to_ref)
    scoped_changed, overlap_paths, unexpected_paths, scope_missing_files = _scope_changed_files(
        changed,
        allowed_files,
        normalize_path_fn=normalize_path_fn,
    )
    allowlist = {
        normalize_path_fn(path) for path in (allowed_files or []) if normalize_path_fn(path)
    }

    if allowlist:
        notes.append(
            "Scope guard: "
            f"matched {len(scoped_changed)}/{len(changed)} git-changed file(s) against PR allowlist "
            f"(unexpected={len(unexpected_paths)}, missing={scope_missing_files})."
        )

    kept = [path for path in scoped_changed if not is_ignored_fn(path, ignores)]
    ignored_count = max(0, len(scoped_changed) - len(kept))
    if not kept:
        notes.append("Only ignored files changed; defaulting to NO_BUMP recommendation.")

    return (
        changed,
        allowlist,
        overlap_paths,
        unexpected_paths,
        scope_missing_files,
        kept,
        ignored_count,
        notes,
    )


def _build_diff_result_impl(
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
    (
        changed,
        allowlist,
        overlap_paths,
        unexpected_paths,
        scope_missing_files,
        kept,
        ignored_count,
        notes,
    ) = _prepare_diff_inputs(
        from_ref=from_ref,
        to_ref=to_ref,
        ignores=ignores,
        allowed_files=allowed_files,
        changed_files_fn=changed_files_fn,
        normalize_path_fn=normalize_path_fn,
        is_ignored_fn=is_ignored_fn,
    )

    if not kept:
        return _empty_diff_result(
            from_ref=from_ref,
            to_ref=to_ref,
            ignored_count=ignored_count,
            allowlist=allowlist,
            overlap_paths=overlap_paths,
            unexpected_paths=unexpected_paths,
            scope_missing_files=scope_missing_files,
            notes=notes,
            repository_root_fn=repository_root_fn,
        )

    file_units, preprocessor_notes, capped_files = _build_file_units(
        from_ref=from_ref,
        to_ref=to_ref,
        kept=kept,
        use_difftastic=use_difftastic,
        build_diff_text_fn=build_diff_text_fn,
        cap_diff_per_file_fn=cap_diff_per_file_fn,
        estimate_tokens_fn=estimate_tokens_fn,
    )
    notes.extend(dedupe_preserve_order_fn(preprocessor_notes))
    if capped_files > 0:
        notes.append(
            f"Per-file diff cap applied to {capped_files} file(s) to reduce prompt dominance."
        )

    full_diff_text, model_diff_text, truncated, approx_full_tokens, approx_prompt_tokens = (
        _materialize_diff_text(
            file_units=file_units,
            token_cap=token_cap,
            chunking_enabled=chunking_enabled,
            estimate_tokens_fn=estimate_tokens_fn,
            truncate_fn=truncate_fn,
            notes=notes,
        )
    )

    notes.append(f"Analyzed {len(kept)} file(s) after filtering.")
    notes.append(f"Approx. prompt tokens: {approx_prompt_tokens}")
    return _assemble_diff_result(
        from_ref=from_ref,
        to_ref=to_ref,
        model_diff_text=model_diff_text,
        full_diff_text=full_diff_text,
        truncated=truncated,
        kept=kept,
        file_units=file_units,
        changed=changed,
        ignored_count=ignored_count,
        approx_prompt_tokens=approx_prompt_tokens,
        approx_full_tokens=approx_full_tokens,
        capped_files=capped_files,
        allowlist=allowlist,
        overlap_paths=overlap_paths,
        unexpected_paths=unexpected_paths,
        scope_missing_files=scope_missing_files,
        notes=notes,
        repository_root_fn=repository_root_fn,
    )


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
    return _build_diff_result_impl(
        from_ref,
        to_ref,
        ignore_patterns,
        allowed_files,
        token_cap,
        use_difftastic,
        chunking_enabled,
        changed_files_fn=changed_files_fn,
        normalize_path_fn=normalize_path_fn,
        is_ignored_fn=is_ignored_fn,
        build_diff_text_fn=build_diff_text_fn,
        cap_diff_per_file_fn=cap_diff_per_file_fn,
        estimate_tokens_fn=estimate_tokens_fn,
        truncate_fn=truncate_fn,
        dedupe_preserve_order_fn=dedupe_preserve_order_fn,
        repository_root_fn=repository_root_fn,
    )
