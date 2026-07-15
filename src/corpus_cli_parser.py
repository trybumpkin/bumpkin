from __future__ import annotations

import argparse
import json

from corpus_queue import DEFAULT_DISTRIBUTION


def parse_distribution(raw: str) -> dict[str, int]:
    if not raw.strip():
        return dict(DEFAULT_DISTRIBUTION)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("--distribution must be a JSON object")
    out: dict[str, int] = {}
    for key, value in parsed.items():
        label = str(key).upper()
        if label not in DEFAULT_DISTRIBUTION:
            raise ValueError(f"Unsupported label in distribution: {key}")
        out[label] = int(value)
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bumpkin corpus acceleration CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-queue", help="Build balanced replay queue from source commits.")
    build.add_argument("--source-repo", required=True)
    build.add_argument("--rev-range", default="HEAD~300..HEAD")
    build.add_argument("--target-count", type=int, default=30)
    build.add_argument("--seed", type=int, default=42)
    build.add_argument("--distribution", default="")
    build.add_argument("--output", default="artifacts/live-pr-validation/queue.json")
    open_prs = sub.add_parser("open-prs", help="Create replay PRs from queue.")
    open_prs.add_argument("--queue-file", required=True)
    open_prs.add_argument("--source-repo", required=True)
    open_prs.add_argument("--fixture-repo", required=True)
    open_prs.add_argument("--base-branch", default="main")
    open_prs.add_argument("--limit", type=int, default=0)
    open_prs.add_argument("--dry-run", action="store_true")
    open_prs.add_argument("--output", default="artifacts/live-pr-validation/open-prs.json")
    collect = sub.add_parser(
        "collect-results", help="Collect expected vs predicted labels from merged PRs."
    )
    collect.add_argument("--repo", default="")
    collect.add_argument("--fixture-repo", default="")
    collect.add_argument("--limit", type=int, default=200)
    collect.add_argument("--output", default="artifacts/live-pr-validation/results.tsv")
    collect.add_argument("--summary", default="artifacts/live-pr-validation/summary.json")
    summarize = sub.add_parser("summarize-results", help="Summarize existing TSV results file.")
    summarize.add_argument("--input", default="artifacts/live-pr-validation/results.tsv")
    return parser
