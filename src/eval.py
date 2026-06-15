from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bumpkin.eval import fixtures as eval_fixtures
from bumpkin.eval import metrics as eval_metrics
from bumpkin.eval import preflight as eval_preflight
from bumpkin.eval import reporting as eval_reporting
from bumpkin.orchestrator import core as orchestrator_core
from bumpkin.planner import plan_analysis_route
from bumpkin.policies import engine as policy_engine
from config import BumpkinConfig, load_bumpkin_config
from diff import DiffResult, DiffUnit
from llm import get_recommendation
from prompt_pack import DEFAULT_LANGUAGE_GROUP, get_prompt_metadata
from token_env import resolve_models_endpoint, resolve_models_token

DEFAULT_PROMPT_GATE_BASELINE = Path("test-diffs/baselines/js-ts-v1.json")
PROMPT_GATE_BASELINES = {
    "javascript-typescript": Path("test-diffs/baselines/js-ts-v1.json"),
    "python": Path("test-diffs/baselines/python-v1.json"),
    "go": Path("test-diffs/baselines/go-v1.json"),
    "rust": Path("test-diffs/baselines/rust-v1.json"),
    "java-kotlin": Path("test-diffs/baselines/java-kotlin-v1.json"),
}
STRICT_MAX_MANUAL_REVIEW_RATE = 0.20
STRICT_MAX_CRITICAL_MISSING_PROOFS = 0
STRICT_MAX_CONTRADICTIONS = 0


def get_default_prompt_gate_baseline(language_group: str) -> Path:
    return PROMPT_GATE_BASELINES.get(language_group, DEFAULT_PROMPT_GATE_BASELINE)


FixtureCase = eval_fixtures.FixtureCase
FixtureResult = eval_fixtures.FixtureResult


def categorize_failure_reason(reason: str | None) -> str | None:
    return eval_preflight.categorize_failure_reason(reason)


def _invoke_recommend_fn(
    recommend_fn: Callable[..., tuple[dict[str, Any], str, str | None, str | None]],
    **kwargs: Any,
) -> tuple[dict[str, Any], str, str | None, str | None]:
    return eval_preflight.invoke_recommend_fn(recommend_fn, **kwargs)


def _normalize_recommendation_result(result: dict[str, Any]) -> dict[str, Any]:
    return eval_preflight.normalize_recommendation_result(result)


def run_eval_preflight(
    *,
    mode: str,
    language_group: str,
    prompt_version: str,
    model: str,
    endpoint: str,
    token: str,
    max_retries: int,
    request_timeout: int = 45,
    recommend_fn: Callable[
        ..., tuple[dict[str, Any], str, str | None, str | None]
    ] = get_recommendation,
) -> dict[str, Any]:
    return eval_preflight.run_eval_preflight(
        mode=mode,
        language_group=language_group,
        prompt_version=prompt_version,
        model=model,
        endpoint=endpoint,
        token=token,
        max_retries=max_retries,
        request_timeout=request_timeout,
        recommend_fn=recommend_fn,
    )


def select_batch_cases(
    cases: list[FixtureCase],
    *,
    batch_size: int | None,
    batch_index: int,
) -> tuple[list[FixtureCase], dict[str, Any]]:
    selected, metadata = eval_preflight.select_batch_cases(
        cases,
        batch_size=batch_size,
        batch_index=batch_index,
    )
    return selected, metadata


def aggregate_results_from_json_dir(
    json_dir: Path,
    *,
    expected_cases: list[FixtureCase],
) -> tuple[list[FixtureResult], dict[str, Any]]:
    aggregated, coverage = eval_preflight.aggregate_results_from_json_dir(
        json_dir,
        expected_cases=expected_cases,
        result_factory=FixtureResult,
    )
    return aggregated, coverage


def _ensure_string_list(value: Any) -> list[str]:
    return eval_fixtures.ensure_string_list(value)


def _validate_expected_payload(
    expected: Any,
    *,
    path: Path,
) -> dict[str, Any]:
    return eval_fixtures.validate_expected_payload(expected, path=path)


def load_fixture_cases(fixtures_dir: Path) -> list[FixtureCase]:
    return eval_fixtures.load_fixture_cases(
        fixtures_dir,
        case_factory=FixtureCase,
        validate_expected_payload_fn=_validate_expected_payload,
        ensure_string_list_fn=_ensure_string_list,
    )


def _matches_expected(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    return eval_fixtures.matches_expected(expected, actual)


def evaluate_fixture_cases(
    cases: list[FixtureCase],
    recommend_fn: Callable[[FixtureCase], dict[str, Any]],
) -> list[FixtureResult]:
    return eval_fixtures.evaluate_fixture_cases(
        cases,
        recommend_fn,
        result_factory=FixtureResult,
        matches_expected_fn=_matches_expected,
    )


def build_case_inputs(case: FixtureCase) -> tuple[list[str], list[str]]:
    return eval_fixtures.build_case_inputs(case)


def _estimate_tokens(text: str) -> int:
    return eval_fixtures.estimate_tokens(text)


def _estimate_case_file_tokens(diff_text: str, *, budget: int = 1200) -> dict[str, int]:
    estimated = max(1, len(diff_text or "") // 5) if diff_text else 0
    return {
        "token_budget": budget,
        "estimated_input_tokens": min(estimated, budget),
        "findings_included": 0,
        "findings_omitted": 0,
    }


def _fallback_config() -> BumpkinConfig:
    return BumpkinConfig(
        ignore_paths=[],
        surface_area=[],
        public_api_entrypoints=[],
        public_api_paths=[],
        policy_mode="pragmatic",
        bugfix_patch_bias=True,
        use_difftastic=False,
        semantic_fallback=True,
        pre_1_0_breaking_as_minor=True,
        docs_only_label="NO_BUMP",
        large_pr_max_files=30,
        large_pr_max_tokens=6000,
        truncated_no_bump_policy="MANUAL_REVIEW",
        chunking_enabled=True,
        chunk_max_tokens=1200,
        chunk_max_count=24,
        chunk_failure_policy="MANUAL_REVIEW",
        impact_evidence_threshold="moderate",
        unknown_boundary_policy="patch_if_bugfix",
        behavior_contract_policy="path_signals",
        noise_suppression_policy="balanced",
        override_governance_policy="strict_audit",
        degraded_provider_policy="MANUAL_REVIEW",
        decision_authority_mode="court",
    )


def _extract_diff_paths(diff_text: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"^diff --git a/(.+?) b/(.+?)$", diff_text, flags=re.MULTILINE):
        path = match.group(2).strip()
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def _build_fixture_diff_result(case: FixtureCase) -> DiffResult:
    full_diff_text = case.diff_text if case.diff_text.endswith("\n") else f"{case.diff_text}\n"
    approx_tokens = _estimate_tokens(full_diff_text)
    analyzed_files = _extract_diff_paths(full_diff_text)
    if not analyzed_files and full_diff_text.strip():
        analyzed_files = [f"fixture/{case.name}.diff"]
    changed_files_total = len(analyzed_files)

    unit_path = analyzed_files[0] if analyzed_files else f"fixture/{case.name}.diff"
    file_units = (
        [
            DiffUnit(
                path=unit_path,
                text=full_diff_text,
                approx_tokens=approx_tokens,
            )
        ]
        if full_diff_text.strip()
        else []
    )

    return DiffResult(
        from_ref=f"fixture/{case.name}/base",
        to_ref=f"fixture/{case.name}/head",
        repo_root=None,
        diff_text=full_diff_text,
        full_diff_text=full_diff_text,
        truncated=False,
        analyzed_files=analyzed_files,
        file_units=file_units,
        changed_files_total=changed_files_total,
        ignored_files_total=0,
        approx_prompt_tokens=approx_tokens,
        approx_full_tokens=approx_tokens,
        capped_files=0,
        scope_allowlist_files_total=0,
        scope_overlap_files=0,
        scope_unexpected_files=0,
        scope_missing_files=0,
        notes=[],
    )


def _is_schema_valid(actual: dict[str, Any]) -> bool:
    return eval_metrics.is_schema_valid(actual)


def build_observed_summary(actual: dict[str, Any]) -> dict[str, Any]:
    return eval_metrics.build_observed_summary(actual)


def _extract_expected_finding_specs(
    expected: dict[str, Any],
) -> list[tuple[str, str | None]]:
    return eval_metrics.extract_expected_finding_specs(expected)


def _extract_actual_finding_specs(actual: dict[str, Any]) -> list[tuple[str, str]]:
    return eval_metrics.extract_actual_finding_specs(actual)


def compute_eval_metrics(
    results: list[FixtureResult],
    *,
    prompt_version: str,
    language_group: str = DEFAULT_LANGUAGE_GROUP,
    promotion_status: str = "candidate",
    total_case_count: int | None = None,
) -> dict[str, Any]:
    return eval_metrics.compute_eval_metrics(
        results,
        prompt_version=prompt_version,
        language_group=language_group,
        promotion_status=promotion_status,
        total_case_count=total_case_count,
    )


def load_prompt_gate_baseline(path: Path) -> dict[str, Any]:
    return eval_metrics.load_prompt_gate_baseline(path)


def compare_against_prompt_gate(
    metrics: dict[str, Any],
    baseline: dict[str, Any],
) -> list[str]:
    return eval_metrics.compare_against_prompt_gate(metrics, baseline)


def _run_eval(
    cases: list[FixtureCase],
    recommend_fn: Callable[[FixtureCase], dict[str, Any]],
    *,
    inter_case_delay_ms: int = 0,
) -> tuple[list[FixtureResult], int, float, float, float]:
    return eval_fixtures.run_eval(
        cases,
        recommend_fn,
        result_factory=FixtureResult,
        matches_expected_fn=_matches_expected,
        estimate_tokens_fn=_estimate_tokens,
        inter_case_delay_ms=inter_case_delay_ms,
    )


def _parse_args() -> argparse.Namespace:
    try:
        default_case_delay_ms = int(os.getenv("BUMPKIN_EVAL_CASE_DELAY_MS", "0"))
    except ValueError:
        default_case_delay_ms = 0

    parser = argparse.ArgumentParser(description="Run Bumpkin fixture evals.")
    parser.add_argument("--fixtures-dir", default="test-diffs", help="Fixtures root directory")
    parser.add_argument(
        "--aggregate-json-dir",
        default="",
        help="Aggregate eval JSON outputs from this directory instead of running model calls.",
    )
    parser.add_argument(
        "--language-group",
        default=DEFAULT_LANGUAGE_GROUP,
        help="Only evaluate fixtures matching this language group.",
    )
    parser.add_argument(
        "--prompt-version",
        default="",
        help="Override prompt version selection.",
    )
    parser.add_argument(
        "--prompt-gate-baseline",
        default="",
        help="JSON file describing required prompt gate metrics.",
    )
    parser.add_argument(
        "--mode",
        default=os.getenv("BUMPKIN_PROVIDER", "auto"),
        help="Provider mode: auto | stub | github-models | openrouter",
    )
    parser.add_argument(
        "--include-tuning-targets",
        action="store_true",
        help="Include fixtures marked with context tuning_target=true.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("BUMPKIN_MODEL", ""),
        help="Model identifier for the configured provider.",
    )
    parser.add_argument(
        "--endpoint",
        default=resolve_models_endpoint(),
        help="Chat completions endpoint for the configured model provider.",
    )
    parser.add_argument("--max-retries", type=int, default=3, help="Model API max retries")
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=int(os.getenv("BUMPKIN_REQUEST_TIMEOUT", "45")),
        help="Per-request model API timeout in seconds",
    )
    parser.add_argument(
        "--case-delay-ms",
        type=int,
        default=default_case_delay_ms,
        help="Pause between fixture evals in milliseconds.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Optional number of fixtures to evaluate per batch.",
    )
    parser.add_argument(
        "--batch-index",
        type=int,
        default=0,
        help="Zero-based batch index when --batch-size is provided.",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional path to write machine-readable eval output.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run only the model preflight check and skip fixture execution.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when the selected quality gate fails.",
    )
    parser.add_argument(
        "--continue-on-preflight-failure",
        action="store_true",
        help=(
            "Continue fixture evaluation even when model preflight fails. "
            "Useful for deterministic/degraded smoke validation."
        ),
    )
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=0.8,
        help="Minimum passing ratio when --strict is used without a prompt gate baseline.",
    )
    return parser.parse_args()


def _filter_cases(
    cases: list[FixtureCase],
    *,
    language_group: str | None,
    include_tuning_targets: bool,
) -> list[FixtureCase]:
    return eval_fixtures.filter_cases(
        cases,
        language_group=language_group,
        include_tuning_targets=include_tuning_targets,
        default_language_group=DEFAULT_LANGUAGE_GROUP,
    )


def _serialize_results(results: list[FixtureResult]) -> list[dict[str, Any]]:
    return eval_reporting.serialize_results(results)


def _write_output_json(path: str, payload: dict[str, Any]) -> None:
    eval_reporting.write_output_json(path, payload)


def main() -> int:
    args = _parse_args()
    if not str(args.model or "").strip():
        raise ValueError("BUMPKIN_MODEL or --model is required.")
    if not str(args.endpoint or "").strip():
        raise ValueError("BUMPKIN_MODELS_ENDPOINT or --endpoint is required.")
    fixtures_dir = Path(args.fixtures_dir)
    if not fixtures_dir.exists():
        raise FileNotFoundError(f"Fixtures directory not found: {fixtures_dir}")

    prompt_metadata = get_prompt_metadata(
        language_group=args.language_group,
        prompt_version=args.prompt_version or None,
    )
    all_cases = _filter_cases(
        load_fixture_cases(fixtures_dir),
        language_group=args.language_group,
        include_tuning_targets=args.include_tuning_targets,
    )
    if not all_cases:
        failure_code = "no_fixtures_for_language_group"
        failure_message = (
            f"No fixture cases found in {fixtures_dir} for language_group={args.language_group}"
        )
        print(failure_message)
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
            "metrics": {
                "evaluation_mode": "pipeline_parity",
                "is_subset_run": False,
                "evaluated_fixture_count": 0,
                "total_case_count": 0,
                "baseline_coverage_complete": False,
                "missing_fixture_names": [],
                "unexpected_fixture_names": [],
                "missing_baseline_categories": [],
            },
            "gate": {
                "failures": [failure_message],
                "failure_codes": [failure_code],
                "strict": args.strict,
            },
        }
        _write_output_json(args.output_json, payload)
        return 1 if args.strict else 0

    if args.aggregate_json_dir:
        results, coverage = aggregate_results_from_json_dir(
            Path(args.aggregate_json_dir),
            expected_cases=all_cases,
        )
        passed_count = sum(1 for row in results if row.passed)
        metrics = compute_eval_metrics(
            results,
            prompt_version=prompt_metadata.prompt_version,
            language_group=prompt_metadata.language_group,
            promotion_status=prompt_metadata.promotion_status,
            total_case_count=len(all_cases),
        )
        metrics["baseline_coverage_complete"] = coverage["baseline_coverage_complete"]
        metrics["missing_fixture_names"] = coverage["missing_fixture_names"]
        metrics["unexpected_fixture_names"] = coverage["unexpected_fixture_names"]
        metrics["missing_baseline_categories"] = []
        preflight = {
            "status": "skipped",
            "reason": "aggregate mode does not perform model preflight.",
            "failure_category": None,
            "failure_reason": None,
            "mode_used": "aggregate",
            "model_used": None,
        }
        pass_rate = metrics["overall_pass_rate"]
        avg_latency_ms = 0.0
        avg_tokens = 0.0
        mode_used_for_summary = "aggregate"
    else:
        token = resolve_models_token(endpoint=args.endpoint)
        try:
            bumpkin_config = load_bumpkin_config()
        except ValueError:
            bumpkin_config = _fallback_config()
        base_public_api_hints = policy_engine.dedupe_preserving_order(
            list(bumpkin_config.surface_area)
            + list(bumpkin_config.public_api_paths)
            + list(bumpkin_config.public_api_entrypoints)
        )
        preflight = run_eval_preflight(
            mode=args.mode,
            language_group=prompt_metadata.language_group,
            prompt_version=prompt_metadata.prompt_version,
            model=args.model,
            endpoint=args.endpoint,
            token=token,
            max_retries=args.max_retries,
            request_timeout=getattr(args, "request_timeout", 45),
        )
        if args.preflight_only:
            payload = {
                "prompt_version": prompt_metadata.prompt_version,
                "language_group": prompt_metadata.language_group,
                "promotion_status": prompt_metadata.promotion_status,
                "preflight": preflight,
                "results": [],
                "metrics": {
                    "evaluation_mode": "pipeline_parity",
                    "is_subset_run": False,
                    "evaluated_fixture_count": 0,
                    "total_case_count": len(all_cases),
                },
                "gate": {
                    "failures": [],
                    "failure_codes": [],
                    "strict": args.strict,
                },
            }
            print(json.dumps(payload["preflight"], indent=2))
            _write_output_json(args.output_json, payload)
            return 1 if args.strict and preflight["status"] == "failed" else 0

        continue_on_preflight_failure = bool(getattr(args, "continue_on_preflight_failure", False))
        if preflight["status"] == "failed" and not continue_on_preflight_failure:
            print(
                "Preflight failed: "
                f"category={preflight['failure_category']} "
                f"reason={preflight['failure_reason']}"
            )
            print(json.dumps(preflight, indent=2))
            payload = {
                "prompt_version": prompt_metadata.prompt_version,
                "language_group": prompt_metadata.language_group,
                "promotion_status": prompt_metadata.promotion_status,
                "preflight": preflight,
                "results": [],
                "metrics": {
                    "evaluation_mode": "pipeline_parity",
                    "is_subset_run": False,
                    "evaluated_fixture_count": 0,
                    "total_case_count": len(all_cases),
                },
                "gate": {
                    "failures": [],
                    "failure_codes": [],
                    "strict": args.strict,
                },
            }
            _write_output_json(args.output_json, payload)
            return 1 if args.strict else 0
        if preflight["status"] == "failed" and continue_on_preflight_failure:
            print(
                "Preflight failed, continuing fixture evaluation because "
                "--continue-on-preflight-failure was set."
            )
            preflight = dict(preflight)
            preflight["continued"] = True

        cases, batch_meta = select_batch_cases(
            all_cases,
            batch_size=args.batch_size,
            batch_index=args.batch_index,
        )

        def recommend(case: FixtureCase) -> dict[str, Any]:
            diff_result = _build_fixture_diff_result(case)
            planner_decision = plan_analysis_route(
                mode=args.mode,
                endpoint=args.endpoint,
                has_model_token=bool(token),
                approx_prompt_tokens=diff_result.approx_prompt_tokens,
                request_timeout=getattr(args, "request_timeout", 45),
                chunking_enabled=bumpkin_config.chunking_enabled,
                chunk_max_tokens=bumpkin_config.chunk_max_tokens,
                chunk_max_count=bumpkin_config.chunk_max_count,
            )
            case_public_hints = policy_engine.dedupe_preserving_order(
                base_public_api_hints + list(case.surface_area)
            )
            core_result = orchestrator_core.analyze_diff_core(
                diff_result=diff_result,
                mode=args.mode,
                model=args.model,
                fallback_model=None,
                endpoint=args.endpoint,
                token=token,
                max_retries=args.max_retries,
                request_timeout=getattr(args, "request_timeout", 45),
                prompt_metadata=prompt_metadata,
                bumpkin_config=bumpkin_config,
                planner_decision=planner_decision,
                notes=[f"Fixture case: {case.name}"],
                event_labels=[],
                scope_mismatch_detected=False,
                scope_mismatch_reason=None,
                scope_guard={
                    "required": False,
                    "source": "fixture",
                    "fetch_error": None,
                    "pr_files_count": 0,
                    "git_files_count": diff_result.changed_files_total,
                    "overlap_count": 0,
                    "unexpected_count": 0,
                    "missing_count": 0,
                    "mismatch_detected": False,
                    "mismatch_reason": None,
                },
                public_api_hints=case_public_hints,
            )
            output = core_result.output
            result = {
                "status": output.get("status"),
                "label": output.get("label"),
                "confidence": output.get("confidence"),
                "reasoning": output.get("reasoning"),
                "changelog": output.get("changelog"),
                "mode_used": output.get("mode"),
                "analysis_state": output.get("analysis_state"),
                "classification_source": output.get("classification_source"),
                "decision_authority": output.get("decision_authority"),
                "deterministic_label": output.get("deterministic_label"),
                "advisory_status": output.get("advisory_status"),
                "advisory_label": output.get("advisory_label"),
                "advisory_confidence": output.get("advisory_confidence"),
                "court_skipped_reason": output.get("court_skipped_reason"),
                "case_file_stats": output.get("case_file_stats")
                or _estimate_case_file_tokens(case.diff_text),
                "findings": output.get("findings", []),
                "decision_trace": output.get("decision_trace"),
                "policy_effects": output.get("policy_effects", []),
                "proof_obligations": output.get("proof_obligations", {}),
                "contradictions": output.get("contradictions", []),
                "fallback_reason": output.get("fallback_reason"),
                "failure_category": output.get("failure_category"),
            }
            if output.get("aggregation_trace"):
                result["aggregation_trace"] = output.get("aggregation_trace")
            return result

        results, passed_count, pass_rate, avg_latency_ms, avg_tokens = _run_eval(
            cases,
            recommend,
            inter_case_delay_ms=getattr(args, "case_delay_ms", 0),
        )
        metrics = compute_eval_metrics(
            results,
            prompt_version=prompt_metadata.prompt_version,
            language_group=prompt_metadata.language_group,
            promotion_status=prompt_metadata.promotion_status,
            total_case_count=batch_meta["total_case_count"],
        )
        metrics["baseline_coverage_complete"] = not metrics["is_subset_run"]
        metrics["missing_fixture_names"] = []
        metrics["unexpected_fixture_names"] = []
        metrics["missing_baseline_categories"] = []
        mode_used_for_summary = args.mode
        print(
            "Batch selection: "
            f"index={batch_meta['batch_index']} size={batch_meta['batch_size']} "
            f"cases={batch_meta['batch_case_count']}/{batch_meta['total_case_count']}"
        )

    metrics["evaluation_mode"] = "pipeline_parity"

    eval_reporting.print_case_results(
        results,
        build_observed_summary_fn=build_observed_summary,
    )
    eval_reporting.print_metrics_summary(
        passed_count=passed_count,
        result_count=len(results),
        pass_rate=pass_rate,
        mode_used_for_summary=mode_used_for_summary,
        avg_latency_ms=avg_latency_ms,
        avg_tokens=avg_tokens,
        metrics=metrics,
    )

    failure_codes: list[str] = []
    gate_failures: list[str] = []
    baseline_gate_failures: list[str] = []
    if metrics["evaluated_fixture_count"] == 0:
        gate_failures.append("aggregate coverage produced zero evaluated fixtures.")
        failure_codes.append("no_evaluated_fixtures")
    if metrics["missing_fixture_names"]:
        gate_failures.append(
            "aggregate coverage missing fixture results: "
            + ", ".join(metrics["missing_fixture_names"])
        )
        failure_codes.append("missing_fixture_results")
    if metrics["unexpected_fixture_names"]:
        gate_failures.append(
            "aggregate coverage included unexpected fixture results: "
            + ", ".join(metrics["unexpected_fixture_names"])
        )
        failure_codes.append("unexpected_fixture_results")
    should_apply_traceability_gate = (
        bool(args.aggregate_json_dir) or str(preflight.get("status", "")).strip().lower() == "ok"
    )
    if should_apply_traceability_gate:
        unexpected_manual_review_rate = float(
            metrics.get("unexpected_manual_review_rate", metrics.get("manual_review_rate", 0.0))
            or 0.0
        )
        if unexpected_manual_review_rate > STRICT_MAX_MANUAL_REVIEW_RATE:
            gate_failures.append(
                "unexpected_manual_review_rate exceeded strict threshold: "
                f"{unexpected_manual_review_rate:.2%} > {STRICT_MAX_MANUAL_REVIEW_RATE:.0%}"
            )
            failure_codes.append("manual_review_rate_exceeded")
        critical_missing_total = int(
            metrics.get(
                "unexpected_critical_missing_proofs_total",
                metrics.get("critical_missing_proofs_total", 0),
            )
            or 0
        )
        if critical_missing_total > STRICT_MAX_CRITICAL_MISSING_PROOFS:
            gate_failures.append(
                "unexpected_critical_missing_proofs_total exceeded strict threshold: "
                f"{critical_missing_total} > {STRICT_MAX_CRITICAL_MISSING_PROOFS}"
            )
            failure_codes.append("critical_missing_proofs_present")
        contradiction_count = int(metrics.get("contradiction_count", 0) or 0)
        if contradiction_count > STRICT_MAX_CONTRADICTIONS:
            gate_failures.append(
                "contradiction_count exceeded strict threshold: "
                f"{contradiction_count} > {STRICT_MAX_CONTRADICTIONS}"
            )
            failure_codes.append("contradictions_present")
    mode_normalized = str(args.mode or "").strip().lower()
    is_stub_mode = mode_normalized == "stub"
    baseline_path = Path(args.prompt_gate_baseline) if args.prompt_gate_baseline else None
    if is_stub_mode and baseline_path and baseline_path.exists():
        print(
            "Stub mode: skipping prompt-gate baseline "
            "(model-quality gates require auto/github-models/openrouter modes)."
        )
        baseline_path = None
    if baseline_path and baseline_path.exists():
        baseline = load_prompt_gate_baseline(baseline_path)
        missing_categories = sorted(
            set(baseline["min_category_pass_rates"]) - set(metrics["category_pass_rates"])
        )
        metrics["missing_baseline_categories"] = missing_categories
        metrics["baseline_coverage_complete"] = (
            metrics["baseline_coverage_complete"] and not missing_categories
        )
        baseline_gate_failures = compare_against_prompt_gate(metrics, baseline)
        gate_failures.extend(baseline_gate_failures)
        if baseline_gate_failures:
            failure_codes.append("prompt_gate_regression")
            print("Prompt gate failures:")
            for failure in baseline_gate_failures:
                print(f"- {failure}")
        else:
            print(
                "Prompt gate passed "
                f"against baseline={baseline_path} for language_group={args.language_group}"
            )
    if metrics["is_subset_run"]:
        print("Subset run detected: baseline comparison is diagnostic-only for present categories.")

    payload = {
        "prompt_version": prompt_metadata.prompt_version,
        "language_group": prompt_metadata.language_group,
        "promotion_status": prompt_metadata.promotion_status,
        "preflight": preflight,
        "results": _serialize_results(results),
        "metrics": metrics,
        "gate": {
            "failures": gate_failures,
            "failure_codes": failure_codes,
            "strict": args.strict,
        },
    }
    _write_output_json(args.output_json, payload)

    if args.strict:
        if "no_evaluated_fixtures" in failure_codes:
            return 1
        if failure_codes and not metrics["is_subset_run"]:
            return 1
        if is_stub_mode:
            print("Stub mode strict gate: skipping accuracy thresholds (smoke mode).")
            return 0
        if (
            baseline_path
            and baseline_path.exists()
            and baseline_gate_failures
            and not metrics["is_subset_run"]
        ):
            return 1
        if (not baseline_path or not baseline_path.exists()) and pass_rate < args.min_pass_rate:
            print(
                f"Pass rate below threshold: {pass_rate:.2f} < {args.min_pass_rate:.2f}. "
                "Treating as failure."
            )
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
