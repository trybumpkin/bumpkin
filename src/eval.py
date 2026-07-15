from __future__ import annotations

import argparse
import re
import sys
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
from eval_cli_args import parse_args as _parse_cli_args
from llm import get_recommendation
from prompt_pack import DEFAULT_LANGUAGE_GROUP
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

__all__ = [
    "FixtureCase",
    "FixtureResult",
    "build_case_inputs",
    "build_observed_summary",
    "categorize_failure_reason",
    "compare_against_prompt_gate",
    "compute_eval_metrics",
    "evaluate_fixture_cases",
    "get_default_prompt_gate_baseline",
    "load_bumpkin_config",
    "load_fixture_cases",
    "load_prompt_gate_baseline",
    "orchestrator_core",
    "plan_analysis_route",
    "policy_engine",
    "resolve_models_endpoint",
    "resolve_models_token",
    "run_eval_preflight",
    "select_batch_cases",
]


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
    return _parse_cli_args()


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
    from eval_pipeline import run

    return run(args, runtime=sys.modules[__name__])


if __name__ == "__main__":
    raise SystemExit(main())
