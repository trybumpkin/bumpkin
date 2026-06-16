from bumpkin.analysis import semantic_review as semantic_review_module


def test_evaluate_proof_obligations_requires_patch_transition() -> None:
    obligations = semantic_review_module.evaluate_proof_obligations(
        status="classified",
        evaluated_label="PATCH",
        semantic_facts=[
            {
                "path": "src/internal/cache.ts",
                "rule": "internal_runtime_delta",
                "action": "changed",
                "target": "buildCacheKey",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
                "before": "old",
                "after": "new",
            }
        ],
    )
    assert obligations["critical_missing"] == []
    assert "runtime_delta_transition_present" in obligations["satisfied"]


def test_evaluate_proof_obligations_accepts_internal_patch_side_effect_transition() -> None:
    obligations = semantic_review_module.evaluate_proof_obligations(
        status="classified",
        evaluated_label="PATCH",
        semantic_facts=[
            {
                "path": "src/bumpkin/app/recommendations.py",
                "rule": "added_external_side_effect",
                "action": "added",
                "target": "response",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
                "before": "",
                "after": "",
            }
        ],
    )
    assert obligations["critical_missing"] == []
    assert "runtime_delta_transition_present" in obligations["satisfied"]


def test_evaluate_proof_obligations_requires_no_bump_invariance() -> None:
    obligations = semantic_review_module.evaluate_proof_obligations(
        status="classified",
        evaluated_label="NO_BUMP",
        semantic_facts=[],
    )
    assert "runtime_invariance_fact_present" in obligations["missing"]
    assert "semantic_fact_present" in obligations["critical_missing"]


def test_critical_missing_proof_obligations_filters_non_empty_values() -> None:
    missing = semantic_review_module.critical_missing_proof_obligations(
        {
            "critical_missing": [
                "semantic_fact_present",
                "",
                "   ",
                None,
                "runtime_delta_transition_present",
            ]
        }
    )
    assert missing == ["semantic_fact_present", "runtime_delta_transition_present"]


def test_critical_missing_proof_obligations_handles_non_list() -> None:
    assert semantic_review_module.critical_missing_proof_obligations({}) == []
    assert (
        semantic_review_module.critical_missing_proof_obligations({"critical_missing": "x"}) == []
    )


def test_detect_contradictions_flags_fix_intent_vs_public_change() -> None:
    contradictions = semantic_review_module.detect_contradictions(
        event_labels=["bump:patch"],
        semantic_facts=[
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
        status="classified",
        final_label="MAJOR",
    )
    assert len(contradictions) == 1
    assert contradictions[0]["code"] == "intent_fix_vs_public_change"


def test_prioritize_semantic_facts_prefers_public_api_then_contradiction_paths() -> None:
    ordered = semantic_review_module.prioritize_semantic_facts(
        [
            {
                "path": "src/internal/cache.ts",
                "rule": "internal_runtime_delta",
                "action": "changed",
                "target": "cache",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            },
            {
                "path": "src/api/public.ts",
                "rule": "export_symbol_added",
                "action": "added",
                "target": "newApi",
                "impact_scope": "public_api",
                "suggested_bump": "MINOR",
                "severity": "MINOR",
            },
            {
                "path": "src/boundary.py",
                "rule": "boundary_contract_change",
                "action": "changed",
                "target": "boundary",
                "impact_scope": "runtime_internal",
                "suggested_bump": "MINOR",
                "severity": "MINOR",
            },
        ],
        contradiction_paths={"src/boundary.py"},
    )
    assert ordered[0]["path"] == "src/api/public.ts"
    assert ordered[1]["path"] == "src/boundary.py"


def test_build_reasoning_trace_includes_semantic_policy_and_contradiction_claims() -> None:
    trace = semantic_review_module.build_reasoning_trace(
        semantic_facts=[
            {
                "path": "src/api/public.ts",
                "line_span": "L1-L2",
                "rule": "export_symbol_removed",
                "action": "removed",
                "target": "legacyEndpoint",
                "impact_scope": "public_api",
                "suggested_bump": "MAJOR",
                "severity": "MAJOR",
                "before": "present",
                "after": "removed",
            }
        ],
        policy_effects=["docs_only_label=NO_BUMP (default)."],
        contradictions=[
            {
                "code": "intent_fix_vs_public_change",
                "message": "Intent mismatch.",
                "evidence_paths": ["src/api/public.ts"],
            }
        ],
        final_label="MAJOR",
    )
    assert len(trace) == 3
    assert trace[0]["claim_id"] == "semantic:1"
    assert trace[1]["claim_id"] == "policy:1"
    assert trace[2]["claim_id"] == "contradiction:1"
