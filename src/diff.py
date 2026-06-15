from __future__ import annotations

from collections.abc import Iterable

from bumpkin.analysis import diff_core

DEFAULT_IGNORES = diff_core.DEFAULT_IGNORES
PER_FILE_CHAR_CAP = diff_core.PER_FILE_CHAR_CAP
DiffUnit = diff_core.DiffUnit
DiffResult = diff_core.DiffResult


def _run_git(args: list[str]) -> str:
    return diff_core.run_git(args)


def _run_command(args: list[str]) -> str:
    return diff_core.run_command(args)


def _latest_tag() -> str | None:
    return diff_core.latest_tag(run_git_fn=_run_git)


def _initial_commit() -> str:
    return diff_core.initial_commit(run_git_fn=_run_git)


def _repository_root() -> str:
    return diff_core.repository_root(run_git_fn=_run_git)


def resolve_refs(from_ref: str | None, to_ref: str | None) -> tuple[str, str, list[str]]:
    return diff_core.resolve_refs(
        from_ref,
        to_ref,
        latest_tag_fn=_latest_tag,
        initial_commit_fn=_initial_commit,
    )


def _is_ignored(path: str, patterns: Iterable[str]) -> bool:
    return diff_core.is_ignored(path, patterns)


def _changed_files(from_ref: str, to_ref: str) -> list[str]:
    return diff_core.changed_files(from_ref, to_ref, run_git_fn=_run_git)


def _normalize_path(path: str) -> str:
    return diff_core.normalize_path(path)


def _difftastic_available() -> bool:
    return diff_core.difftastic_available()


def _build_diff_text(
    from_ref: str,
    to_ref: str,
    files: list[str],
    use_difftastic: bool,
) -> tuple[str, list[str]]:
    return diff_core.build_diff_text(
        from_ref,
        to_ref,
        files,
        use_difftastic,
        run_git_fn=_run_git,
        run_command_fn=_run_command,
        difftastic_available_fn=_difftastic_available,
    )


def _estimate_tokens(text: str) -> int:
    return diff_core.estimate_tokens(text)


def _cap_diff_per_file(diff_text: str, max_chars_per_file: int) -> tuple[str, int]:
    return diff_core.cap_diff_per_file(diff_text, max_chars_per_file)


def _truncate(text: str, token_cap: int) -> tuple[str, bool]:
    return diff_core.truncate(text, token_cap)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    return diff_core.dedupe_preserve_order(items)


def build_diff(
    from_ref: str,
    to_ref: str,
    ignore_patterns: Iterable[str] | None = None,
    allowed_files: Iterable[str] | None = None,
    token_cap: int = 6000,
    use_difftastic: bool = False,
    chunking_enabled: bool = True,
) -> DiffResult:
    return diff_core.build_diff(
        from_ref,
        to_ref,
        ignore_patterns=ignore_patterns,
        allowed_files=allowed_files,
        token_cap=token_cap,
        use_difftastic=use_difftastic,
        chunking_enabled=chunking_enabled,
        changed_files_fn=_changed_files,
        normalize_path_fn=_normalize_path,
        is_ignored_fn=_is_ignored,
        build_diff_text_fn=_build_diff_text,
        cap_diff_per_file_fn=_cap_diff_per_file,
        estimate_tokens_fn=_estimate_tokens,
        truncate_fn=_truncate,
        dedupe_preserve_order_fn=_dedupe_preserve_order,
        repository_root_fn=_repository_root,
    )
