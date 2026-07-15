"""Stable preflight API assembled from focused evaluation helpers."""

from bumpkin.eval.preflight_aggregate import aggregate_results_from_json_dir
from bumpkin.eval.preflight_batches import select_batch_cases
from bumpkin.eval.preflight_errors import categorize_failure_reason
from bumpkin.eval.preflight_model import (
    invoke_recommend_fn,
    normalize_recommendation_result,
    run_eval_preflight,
)

__all__ = [
    "aggregate_results_from_json_dir",
    "categorize_failure_reason",
    "invoke_recommend_fn",
    "normalize_recommendation_result",
    "run_eval_preflight",
    "select_batch_cases",
]
