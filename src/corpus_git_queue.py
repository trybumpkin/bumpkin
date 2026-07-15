from __future__ import annotations

from pathlib import Path

from corpus_labels import infer_expected_label
from corpus_models import CommitCandidate
from corpus_process import run_git


def _read_git_log_with_fallback(source_repo: Path, rev_range: str) -> tuple[str, str]:
    base_args = ["log", "--no-merges", "--reverse", "--pretty=format:%H%x1f%s", "--name-only"]
    try:
        return run_git(source_repo, [*base_args, rev_range]), rev_range
    except RuntimeError as err:
        if "ambiguous argument" not in str(err):
            raise
        return run_git(source_repo, [*base_args, "HEAD"]), "HEAD"


def list_commit_candidates(source_repo: Path, rev_range: str) -> tuple[list[CommitCandidate], str]:
    raw, resolved_rev_range = _read_git_log_with_fallback(source_repo, rev_range)
    out: list[CommitCandidate] = []
    current_sha = ""
    current_subject = ""
    current_files: list[str] = []

    def flush() -> None:
        nonlocal current_sha, current_subject, current_files
        if not current_sha:
            return
        file_list = [file for file in current_files if file]
        label, category = infer_expected_label(current_subject, file_list)
        out.append(CommitCandidate(current_sha, current_subject, file_list, label, category))
        current_sha = ""
        current_subject = ""
        current_files = []

    for line in raw.splitlines():
        if "\x1f" in line:
            flush()
            current_sha, current_subject = (part.strip() for part in line.split("\x1f", 1))
        elif line.strip():
            current_files.append(line.strip())
    flush()
    return [candidate for candidate in out if candidate.files], resolved_rev_range
