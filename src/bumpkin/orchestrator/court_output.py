from __future__ import annotations

from typing import Any

from bumpkin.config import BumpkinConfig
from bumpkin.orchestrator import explainability as orchestrator_explainability


def _uses_accepted_evidence_ids(
    *,
    court_advisory: dict[str, Any],
    evidence_lookup: dict[str, dict[str, str]],
) -> bool:
    accepted_ids = orchestrator_explainability._as_object_list(
        court_advisory.get("accepted_evidence_ids")
    )
    if accepted_ids is None:
        return False
    normalized_ids = [str(item).strip() for item in accepted_ids if str(item).strip()]
    return any(item in evidence_lookup for item in normalized_ids)


def _reasoning_intro_for_label(label: str) -> str:
    mapping = {
        "MAJOR": "Court selected MAJOR because a breaking behavior change was detected",
        "MINOR": "Court selected MINOR because backward-compatible behavior was added",
        "PATCH": "Court selected PATCH because internal behavior was updated",
        "NO_BUMP": "Court selected NO_BUMP because changes are operational only",
    }
    return mapping.get(label.upper(), f"Court selected {label} from available evidence")


def _render_evidence_grounded_reasoning(
    *,
    advisory_label: str,
    court_advisory: dict[str, Any],
    evidence_lookup: dict[str, dict[str, str]],
) -> tuple[str | None, bool]:
    records = orchestrator_explainability._select_explanation_records(
        advisory_label=advisory_label,
        court_advisory=court_advisory,
        evidence_lookup=evidence_lookup,
        max_items=3,
    )
    if not records:
        return None, False
    if orchestrator_explainability._is_explanation_dsl_enabled():
        facts = orchestrator_explainability.explanation_dsl.build_explanation_facts(
            advisory_label=advisory_label,
            records=records,
            max_target_items=2,
        )
        if facts:
            reasoning = orchestrator_explainability.explanation_dsl.render_reasoning_from_facts(
                facts
            )
            if (
                reasoning
                and orchestrator_explainability.explanation_dsl.passes_quality_policy(reasoning)
                and orchestrator_explainability._is_human_readable_explanation(reasoning)
            ):
                return reasoning, True

    paths = [
        str(record.get("path", "")).strip()
        for record in records
        if str(record.get("path", "")).strip()
    ]
    target_summary = orchestrator_explainability._summarize_path_targets(paths)
    change_hint = orchestrator_explainability._change_hint_from_records(records)
    detail = f", including {change_hint}" if change_hint else ""
    reasoning = f"{_reasoning_intro_for_label(advisory_label)} in {target_summary}{detail}."
    if len(reasoning) > 320:
        reasoning = reasoning[:317].rstrip() + "..."
    if not orchestrator_explainability._is_human_readable_explanation(reasoning):
        return None, False
    return reasoning, True


def _render_evidence_grounded_changelog(
    *,
    advisory_label: str,
    court_advisory: dict[str, Any],
    evidence_lookup: dict[str, dict[str, str]],
) -> tuple[str | None, bool]:
    records = orchestrator_explainability._select_explanation_records(
        advisory_label=advisory_label,
        court_advisory=court_advisory,
        evidence_lookup=evidence_lookup,
        max_items=3,
    )
    if not records:
        return None, False
    if orchestrator_explainability._is_explanation_dsl_enabled():
        facts = orchestrator_explainability.explanation_dsl.build_explanation_facts(
            advisory_label=advisory_label,
            records=records,
            max_target_items=2,
        )
        if facts:
            changelog = orchestrator_explainability.explanation_dsl.render_changelog_from_facts(
                facts
            )
            if (
                changelog
                and orchestrator_explainability.explanation_dsl.passes_quality_policy(changelog)
                and orchestrator_explainability._is_human_readable_explanation(changelog)
            ):
                return changelog, True

    if advisory_label == "NO_BUMP":
        return "chore: no release required", True
    paths = [
        str(record.get("path", "")).strip()
        for record in records
        if str(record.get("path", "")).strip()
    ]
    primary = records[0]
    scope = orchestrator_explainability._derive_scope_from_path(
        paths[0] if paths else "",
        rule=str(primary.get("rule", "")),
    )
    target_summary = orchestrator_explainability._summarize_path_targets(paths)
    change_hint = orchestrator_explainability._change_hint_from_records(records)
    detail = f" via {change_hint}" if change_hint else ""
    if advisory_label == "MAJOR":
        changelog = f"feat({scope})!: introduce breaking behavior across {target_summary}{detail}"
        if orchestrator_explainability._is_human_readable_explanation(changelog):
            return changelog, True
        return None, False
    if advisory_label == "MINOR":
        changelog = f"feat({scope}): add behavior across {target_summary}{detail}"
        if orchestrator_explainability._is_human_readable_explanation(changelog):
            return changelog, True
        return None, False
    if advisory_label == "PATCH":
        changelog = f"fix({scope}): update behavior across {target_summary}{detail}"
        if orchestrator_explainability._is_human_readable_explanation(changelog):
            return changelog, True
        return None, False
    return None, False


def _is_generic_court_summary(summary: str, *, label: str | None) -> bool:
    normalized = summary.strip()
    if not normalized:
        return True
    lowered = normalized.lower()
    if lowered == "compatibility court selected the final semver classification.":
        return True
    normalized_label = str(label or "").strip().upper()
    return bool(
        normalized_label
        and lowered
        == f"court selected {normalized_label.lower()} based on the strongest evidence in the case file."
    )


def _prefer_deterministic_explanation(
    *,
    court_advisory: dict[str, Any],
    advisory_label: str | None,
) -> bool:
    confidence = str(court_advisory.get("confidence", "")).strip().lower()
    summary = str(court_advisory.get("judge_summary", "")).strip()
    return confidence == "low" or _is_generic_court_summary(summary, label=advisory_label)


def _select_court_reasoning(
    *,
    court_advisory: dict[str, Any],
    advisory_label: str | None,
    pre_court_result: dict[str, Any],
) -> tuple[str, bool]:
    court_summary = str(court_advisory.get("judge_summary", "")).strip()
    deterministic_reasoning = str(pre_court_result.get("reasoning", "")).strip()
    if (
        _prefer_deterministic_explanation(
            court_advisory=court_advisory,
            advisory_label=advisory_label,
        )
        and deterministic_reasoning
    ):
        return deterministic_reasoning, True
    if court_summary:
        return court_summary, False
    if deterministic_reasoning:
        return deterministic_reasoning, True
    return "Compatibility court selected the final SemVer classification.", False


def _select_court_changelog(
    *,
    advisory_label: str,
    court_advisory: dict[str, Any],
    pre_court_result: dict[str, Any],
) -> tuple[str, bool]:
    deterministic_label = str(pre_court_result.get("label", "")).strip().upper()
    deterministic_changelog = str(pre_court_result.get("changelog", "")).strip()
    if (
        deterministic_label == advisory_label
        and deterministic_changelog
        and _prefer_deterministic_explanation(
            court_advisory=court_advisory,
            advisory_label=advisory_label,
        )
    ):
        return deterministic_changelog, True
    return orchestrator_explainability._changelog_for_label(advisory_label), False


def _apply_docs_only_policy(
    result: dict[str, object],
    bumpkin_config: BumpkinConfig,
    notes: list[str],
) -> dict[str, object]:
    if str(result.get("status", "classified")) != "classified":
        return result
    if str(result.get("label", "")).upper() != "NO_BUMP":
        return result
    if bumpkin_config.docs_only_label != "PATCH":
        return result

    updated = dict(result)
    updated["label"] = "PATCH"
    updated["changelog"] = "chore: release required by repo policy"
    notes.append("Repository policy remapped NO_BUMP to PATCH via docs_only_label=PATCH.")
    return updated


def _should_skip_court_advisory(
    *,
    status: str,
    deterministic_label: str | None,
    deterministic_confidence: str | None,
    mode_used: str,
    classification_source: str,
) -> tuple[bool, str | None]:
    if status != "classified" or not deterministic_label:
        return False, None

    normalized_label = deterministic_label.upper()
    normalized_confidence = str(deterministic_confidence or "").strip().lower()
    normalized_mode = mode_used.strip().lower()
    normalized_source = classification_source.strip().lower()
    degraded_path = normalized_mode.startswith("fallback") or "degraded" in normalized_source

    if degraded_path:
        return False, None

    if normalized_confidence == "high":
        return True, f"deterministic_high_confidence_{normalized_label.lower()}"

    return False, None


def _build_skipped_court_advisory(
    *,
    deterministic_label: str | None,
    deterministic_confidence: str | None,
    court_skipped_reason: str,
) -> dict[str, Any]:
    skipped_label = deterministic_label or "deterministic"
    return {
        "status": "skipped",
        "label": deterministic_label,
        "confidence": deterministic_confidence or "high",
        "judge_summary": (
            f"Court advisory skipped ({court_skipped_reason}) for deterministic {skipped_label}."
        ),
        "prosecutor_claims": [],
        "defender_claims": [],
        "accepted_arguments": [
            f"Deterministic {skipped_label} decision accepted without court call."
        ],
        "rejected_arguments": [],
        "unresolved_risks": [],
        "accepted_evidence_ids": [],
        "rejected_evidence_ids": [],
        "disagreement_reason": None,
    }


uses_accepted_evidence_ids = _uses_accepted_evidence_ids
reasoning_intro_for_label = _reasoning_intro_for_label
render_evidence_grounded_reasoning = _render_evidence_grounded_reasoning
render_evidence_grounded_changelog = _render_evidence_grounded_changelog
is_generic_court_summary = _is_generic_court_summary
prefer_deterministic_explanation = _prefer_deterministic_explanation
select_court_reasoning = _select_court_reasoning
select_court_changelog = _select_court_changelog
apply_docs_only_policy = _apply_docs_only_policy
should_skip_court_advisory = _should_skip_court_advisory
build_skipped_court_advisory = _build_skipped_court_advisory
