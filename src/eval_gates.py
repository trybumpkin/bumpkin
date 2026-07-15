from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from eval_run_types import EvaluationRun

STRICT_MAX_MANUAL_REVIEW_RATE = 0.20
STRICT_MAX_CRITICAL_MISSING_PROOFS = 0
STRICT_MAX_CONTRADICTIONS = 0


def _traceability_gates(
    args: argparse.Namespace,
    metrics: dict[str, Any],
    preflight: dict[str, Any],
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    codes: list[str] = []
    if metrics["evaluated_fixture_count"] == 0:
        failures.append("aggregate coverage produced zero evaluated fixtures.")
        codes.append("no_evaluated_fixtures")
    for key, message, code in (
        (
            "missing_fixture_names",
            "aggregate coverage missing fixture results: ",
            "missing_fixture_results",
        ),
        (
            "unexpected_fixture_names",
            "aggregate coverage included unexpected fixture results: ",
            "unexpected_fixture_results",
        ),
    ):
        if metrics[key]:
            failures.append(message + ", ".join(metrics[key]))
            codes.append(code)
    if bool(args.aggregate_json_dir) or str(preflight.get("status", "")).lower() == "ok":
        manual_rate = float(
            metrics.get(
                "unexpected_manual_review_rate",
                metrics.get("manual_review_rate", 0.0),
            )
            or 0.0
        )
        if manual_rate > STRICT_MAX_MANUAL_REVIEW_RATE:
            failures.append(
                "unexpected_manual_review_rate exceeded strict threshold: "
                f"{manual_rate:.2%} > {STRICT_MAX_MANUAL_REVIEW_RATE:.0%}"
            )
            codes.append("manual_review_rate_exceeded")
        missing_proofs = int(
            metrics.get(
                "unexpected_critical_missing_proofs_total",
                metrics.get("critical_missing_proofs_total", 0),
            )
            or 0
        )
        if missing_proofs > STRICT_MAX_CRITICAL_MISSING_PROOFS:
            failures.append(
                "unexpected_critical_missing_proofs_total exceeded strict threshold: "
                f"{missing_proofs} > {STRICT_MAX_CRITICAL_MISSING_PROOFS}"
            )
            codes.append("critical_missing_proofs_present")
        contradictions = int(metrics.get("contradiction_count", 0) or 0)
        if contradictions > STRICT_MAX_CONTRADICTIONS:
            failures.append(f"contradiction_count exceeded strict threshold: {contradictions} > 0")
            codes.append("contradictions_present")
    return failures, codes


def _baseline_failures(
    args: argparse.Namespace,
    runtime: Any,
    run: EvaluationRun,
) -> tuple[list[str], Path | None]:
    baseline_path = Path(args.prompt_gate_baseline) if args.prompt_gate_baseline else None
    if str(args.mode).strip().lower() == "stub" and baseline_path and baseline_path.exists():
        print(
            "Stub mode: skipping prompt-gate baseline "
            "(model-quality gates require auto/github-models/openrouter modes)."
        )
        baseline_path = None
    if not baseline_path or not baseline_path.exists():
        return [], baseline_path
    baseline = runtime.load_prompt_gate_baseline(baseline_path)
    missing = sorted(
        set(baseline["min_category_pass_rates"]) - set(run.metrics["category_pass_rates"])
    )
    run.metrics["missing_baseline_categories"] = missing
    run.metrics["baseline_coverage_complete"] = (
        run.metrics["baseline_coverage_complete"] and not missing
    )
    failures = runtime.compare_against_prompt_gate(run.metrics, baseline)
    if failures:
        print("Prompt gate failures:")
        for failure in failures:
            print(f"- {failure}")
    else:
        print(
            f"Prompt gate passed against baseline={baseline_path} "
            f"for language_group={args.language_group}"
        )
    return failures, baseline_path


def _strict_exit(
    args: argparse.Namespace,
    run: EvaluationRun,
    codes: list[str],
    baseline_path: Path | None,
    baseline_failures: list[str],
) -> int:
    if not args.strict:
        return 0
    if "no_evaluated_fixtures" in codes or (codes and not run.metrics["is_subset_run"]):
        return 1
    if str(args.mode).strip().lower() == "stub":
        print("Stub mode strict gate: skipping accuracy thresholds (smoke mode).")
        return 0
    if baseline_path and baseline_failures and not run.metrics["is_subset_run"]:
        return 1
    if (not baseline_path or not baseline_path.exists()) and run.pass_rate < args.min_pass_rate:
        print(
            f"Pass rate below threshold: {run.pass_rate:.2f} < "
            f"{args.min_pass_rate:.2f}. Treating as failure."
        )
        return 1
    return 0


def finalize(
    args: argparse.Namespace,
    runtime: Any,
    run: EvaluationRun,
    prompt_metadata: Any,
) -> int:
    run.metrics["evaluation_mode"] = "pipeline_parity"
    runtime.eval_reporting.print_case_results(
        run.results,
        build_observed_summary_fn=runtime.build_observed_summary,
    )
    runtime.eval_reporting.print_metrics_summary(
        passed_count=run.passed_count,
        result_count=len(run.results),
        pass_rate=run.pass_rate,
        mode_used_for_summary=run.mode_used,
        avg_latency_ms=run.avg_latency_ms,
        avg_tokens=run.avg_tokens,
        metrics=run.metrics,
    )
    failures, codes = _traceability_gates(args, run.metrics, run.preflight)
    baseline_failures, baseline_path = _baseline_failures(args, runtime, run)
    if baseline_failures:
        failures.extend(baseline_failures)
        codes.append("prompt_gate_regression")
    if run.metrics["is_subset_run"]:
        print("Subset run detected: baseline comparison is diagnostic-only for present categories.")
    payload = {
        "prompt_version": prompt_metadata.prompt_version,
        "language_group": prompt_metadata.language_group,
        "promotion_status": prompt_metadata.promotion_status,
        "preflight": run.preflight,
        "results": runtime._serialize_results(run.results),
        "metrics": run.metrics,
        "gate": {"failures": failures, "failure_codes": codes, "strict": args.strict},
    }
    runtime._write_output_json(args.output_json, payload)
    return _strict_exit(args, run, codes, baseline_path, baseline_failures)
