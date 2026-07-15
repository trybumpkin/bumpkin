from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from corpus_cli_parser import build_parser, parse_distribution
from corpus_git_queue import list_commit_candidates
from corpus_models import PRResultRow
from corpus_process import run_git
from corpus_queue import build_balanced_queue, load_queue, write_queue
from corpus_replay import open_replay_prs
from corpus_results import collect_results, summarize_rows, write_results_tsv


def _repo_slug_from_remote(repo: Path) -> str:
    remote = run_git(repo, ["config", "--get", "remote.origin.url"]).strip()
    if remote.startswith("git@github.com:"):
        slug = remote.removeprefix("git@github.com:")
    elif remote.startswith("https://github.com/"):
        slug = remote.removeprefix("https://github.com/")
    else:
        raise ValueError(f"Unsupported remote format for GitHub slug extraction: {remote}")
    return slug.removesuffix(".git").strip("/")


def _load_results(path: Path) -> list[PRResultRow]:
    with path.open() as handle:
        return [
            PRResultRow(
                pr_number=int(row["pr_number"]),
                url=row["url"],
                expected_label=row["expected_label"],
                predicted_label=row["predicted_label"],
                confidence=row["confidence"],
                mode_used=row["mode_used"],
                analysis_state=row.get("analysis_state", "unknown"),
                classification_source=row.get("classification_source", "unknown"),
                override_status=row.get("override_status", "unknown"),
                override_applied=row.get("override_applied", "").strip().lower() == "true",
                mismatch_type=row.get("mismatch_type", "none"),
                status=row["status"],
            )
            for row in csv.DictReader(handle, delimiter="\t")
        ]


def _build_queue_command(args: argparse.Namespace) -> int:
    source_repo = Path(args.source_repo).resolve()
    candidates, resolved_rev_range = list_commit_candidates(source_repo, args.rev_range)
    selected = build_balanced_queue(
        candidates,
        target_count=args.target_count,
        seed=args.seed,
        distribution=parse_distribution(args.distribution),
    )
    output = Path(args.output)
    write_queue(
        output,
        selected,
        source_repo=source_repo,
        rev_range=args.rev_range,
        resolved_rev_range=resolved_rev_range,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "total_candidates": len(candidates),
                "selected": len(selected),
                "resolved_rev_range": resolved_rev_range,
            },
            indent=2,
        )
    )
    return 0


def _open_prs_command(args: argparse.Namespace) -> int:
    rows = open_replay_prs(
        source_repo=Path(args.source_repo).resolve(),
        fixture_repo=Path(args.fixture_repo).resolve(),
        queue=load_queue(Path(args.queue_file)),
        base_branch=args.base_branch,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, indent=2))
    print(json.dumps({"output": str(output), "rows": len(rows)}, indent=2))
    return 0


def _collect_command(args: argparse.Namespace) -> int:
    repo = args.repo.strip()
    if not repo:
        if not args.fixture_repo:
            raise ValueError("Provide --repo or --fixture-repo for collect-results.")
        repo = _repo_slug_from_remote(Path(args.fixture_repo).resolve())
    if not repo:
        raise ValueError("Provide --repo or --fixture-repo for collect-results.")
    rows = collect_results(repo=repo, limit=args.limit)
    write_results_tsv(Path(args.output), rows)
    summary = summarize_rows(rows)
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2))
    print(json.dumps({"rows": len(rows), "output": args.output, "summary": args.summary}, indent=2))
    return 0


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "build-queue":
        return _build_queue_command(args)
    if args.command == "open-prs":
        return _open_prs_command(args)
    if args.command == "collect-results":
        return _collect_command(args)
    if args.command == "summarize-results":
        print(json.dumps(summarize_rows(_load_results(Path(args.input))), indent=2))
        return 0
    raise AssertionError(f"Unsupported command: {args.command}")
