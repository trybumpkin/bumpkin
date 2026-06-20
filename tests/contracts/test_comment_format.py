from comment import COMMENT_MARKER, format_recommendation_comment


def test_comment_format_includes_version_and_override() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "MINOR",
            "confidence": "high",
            "reasoning": "Added an exported function in src/api.py.",
            "changelog": "feat: add exported helper",
        },
        notes=["Detected versioning scheme: semver."],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/api.py",
                "rule": "export_symbol_added",
                "action": "added",
                "target": "exported helper",
                "impact_scope": "public_api",
                "suggested_bump": "MINOR",
                "severity": "MINOR",
            }
        ],
        current_tag="v1.2.3",
        next_tag="v1.3.0",
        override_summary="🔁 Override applied via `bump:minor`: PATCH → MINOR",
        policy_effects=["docs_only_label=NO_BUMP (default)."],
        override_status="applied via `bump:minor`: PATCH → MINOR",
    )
    assert "Recommendation : 🟡 MINOR" in body
    assert "Next version   : v1.2.3 → v1.3.0" in body
    assert "Override      : applied via `bump:minor`: PATCH → MINOR" in body
    assert "Summary        : files affected: src/api.py; public=1, internal=0." in body
    assert (
        "Reasoning      : public API additive evidence detected without breaking removal." in body
    )
    assert "Why this bump :" not in body
    assert "Summary        : label=" not in body
    assert "Changelog      :" not in body
    assert "- src/api.py | rule=export_symbol_added | scope=public_api | suggested=MINOR" in body
    assert body.index("Next version   : v1.2.3 → v1.3.0") < body.index("<details>")
    assert "Policy effects:" in body
    assert "<summary>Details</summary>" in body
    assert COMMENT_MARKER in body


def test_comment_format_manual_review_omits_classification_fields() -> None:
    body = format_recommendation_comment(
        result={
            "status": "manual_review",
            "label": None,
            "confidence": None,
            "reasoning": "Automatic analysis failed. Please classify this PR manually.",
            "changelog": None,
        },
        notes=["Prompt pack version: v1.0.0."],
        mode="github-models",
        fallback_reason="HTTP 503",
        current_tag=None,
        next_tag=None,
        proof_obligations={
            "version": "proof_obligations_v1",
            "required": ["semantic_fact_present"],
            "satisfied": [],
            "missing": ["semantic_fact_present", "semantic_fact_transition_present"],
            "critical_missing": ["semantic_fact_present"],
        },
    )
    assert "Manual review required" in body
    assert "🤖 Bumpkin Manual Review Required" in body
    assert "🤖 Bumpkin Recommendation" not in body
    assert "Fallback reason: HTTP 503" in body
    assert "Proposed bump (court): n/a" in body
    assert "Final decision: manual review required." in body
    assert "Missing proof obligations:" in body
    assert "- semantic_fact_present" in body
    assert "Recommendation :" not in body
    assert "Confidence     :" not in body
    assert "Changelog      :" not in body
    assert "Summary        : files affected: none; public=0, internal=0." in body
    assert "Reasoning      : automatic classification unavailable; manual review required." in body
    assert "Next version   : not computed" in body
    assert body.index("Next version   : not computed") < body.index("<details>")
    assert COMMENT_MARKER in body


def test_comment_format_no_bump_shows_no_bump_label() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "NO_BUMP",
            "confidence": "high",
            "reasoning": "Only docs/config metadata changed and no runtime API files were impacted.",
            "changelog": "chore: no release required",
        },
        notes=["Only ignored files changed; defaulting to NO_BUMP recommendation."],
        mode="no-bump",
        explainability_rows=[
            {
                "path": ".github/workflows/ci.yml",
                "rule": "changed_file_path",
                "action": "modified",
                "target": "canary gate selector",
                "impact_scope": "non_runtime",
                "suggested_bump": "NO_BUMP",
                "severity": "NO_BUMP",
            }
        ],
        current_tag="v1.2.3",
        next_tag=None,
        policy_effects=["docs_only_label=NO_BUMP (default)."],
        override_status="none",
    )
    assert "Recommendation : ⚪ NO_BUMP" in body
    assert "Next version   : not computed (current=v1.2.3)" in body
    assert "Summary        : files affected: none; public=0, internal=0." in body
    assert "🤖 Bumpkin Recommendation" in body


def test_comment_format_semantic_fallback_title() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "MAJOR",
            "confidence": "medium",
            "reasoning": "Semantic fallback detected removed exported API symbols.",
            "changelog": "feat: remove exported api symbols",
        },
        notes=["Model analysis unavailable; used semantic fallback classifier."],
        mode="fallback-heuristic",
        explainability_rows=[
            {
                "path": "src/api.py",
                "rule": "export_symbol_removed",
                "action": "removed",
                "target": "legacy endpoint",
                "impact_scope": "public_api",
                "suggested_bump": "MAJOR",
                "severity": "MAJOR",
            }
        ],
        current_tag="0.5.0",
        next_tag="0.6.0",
    )
    assert "🤖 Bumpkin (semantic fallback)" in body
    assert "Recommendation : 🔴 MAJOR" in body


def test_comment_format_includes_findings_and_aggregation() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "MAJOR",
            "confidence": "medium",
            "reasoning": "Deterministic JS/TS exported API analysis produced findings.",
            "changelog": "feat: introduce breaking api changes",
        },
        notes=["Deterministic findings engine produced 2 finding(s)."],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/api.ts",
                "rule": "export_symbol_removed",
                "action": "removed",
                "target": "oldApi",
                "impact_scope": "public_api",
                "suggested_bump": "MAJOR",
                "severity": "MAJOR",
            }
        ],
        findings=[
            {
                "id": "export_symbol_removed:1",
                "severity": "MAJOR",
                "rule": "export_symbol_removed",
                "confidence": "high",
                "title": "Removed exported symbol(s): oldApi",
                "why": "Removing exported API symbols is a breaking public API change.",
                "evidence": [{"path": "src/api.ts", "snippet": "export function oldApi() {}"}],
                "suggested_bump": "MAJOR",
            }
        ],
        aggregation_trace="MAJOR findings present; selected MAJOR.",
    )
    assert "Aggregation   : MAJOR findings present; selected MAJOR." in body
    assert "Summary        : files affected: src/api.ts; public=1, internal=0." in body
    assert "Reasoning      : public API breaking evidence detected." in body
    assert "Findings:" in body
    assert "- src/api.ts | rule=export_symbol_removed | scope=public_api | suggested=MAJOR" in body
    assert "symbol=oldApi" in body


def test_comment_format_includes_exported_constant_symbol_in_findings() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "MINOR",
            "confidence": "high",
            "reasoning": "Deterministic Python exported API analysis produced findings.",
            "changelog": "feat: export default greeting constant",
        },
        notes=["Deterministic findings engine produced 1 finding(s)."],
        mode="github-models",
        findings=[
            {
                "id": "export_symbol_added:1",
                "severity": "MINOR",
                "rule": "export_symbol_added",
                "confidence": "high",
                "title": "Added exported symbol(s): DEFAULT_GREETING",
                "why": "Adding exported API symbols is a backward-compatible public API change.",
                "evidence": [
                    {
                        "path": "src/python_test/api.py",
                        "snippet": 'DEFAULT_GREETING = "Hello"',
                    }
                ],
                "suggested_bump": "MINOR",
                "impact_scope": "public_api",
            }
        ],
    )

    assert (
        "- src/python_test/api.py | rule=export_symbol_added | scope=public_api | suggested=MINOR"
        in body
    )
    assert "symbol=DEFAULT_GREETING" in body


def test_comment_format_includes_exported_constant_symbol_from_explainability_rows() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "MINOR",
            "confidence": "high",
            "reasoning": "Deterministic Python exported API analysis produced findings.",
            "changelog": "feat: export default greeting constant",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/python_test/api.py",
                "rule": "export_symbol_added",
                "action": "added",
                "target": "DEFAULT_GREETING",
                "impact_scope": "public_api",
                "suggested_bump": "MINOR",
                "severity": "MINOR",
            }
        ],
    )

    assert (
        "- src/python_test/api.py | rule=export_symbol_added | scope=public_api | suggested=MINOR"
        in body
    )
    assert "symbol=DEFAULT_GREETING" in body


def test_comment_format_includes_analysis_state_for_classified_result() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "MINOR",
            "confidence": "high",
            "reasoning": "Added exported API symbol.",
            "changelog": "feat: add exported api symbols",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/api.ts",
                "rule": "export_symbol_added",
                "action": "added",
                "target": "newApi",
                "impact_scope": "public_api",
                "suggested_bump": "MINOR",
                "severity": "MINOR",
            }
        ],
        analysis_state="authoritative",
        classification_source="deterministic-findings",
        override_status="none",
    )
    assert "Analysis state: authoritative (source=deterministic-findings)" in body


def test_comment_format_includes_failure_class_and_fallback_note() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Fallback classifier used.",
            "changelog": "fix: internal implementation update",
        },
        notes=[],
        mode="fallback-heuristic",
        explainability_rows=[
            {
                "path": "src/core.py",
                "rule": "changed_file_path",
                "action": "modified",
                "target": "retry flow",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            }
        ],
        fallback_reason="HTTP 429: Too many requests from primary model endpoint",
        analysis_state="degraded_fallback",
        classification_source="semantic-fallback",
        failure_category="rate_limited",
        override_status="none",
    )
    assert "Analysis state: degraded_fallback (source=semantic-fallback)" in body
    assert "Failure class : rate_limited" in body
    assert "Fallback note : HTTP 429:" in body
    assert "Summary        : files affected: none; public=0, internal=0." in body


def test_comment_format_truncates_long_findings_list() -> None:
    findings = [
        {
            "id": f"finding:{index}",
            "severity": "PATCH",
            "rule": "non_export_runtime_change",
            "confidence": "medium",
            "title": f"Finding {index}",
            "why": "Internal behavior change.",
            "evidence": [{"path": "src/a.ts", "snippet": "const a = 1;"}],
            "suggested_bump": "PATCH",
        }
        for index in range(10)
    ]
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "medium",
            "reasoning": "Internal runtime updates.",
            "changelog": "fix: internal updates",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/a.ts",
                "rule": "changed_file_path",
                "action": "modified",
                "target": f"Finding {index}",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            }
            for index in range(10)
        ],
        findings=findings,
        override_status="none",
    )
    assert "... and 2 more finding(s)" in body


def test_comment_format_summary_caps_file_locations_at_two_items() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Multiple internal deltas detected.",
            "changelog": "fix: internal runtime updates",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/a.py",
                "rule": "internal_runtime_delta",
                "action": "modified",
                "target": "a",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            },
            {
                "path": "src/b.py",
                "line_span": "10-14",
                "rule": "internal_runtime_delta",
                "action": "modified",
                "target": "b",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            },
            {
                "path": "src/c.py",
                "rule": "internal_runtime_delta",
                "action": "modified",
                "target": "c",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            },
        ],
        override_status="none",
    )
    assert (
        "Summary        : files affected: src/a.py, src/b.py:10-14, +1 more; public=0, internal=3."
        in body
    )


def test_comment_format_includes_boundary_and_decision_trace() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Boundary was unclear.",
            "changelog": "fix: internal bugfix under uncertain public-api boundary",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/boundary.py",
                "rule": "changed_file_path",
                "action": "modified",
                "target": "boundary handling",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            }
        ],
        boundary_summary={"public": 0, "internal": 1, "unknown": 2},
        decision_trace={"policy_actions": ["unknown_boundary -> confidence_low"]},
        override_status="none",
    )
    assert "Boundary      : public=0, internal=1, unknown=2" in body
    assert "Decision trace:" in body
    assert "- unknown_boundary -> confidence_low" in body


def test_comment_format_includes_evidence_refs_in_advisory_block() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Court selected PATCH because accepted evidence indicates internal implementation updates in core.py and court.py.",
            "changelog": "fix(orchestrator): update behavior across core.py and court.py",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "rule": "changed_file_path",
                "action": "modified",
                "target": "court evidence handling",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            }
        ],
        advisory_status="aligned",
        advisory_label="PATCH",
        advisory_confidence="low",
        advisory_summary="Court selected PATCH based on case-file evidence.",
        advisory_accepted_evidence_ids=["path_marker:1", "path_marker:2"],
        advisory_rejected_evidence_ids=["finding:f3"],
        override_status="none",
    )
    assert "evidence_refs=accepted[path_marker:1, path_marker:2] rejected[finding:f3]" in body
    assert "Summary        : files affected: none; public=0, internal=0." in body


def test_comment_format_filters_redundant_classified_notes_and_caps_output() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Internal implementation update.",
            "changelog": "fix(core): internal behavior update",
        },
        notes=[
            "Analysis state: authoritative (source=court).",
            "policy_mode=pragmatic; bugfix_patch_bias=true.",
            "policy_mode=pragmatic; bugfix_patch_bias=true.",
            "Planner route: full (reason=within_provider_budget, provider=openai-compatible).",
            "Evidence extraction produced 1 item(s).",
            "Compatibility court analyzed by model: gemini-2.5-flash.",
            "Prompt pack: generic-v0 (language_group=generic, promotion_status=experimental).",
            "Scope guard loaded 2 PR file(s) from GitHub API.",
            "No deterministic JS/TS exported API findings were produced.",
            "unknown_boundary_policy configured; no effect (label=PATCH).",
            "court_verdict confidence=low from accepted evidence.",
        ],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/core.py",
                "rule": "changed_file_path",
                "action": "modified",
                "target": "notes filtering",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            }
        ],
        classification_source="court",
        advisory_status="aligned",
        override_status="none",
    )
    assert "Analysis state: authoritative (source=court)." not in body
    assert "unknown_boundary_policy configured; no effect (label=PATCH)." not in body
    assert "court_verdict confidence=low from accepted evidence." not in body
    assert body.count("policy_mode=pragmatic; bugfix_patch_bias=true.") == 1
    assert "- ... and 1 more note(s)" in body


def test_comment_format_avoids_path_only_summary_for_pr42_style_rows() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Court selected PATCH based on strongest evidence.",
            "changelog": "fix: internal implementation update",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/bumpkin/contracts.py",
                "rule": "changed_file_path",
                "action": "modified",
                "target": "explainability_rows",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            },
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "rule": "changed_file_path",
                "action": "modified",
                "target": "file content",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            },
        ],
        override_status="none",
    )
    assert "Summary        : files affected: none; public=0, internal=0." in body
    assert "Summary        : src/bumpkin/contracts.py: modified explainability_rows" not in body


def test_comment_format_uses_explicit_before_after_for_patch_and_no_bump() -> None:
    patch_body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "medium",
            "reasoning": "Internal runtime update.",
            "changelog": "fix: internal runtime update",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/internal/cache.ts",
                "line_span": "42-57",
                "rule": "internal_runtime_delta",
                "action": "changed",
                "target": "buildCacheKey",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
                "before": "`${user.id}`",
                "after": "`${user.orgId}:${user.id}`",
                "impact_reason": "internal runtime behavior changed",
            }
        ],
        override_status="none",
    )
    assert (
        "Summary        : files affected: src/internal/cache.ts:42-57; public=0, internal=1."
        in patch_body
    )
    assert (
        "- src/internal/cache.ts:42-57 | rule=internal_runtime_delta | scope=runtime_internal | suggested=PATCH"
        in patch_body
    )
    assert (
        "Reasoning      : runtime-internal deltas detected; no public API evidence." in patch_body
    )

    no_bump_body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "NO_BUMP",
            "confidence": "high",
            "reasoning": "Operational-only updates.",
            "changelog": "chore: no release required",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "CHANGELOG.md",
                "rule": "runtime_contract_unchanged",
                "action": "unchanged",
                "target": "runtime contract",
                "impact_scope": "non_runtime",
                "suggested_bump": "NO_BUMP",
                "severity": "NO_BUMP",
                "before": "runtime contract unchanged",
                "after": "runtime contract unchanged",
                "impact_reason": "non-runtime-only changes",
            }
        ],
        override_status="none",
    )
    assert "Summary        : files affected: CHANGELOG.md; public=0, internal=0." in no_bump_body
    assert (
        "Reasoning      : non-runtime-only evidence detected; runtime/public impact not observed."
        in no_bump_body
    )
    assert "| transition=" not in no_bump_body
    assert "| symbol=" not in no_bump_body


def test_comment_format_prefers_concrete_target_label_over_generic_target() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Internal runtime update.",
            "changelog": "fix: improve cache key behavior",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/comment.py",
                "rule": "internal_runtime_delta",
                "action": "modified",
                "target": "internal runtime behavior",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
                "before": "const buildCacheKey = user.id",
                "after": "const buildCacheKey = `${user.orgId}:${user.id}`",
            }
        ],
        override_status="none",
    )
    assert "Summary        : files affected: src/comment.py; public=0, internal=1." in body
    assert (
        "- src/comment.py | rule=internal_runtime_delta | scope=runtime_internal | suggested=PATCH"
        in body
    )
    assert "transition=const buildCacheKey" not in body


def test_comment_format_omits_noisy_patch_transition_rows() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Internal runtime update.",
            "changelog": "fix: adjust transition rendering",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/comment.py",
                "rule": "internal_runtime_delta",
                "action": "modified",
                "target": "_normalize_semantic_target",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
                "before": "return _shorten(compact, limit=48)",
                "after": "GENERIC_TRANSITION_TEXTS = {",
            }
        ],
        override_status="none",
    )
    assert (
        "- src/comment.py | rule=internal_runtime_delta | scope=runtime_internal | suggested=PATCH"
        in body
    )
    assert "| transition=" not in body


def test_comment_format_keeps_state_like_patch_transitions() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Internal runtime update.",
            "changelog": "fix: add internal cache marker",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/cache.py",
                "rule": "internal_runtime_delta",
                "action": "added",
                "target": "cache marker",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            }
        ],
        override_status="none",
    )
    assert (
        "- src/cache.py | rule=internal_runtime_delta | scope=runtime_internal | suggested=PATCH"
        in body
    )
    assert "| transition=" not in body


def test_comment_format_maps_internal_target_wording_in_summary_and_findings() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Internal runtime update.",
            "changelog": "fix: runtime text comparison hardening",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/comment.py",
                "rule": "internal_runtime_delta",
                "action": "modified",
                "target": "`snippet normalization`",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            }
        ],
        override_status="none",
    )
    assert "Summary        : files affected: src/comment.py; public=0, internal=1." in body
    assert (
        "- src/comment.py | rule=internal_runtime_delta | scope=runtime_internal | suggested=PATCH"
        in body
    )
    assert "snippet normalization" not in body


def test_comment_format_disambiguates_compile_target_with_regex_context() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Internal runtime update.",
            "changelog": "fix: refine regex handling",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/comment.py",
                "rule": "internal_runtime_delta",
                "action": "modified",
                "target": "compile",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
                "after": 'TRANSITION_IMPORT_PATTERN = re.compile(r"^")',
            }
        ],
        override_status="none",
    )
    assert "Summary        : files affected: src/comment.py; public=0, internal=1." in body
    assert (
        "- src/comment.py | rule=internal_runtime_delta | scope=runtime_internal | suggested=PATCH"
        in body
    )


def test_comment_format_keeps_ambiguous_target_when_context_is_weak() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Internal runtime update.",
            "changelog": "fix: update helper internals",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/comment.py",
                "rule": "internal_runtime_delta",
                "action": "modified",
                "target": "update",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            }
        ],
        override_status="none",
    )
    assert "Summary        : files affected: src/comment.py; public=0, internal=1." in body
    assert (
        "- src/comment.py | rule=internal_runtime_delta | scope=runtime_internal | suggested=PATCH"
        in body
    )


def test_comment_format_omits_low_signal_extracted_symbol() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Internal runtime update.",
            "changelog": "fix: streamline findings rendering internals",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/comment.py",
                "rule": "internal_runtime_delta",
                "action": "modified",
                "target": "internal runtime behavior",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
                "after": "locations.append(location)",
            }
        ],
        override_status="none",
    )
    assert "Summary        : files affected: src/comment.py; public=0, internal=1." in body
    assert (
        "- src/comment.py | rule=internal_runtime_delta | scope=runtime_internal | suggested=PATCH"
        in body
    )
    assert "symbol=locations" not in body


def test_comment_format_includes_contradictions_in_details() -> None:
    body = format_recommendation_comment(
        result={
            "status": "classified",
            "label": "MAJOR",
            "confidence": "medium",
            "reasoning": "Public API break detected.",
            "changelog": "feat(api)!: remove legacy endpoint",
        },
        notes=[],
        mode="github-models",
        explainability_rows=[
            {
                "path": "src/api/public.ts",
                "rule": "export_symbol_removed",
                "action": "removed",
                "target": "legacyEndpoint",
                "impact_scope": "public_api",
                "suggested_bump": "MAJOR",
                "severity": "MAJOR",
            }
        ],
        contradictions=[
            {
                "code": "intent_fix_vs_public_change",
                "message": "PR intent suggests fix/patch, but semantic facts indicate public API changes.",
                "evidence_paths": ["src/api/public.ts"],
            }
        ],
        override_status="none",
    )
    assert "Contradictions:" in body
    assert "intent_fix_vs_public_change" in body
    assert "evidence=src/api/public.ts" in body
