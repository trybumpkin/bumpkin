from typing import Self

from bumpkin.analysis.diffing import DiffResult
from bumpkin.orchestrator import core as core_module


def test_workspace_loader_for_diff_result_skips_synthetic_eval_diffs() -> None:
    diff_result = DiffResult(
        from_ref="fixture/base",
        to_ref="fixture/head",
        repo_root=None,
        diff_text="diff --git a/pkg/api.py b/pkg/api.py\n",
        full_diff_text="diff --git a/pkg/api.py b/pkg/api.py\n",
        truncated=False,
        analyzed_files=["pkg/api.py"],
        file_units=[],
        changed_files_total=1,
        ignored_files_total=0,
        approx_prompt_tokens=1,
        approx_full_tokens=1,
        capped_files=0,
        scope_allowlist_files_total=0,
        scope_overlap_files=0,
        scope_unexpected_files=0,
        scope_missing_files=0,
        notes=[],
    )

    assert core_module._workspace_loader_for_diff_result(diff_result) is None


def test_should_skip_court_for_high_confidence_minor() -> None:
    should_skip, reason = core_module._should_skip_court_advisory(
        status="classified",
        deterministic_label="MINOR",
        deterministic_confidence="high",
        mode_used="deterministic-findings",
        classification_source="hybrid",
    )

    assert should_skip is True
    assert reason == "deterministic_high_confidence_minor"


def test_should_not_skip_court_for_medium_confidence_minor() -> None:
    should_skip, reason = core_module._should_skip_court_advisory(
        status="classified",
        deterministic_label="MINOR",
        deterministic_confidence="medium",
        mode_used="deterministic-findings",
        classification_source="hybrid",
    )

    assert should_skip is False
    assert reason is None


def test_should_not_skip_court_for_medium_confidence_patch() -> None:
    should_skip, reason = core_module._should_skip_court_advisory(
        status="classified",
        deterministic_label="PATCH",
        deterministic_confidence="medium",
        mode_used="deterministic-heuristic",
        classification_source="deterministic-heuristic",
    )

    assert should_skip is False
    assert reason is None


def test_should_skip_court_for_high_confidence_patch() -> None:
    should_skip, reason = core_module._should_skip_court_advisory(
        status="classified",
        deterministic_label="PATCH",
        deterministic_confidence="high",
        mode_used="deterministic-heuristic",
        classification_source="deterministic-heuristic",
    )

    assert should_skip is True
    assert reason == "deterministic_high_confidence_patch"


def test_should_not_skip_court_on_degraded_path() -> None:
    should_skip, reason = core_module._should_skip_court_advisory(
        status="classified",
        deterministic_label="MINOR",
        deterministic_confidence="high",
        mode_used="fallback-heuristic",
        classification_source="degraded-provider",
    )

    assert should_skip is False
    assert reason is None


def test_select_court_reasoning_prefers_deterministic_on_generic_summary() -> None:
    reasoning, used_deterministic = core_module._select_court_reasoning(
        court_advisory={
            "confidence": "low",
            "judge_summary": "Court selected PATCH based on the strongest evidence in the case file.",
        },
        advisory_label="PATCH",
        pre_court_result={
            "status": "classified",
            "label": "PATCH",
            "reasoning": "Specific deterministic reason from exported symbol and behavior analysis.",
            "changelog": "fix(core): preserve compatibility in court fallback parser",
        },
    )
    assert used_deterministic is True
    assert reasoning.startswith("Specific deterministic reason")


def test_select_court_changelog_prefers_deterministic_when_labels_match() -> None:
    changelog, used_deterministic = core_module._select_court_changelog(
        advisory_label="PATCH",
        court_advisory={
            "confidence": "low",
            "judge_summary": "Court selected PATCH based on the strongest evidence in the case file.",
        },
        pre_court_result={
            "status": "classified",
            "label": "PATCH",
            "reasoning": "Specific deterministic reason.",
            "changelog": "fix(court): improve malformed response recovery",
        },
    )
    assert used_deterministic is True
    assert changelog == "fix(court): improve malformed response recovery"


def test_select_court_changelog_keeps_label_mapping_when_labels_differ() -> None:
    changelog, used_deterministic = core_module._select_court_changelog(
        advisory_label="MINOR",
        court_advisory={
            "confidence": "low",
            "judge_summary": "Court selected MINOR based on the strongest evidence in the case file.",
        },
        pre_court_result={
            "status": "classified",
            "label": "PATCH",
            "reasoning": "Specific deterministic reason.",
            "changelog": "fix(court): improve malformed response recovery",
        },
    )
    assert used_deterministic is False
    assert changelog == "feat: add backward-compatible api changes"


def test_render_evidence_grounded_reasoning_uses_accepted_evidence_ids() -> None:
    reasoning, used = core_module._render_evidence_grounded_reasoning(
        advisory_label="PATCH",
        court_advisory={"accepted_evidence_ids": ["finding:f1"]},
        evidence_lookup={
            "finding:f1": {
                "evidence_id": "finding:f1",
                "rule": "internal_change",
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "if value:",
            }
        },
    )
    assert used is True
    assert reasoning is not None
    assert "path_marker:" not in reasoning
    assert "finding:f1" not in reasoning
    assert "core.py" in reasoning


def test_render_evidence_grounded_reasoning_uses_major_label_template() -> None:
    reasoning, used = core_module._render_evidence_grounded_reasoning(
        advisory_label="MAJOR",
        court_advisory={"accepted_evidence_ids": ["finding:f1"]},
        evidence_lookup={
            "finding:f1": {
                "evidence_id": "finding:f1",
                "rule": "export_symbol_removed",
                "path": "src/api/client.ts",
                "snippet": "export function removeLegacyClient() {}",
            }
        },
    )
    assert used is True
    assert reasoning is not None
    assert reasoning.startswith("Court selected MAJOR")
    assert "`removeLegacyClient`" in reasoning


def test_render_evidence_grounded_changelog_uses_file_context() -> None:
    changelog, used = core_module._render_evidence_grounded_changelog(
        advisory_label="PATCH",
        court_advisory={"accepted_evidence_ids": ["behavior_marker:2"]},
        evidence_lookup={
            "behavior_marker:2": {
                "evidence_id": "behavior_marker:2",
                "rule": "added_external_side_effect",
                "path": "src/services/billing/processor.py",
                "snippet": "fetch(url)",
            }
        },
    )
    assert used is True
    assert changelog is not None
    assert changelog.startswith("fix(billing): update behavior across processor.py")
    assert "fetch(url)" in changelog


def test_render_evidence_grounded_changelog_uses_minor_label_template() -> None:
    changelog, used = core_module._render_evidence_grounded_changelog(
        advisory_label="MINOR",
        court_advisory={"accepted_evidence_ids": ["finding:f1"]},
        evidence_lookup={
            "finding:f1": {
                "evidence_id": "finding:f1",
                "rule": "export_symbol_added",
                "path": "src/api/client.ts",
                "snippet": "export function getUserProfile() {}",
            }
        },
    )
    assert used is True
    assert changelog == "feat(api): add behavior across client.ts via `getUserProfile`"


def test_render_evidence_grounded_reasoning_falls_back_without_accepted_ids() -> None:
    reasoning, used = core_module._render_evidence_grounded_reasoning(
        advisory_label="PATCH",
        court_advisory={},
        evidence_lookup={
            "path_marker:1": {
                "evidence_id": "path_marker:1",
                "rule": "changed_file_path",
                "path": "src/bumpkin/orchestrator/court.py",
                "snippet": "src/bumpkin/orchestrator/court.py",
            }
        },
    )
    assert used is True
    assert reasoning is not None
    assert "path_marker:1" not in reasoning
    assert "changed_file_path" not in reasoning
    assert "court.py" in reasoning


def test_render_evidence_grounded_reasoning_includes_symbol_hint_from_snippet() -> None:
    reasoning, used = core_module._render_evidence_grounded_reasoning(
        advisory_label="PATCH",
        court_advisory={"accepted_evidence_ids": ["path_marker:1"]},
        evidence_lookup={
            "path_marker:1": {
                "evidence_id": "path_marker:1",
                "rule": "changed_file_path",
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "def _is_template_reasoning(text: str) -> bool:",
            }
        },
    )
    assert used is True
    assert reasoning is not None
    assert "`_is_template_reasoning`" in reasoning
    assert "core.py" in reasoning


def test_render_evidence_grounded_changelog_falls_back_without_accepted_ids() -> None:
    changelog, used = core_module._render_evidence_grounded_changelog(
        advisory_label="PATCH",
        court_advisory={},
        evidence_lookup={
            "path_marker:1": {
                "evidence_id": "path_marker:1",
                "rule": "changed_file_path",
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "src/bumpkin/orchestrator/core.py",
            },
            "path_marker:2": {
                "evidence_id": "path_marker:2",
                "rule": "changed_file_path",
                "path": "src/bumpkin/orchestrator/court.py",
                "snippet": "src/bumpkin/orchestrator/court.py",
            },
        },
    )
    assert used is True
    assert changelog == "fix(orchestrator): update behavior across core.py and court.py"


def test_render_evidence_grounded_changelog_includes_symbol_hint_from_snippet() -> None:
    changelog, used = core_module._render_evidence_grounded_changelog(
        advisory_label="PATCH",
        court_advisory={"accepted_evidence_ids": ["path_marker:1"]},
        evidence_lookup={
            "path_marker:1": {
                "evidence_id": "path_marker:1",
                "rule": "changed_file_path",
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "def _is_template_reasoning(text: str) -> bool:",
            }
        },
    )
    assert used is True
    assert changelog is not None
    assert changelog.startswith("fix(orchestrator): update behavior across core.py")
    assert "`_is_template_reasoning`" in changelog


def test_extract_symbol_hint_handles_python_typed_assignment() -> None:
    hint = core_module._extract_symbol_hint("first_change_snippet_by_path: dict[str, str] = {}")
    assert hint == "`first_change_snippet_by_path`"


def test_change_hint_from_records_prefers_typed_assignment_symbol() -> None:
    hint = core_module._change_hint_from_records(
        [
            {
                "path": "src/bumpkin/analysis/evidence.py",
                "snippet": "first_change_snippet_by_path: dict[str, str] = {}",
            }
        ]
    )
    assert hint == "`first_change_snippet_by_path`"


def test_change_hint_from_records_rewrites_low_signal_symbol_to_operation_hint() -> None:
    hint = core_module._change_hint_from_records(
        [
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "normalized_snippet = snippet.lower()",
            }
        ]
    )
    assert hint == "`text comparison hardening`"


def test_change_hint_from_records_rewrites_constant_filter_to_intent_hint() -> None:
    hint = core_module._change_hint_from_records(
        [
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "if symbol_name in LOW_SIGNAL_HINT_SYMBOLS:",
            }
        ]
    )
    assert hint == "`explanation quality filtering`"


def test_change_hint_from_records_import_only_uses_dependency_wiring() -> None:
    hint = core_module._change_hint_from_records(
        [
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "import os",
            }
        ]
    )
    assert hint == "`integration wiring`"


def test_change_hint_from_records_prefers_symbol_over_import_only() -> None:
    hint = core_module._change_hint_from_records(
        [
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "import os",
            },
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "def _is_explanation_dsl_enabled() -> bool:",
            },
        ]
    )
    assert hint == "`_is_explanation_dsl_enabled`"


def test_change_hint_from_records_redacts_regex_literal_to_label() -> None:
    hint = core_module._change_hint_from_records(
        [
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": r'r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[^=]+\s*=",',
            }
        ]
    )
    assert hint == "`regex pattern`"


def test_should_run_explanation_polish_for_low_quality_text() -> None:
    should = core_module._should_run_explanation_polish(
        reasoning="Court selected PATCH because accepted evidence indicates internal implementation updates in core.py and 2 more file(s).",
        changelog="fix(core): update behavior across core.py and 2 more file(s)",
        confidence="low",
        token="token",
    )
    assert should is True


def test_should_skip_explanation_polish_for_high_quality_text() -> None:
    should = core_module._should_run_explanation_polish(
        reasoning=(
            "Court selected PATCH because accepted evidence indicates internal implementation updates "
            "in core.py and pipeline.py without any public API impact."
        ),
        changelog="fix(orchestrator): update behavior across core.py and pipeline.py",
        confidence="medium",
        token="token",
    )
    assert should is False


def test_should_run_explanation_polish_for_low_confidence_template_text() -> None:
    should = core_module._should_run_explanation_polish(
        reasoning="Court selected PATCH because accepted evidence indicates internal implementation updates in core.py.",
        changelog="fix(orchestrator): update behavior across core.py",
        confidence="low",
        token="token",
    )
    assert should is True


def test_uses_accepted_evidence_ids_detects_valid_references() -> None:
    used = core_module._uses_accepted_evidence_ids(
        court_advisory={"accepted_evidence_ids": ["finding:f1", "missing:id"]},
        evidence_lookup={
            "finding:f1": {
                "evidence_id": "finding:f1",
                "rule": "internal_change",
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "if value:",
            }
        },
    )
    assert used is True


def test_build_explainability_rows_uses_deterministic_delta_rows() -> None:
    rows = core_module._build_explainability_rows(
        advisory_label="PATCH",
        court_advisory={"accepted_evidence_ids": ["path_marker:1"]},
        evidence_lookup={
            "path_marker:1": {
                "evidence_id": "path_marker:1",
                "rule": "changed_file_path",
                "severity": "PATCH",
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "def _format_notes_block(notes: list[str]) -> str:",
            }
        },
        analyzed_files=["src/bumpkin/orchestrator/core.py"],
        diff_text="diff --git a/src/bumpkin/orchestrator/core.py b/src/bumpkin/orchestrator/core.py\n+def _format_notes_block(notes: list[str]) -> str:\n",
    )
    assert len(rows) == 1
    assert rows[0]["path"] == "src/bumpkin/orchestrator/core.py"
    assert rows[0]["rule"] == "internal_runtime_delta"
    assert rows[0]["action"] == "changed"
    assert rows[0]["target"] == "_format_notes_block"
    assert rows[0]["before"] == "previous behavior"
    assert rows[0]["after"] == "def _format_notes_block(notes: list[str]) -> str:"


def test_build_explainability_rows_returns_empty_without_records() -> None:
    rows = core_module._build_explainability_rows(
        advisory_label="PATCH",
        court_advisory={},
        evidence_lookup={},
        analyzed_files=[],
        diff_text="",
    )
    assert rows == []


def test_build_explainability_rows_builds_patch_fallback_from_runtime_delta() -> None:
    rows = core_module._build_explainability_rows(
        advisory_label="PATCH",
        court_advisory={},
        evidence_lookup={},
        analyzed_files=["src/internal/cache.ts"],
        diff_text=(
            "diff --git a/src/internal/cache.ts b/src/internal/cache.ts\n"
            "--- a/src/internal/cache.ts\n"
            "+++ b/src/internal/cache.ts\n"
            "@@ -42,1 +42,1 @@\n"
            "-const buildCacheKey = (user) => `${user.id}`;\n"
            "+const buildCacheKey = (user) => `${user.orgId}:${user.id}`;\n"
        ),
    )
    assert rows[0]["rule"] == "internal_runtime_delta"
    assert rows[0]["line_span"] == "42"
    assert rows[0]["before"].startswith("const buildCacheKey")
    assert rows[0]["after"].startswith("const buildCacheKey")


def test_build_explainability_rows_builds_no_bump_invariance_for_non_runtime_files() -> None:
    rows = core_module._build_explainability_rows(
        advisory_label="NO_BUMP",
        court_advisory={},
        evidence_lookup={},
        analyzed_files=["CHANGELOG.md", ".github/workflows/ci.yml"],
        diff_text="",
    )
    assert rows
    assert rows[0]["rule"] == "runtime_contract_unchanged"
    assert rows[0]["before"] == "runtime contract unchanged"
    assert rows[0]["after"] == "runtime contract unchanged"


def test_validate_polish_payload_accepts_humanized_text_with_anchor() -> None:
    reasoning, changelog = core_module._validate_polish_payload(
        {
            "reasoning": (
                "Court selected PATCH because accepted evidence indicates internal implementation "
                "updates in core.py and pipeline.py."
            ),
            "changelog": "fix(orchestrator): update behavior across core.py and pipeline.py",
        },
        file_anchors={"core.py", "pipeline.py"},
    )
    assert "core.py" in reasoning
    assert changelog.startswith("fix(")


def test_extract_polish_payload_recovers_plaintext_fields() -> None:
    payload = core_module._extract_polish_payload(
        "Reasoning: Court selected PATCH because internal updates affected core.py.\n"
        "Changelog: fix(orchestrator): update behavior across core.py\n"
    )
    assert "core.py" in payload["reasoning"]
    assert payload["changelog"].startswith("fix(")


def test_extract_polish_payload_recovers_inline_changelog_without_labels() -> None:
    payload = core_module._extract_polish_payload(
        "Court selected PATCH because internal implementation updates affected core.py. "
        "fix(orchestrator): update behavior across core.py"
    )
    assert "core.py" in payload["reasoning"]
    assert payload["changelog"] == "fix(orchestrator): update behavior across core.py"


def test_summarize_path_targets_dedupes_repeated_filenames() -> None:
    summary = core_module._summarize_path_targets(
        [
            "src/bumpkin/orchestrator/core.py",
            "src/bumpkin/orchestrator/core.py",
            "src/bumpkin/orchestrator/pipeline.py",
        ]
    )
    assert summary == "core.py and pipeline.py"


def test_passes_explicitness_gate_requires_two_anchors_when_two_files_present() -> None:
    passed, reason = core_module._passes_explicitness_gate(
        reasoning="Court selected PATCH because internal logic was updated in core.py and pipeline.py.",
        changelog="fix(orchestrator): update internal logic in core.py and pipeline.py",
        advisory_label="PATCH",
        records=[
            {"path": "src/bumpkin/orchestrator/core.py", "rule": "changed_file_path"},
            {
                "path": "src/bumpkin/orchestrator/pipeline.py",
                "rule": "changed_file_path",
            },
        ],
    )
    assert passed is True
    assert reason is None


def test_passes_explicitness_gate_fails_when_missing_required_anchors() -> None:
    passed, reason = core_module._passes_explicitness_gate(
        reasoning="Court selected PATCH because internal logic was updated in core.py.",
        changelog="fix(orchestrator): update internal logic in core.py",
        advisory_label="PATCH",
        records=[
            {"path": "src/bumpkin/orchestrator/core.py", "rule": "changed_file_path"},
            {
                "path": "src/bumpkin/orchestrator/pipeline.py",
                "rule": "changed_file_path",
            },
        ],
    )
    assert passed is False
    assert reason is not None and reason.startswith("insufficient_file_anchors")


def test_passes_explicitness_gate_rejects_template_reasoning() -> None:
    passed, reason = core_module._passes_explicitness_gate(
        reasoning=(
            "Court selected PATCH because accepted evidence indicates internal implementation "
            "updates in core.py and pipeline.py."
        ),
        changelog="fix(orchestrator): update internal logic in core.py and pipeline.py",
        advisory_label="PATCH",
        records=[
            {"path": "src/bumpkin/orchestrator/core.py", "rule": "changed_file_path"},
            {
                "path": "src/bumpkin/orchestrator/pipeline.py",
                "rule": "changed_file_path",
            },
        ],
    )
    assert passed is False
    assert reason == "generic_template_reasoning"


def test_merge_anchor_records_appends_missing_fallback_paths() -> None:
    records = [
        {"path": "src/bumpkin/orchestrator/core.py", "rule": "changed_file_path"},
    ]
    merged = core_module._merge_anchor_records(
        records,
        ["src/bumpkin/orchestrator/core.py", "src/bumpkin/orchestrator/pipeline.py"],
    )
    paths = [str(item.get("path", "")) for item in merged]
    assert paths == [
        "src/bumpkin/orchestrator/core.py",
        "src/bumpkin/orchestrator/pipeline.py",
    ]


def test_enforce_explicit_explanation_regenerates_when_text_is_generic() -> None:
    reasoning, changelog, regenerated = core_module._enforce_explicit_explanation(
        advisory_label="PATCH",
        reasoning="Court selected PATCH based on evidence.",
        changelog="fix: internal update",
        records=[
            {"path": "src/bumpkin/orchestrator/core.py", "rule": "changed_file_path"},
            {
                "path": "src/bumpkin/orchestrator/pipeline.py",
                "rule": "changed_file_path",
            },
        ],
    )
    assert regenerated is True
    assert "core.py" in reasoning and "pipeline.py" in reasoning
    assert changelog.startswith("fix(")


def test_enforce_explicit_explanation_uses_fallback_paths_when_records_empty() -> None:
    reasoning, changelog, regenerated = core_module._enforce_explicit_explanation(
        advisory_label="PATCH",
        reasoning="Court selected PATCH based on evidence.",
        changelog="fix: internal update",
        records=[],
        fallback_paths=[
            "src/bumpkin/orchestrator/core.py",
            "src/bumpkin/orchestrator/pipeline.py",
        ],
    )
    assert regenerated is True
    assert "core.py" in reasoning and "pipeline.py" in reasoning
    assert changelog.startswith("fix(")


def test_enforce_explicit_explanation_uses_diff_context_anchor_when_paths_unavailable() -> None:
    reasoning, changelog, regenerated = core_module._enforce_explicit_explanation(
        advisory_label="PATCH",
        reasoning="Court selected PATCH based on evidence.",
        changelog="fix: internal update",
        records=[],
    )
    assert regenerated is True
    assert "diff context" in reasoning
    assert "diff context" in changelog
    assert changelog.startswith("fix(")


def test_polish_explanation_attempts_repair_on_non_json_output(monkeypatch) -> None:
    class _FakeResponse:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"Could not provide valid JSON for this request."}}]}'

    called = {"repair": False}

    def _fake_repair(**_: object) -> tuple[str, str]:
        called["repair"] = True
        return (
            "Court selected PATCH because internal implementation updates affected core.py.",
            "fix(orchestrator): update behavior across core.py",
        )

    monkeypatch.setattr(
        core_module.explanation_polish.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse(),
    )
    monkeypatch.setattr(core_module.explanation_polish, "_attempt_polish_repair", _fake_repair)
    monkeypatch.setattr(core_module.explanation_polish, "apply_model_call_interval", lambda: None)

    reasoning, changelog, applied, error = core_module._polish_explanation_with_model(
        advisory_label="PATCH",
        draft_reasoning="Court selected PATCH because accepted evidence indicates internal implementation updates in core.py.",
        draft_changelog="fix(orchestrator): update behavior across core.py",
        records=[
            {
                "evidence_id": "path_marker:1",
                "rule": "changed_file_path",
                "path": "src/bumpkin/orchestrator/core.py",
                "snippet": "src/bumpkin/orchestrator/core.py",
            }
        ],
        token="token",
        endpoint="https://models.inference.ai.azure.com/chat/completions",
        model="openai/gpt-5-mini",
        max_retries=1,
        request_timeout=5,
    )
    assert called["repair"] is True
    assert applied is True
    assert error is None
    assert "core.py" in reasoning
    assert changelog.startswith("fix(")


