from __future__ import annotations

import json
from dataclasses import dataclass, field

DEFAULT_LANGUAGE_GROUP = "javascript-typescript"
PROMPT_VERSION = "js-ts-v1"
PYTHON_PROMPT_VERSION = "python-v1"
GENERIC_PROMPT_VERSION = "generic-v0"

SYSTEM_PROMPT = (
    "You classify git diffs into SemVer impact. "
    "Return strict JSON with keys: label, confidence, reasoning, changelog. "
    "label must be MAJOR|MINOR|PATCH|NO_BUMP. confidence must be high|medium|low. "
    "reasoning must cite concrete changed files or symbols. "
    "changelog must start with feat:, fix:, or chore:. "
    "Do not wrap JSON in markdown code fences."
)

CLASSIFICATION_RUBRIC = (
    "SemVer classification rubric:\n"
    "- MAJOR: a breaking change to an exported or public API contract.\n"
    "- MINOR: a backward-compatible addition to exported or public API.\n"
    "- PATCH: internal fixes, refactors, or non-public changes.\n"
    "- NO_BUMP: docs/config/metadata-only changes with no runtime API or behavior impact.\n"
    "- Mixed diffs take the highest-impact label present.\n"
    "- Docs-only or config-only changes are NO_BUMP.\n"
)

CONFIDENCE_POLICY = (
    "Confidence policy:\n"
    "- Use high when the diff clearly shows exported API impact.\n"
    "- Use medium when the likely outcome is clear but some context is missing.\n"
    "- Use low when the public-vs-internal boundary is ambiguous or surface-area context is missing.\n"
)

JS_TS_PUBLIC_API_RULES = (
    "JavaScript/TypeScript public API rules:\n"
    "- Treat exported functions, classes, types, interfaces, consts, and re-exports as public API candidates.\n"
    "- Removing an exported symbol is usually MAJOR.\n"
    "- Changing the required parameters or return contract of an exported symbol is usually MAJOR.\n"
    "- Adding a new exported symbol is usually MINOR if existing callers remain compatible.\n"
    "- Changes in non-exported helpers are PATCH unless surface-area hints say otherwise.\n"
)

GENERIC_PUBLIC_API_RULES = (
    "Generic public API rules:\n"
    "- Treat obviously exported, public, or externally consumed symbols as public API candidates.\n"
    "- Removing a public symbol is usually MAJOR.\n"
    "- Changing the required parameters or return contract of a public symbol is usually MAJOR.\n"
    "- Adding a new public symbol is usually MINOR if existing callers remain compatible.\n"
    "- Changes to internal helpers, docs, tests, or implementation-only details are PATCH.\n"
)
PYTHON_PUBLIC_API_RULES = (
    "Python public API rules:\n"
    "- Treat names exported via __all__ as public API.\n"
    "- When __all__ is absent, treat top-level names without a leading underscore as public API candidates.\n"
    "- Treat public class constructors and public top-level functions as part of the supported API surface.\n"
    "- Removing a public symbol or raising the minimum supported Python version is usually MAJOR.\n"
    "- Adding a new public symbol or only optional constructor/function parameters is usually MINOR.\n"
    "- Internal underscore helpers, tests, and docs-only changes are PATCH or NO_BUMP unless stronger "
    "evidence says otherwise.\n"
)

REQUIRED_FEW_SHOT_CATEGORIES = {
    "minor_export_added",
    "major_export_removed",
    "major_signature_change",
    "patch_internal_refactor",
    "ambiguous_public_surface",
    "mixed_major_minor",
    "surface_area_required",
}


@dataclass(frozen=True)
class FewShotExample:
    category: str
    diff_text: str
    output: dict[str, str]
    surface_area_hints: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PromptPackMetadata:
    prompt_version: str
    language_group: str
    promotion_status: str
    fixture_set: str


@dataclass(frozen=True)
class PromptPack:
    metadata: PromptPackMetadata
    system_prompt: str
    language_rules: str
    few_shot_examples: tuple[FewShotExample, ...] = field(default_factory=tuple)


FEW_SHOT_EXAMPLES = [
    FewShotExample(
        category="minor_export_added",
        diff_text="+ export function getUserProfile(userId) { return { id: userId }; }",
        output={
            "label": "MINOR",
            "confidence": "high",
            "reasoning": "A new exported function getUserProfile was added without changing existing exported signatures.",
            "changelog": "feat: add getUserProfile exported API",
        },
    ),
    FewShotExample(
        category="major_export_removed",
        diff_text="- export function login(username, password) {}",
        output={
            "label": "MAJOR",
            "confidence": "high",
            "reasoning": "The exported function login was removed, which breaks consumers relying on that public API.",
            "changelog": "feat: remove login exported API",
        },
    ),
    FewShotExample(
        category="major_signature_change",
        diff_text="- export function login(user, pass) {}\n+ export function login(credentials) {}",
        output={
            "label": "MAJOR",
            "confidence": "high",
            "reasoning": "The exported function login changed its required parameter contract, which is a breaking API change.",
            "changelog": "feat: change login exported API signature",
        },
    ),
    FewShotExample(
        category="patch_internal_refactor",
        diff_text="- const buildCacheKey = (user) => `${user.id}`\n+ const buildCacheKey = (user) => `${user.orgId}:${user.id}`",
        output={
            "label": "PATCH",
            "confidence": "high",
            "reasoning": "Only a non-exported helper changed and no exported API surface was added, removed, or modified.",
            "changelog": "fix: tighten internal cache key handling",
        },
    ),
    FewShotExample(
        category="ambiguous_public_surface",
        diff_text="- function normalizeUser(user) {}\n+ function normalizeUser(user, opts) {}",
        output={
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "The diff changes a function signature, but it is not clearly exported and no surface-area hint confirms it is public API.",
            "changelog": "fix: adjust user normalization helper",
        },
    ),
    FewShotExample(
        category="mixed_major_minor",
        diff_text=(
            "- export function login(user, pass) {}\n"
            "+ export function login(credentials) {}\n"
            "+ export function listTeams() {}"
        ),
        output={
            "label": "MAJOR",
            "confidence": "high",
            "reasoning": "The diff both adds a new export and changes the exported login signature, and the breaking change dominates.",
            "changelog": "feat: change login API and add listTeams export",
        },
    ),
    FewShotExample(
        category="surface_area_required",
        diff_text="- function normalizeBilling(user, opts) {}\n+ function normalizeBilling(user, opts, audit) {}",
        surface_area_hints=("src/billing/public.ts",),
        output={
            "label": "MAJOR",
            "confidence": "high",
            "reasoning": "The changed function lives in a surface_area path, so it should be treated as public API, and adding a required parameter is breaking.",
            "changelog": "feat: change billing public helper signature",
        },
    ),
]
PYTHON_FEW_SHOT_EXAMPLES = [
    FewShotExample(
        category="minor_export_added",
        diff_text=(
            "class Settings(BaseSettings):\n"
            "    pass\n\n"
            "+def list_users() -> list[str]:\n"
            "+    return []"
        ),
        output={
            "label": "MINOR",
            "confidence": "high",
            "reasoning": "A new public top-level Python function list_users was added without "
            "breaking existing imports or call signatures.",
            "changelog": "feat: add list_users helper",
        },
    ),
    FewShotExample(
        category="major_signature_change",
        diff_text=(
            "class TomlConfigSettingsSource:\n"
            "-    def __init__(self, settings_cls: type[BaseSettings], toml_file: PathType | None = "
            "DEFAULT_PATH):\n"
            "+    def __init__(self, settings_cls: type[BaseSettings], toml_file: PathType | None = "
            "DEFAULT_PATH, strict: bool):"
        ),
        output={
            "label": "MAJOR",
            "confidence": "high",
            "reasoning": "The public constructor TomlConfigSettingsSource.__init__ gained a required "
            "parameter, which breaks existing callers.",
            "changelog": "feat: change TomlConfigSettingsSource constructor",
        },
    ),
    FewShotExample(
        category="patch_internal_refactor",
        diff_text=(
            "-def _normalize_user(value: str) -> str:\n"
            "-    return value\n"
            "+def _normalize_user(value: str) -> str:\n"
            "+    return value.strip()"
        ),
        output={
            "label": "PATCH",
            "confidence": "high",
            "reasoning": "Only an internal underscore-prefixed helper changed, with no clear public "
            "API addition or break.",
            "changelog": "fix: tighten internal normalization logic",
        },
    ),
    FewShotExample(
        category="python_support_floor_raise",
        diff_text=('-requires-python = ">=3.9"\n+requires-python = ">=3.10"'),
        output={
            "label": "MAJOR",
            "confidence": "high",
            "reasoning": "The package raised its minimum supported Python version, which is a "
            "breaking compatibility change for users on the dropped runtime.",
            "changelog": "feat: raise minimum supported Python version",
        },
    ),
]

JS_TS_PROMPT_PACK = PromptPack(
    metadata=PromptPackMetadata(
        prompt_version=PROMPT_VERSION,
        language_group=DEFAULT_LANGUAGE_GROUP,
        promotion_status="promoted",
        fixture_set="test-diffs",
    ),
    system_prompt=SYSTEM_PROMPT,
    language_rules=JS_TS_PUBLIC_API_RULES,
    few_shot_examples=tuple(FEW_SHOT_EXAMPLES),
)

GENERIC_PROMPT_PACK = PromptPack(
    metadata=PromptPackMetadata(
        prompt_version=GENERIC_PROMPT_VERSION,
        language_group="generic",
        promotion_status="experimental",
        fixture_set="test-diffs",
    ),
    system_prompt=SYSTEM_PROMPT,
    language_rules=GENERIC_PUBLIC_API_RULES,
)
PYTHON_PROMPT_PACK = PromptPack(
    metadata=PromptPackMetadata(
        prompt_version=PYTHON_PROMPT_VERSION,
        language_group="python",
        promotion_status="experimental",
        fixture_set="test-diffs",
    ),
    system_prompt=SYSTEM_PROMPT,
    language_rules=PYTHON_PUBLIC_API_RULES,
    few_shot_examples=tuple(PYTHON_FEW_SHOT_EXAMPLES),
)

PROMPT_PACKS_BY_VERSION = {
    JS_TS_PROMPT_PACK.metadata.prompt_version: JS_TS_PROMPT_PACK,
    PYTHON_PROMPT_PACK.metadata.prompt_version: PYTHON_PROMPT_PACK,
    GENERIC_PROMPT_PACK.metadata.prompt_version: GENERIC_PROMPT_PACK,
}


def get_prompt_pack(
    language_group: str | None = None,
    prompt_version: str | None = None,
) -> PromptPack:
    if prompt_version:
        try:
            return PROMPT_PACKS_BY_VERSION[prompt_version]
        except KeyError as err:
            raise ValueError(f"Unknown prompt version: {prompt_version!r}") from err

    if language_group in {None, DEFAULT_LANGUAGE_GROUP}:
        return JS_TS_PROMPT_PACK
    if language_group == "python":
        return PYTHON_PROMPT_PACK

    return GENERIC_PROMPT_PACK


def get_prompt_metadata(
    language_group: str | None = None,
    prompt_version: str | None = None,
) -> PromptPackMetadata:
    return get_prompt_pack(language_group=language_group, prompt_version=prompt_version).metadata


def _build_user_prompt(
    diff_text: str,
    *,
    language_rules: str,
    surface_area_hints: list[str] | None = None,
    language_hints: list[str] | None = None,
) -> str:
    sections = [
        "Analyze this git diff and classify impact.",
        CLASSIFICATION_RUBRIC,
        language_rules,
        CONFIDENCE_POLICY,
    ]

    if surface_area_hints:
        hints = "\n".join(f"- {hint}" for hint in surface_area_hints)
        sections.append(
            "Public API surface hints:\n"
            f"{hints}\n"
            "Treat matching files as public API by default.\n"
            "Only override that assumption when the diff clearly proves the changed code is internal."
        )
    else:
        sections.append(
            "Public API surface hints:\n"
            "- none provided\n"
            "No explicit surface_area hints were provided.\n"
            "If the diff is ambiguous about public API impact, keep confidence low."
        )

    if language_hints:
        hints = "\n".join(f"- {hint}" for hint in language_hints)
        sections.append(f"Language-specific public API hints:\n{hints}")

    sections.append(f"Diff:\n{diff_text}\n\nRespond with JSON only.")
    return "\n\n".join(sections)


def build_messages(
    diff_text: str,
    *,
    language_group: str | None = None,
    prompt_version: str | None = None,
    surface_area_hints: list[str] | None = None,
    language_hints: list[str] | None = None,
) -> list[dict[str, str]]:
    prompt_pack = get_prompt_pack(language_group=language_group, prompt_version=prompt_version)
    messages: list[dict[str, str]] = [{"role": "system", "content": prompt_pack.system_prompt}]

    for example in prompt_pack.few_shot_examples:
        messages.append(
            {
                "role": "user",
                "content": _build_user_prompt(
                    example.diff_text,
                    language_rules=prompt_pack.language_rules,
                    surface_area_hints=list(example.surface_area_hints) or None,
                ),
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(example.output, separators=(",", ":")),
            }
        )

    messages.append(
        {
            "role": "user",
            "content": _build_user_prompt(
                diff_text,
                language_rules=prompt_pack.language_rules,
                surface_area_hints=surface_area_hints,
                language_hints=language_hints,
            ),
        }
    )
    return messages
