from __future__ import annotations

import os
from argparse import Namespace
from types import SimpleNamespace
from typing import Any

from bumpkin.orchestrator import pipeline as orchestrator_pipeline


def test_pipeline_run_stays_quiet_in_capture_mode(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token-123")
    monkeypatch.setenv("BUMPKIN_CAPTURE_PR_COMMENT_ONLY", "1")

    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.orchestrator_scope.read_event_context",
        lambda _path: SimpleNamespace(pr_number=68, labels=[]),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.orchestrator_scope.select_diff_scope",
        lambda _from_ref, _to_ref, _event_context: ("base", "head", []),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.resolve_refs",
        lambda _from_ref, _to_ref: ("base", "head", []),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.orchestrator_scope.fetch_pr_changed_files",
        lambda **_kwargs: (["src/api.ts"], None),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.load_bumpkin_config",
        orchestrator_pipeline._fallback_config,
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.build_diff",
        lambda **_kwargs: SimpleNamespace(
            notes=[],
            analyzed_files=["src/api.ts"],
            approx_prompt_tokens=128,
            changed_files_total=1,
            scope_overlap_files=1,
            scope_unexpected_files=0,
            scope_missing_files=0,
        ),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.orchestrator_scope.evaluate_scope_mismatch",
        lambda **_kwargs: (False, None),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.resolve_models_token", lambda endpoint: "token"
    )
    monkeypatch.setattr("bumpkin.orchestrator.pipeline.detect_language_groups", lambda _files: [])
    monkeypatch.setattr("bumpkin.orchestrator.pipeline.detect_language_hints", lambda _files: [])
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.get_prompt_metadata",
        lambda **_kwargs: SimpleNamespace(promotion_status="promoted"),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.plan_analysis_route",
        lambda **_kwargs: SimpleNamespace(
            route="full",
            reason="ok",
            provider_profile=SimpleNamespace(provider="test"),
        ),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.orchestrator_core.analyze_diff_core",
        lambda **_kwargs: SimpleNamespace(
            output={"status": "classified", "label": "PATCH", "confidence": "high"},
            result={"status": "classified", "label": "PATCH", "confidence": "high"},
            notes=[],
            mode_used="github-models",
            fallback_reason=None,
            current_tag="v1.2.3",
            next_tag="v1.2.4",
            override_summary=None,
            findings=[],
            explainability_rows=[],
            aggregation_trace=None,
            boundary_summary=None,
            decision_trace={},
            analysis_state=None,
            classification_source=None,
            failure_category=None,
            policy_effects=[],
            override_status=None,
            court_advisory={},
            court_fallback_reason=None,
            proof_obligations={},
            contradictions=[],
        ),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.validate_output_contract", lambda _output: []
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.format_recommendation_comment",
        lambda **_kwargs: "<!-- bumpkin:recommendation -->\nbody\n",
    )
    monkeypatch.setattr("bumpkin.orchestrator.pipeline.post_pr_comment", lambda **_kwargs: None)

    exit_code = orchestrator_pipeline.run(
        Namespace(
            from_ref="",
            to_ref="",
            token_cap=6000,
            use_difftastic="",
            mode="github-models",
            model="gpt-5-mini",
            fallback_model="",
            models_endpoint="https://example.com/v1",
            max_retries=1,
            request_timeout=45,
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert os.environ.get("BUMPKIN_CAPTURE_PR_COMMENT_ONLY") == "1"


def test_pipeline_does_not_call_python_pack_generic_fallback(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token-123")
    monkeypatch.setenv("BUMPKIN_CAPTURE_PR_COMMENT_ONLY", "1")

    captured_notes: list[str] = []

    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.orchestrator_scope.read_event_context",
        lambda _path: SimpleNamespace(pr_number=68, labels=[]),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.orchestrator_scope.select_diff_scope",
        lambda _from_ref, _to_ref, _event_context: ("base", "head", []),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.resolve_refs",
        lambda _from_ref, _to_ref: ("base", "head", []),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.orchestrator_scope.fetch_pr_changed_files",
        lambda **_kwargs: (["pkg/api.py"], None),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.load_bumpkin_config",
        orchestrator_pipeline._fallback_config,
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.build_diff",
        lambda **_kwargs: SimpleNamespace(
            notes=[],
            analyzed_files=["pkg/api.py"],
            approx_prompt_tokens=128,
            changed_files_total=1,
            scope_overlap_files=1,
            scope_unexpected_files=0,
            scope_missing_files=0,
        ),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.orchestrator_scope.evaluate_scope_mismatch",
        lambda **_kwargs: (False, None),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.resolve_models_token", lambda endpoint: "token"
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.detect_language_groups", lambda _files: ["python"]
    )
    monkeypatch.setattr("bumpkin.orchestrator.pipeline.detect_language_hints", lambda _files: [])
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.get_prompt_metadata",
        lambda **_kwargs: SimpleNamespace(language_group="python", promotion_status="experimental"),
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.plan_analysis_route",
        lambda **_kwargs: SimpleNamespace(
            route="full",
            reason="ok",
            provider_profile=SimpleNamespace(provider="test"),
        ),
    )

    def _analyze_diff_core(**kwargs: Any) -> SimpleNamespace:
        captured_notes.extend(kwargs["notes"])
        return SimpleNamespace(
            output={"status": "classified", "label": "PATCH", "confidence": "high"},
            result={"status": "classified", "label": "PATCH", "confidence": "high"},
            notes=kwargs["notes"],
            mode_used="github-models",
            fallback_reason=None,
            current_tag="v1.2.3",
            next_tag="v1.2.4",
            override_summary=None,
            findings=[],
            explainability_rows=[],
            aggregation_trace=None,
            boundary_summary=None,
            decision_trace={},
            analysis_state=None,
            classification_source=None,
            failure_category=None,
            policy_effects=[],
            override_status=None,
            court_advisory={},
            court_fallback_reason=None,
            proof_obligations={},
            contradictions=[],
        )

    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.orchestrator_core.analyze_diff_core",
        _analyze_diff_core,
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.validate_output_contract", lambda _output: []
    )
    monkeypatch.setattr(
        "bumpkin.orchestrator.pipeline.format_recommendation_comment",
        lambda **_kwargs: "<!-- bumpkin:recommendation -->\nbody\n",
    )
    monkeypatch.setattr("bumpkin.orchestrator.pipeline.post_pr_comment", lambda **_kwargs: None)

    exit_code = orchestrator_pipeline.run(
        Namespace(
            from_ref="",
            to_ref="",
            token_cap=6000,
            use_difftastic="",
            mode="github-models",
            model="gpt-5-mini",
            fallback_model="",
            models_endpoint="https://example.com/v1",
            max_retries=1,
            request_timeout=45,
        )
    )

    assert exit_code == 0
    assert not any("experimental generic prompt pack" in note for note in captured_notes)
