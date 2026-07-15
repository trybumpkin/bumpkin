import pytest

from llm import (
    LLMResponseError,
    _build_messages,
    _coerce_recommendation_payload,
    _extract_content,
    _extract_json_payload,
    validate_recommendation,
)


def test_extract_json_payload_handles_markdown_fence() -> None:
    payload = _extract_json_payload(
        """```json
{"label":"PATCH","confidence":"high","reasoning":"Updated internal helper in src/core.py.","changelog":"fix: tighten helper null checks"}
```"""
    )
    assert payload["label"] == "PATCH"


def test_extract_content_handles_segmented_message_blocks() -> None:
    content = _extract_content(
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


def test_extract_content_handles_tool_call_arguments() -> None:
    content = _extract_content(
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


def test_validate_recommendation_rejects_bad_changelog_prefix() -> None:
    with pytest.raises(LLMResponseError):
        validate_recommendation(
            {
                "label": "PATCH",
                "confidence": "high",
                "reasoning": "Adjusted internal branch condition in src/core.py to avoid crash.",
                "changelog": "updated helper logic",
            }
        )


def test_validate_recommendation_accepts_scoped_conventional_commit() -> None:
    valid = validate_recommendation(
        {
            "label": "MINOR",
            "confidence": "high",
            "reasoning": "Adds exported helper while preserving backward compatibility.",
            "changelog": "feat(api)!: adjust exported helper contract",
        }
    )
    assert valid["label"] == "MINOR"


def test_extract_json_payload_handles_nested_json_string() -> None:
    payload = _extract_json_payload(
        '"{\\"label\\":\\"PATCH\\",\\"confidence\\":\\"high\\",\\"reasoning\\":\\"internal fix\\",\\"changelog\\":\\"fix: internal repair\\"}"'
    )
    assert payload["label"] == "PATCH"


def test_extract_json_payload_repairs_unclosed_object() -> None:
    payload = _extract_json_payload(
        "{\n"
        '"label":"PATCH",\n'
        '"confidence":"high",\n'
        '"reasoning":"Adjusted internal helper so the final payload is recoverable.",\n'
        '"changelog":"fix: recover truncated output"\n'
    )
    assert payload["label"] == "PATCH"
    assert payload["changelog"] == "fix: recover truncated output"


def test_coerce_recommendation_payload_maps_alias_fields() -> None:
    payload = _coerce_recommendation_payload(
        {
            "version_bump": "minor",
            "certainty": "moderate",
            "explanation": "Adds a new export and keeps old behavior intact.",
            "conventional_commit": "feat(api): add helper",
        }
    )
    assert payload["label"] == "MINOR"
    assert payload["confidence"] == "medium"
    assert payload["changelog"].startswith("feat")


def test_coerce_recommendation_payload_backfills_required_fields() -> None:
    payload = _coerce_recommendation_payload({"label": "PATCH"})
    assert payload["label"] == "PATCH"
    assert payload["changelog"].startswith("fix:")
    assert len(payload["reasoning"]) >= 20


def test_build_messages_includes_surface_area_hints() -> None:
    messages = _build_messages(
        "+ export function getUserProfile() {}",
        surface_area_hints=["src/api/**", "src/public/index.ts"],
    )
    prompt = messages[-1]["content"]
    assert "Public API surface hints" in prompt
    assert "src/api/**" in prompt
    assert "src/public/index.ts" in prompt


def test_build_messages_warns_when_surface_area_missing() -> None:
    messages = _build_messages("+ update README", surface_area_hints=None)
    prompt = messages[-1]["content"]
    assert "No explicit surface_area hints were provided" in prompt


def test_build_messages_includes_language_hints() -> None:
    messages = _build_messages(
        "+ export function getUserProfile() {}",
        surface_area_hints=["src/api/**"],
        language_hints=[
            "For JavaScript/TypeScript, treat exported symbol signature changes as breaking."
        ],
    )
    prompt = messages[-1]["content"]
    assert "Language-specific public API hints" in prompt
    assert "JavaScript/TypeScript" in prompt


def test_build_messages_includes_few_shot_pairs() -> None:
    messages = _build_messages("+ export function getUserProfile() {}")
    assert messages[0]["role"] == "system"
    assert len(messages) >= 6
