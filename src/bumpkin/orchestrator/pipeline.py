from __future__ import annotations

import json
import os
from argparse import Namespace
from typing import Protocol

from bumpkin.analysis.diffing import DEFAULT_IGNORES, build_diff, resolve_refs
from bumpkin.analysis.language import detect_language_groups, detect_language_hints
from bumpkin.config import BumpkinConfig, load_bumpkin_config
from bumpkin.contracts import validate_output_contract
from bumpkin.io.comments import format_recommendation_comment, post_pr_comment
from bumpkin.io.tokens import resolve_models_token
from bumpkin.orchestrator import core as orchestrator_core
from bumpkin.orchestrator import scope as orchestrator_scope
from bumpkin.planner import plan_analysis_route
from bumpkin.policies import engine as policy_engine
from bumpkin.prompt_pack import get_prompt_metadata


class CommentPoster(Protocol):
    def __call__(self, *, token: str, repo: str, pr_number: int, body: str) -> None: ...


def _parse_optional_bool(value: str | None) -> bool | None:
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


def _capture_pr_comment_only() -> bool:
    return bool(_parse_optional_bool(os.getenv("BUMPKIN_CAPTURE_PR_COMMENT_ONLY")))


def _emit_pipeline_log(message: str) -> None:
    if _capture_pr_comment_only():
        return
    print(message)


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


def run(args: Namespace, *, comment_poster: CommentPoster | None = None) -> int:
    repo = os.getenv("GITHUB_REPOSITORY", "")
    github_token = os.getenv("GITHUB_TOKEN", "")
    event_path = os.getenv("GITHUB_EVENT_PATH")
    event_context = orchestrator_scope.read_event_context(event_path)
    resolved_comment_poster = post_pr_comment if comment_poster is None else comment_poster

    from_ref_input, to_ref_input, notes = orchestrator_scope.select_diff_scope(
        args.from_ref,
        args.to_ref,
        event_context,
    )

    from_ref, to_ref, resolved_notes = resolve_refs(from_ref_input, to_ref_input)
    notes.extend(resolved_notes)

    scope_guard_required = event_context.pr_number is not None
    pr_file_allowlist: list[str] | None = None
    scope_guard_fetch_error: str | None = None
    if scope_guard_required and event_context.pr_number is not None:
        pr_file_allowlist, scope_guard_fetch_error = orchestrator_scope.fetch_pr_changed_files(
            token=github_token,
            repo=repo,
            pr_number=event_context.pr_number,
            request_fn=orchestrator_scope.github_api_request,
        )
        if pr_file_allowlist is not None:
            notes.append(f"Scope guard loaded {len(pr_file_allowlist)} PR file(s) from GitHub API.")
        elif scope_guard_fetch_error:
            notes.append(scope_guard_fetch_error)

    try:
        bumpkin_config = load_bumpkin_config()
    except ValueError as err:
        notes.append(str(err))
        bumpkin_config = _fallback_config()

    ignore_patterns = list(DEFAULT_IGNORES)
    if bumpkin_config.ignore_paths:
        for pattern in bumpkin_config.ignore_paths:
            if pattern not in ignore_patterns:
                ignore_patterns.append(pattern)
        notes.append(
            f"Merged ignore_paths from bumpkin.yml ({len(bumpkin_config.ignore_paths)} pattern(s))."
        )
    if bumpkin_config.surface_area:
        notes.append(
            f"Loaded surface_area hints from bumpkin.yml ({len(bumpkin_config.surface_area)} pattern(s))."
        )
    if bumpkin_config.public_api_paths or bumpkin_config.public_api_entrypoints:
        notes.append(
            "Loaded public_api contract from bumpkin.yml "
            f"(paths={len(bumpkin_config.public_api_paths)}, "
            f"entrypoints={len(bumpkin_config.public_api_entrypoints)})."
        )
    public_api_hints = policy_engine.dedupe_preserving_order(
        list(bumpkin_config.surface_area)
        + list(bumpkin_config.public_api_paths)
        + list(bumpkin_config.public_api_entrypoints)
    )
    cli_difftastic = _parse_optional_bool(args.use_difftastic)
    use_difftastic = bumpkin_config.use_difftastic if cli_difftastic is None else cli_difftastic
    if use_difftastic:
        notes.append("Difftastic preprocessing requested.")

    diff_result = build_diff(
        from_ref=from_ref,
        to_ref=to_ref,
        ignore_patterns=ignore_patterns,
        allowed_files=pr_file_allowlist,
        token_cap=args.token_cap,
        use_difftastic=use_difftastic,
        chunking_enabled=bumpkin_config.chunking_enabled,
    )

    notes.extend(diff_result.notes)
    scope_mismatch_detected, scope_mismatch_reason = orchestrator_scope.evaluate_scope_mismatch(
        required=scope_guard_required,
        fetch_error=scope_guard_fetch_error,
        git_files_count=diff_result.changed_files_total,
        overlap_count=diff_result.scope_overlap_files,
        unexpected_count=diff_result.scope_unexpected_files,
        missing_count=diff_result.scope_missing_files,
    )
    scope_guard: dict[str, object] = {
        "required": scope_guard_required,
        "source": "github-pr-files" if pr_file_allowlist is not None else "unavailable",
        "fetch_error": scope_guard_fetch_error,
        "pr_files_count": len(pr_file_allowlist or []),
        "git_files_count": diff_result.changed_files_total,
        "overlap_count": diff_result.scope_overlap_files,
        "unexpected_count": diff_result.scope_unexpected_files,
        "missing_count": diff_result.scope_missing_files,
        "mismatch_detected": scope_mismatch_detected,
        "mismatch_reason": scope_mismatch_reason,
    }
    if scope_mismatch_detected and scope_mismatch_reason:
        notes.append(f"Scope mismatch guard triggered: {scope_mismatch_reason}.")

    models_token = resolve_models_token(endpoint=args.models_endpoint)
    detected_language_groups = detect_language_groups(diff_result.analyzed_files)
    if len(detected_language_groups) == 1:
        prompt_language_group = detected_language_groups[0]
    elif len(detected_language_groups) == 0:
        prompt_language_group = "generic"
    else:
        prompt_language_group = "generic"
    prompt_metadata = get_prompt_metadata(language_group=prompt_language_group)
    if len(detected_language_groups) > 1:
        notes.append(
            "Detected multiple language groups; using the experimental generic prompt pack."
        )
    elif (
        getattr(prompt_metadata, "language_group", prompt_language_group) == "generic"
        and prompt_metadata.promotion_status != "promoted"
    ):
        notes.append(
            "Using an experimental generic prompt pack because no promoted language-specific pack matched."
        )

    language_hints = detect_language_hints(diff_result.analyzed_files)
    if language_hints:
        notes.append(f"Injected {len(language_hints)} language-specific API hint(s).")

    planner_decision = plan_analysis_route(
        mode=args.mode,
        endpoint=args.models_endpoint,
        has_model_token=bool(models_token),
        approx_prompt_tokens=diff_result.approx_prompt_tokens,
        request_timeout=getattr(args, "request_timeout", 45),
        chunking_enabled=bumpkin_config.chunking_enabled,
        chunk_max_tokens=bumpkin_config.chunk_max_tokens,
        chunk_max_count=bumpkin_config.chunk_max_count,
    )
    notes.append(
        "Planner route: "
        f"{planner_decision.route} "
        f"(reason={planner_decision.reason}, provider={planner_decision.provider_profile.provider})."
    )

    core_result = orchestrator_core.analyze_diff_core(
        diff_result=diff_result,
        mode=args.mode,
        model=args.model,
        fallback_model=args.fallback_model or None,
        endpoint=args.models_endpoint,
        token=models_token,
        max_retries=args.max_retries,
        request_timeout=getattr(args, "request_timeout", 45),
        prompt_metadata=prompt_metadata,
        bumpkin_config=bumpkin_config,
        planner_decision=planner_decision,
        notes=notes,
        event_labels=event_context.labels,
        scope_mismatch_detected=scope_mismatch_detected,
        scope_mismatch_reason=scope_mismatch_reason,
        scope_guard=scope_guard,
        public_api_hints=public_api_hints,
        language_hints=language_hints,
    )

    output = core_result.output
    contract_errors = validate_output_contract(output)
    if contract_errors:
        raise RuntimeError("Output contract validation failed: " + "; ".join(contract_errors))
    if not _capture_pr_comment_only():
        print(json.dumps(output, indent=2))

    pr_number = event_context.pr_number
    if pr_number is None:
        _emit_pipeline_log("No pull_request event payload detected; skipping PR comment posting.")
        return 0

    body = format_recommendation_comment(
        result=core_result.result,
        notes=core_result.notes,
        mode=core_result.mode_used,
        fallback_reason=core_result.fallback_reason,
        current_tag=core_result.current_tag,
        next_tag=core_result.next_tag,
        override_summary=core_result.override_summary,
        findings=[finding.to_dict() for finding in core_result.findings],
        explainability_rows=core_result.explainability_rows,
        aggregation_trace=core_result.aggregation_trace,
        boundary_summary=core_result.boundary_summary,
        decision_trace=core_result.decision_trace,
        analysis_state=core_result.analysis_state,
        classification_source=core_result.classification_source,
        failure_category=core_result.failure_category,
        policy_effects=core_result.policy_effects,
        override_status=core_result.override_status,
        advisory_status=str(core_result.court_advisory.get("status", "skipped")),
        advisory_label=(
            str(core_result.court_advisory.get("label", "")).upper()
            if core_result.court_advisory.get("label")
            else None
        ),
        advisory_confidence=str(core_result.court_advisory.get("confidence", "")).strip() or None,
        advisory_summary=str(core_result.court_advisory.get("judge_summary", "")).strip() or None,
        advisory_fallback_reason=core_result.court_fallback_reason,
        disagreement_reason=str(core_result.court_advisory.get("disagreement_reason", "")).strip()
        or None,
        advisory_accepted_evidence_ids=core_result.court_advisory.get("accepted_evidence_ids", []),
        advisory_rejected_evidence_ids=core_result.court_advisory.get("rejected_evidence_ids", []),
        proof_obligations=core_result.proof_obligations,
        contradictions=core_result.contradictions,
    )
    resolved_comment_poster(token=github_token, repo=repo, pr_number=pr_number, body=body)
    if _capture_pr_comment_only():
        return 0
    print(f"Posted recommendation comment to PR #{pr_number}.")
    return 0
