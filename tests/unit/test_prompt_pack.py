from prompt_pack import (
    FEW_SHOT_EXAMPLES,
    PROMPT_VERSION,
    PYTHON_PROMPT_VERSION,
    REQUIRED_FEW_SHOT_CATEGORIES,
    build_messages,
    get_prompt_pack,
)


def test_prompt_version_is_set() -> None:
    assert PROMPT_VERSION.startswith("js-ts-v")


def test_prompt_pack_has_few_shot_examples() -> None:
    assert len(FEW_SHOT_EXAMPLES) >= 2


def test_prompt_pack_covers_required_few_shot_categories() -> None:
    categories = {example.category for example in FEW_SHOT_EXAMPLES}
    assert REQUIRED_FEW_SHOT_CATEGORIES.issubset(categories)


def test_build_messages_ends_with_runtime_user_prompt() -> None:
    messages = build_messages(
        "+ export function ping() {}",
        language_group="javascript-typescript",
        surface_area_hints=["src/api/**"],
    )
    assert messages[-1]["role"] == "user"
    assert "Diff:" in messages[-1]["content"]
    assert "SemVer classification rubric" in messages[-1]["content"]
    assert "JavaScript/TypeScript public API rules" in messages[-1]["content"]
    assert "Public API surface hints" in messages[-1]["content"]


def test_build_messages_treats_surface_area_as_public_api_by_default() -> None:
    messages = build_messages(
        "- function normalizeBilling(user, opts) {}\n+ function normalizeBilling(user, opts, audit) {}",
        language_group="javascript-typescript",
        surface_area_hints=["src/billing/public.ts"],
    )

    assert "Treat matching files as public API by default." in messages[-1]["content"]
    assert (
        "Only override that assumption when the diff clearly proves the changed code is internal."
        in messages[-1]["content"]
    )


def test_get_prompt_pack_returns_promoted_js_ts_pack() -> None:
    pack = get_prompt_pack(language_group="javascript-typescript")

    assert pack.metadata.prompt_version == "js-ts-v1"
    assert pack.metadata.language_group == "javascript-typescript"
    assert pack.metadata.promotion_status == "promoted"


def test_get_prompt_pack_uses_experimental_generic_fallback() -> None:
    pack = get_prompt_pack(language_group="go")

    assert pack.metadata.prompt_version == "generic-v0"
    assert pack.metadata.language_group == "generic"
    assert pack.metadata.promotion_status == "experimental"


def test_get_prompt_pack_returns_python_pack() -> None:
    pack = get_prompt_pack(language_group="python")

    assert pack.metadata.prompt_version == PYTHON_PROMPT_VERSION
    assert pack.metadata.language_group == "python"
    assert pack.metadata.promotion_status == "experimental"


def test_build_messages_uses_generic_prompt_for_unsupported_language() -> None:
    messages = build_messages(
        "+ pub fn ping() {}",
        language_group="go",
    )

    assert "JavaScript/TypeScript public API rules" not in messages[-1]["content"]
    assert "Generic public API rules" in messages[-1]["content"]


def test_build_messages_uses_python_prompt_for_python_language_group() -> None:
    messages = build_messages(
        '+requires-python = ">=3.10"',
        language_group="python",
    )

    assert "Generic public API rules" not in messages[-1]["content"]
    assert "Python public API rules" in messages[-1]["content"]


def test_surface_area_required_is_a_required_few_shot_category() -> None:
    assert "surface_area_required" in REQUIRED_FEW_SHOT_CATEGORIES
