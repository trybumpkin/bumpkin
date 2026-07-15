from __future__ import annotations

import argparse
import os
from collections.abc import Mapping
from typing import Any

from bumpkin.orchestrator import adjudication as orchestrator_adjudication
from bumpkin.orchestrator import scope as orchestrator_scope
from bumpkin.policies import engine as policy_engine
from bumpkin.policies import guards as guard_policies
from config import BumpkinConfig
from findings import Finding
from token_env import is_valid_models_endpoint, resolve_models_endpoint


def _categorize_failure_reason(reason: str | None) -> str | None:
    return orchestrator_adjudication.categorize_failure_reason(reason)


def _source_from_mode(mode_used: str) -> str:
    return orchestrator_adjudication.source_from_mode(mode_used)


def _derive_analysis_state(
    *,
    status: str,
    classification_source: str,
) -> tuple[str, str]:
    return orchestrator_adjudication.derive_analysis_state(
        status=status,
        classification_source=classification_source,
    )


def _apply_findings_adjudication(
    model_result: Mapping[str, Any],
    *,
    aggregated_findings: Any | None,
    mode_used: str,
    notes: list[str],
) -> tuple[dict[str, object], str | None, str]:
    return orchestrator_adjudication.apply_findings_adjudication(
        dict(model_result),
        aggregated_findings=aggregated_findings,
        mode_used=mode_used,
        notes=notes,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bumpkin recommendation pipeline")
    parser.add_argument("--from-ref", default="", help="Base git ref")
    parser.add_argument("--to-ref", default="", help="Target git ref")
    parser.add_argument("--token-cap", type=int, default=6000, help="Approx token cap")
    parser.add_argument(
        "--use-difftastic",
        default=os.getenv("BUMPKIN_USE_DIFFTASTIC", ""),
        help="Optional override for difftastic preprocessor usage (true/false).",
    )
    parser.add_argument(
        "--mode",
        default=os.getenv("BUMPKIN_PROVIDER", "auto"),
        help="Provider mode: auto | stub | github-models | openrouter",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("BUMPKIN_MODEL", ""),
        help="Model identifier for the configured provider.",
    )
    parser.add_argument(
        "--fallback-model",
        default=os.getenv("BUMPKIN_FALLBACK_MODEL", ""),
        help="Optional fallback model id used when primary model is unavailable.",
    )
    parser.add_argument(
        "--models-endpoint",
        default=resolve_models_endpoint(),
        help="Chat completions endpoint for the configured model provider.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retries for model requests",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=int(os.getenv("BUMPKIN_REQUEST_TIMEOUT", "45")),
        help="Per-request model API timeout in seconds",
    )
    return parser.parse_args()


def _parse_optional_bool(value: str) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "":
        return None
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


PREventContext = orchestrator_scope.PREventContext
OverrideResolution = orchestrator_scope.OverrideResolution


def _run_git(args: list[str]) -> str:
    return orchestrator_scope.run_git(args)


def _resolve_merge_parent_sha(merge_sha: str) -> str | None:
    return orchestrator_scope.resolve_merge_parent_sha(merge_sha)


def _read_event_context(event_path: str | None) -> PREventContext:
    return orchestrator_scope.read_event_context(event_path)


def _select_diff_scope(
    from_ref_arg: str,
    to_ref_arg: str,
    event_context: PREventContext,
    *,
    merge_parent_resolver: Any = _resolve_merge_parent_sha,
) -> tuple[str, str, list[str]]:
    return orchestrator_scope.select_diff_scope(
        from_ref_arg,
        to_ref_arg,
        event_context,
        merge_parent_resolver=merge_parent_resolver,
    )


def _normalize_repo_path(path: str) -> str:
    return orchestrator_scope.normalize_repo_path(path)


def _github_api_request(token: str, url: str) -> Any:
    return orchestrator_scope.github_api_request(token, url)


def _fetch_pr_changed_files(
    *,
    token: str,
    repo: str,
    pr_number: int,
) -> tuple[list[str] | None, str | None]:
    return orchestrator_scope.fetch_pr_changed_files(
        token=token,
        repo=repo,
        pr_number=pr_number,
        request_fn=_github_api_request,
    )


def _evaluate_scope_mismatch(
    *,
    required: bool,
    fetch_error: str | None,
    git_files_count: int,
    overlap_count: int,
    unexpected_count: int,
    missing_count: int,
) -> tuple[bool, str | None]:
    return orchestrator_scope.evaluate_scope_mismatch(
        required=required,
        fetch_error=fetch_error,
        git_files_count=git_files_count,
        overlap_count=overlap_count,
        unexpected_count=unexpected_count,
        missing_count=missing_count,
    )


def _resolve_override_governance(
    labels: list[str],
    *,
    policy: str,
) -> OverrideResolution:
    return orchestrator_scope.resolve_override_governance(
        labels,
        policy=policy,
    )


def _resolve_override_label(
    labels: list[str],
) -> tuple[str | None, str | None, str | None]:
    return orchestrator_scope.resolve_override_label(labels)


def _apply_docs_only_policy(
    result: Mapping[str, Any],
    bumpkin_config: BumpkinConfig,
    notes: list[str],
) -> dict[str, object]:
    if str(result.get("status", "classified")) != "classified":
        return dict(result)
    if str(result.get("label", "")).upper() != "NO_BUMP":
        return dict(result)
    if bumpkin_config.docs_only_label != "PATCH":
        return dict(result)

    updated: dict[str, object] = dict(result)
    updated["label"] = "PATCH"
    updated["changelog"] = "chore: release required by repo policy"
    notes.append("Repository policy remapped NO_BUMP to PATCH via docs_only_label=PATCH.")
    return updated


def _is_docs_or_config_path(path: str) -> bool:
    return guard_policies.is_docs_or_config_path(path)


def _surface_area_touched(analyzed_files: list[str], surface_area_hints: list[str]) -> bool:
    return guard_policies.surface_area_touched(analyzed_files, surface_area_hints)


def _uncertain_no_bump_result(policy: str, reasoning: str) -> dict[str, object]:
    return guard_policies.uncertain_no_bump_result(policy, reasoning)


def _apply_truncated_no_bump_guard(
    result: Mapping[str, Any],
    *,
    truncated: bool,
    analyzed_files: list[str],
    policy: str,
    notes: list[str],
) -> tuple[dict[str, object], bool]:
    return guard_policies.apply_truncated_no_bump_guard(
        dict(result),
        truncated=truncated,
        analyzed_files=analyzed_files,
        policy=policy,
        notes=notes,
    )


def _apply_truncated_surface_area_guard(
    result: Mapping[str, Any],
    *,
    truncated: bool,
    analyzed_files: list[str],
    surface_area_hints: list[str],
    chunking_meta: dict[str, object] | None,
    notes: list[str],
) -> tuple[dict[str, object], bool]:
    return guard_policies.apply_truncated_surface_area_guard(
        dict(result),
        truncated=truncated,
        analyzed_files=analyzed_files,
        surface_area_hints=surface_area_hints,
        chunking_meta=chunking_meta,
        notes=notes,
    )


def _apply_large_pr_no_bump_guard(
    result: Mapping[str, Any],
    *,
    analyzed_files_count: int,
    approx_prompt_tokens: int,
    max_files: int,
    max_tokens: int,
    policy: str,
    notes: list[str],
) -> tuple[dict[str, object], bool]:
    return guard_policies.apply_large_pr_no_bump_guard(
        dict(result),
        analyzed_files_count=analyzed_files_count,
        approx_prompt_tokens=approx_prompt_tokens,
        max_files=max_files,
        max_tokens=max_tokens,
        policy=policy,
        notes=notes,
    )


def _apply_analysis_coverage_guard(
    result: Mapping[str, Any],
    *,
    analyzed_files: list[str],
    findings: list[Finding],
    chunking_meta: dict[str, object] | None,
    notes: list[str],
) -> tuple[dict[str, object], bool]:
    return guard_policies.apply_analysis_coverage_guard(
        dict(result),
        analyzed_files=analyzed_files,
        findings=findings,
        chunking_meta=chunking_meta,
        notes=notes,
    )


def _derive_docs_only_policy_effect(
    *,
    status: str,
    label: str | None,
    docs_only_label: str,
) -> str:
    return policy_engine.derive_docs_only_policy_effect(
        status=status,
        label=label,
        docs_only_label=docs_only_label,
    )


def _derive_pre_1_0_policy_effect(
    *,
    status: str,
    label: str | None,
    current_tag: str | None,
    pre_1_0_breaking_as_minor: bool,
) -> str | None:
    return policy_engine.derive_pre_1_0_policy_effect(
        status=status,
        label=label,
        current_tag=current_tag,
        pre_1_0_breaking_as_minor=pre_1_0_breaking_as_minor,
    )


def _dedupe_preserving_order(items: list[str]) -> list[str]:
    return policy_engine.dedupe_preserving_order(items)


def _path_matches_hints(path: str, hints: list[str]) -> bool:
    return policy_engine.path_matches_hints(path, hints)


def _classify_finding_boundary(finding: Finding, *, public_hints: list[str]) -> str:
    return policy_engine.classify_finding_boundary(finding, public_hints=public_hints)


def _summarize_boundary(findings: list[Finding], *, public_hints: list[str]) -> dict[str, int]:
    return policy_engine.summarize_boundary(findings, public_hints=public_hints)


def _finding_severity_counts(findings: list[Finding]) -> dict[str, int]:
    return policy_engine.finding_severity_counts(findings)


def _has_bugfix_intent(result: dict[str, object]) -> bool:
    return policy_engine.has_bugfix_intent(result)


def _apply_policy_mode(
    result: Mapping[str, Any],
    *,
    boundary_summary: dict[str, int],
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    return policy_engine.apply_policy_mode(
        dict(result),
        boundary_summary=boundary_summary,
        config=config,
        notes=notes,
    )


def _manual_review_result(reasoning: str) -> dict[str, object]:
    return policy_engine.manual_review_result(reasoning)


def _apply_unknown_boundary_policy(
    result: Mapping[str, Any],
    *,
    boundary_summary: dict[str, int],
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    return policy_engine.apply_unknown_boundary_policy(
        dict(result),
        boundary_summary=boundary_summary,
        config=config,
        notes=notes,
    )


def _detect_behavior_contract_signals(
    analyzed_files: list[str],
    *,
    policy: str,
) -> dict[str, object]:
    return policy_engine.detect_behavior_contract_signals(analyzed_files, policy=policy)


def _summarize_evidence(
    findings: list[Finding],
    *,
    public_hints: list[str],
    contract_signals: dict[str, object],
) -> dict[str, int]:
    return policy_engine.summarize_evidence(
        findings,
        public_hints=public_hints,
        contract_signals=contract_signals,
    )


def _apply_impact_evidence_threshold(
    result: Mapping[str, Any],
    *,
    boundary_summary: dict[str, int],
    evidence_summary: dict[str, int],
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    return policy_engine.apply_impact_evidence_threshold(
        dict(result),
        boundary_summary=boundary_summary,
        evidence_summary=evidence_summary,
        config=config,
        notes=notes,
    )


def _apply_noise_suppression_policy(
    result: Mapping[str, Any],
    *,
    noise_ratio: float,
    changed_files_total: int,
    evidence_summary: dict[str, int],
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    return policy_engine.apply_noise_suppression_policy(
        dict(result),
        noise_ratio=noise_ratio,
        changed_files_total=changed_files_total,
        evidence_summary=evidence_summary,
        config=config,
        notes=notes,
    )


def _apply_degraded_provider_policy(
    result: Mapping[str, Any],
    *,
    mode_used: str,
    classification_source: str,
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    return policy_engine.apply_degraded_provider_policy(
        dict(result),
        mode_used=mode_used,
        classification_source=classification_source,
        config=config,
        notes=notes,
    )


def main() -> int:
    args = _parse_args()
    if not str(args.model or "").strip():
        raise ValueError("BUMPKIN_MODEL or --model is required.")
    if not str(args.models_endpoint or "").strip():
        raise ValueError("BUMPKIN_ENDPOINT or --models-endpoint is required.")
    if not is_valid_models_endpoint(str(args.models_endpoint)):
        raise ValueError("BUMPKIN_ENDPOINT or --models-endpoint must be a valid http(s) URL.")
    from bumpkin.orchestrator import pipeline as orchestrator_pipeline

    return orchestrator_pipeline.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
