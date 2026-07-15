from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

from eval_run_types import EvaluationRun


@dataclass
class ModelSetup:
    token: str
    config: Any
    public_api_hints: list[str]
    preflight: dict[str, Any]
    cases: list[Any]
    batch_meta: dict[str, Any]


def _write_early_payload(
    args: argparse.Namespace,
    runtime: Any,
    *,
    prompt_metadata: Any,
    preflight: dict[str, Any],
    total_case_count: int,
    failure_code: str | None = None,
    failure_message: str | None = None,
) -> None:
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
            "total_case_count": total_case_count,
            "baseline_coverage_complete": False,
            "missing_fixture_names": [],
            "unexpected_fixture_names": [],
            "missing_baseline_categories": [],
        },
        "gate": {
            "failures": [failure_message] if failure_message else [],
            "failure_codes": [failure_code] if failure_code else [],
            "strict": args.strict,
        },
    }
    runtime._write_output_json(args.output_json, payload)


def prepare_model(
    args: argparse.Namespace,
    runtime: Any,
    *,
    prompt_metadata: Any,
    all_cases: list[Any],
) -> ModelSetup | int:
    token = runtime.resolve_models_token(endpoint=args.endpoint)
    try:
        bumpkin_config = runtime.load_bumpkin_config()
    except ValueError:
        bumpkin_config = runtime._fallback_config()
    public_api_hints = runtime.policy_engine.dedupe_preserving_order(
        list(bumpkin_config.surface_area)
        + list(bumpkin_config.public_api_paths)
        + list(bumpkin_config.public_api_entrypoints)
    )
    preflight = runtime.run_eval_preflight(
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
            "gate": {"failures": [], "failure_codes": [], "strict": args.strict},
        }
        print(json.dumps(payload["preflight"], indent=2))
        runtime._write_output_json(args.output_json, payload)
        return 1 if args.strict and preflight["status"] == "failed" else 0
    continue_on_failure = bool(getattr(args, "continue_on_preflight_failure", False))
    if preflight["status"] == "failed" and not continue_on_failure:
        print(
            f"Preflight failed: category={preflight['failure_category']} "
            f"reason={preflight['failure_reason']}"
        )
        print(json.dumps(preflight, indent=2))
        _write_early_payload(
            args,
            runtime,
            prompt_metadata=prompt_metadata,
            preflight=preflight,
            total_case_count=len(all_cases),
        )
        return 1 if args.strict else 0
    if preflight["status"] == "failed":
        print(
            "Preflight failed, continuing fixture evaluation because "
            "--continue-on-preflight-failure was set."
        )
        preflight = dict(preflight)
        preflight["continued"] = True
    cases, batch_meta = runtime.select_batch_cases(
        all_cases,
        batch_size=args.batch_size,
        batch_index=args.batch_index,
    )
    return ModelSetup(token, bumpkin_config, public_api_hints, preflight, cases, batch_meta)


def _recommendation_fn(
    args: argparse.Namespace,
    runtime: Any,
    *,
    prompt_metadata: Any,
    setup: ModelSetup,
) -> Any:
    def recommend(case: Any) -> dict[str, Any]:
        diff_result = runtime._build_fixture_diff_result(case)
        planner_decision = runtime.plan_analysis_route(
            mode=args.mode,
            endpoint=args.endpoint,
            has_model_token=bool(setup.token),
            approx_prompt_tokens=diff_result.approx_prompt_tokens,
            request_timeout=getattr(args, "request_timeout", 45),
            chunking_enabled=setup.config.chunking_enabled,
            chunk_max_tokens=setup.config.chunk_max_tokens,
            chunk_max_count=setup.config.chunk_max_count,
        )
        case_public_hints = runtime.policy_engine.dedupe_preserving_order(
            setup.public_api_hints + list(case.surface_area)
        )
        core_result = runtime.orchestrator_core.analyze_diff_core(
            diff_result=diff_result,
            mode=args.mode,
            model=args.model,
            fallback_model=None,
            endpoint=args.endpoint,
            token=setup.token,
            max_retries=args.max_retries,
            request_timeout=getattr(args, "request_timeout", 45),
            prompt_metadata=prompt_metadata,
            bumpkin_config=setup.config,
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
            key: output.get(key)
            for key in (
                "status",
                "label",
                "confidence",
                "reasoning",
                "changelog",
                "analysis_state",
                "classification_source",
                "decision_authority",
                "deterministic_label",
                "advisory_status",
                "advisory_label",
                "advisory_confidence",
                "court_skipped_reason",
                "decision_trace",
                "policy_effects",
                "proof_obligations",
                "contradictions",
                "fallback_reason",
                "failure_category",
            )
        }
        result["mode_used"] = output.get("mode")
        result["case_file_stats"] = output.get(
            "case_file_stats"
        ) or runtime._estimate_case_file_tokens(case.diff_text)
        result["findings"] = output.get("findings", [])
        if output.get("aggregation_trace"):
            result["aggregation_trace"] = output["aggregation_trace"]
        return result

    return recommend


def run_model(
    args: argparse.Namespace,
    runtime: Any,
    *,
    prompt_metadata: Any,
    setup: ModelSetup,
) -> EvaluationRun:
    recommend = _recommendation_fn(
        args,
        runtime,
        prompt_metadata=prompt_metadata,
        setup=setup,
    )
    results, passed_count, pass_rate, avg_latency_ms, avg_tokens = runtime._run_eval(
        setup.cases,
        recommend,
        inter_case_delay_ms=getattr(args, "case_delay_ms", 0),
    )
    metrics = runtime.compute_eval_metrics(
        results,
        prompt_version=prompt_metadata.prompt_version,
        language_group=prompt_metadata.language_group,
        promotion_status=prompt_metadata.promotion_status,
        total_case_count=setup.batch_meta["total_case_count"],
    )
    metrics.update(
        baseline_coverage_complete=not metrics["is_subset_run"],
        missing_fixture_names=[],
        unexpected_fixture_names=[],
        missing_baseline_categories=[],
    )
    print(
        f"Batch selection: index={setup.batch_meta['batch_index']} "
        f"size={setup.batch_meta['batch_size']} "
        f"cases={setup.batch_meta['batch_case_count']}/"
        f"{setup.batch_meta['total_case_count']}"
    )
    return EvaluationRun(
        results,
        passed_count,
        pass_rate,
        avg_latency_ms,
        avg_tokens,
        metrics,
        setup.preflight,
        args.mode,
    )
