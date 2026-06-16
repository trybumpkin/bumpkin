from bumpkin.analysis import explanation_facts as facts_module


def test_build_explanation_facts_patch_includes_scope_and_hint() -> None:
    facts = facts_module.build_explanation_facts(
        advisory_label="PATCH",
        records=[
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "rule": "changed_file_path",
                "snippet": "def _is_explanation_dsl_enabled() -> bool:",
            }
        ],
    )
    assert facts is not None
    assert facts.label == "PATCH"
    assert facts.scope == "orchestrator"
    assert facts.target_summary == "core.py"
    assert facts.operation_hint == "`_is_explanation_dsl_enabled`"


def test_build_explanation_facts_no_bump_supported() -> None:
    facts = facts_module.build_explanation_facts(
        advisory_label="NO_BUMP",
        records=[
            {"path": ".github/workflows/ci.yml", "rule": "changed_file_path", "snippet": "name: CI"}
        ],
    )
    assert facts is not None
    assert facts.label == "NO_BUMP"
    assert facts.target_summary == "ci.yml"


def test_build_explanation_facts_minor_supported() -> None:
    facts = facts_module.build_explanation_facts(
        advisory_label="MINOR",
        records=[
            {
                "path": "src/api/client.ts",
                "rule": "export_symbol_added",
                "snippet": "export function getUserProfile() {}",
            }
        ],
    )
    assert facts is not None
    assert facts.label == "MINOR"
    assert facts.operation_hint == "`getUserProfile`"


def test_build_explanation_facts_major_supported() -> None:
    facts = facts_module.build_explanation_facts(
        advisory_label="MAJOR",
        records=[
            {
                "path": "src/api/client.ts",
                "rule": "export_symbol_removed",
                "snippet": "export function removeLegacyClient() {}",
            }
        ],
    )
    assert facts is not None
    assert facts.label == "MAJOR"
    assert facts.operation_hint == "`removeLegacyClient`"


def test_change_hint_from_records_marks_regex_pattern() -> None:
    hint = facts_module.change_hint_from_records(
        [
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": r'r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"',
            }
        ]
    )
    assert hint == "`regex pattern`"


def test_change_hint_from_records_rewrites_low_signal_filter() -> None:
    hint = facts_module.change_hint_from_records(
        [
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "if symbol_name in LOW_SIGNAL_HINT_SYMBOLS:",
            }
        ]
    )
    assert hint == "`explanation quality filtering`"


def test_change_hint_from_records_uses_dependency_wiring_for_import_only() -> None:
    hint = facts_module.change_hint_from_records(
        [{"path": "src/bumpkin/orchestrator/core.py", "snippet": "import os"}]
    )
    assert hint == "`integration wiring`"


def test_change_hint_from_records_prefers_symbol_over_import_only() -> None:
    hint = facts_module.change_hint_from_records(
        [
            {"path": "src/bumpkin/orchestrator/core.py", "snippet": "import os"},
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "def _is_explanation_dsl_enabled() -> bool:",
            },
        ]
    )
    assert hint == "`_is_explanation_dsl_enabled`"


def test_change_hint_from_records_prefers_behavior_over_import_only() -> None:
    hint = facts_module.change_hint_from_records(
        [
            {"path": "src/bumpkin/orchestrator/core.py", "snippet": "from typing import Any"},
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "if symbol_name in LOW_SIGNAL_HINT_SYMBOLS:",
            },
        ]
    )
    assert hint == "`explanation quality filtering`"


def test_render_patch_from_facts_is_human_readable() -> None:
    facts = facts_module.ExplanationFacts(
        label="PATCH",
        target_summary="core.py and evidence.py",
        scope="orchestrator",
        operation_hint="`explanation quality filtering`",
        has_path_targets=True,
    )
    reasoning = facts_module.render_reasoning_from_facts(facts)
    changelog = facts_module.render_changelog_from_facts(facts)
    assert reasoning is not None and "LOW_SIGNAL_HINT_SYMBOLS" not in reasoning
    assert changelog is not None and changelog.startswith("fix(orchestrator):")
    assert facts_module.passes_quality_policy(reasoning)
    assert facts_module.passes_quality_policy(changelog)


def test_render_minor_from_facts_is_human_readable() -> None:
    facts = facts_module.ExplanationFacts(
        label="MINOR",
        target_summary="client.ts",
        scope="api",
        operation_hint="`getUserProfile`",
        has_path_targets=True,
    )
    reasoning = facts_module.render_reasoning_from_facts(facts)
    changelog = facts_module.render_changelog_from_facts(facts)
    assert reasoning is not None and reasoning.startswith("Court selected MINOR")
    assert changelog == "feat(api): add behavior across client.ts via `getUserProfile`"


def test_render_major_from_facts_is_human_readable() -> None:
    facts = facts_module.ExplanationFacts(
        label="MAJOR",
        target_summary="client.ts",
        scope="api",
        operation_hint="`removeLegacyClient`",
        has_path_targets=True,
    )
    reasoning = facts_module.render_reasoning_from_facts(facts)
    changelog = facts_module.render_changelog_from_facts(facts)
    assert reasoning is not None and reasoning.startswith("Court selected MAJOR")
    assert (
        changelog
        == "feat(api)!: introduce breaking behavior across client.ts via `removeLegacyClient`"
    )


def test_build_delta_rows_emits_deterministic_row_shape() -> None:
    rows = facts_module.build_delta_rows(
        advisory_label="PATCH",
        records=[
            {
                "evidence_id": "path_marker:1",
                "rule": "changed_file_path",
                "severity": "PATCH",
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "def _format_notes_block(notes: list[str]) -> str:",
            }
        ],
    )
    assert rows == [
        {
            "path": "src/bumpkin/orchestrator/core.py",
            "rule": "changed_file_path",
            "action": "modified",
            "target": "_format_notes_block",
            "impact_scope": "runtime_internal",
            "suggested_bump": "PATCH",
            "severity": "PATCH",
        }
    ]


def test_build_delta_rows_sorts_by_severity_then_path_then_rule_then_target() -> None:
    rows = facts_module.build_delta_rows(
        advisory_label="PATCH",
        records=[
            {
                "rule": "changed_file_path",
                "severity": "PATCH",
                "path": "src/z.py",
                "snippet": "def zed() -> None:",
            },
            {
                "rule": "export_symbol_removed",
                "severity": "MAJOR",
                "path": "src/a.py",
                "snippet": "export function oldApi() {}",
            },
        ],
    )
    assert rows[0]["severity"] == "MAJOR"
    assert rows[0]["path"] == "src/a.py"


def test_filter_semantic_delta_rows_drops_path_only_rules() -> None:
    rows = facts_module.filter_semantic_delta_rows(
        [
            {
                "path": "src/core.py",
                "rule": "changed_file_path",
                "action": "modified",
                "target": "core flow",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            },
            {
                "path": "src/api.ts",
                "rule": "export_symbol_added",
                "action": "added",
                "target": "getUserProfile",
                "impact_scope": "public_api",
                "suggested_bump": "MINOR",
                "severity": "MINOR",
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["rule"] == "export_symbol_added"


def test_build_delta_rows_preserves_explicit_before_after_fields() -> None:
    rows = facts_module.build_delta_rows(
        advisory_label="PATCH",
        records=[
            {
                "rule": "internal_runtime_delta",
                "severity": "PATCH",
                "path": "src/internal/cache.ts",
                "snippet": "buildCacheKey",
                "before": "`${user.id}`",
                "after": "`${user.orgId}:${user.id}`",
                "impact_reason": "internal runtime behavior changed",
            }
        ],
    )
    assert rows[0]["before"] == "`${user.id}`"
    assert rows[0]["after"] == "`${user.orgId}:${user.id}`"
    assert rows[0]["impact_reason"] == "internal runtime behavior changed"


def test_build_delta_rows_marks_runtime_contract_unchanged_as_unchanged_action() -> None:
    rows = facts_module.build_delta_rows(
        advisory_label="NO_BUMP",
        records=[
            {
                "rule": "runtime_contract_unchanged",
                "severity": "NO_BUMP",
                "path": "CHANGELOG.md",
                "snippet": "CHANGELOG.md",
                "before": "runtime contract unchanged",
                "after": "runtime contract unchanged",
            }
        ],
    )
    assert rows[0]["action"] == "unchanged"
