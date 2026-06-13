from __future__ import annotations

from pathlib import Path

LANGUAGE_HINTS = {
    "javascript-typescript": (
        "For JavaScript/TypeScript, treat removal or signature changes of exported symbols "
        "(export/exports/module.exports/public exports) as potential breaking changes."
    ),
    "python": (
        "For Python, treat symbols in __all__ or names without a leading underscore as "
        "public API candidates; removals/signature changes may be breaking."
    ),
    "go": (
        "For Go, exported identifiers are capitalized; treat signature changes/removals of "
        "capitalized functions/types as potential breaking changes."
    ),
    "rust": (
        "For Rust, treat pub symbols as public API; removal or signature changes can be breaking."
    ),
    "java-kotlin": (
        "For Java/Kotlin, treat public methods/classes as public API; signature changes/removals "
        "can be breaking."
    ),
}


def get_language_hints_for_groups(groups: list[str]) -> list[str]:
    ordered = sorted({group for group in groups if group in LANGUAGE_HINTS})
    return [LANGUAGE_HINTS[group] for group in ordered]


def _language_group_for_suffix(suffix: str) -> str | None:
    if suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        return "javascript-typescript"
    if suffix in {".py", ".pyi"}:
        return "python"
    if suffix == ".go":
        return "go"
    if suffix == ".rs":
        return "rust"
    if suffix in {".java", ".kt", ".kts"}:
        return "java-kotlin"
    return None


def detect_language_hints(file_paths: list[str]) -> list[str]:
    groups = detect_language_groups(file_paths)
    return get_language_hints_for_groups(groups)


def detect_language_groups(file_paths: list[str]) -> list[str]:
    groups: set[str] = set()
    for file_path in file_paths:
        group = _language_group_for_suffix(Path(file_path).suffix.lower())
        if group:
            groups.add(group)

    return sorted(groups)


__all__ = ["detect_language_groups", "detect_language_hints", "get_language_hints_for_groups"]
