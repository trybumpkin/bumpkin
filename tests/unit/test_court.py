import json
from typing import Self

import pytest

from bumpkin.orchestrator import court as court_module


def test_extract_json_payload_handles_prose_wrapped_json() -> None:
    payload = court_module._extract_json_payload(
        "Court verdict follows.\n"
        '{"label":"PATCH","confidence":"high","judge_summary":"Evidence supports patch.",'
        '"prosecutor_claims":[],"defender_claims":[],"accepted_arguments":[],"rejected_arguments":[],'
        '"unresolved_risks":[]}\n'
        "End of verdict."
    )
    assert payload["label"] == "PATCH"


def test_extract_content_handles_segmented_message_blocks() -> None:
    content = court_module._extract_content(
        {
            "choices": [
                {
                    "message": {
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"label":"PATCH","confidence":"low"}',
                            }
                        ]
                    }
                }
            ]
        }
    )
    assert '"label":"PATCH"' in content


def test_extract_content_handles_segmented_value_blocks() -> None:
    content = court_module._extract_content(
        {
            "choices": [
                {
                    "message": {
                        "content": [
                            {
                                "type": "text",
                                "value": '{"label":"MINOR","confidence":"medium"}',
                            }
                        ]
                    }
                }
            ]
        }
    )
    assert '"label":"MINOR"' in content


def test_extract_content_handles_tool_call_arguments() -> None:
    content = court_module._extract_content(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"function": {"arguments": '{"label":"PATCH","confidence":"low"}'}}
                        ]
                    }
                }
            ]
        }
    )
    assert '"label":"PATCH"' in content


def test_extract_json_payload_handles_nested_json_string() -> None:
    payload = court_module._extract_json_payload(
        '"{\\"label\\":\\"PATCH\\",\\"confidence\\":\\"high\\",\\"judge_summary\\":\\"Evidence supports patch.\\"}"'
    )
    assert payload["label"] == "PATCH"


def test_extract_json_payload_recovers_from_plaintext_verdict() -> None:
    payload = court_module._extract_json_payload(
        "Court verdict: PATCH. Confidence: moderate. "
        "Judge summary: This change updates internals with no public API impact."
    )
    assert payload["label"] == "PATCH"
    assert payload["confidence"] == "medium"


def test_extract_json_payload_recovers_semantic_minor_phrase() -> None:
    payload = court_module._extract_json_payload(
        "The evidence points to a backward-compatible feature addition with moderate confidence."
    )
    assert payload["label"] == "MINOR"
    assert payload["confidence"] == "medium"


def test_extract_json_payload_error_includes_content_preview() -> None:
    with pytest.raises(RuntimeError, match="content_preview"):
        court_module._extract_json_payload("Unable to provide a verdict at this time.")


def test_extract_json_payload_uses_fallback_label_for_truncated_label_key() -> None:
    payload = court_module._extract_json_payload('{ "label', fallback_label="PATCH")
    assert payload["label"] == "PATCH"
    assert payload["confidence"] == "low"


def test_extract_json_payload_uses_fallback_label_for_single_brace() -> None:
    payload = court_module._extract_json_payload("{", fallback_label="MINOR")
    assert payload["label"] == "MINOR"
    assert payload["confidence"] == "low"


def test_validate_court_payload_coerces_alias_fields() -> None:
    payload = court_module._validate_court_payload(
        {
            "version_bump": "minor",
            "certainty": "moderate",
            "reasoning": "Adds new export while preserving compatibility.",
        }
    )
    assert payload["label"] == "MINOR"
    assert payload["confidence"] == "medium"
    assert len(payload["judge_summary"]) >= 12


def test_validate_court_payload_rewrites_structured_judge_summary() -> None:
    payload = court_module._validate_court_payload(
        {
            "label": "PATCH",
            "confidence": "low",
            "judge_summary": '{"label":"PATCH"',
        }
    )
    assert payload["judge_summary"] == (
        "Court selected PATCH based on the strongest evidence in the case file."
    )


def test_extract_case_file_evidence_ids_reads_case_file_records() -> None:
    evidence_ids = court_module._extract_case_file_evidence_ids(
        json.dumps(
            {
                "version": "case_file_v1",
                "evidence_records": [
                    {"evidence_id": "finding:f1"},
                    {"evidence_id": "behavior_marker:2"},
                ],
            }
        )
    )
    assert evidence_ids == {"finding:f1", "behavior_marker:2"}


def test_validate_court_payload_rejects_unknown_evidence_ids() -> None:
    with pytest.raises(RuntimeError, match="unknown evidence ids"):
        court_module._validate_court_payload(
            {
                "label": "PATCH",
                "confidence": "medium",
                "judge_summary": "Evidence supports patch-level compatibility changes.",
                "accepted_evidence_ids": ["finding:f99"],
            },
            valid_evidence_ids={"finding:f1"},
        )


def test_run_court_advisory_skips_without_engine_label() -> None:
    advisory, reason, model = court_module.run_court_advisory(
        mode="auto",
        model="openai/gpt-5-mini",
        fallback_model=None,
        endpoint="https://models.inference.ai.azure.com/chat/completions",
        token="token",
        max_retries=1,
        request_timeout=5,
        engine_label=None,
        case_file_text="{}",
    )
    assert advisory["status"] == "skipped"
    assert reason is None
    assert model is None


def test_run_court_advisory_degrades_without_token() -> None:
    advisory, reason, model = court_module.run_court_advisory(
        mode="auto",
        model="openai/gpt-5-mini",
        fallback_model=None,
        endpoint="https://models.inference.ai.azure.com/chat/completions",
        token="",
        max_retries=1,
        request_timeout=5,
        engine_label="MINOR",
        case_file_text="{}",
    )
    assert advisory["status"] == "degraded"
    assert reason == "missing_model_token"
    assert model is None


def test_run_court_advisory_marks_manual_review_on_disagreement(monkeypatch) -> None:
    def _fake_call_with_fallback(**_: object):
        return (
            {
                "label": "PATCH",
                "confidence": "medium",
                "judge_summary": "Judge selected PATCH from evidence.",
                "prosecutor_claims": ["claim-a"],
                "defender_claims": ["claim-b"],
                "accepted_arguments": ["claim-b"],
                "rejected_arguments": ["claim-a"],
                "unresolved_risks": [],
                "accepted_evidence_ids": ["finding:f1"],
                "rejected_evidence_ids": [],
            },
            "openai/gpt-5-mini",
        )

    monkeypatch.setattr(court_module, "_call_with_fallback", _fake_call_with_fallback)
    advisory, reason, model = court_module.run_court_advisory(
        mode="auto",
        model="openai/gpt-5-mini",
        fallback_model=None,
        endpoint="https://models.inference.ai.azure.com/chat/completions",
        token="token",
        max_retries=1,
        request_timeout=5,
        engine_label="MINOR",
        case_file_text="{}",
    )
    assert advisory["status"] == "manual_review"
    assert "disagreed" in str(advisory["disagreement_reason"]).lower()
    assert reason is None
    assert model == "openai/gpt-5-mini"


def test_build_court_messages_includes_language_hints() -> None:
    messages = court_module.build_court_messages(
        case_file_text="{}",
        engine_label="MINOR",
        language_hints=["For Python, treat __all__ exports as public API candidates."],
    )

    assert "Language-specific API hints:" in messages[1]["content"]
    assert "__all__ exports as public API candidates" in messages[1]["content"]


def test_call_model_attempts_repair_on_parse_failure(monkeypatch) -> None:
    class _FakeResponse:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "unable to classify"}}]}).encode(
                "utf-8"
            )

    called = {"repair": False}

    def _fake_repair_payload(**_: object) -> dict[str, object]:
        called["repair"] = True
        return {
            "label": "PATCH",
            "confidence": "low",
            "judge_summary": "Court selected PATCH based on the strongest evidence in the case file.",
            "prosecutor_claims": [],
            "defender_claims": [],
            "accepted_arguments": [],
            "rejected_arguments": [],
            "unresolved_risks": [],
        }

    monkeypatch.setattr(
        court_module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse(),
    )
    monkeypatch.setattr(court_module, "_attempt_repair_payload", _fake_repair_payload)
    monkeypatch.setattr(court_module, "apply_model_call_interval", lambda: None)

    payload = court_module._call_model(
        token="token",
        endpoint="https://models.inference.ai.azure.com/chat/completions",
        model="openai/gpt-5-mini",
        messages=[{"role": "user", "content": "test"}],
        fallback_label="PATCH",
        max_retries=1,
        request_timeout=5,
    )
    assert called["repair"] is True
    assert payload["label"] == "PATCH"
