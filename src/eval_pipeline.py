from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from eval_gates import finalize
from eval_model_runner import prepare_model, run_model
from eval_run_types import EvaluationRun
from prompt_pack import get_prompt_metadata


def _base_metrics(*, total_case_count: int) -> dict[str, Any]:
    return {
        "evaluation_mode": "pipeline_parity",
        "is_subset_run": False,
        "evaluated_fixture_count": 0,
        "total_case_count": total_case_count,
        "baseline_coverage_complete": False,
        "missing_fixture_names": [],
        "unexpected_fixture_names": [],
        "missing_baseline_categories": [],
    }


def _write_no_fixture_result(
    args: argparse.Namespace,
    runtime: Any,
    *,
    prompt_metadata: Any,
    message: str,
) -> None:
    payload = {
        "prompt_version": prompt_metadata.prompt_version,
        "language_group": prompt_metadata.language_group,
        "promotion_status": prompt_metadata.promotion_status,
        "preflight": {
            "status": "skipped",
            "reason": "no fixtures selected for requested language group.",
            "failure_category": None,
            "failure_reason": None,
            "mode_used": "n/a",
            "model_used": None,
        },
        "results": [],
        "metrics": _base_metrics(total_case_count=0),
        "gate": {
            "failures": [message],
            "failure_codes": ["no_fixtures_for_language_group"],
            "strict": args.strict,
        },
    }
    runtime._write_output_json(args.output_json, payload)


def _aggregate_run(
    runtime: Any,
    *,
    prompt_metadata: Any,
    all_cases: list[Any],
    aggregate_json_dir: str,
) -> EvaluationRun:
    results, coverage = runtime.aggregate_results_from_json_dir(
        Path(aggregate_json_dir),
        expected_cases=all_cases,
    )
    metrics = runtime.compute_eval_metrics(
        results,
        prompt_version=prompt_metadata.prompt_version,
        language_group=prompt_metadata.language_group,
        promotion_status=prompt_metadata.promotion_status,
        total_case_count=len(all_cases),
    )
    metrics.update(
        baseline_coverage_complete=coverage["baseline_coverage_complete"],
        missing_fixture_names=coverage["missing_fixture_names"],
        unexpected_fixture_names=coverage["unexpected_fixture_names"],
        missing_baseline_categories=[],
    )
    return EvaluationRun(
        results=results,
        passed_count=sum(row.passed for row in results),
        pass_rate=metrics["overall_pass_rate"],
        avg_latency_ms=0.0,
        avg_tokens=0.0,
        metrics=metrics,
        preflight={
            "status": "skipped",
            "reason": "aggregate mode does not perform model preflight.",
            "failure_category": None,
            "failure_reason": None,
            "mode_used": "aggregate",
            "model_used": None,
        },
        mode_used="aggregate",
    )


def run(args: argparse.Namespace, *, runtime: Any) -> int:
    if not str(args.model or "").strip():
        raise ValueError("BUMPKIN_MODEL or --model is required.")
    if not str(args.endpoint or "").strip():
        raise ValueError("BUMPKIN_ENDPOINT or --endpoint is required.")
    fixtures_dir = Path(args.fixtures_dir)
    if not fixtures_dir.exists():
        raise FileNotFoundError(f"Fixtures directory not found: {fixtures_dir}")
    prompt_metadata = get_prompt_metadata(
        language_group=args.language_group,
        prompt_version=args.prompt_version or None,
    )
    all_cases = runtime._filter_cases(
        runtime.load_fixture_cases(fixtures_dir),
        language_group=args.language_group,
        include_tuning_targets=args.include_tuning_targets,
    )
    if not all_cases:
        message = (
            f"No fixture cases found in {fixtures_dir} for language_group={args.language_group}"
        )
        print(message)
        _write_no_fixture_result(
            args,
            runtime,
            prompt_metadata=prompt_metadata,
            message=message,
        )
        return 1 if args.strict else 0
    if args.aggregate_json_dir:
        evaluation = _aggregate_run(
            runtime,
            prompt_metadata=prompt_metadata,
            all_cases=all_cases,
            aggregate_json_dir=args.aggregate_json_dir,
        )
    else:
        setup = prepare_model(
            args,
            runtime,
            prompt_metadata=prompt_metadata,
            all_cases=all_cases,
        )
        if isinstance(setup, int):
            return setup
        evaluation = run_model(
            args,
            runtime,
            prompt_metadata=prompt_metadata,
            setup=setup,
        )
    return finalize(args, runtime, evaluation, prompt_metadata)
