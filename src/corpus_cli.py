from __future__ import annotations

from corpus_commands import main as _main
from corpus_git_queue import list_commit_candidates
from corpus_labels import infer_expected_label, parse_expected_label_from_body
from corpus_models import CommitCandidate, ParsedPrediction, PRResultRow
from corpus_queue import build_balanced_queue
from corpus_replay import open_replay_prs
from corpus_results import (
    collect_results,
    extract_bumpkin_prediction,
    summarize_rows,
    write_results_tsv,
)

__all__ = [
    "CommitCandidate",
    "PRResultRow",
    "ParsedPrediction",
    "build_balanced_queue",
    "collect_results",
    "extract_bumpkin_prediction",
    "infer_expected_label",
    "list_commit_candidates",
    "open_replay_prs",
    "parse_expected_label_from_body",
    "summarize_rows",
    "write_results_tsv",
]


if __name__ == "__main__":
    raise SystemExit(_main())
