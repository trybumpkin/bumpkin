from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

from corpus_models import CommitCandidate
from corpus_process import run_gh, run_git


def _repo_slug_from_remote(repo: Path) -> str:
    remote = run_git(repo, ["config", "--get", "remote.origin.url"]).strip()
    if remote.startswith("git@github.com:"):
        slug = remote.removeprefix("git@github.com:")
    elif remote.startswith("https://github.com/"):
        slug = remote.removeprefix("https://github.com/")
    else:
        raise ValueError(f"Unsupported remote format for GitHub slug extraction: {remote}")
    return slug.removesuffix(".git").strip("/")


def _pr_body(item: CommitCandidate) -> str:
    return (
        f"<!-- bumpkin:expected-label:{item.expected_label} -->\n"
        f"Expected label: {item.expected_label}\n"
        f"Category: {item.category}\n"
        f"Source commit: {item.sha}\n"
    )


def _apply_source_commit(source_repo: Path, fixture_repo: Path, sha: str) -> None:
    patch = run_git(source_repo, ["show", "--format=", "--binary", sha])
    run_git(fixture_repo, ["apply", "-3", "--whitespace=nowarn", "-"], stdin=patch)


def _dry_run_result(item: CommitCandidate, branch: str, title: str) -> dict[str, Any]:
    return {
        "sha": item.sha,
        "branch": branch,
        "title": title,
        "expected_label": item.expected_label,
        "category": item.category,
        "status": "dry_run",
    }


def open_replay_prs(
    *,
    source_repo: Path,
    fixture_repo: Path,
    queue: list[CommitCandidate],
    base_branch: str,
    limit: int,
    dry_run: bool,
) -> list[dict[str, Any]]:
    repo_slug = _repo_slug_from_remote(fixture_repo)
    selected = queue if limit <= 0 else queue[:limit]
    results: list[dict[str, Any]] = []
    run_git(fixture_repo, ["checkout", base_branch])
    run_git(fixture_repo, ["pull", "--ff-only", "origin", base_branch])

    for index, item in enumerate(selected, start=1):
        branch = f"corpus/{index:03d}-{item.expected_label.lower()}-{item.sha[:8]}"
        title = f"corpus: replay {item.sha[:8]} [{item.expected_label}]"
        if dry_run:
            results.append(_dry_run_result(item, branch, title))
            continue
        try:
            run_git(fixture_repo, ["checkout", "-B", branch, base_branch])
            _apply_source_commit(source_repo, fixture_repo, item.sha)
            run_git(fixture_repo, ["add", "-A"])
            if not run_git(fixture_repo, ["status", "--porcelain"]).strip():
                results.append({"sha": item.sha, "branch": branch, "status": "skipped_no_changes"})
                run_git(fixture_repo, ["checkout", base_branch])
                run_git(fixture_repo, ["branch", "-D", branch])
                continue
            run_git(
                fixture_repo,
                ["commit", "-m", f"chore(corpus): replay {item.sha[:8]} ({item.expected_label})"],
            )
            run_git(fixture_repo, ["push", "-u", "origin", branch])
            pr_url = run_gh(
                [
                    "pr",
                    "create",
                    "--repo",
                    repo_slug,
                    "--base",
                    base_branch,
                    "--head",
                    branch,
                    "--title",
                    title,
                    "--body",
                    _pr_body(item),
                ]
            ).strip()
            results.append(
                {
                    "sha": item.sha,
                    "branch": branch,
                    "status": "opened",
                    "url": pr_url,
                    "expected_label": item.expected_label,
                    "category": item.category,
                }
            )
        except RuntimeError as err:
            results.append(
                {"sha": item.sha, "branch": branch, "status": "failed", "error": str(err)}
            )
            with suppress(RuntimeError):
                run_git(fixture_repo, ["checkout", base_branch])
    return results
