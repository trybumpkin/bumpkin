from __future__ import annotations

import re
from typing import Any

DIFF_GIT_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
EXPORT_LINE_PATTERNS = [
    re.compile(r"\bexport\s+(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\bexport\s+class\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\bexport\s+(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\bexport\s+(?:interface|type|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"),
]
SIGNATURE_PATTERNS = [
    re.compile(r"\b(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)"),
    re.compile(
        r"\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*(?::\s*[^=]+)?=>"
    ),
    re.compile(r"\b(?:public|private|protected)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*{"),
]
DOC_PATH_HINTS = ("docs/", "readme", "changelog", ".md", ".rst", ".txt")
CONFIG_PATH_HINTS = (
    ".github/workflows/",
    "bumpkin.yml",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "renovate.json",
)
DOC_CONTENT_HINTS = (
    "readme",
    "changelog",
    "documentation",
    "docs",
    "release notes",
    "branch protection",
)
CONFIG_CONTENT_HINTS = (
    "renovate",
    "$schema",
    "extends",
    "schedule",
    "description",
)
AMBIGUOUS_CODE_HINTS = (
    "refactor",
    "api",
    "internal",
    "runtime",
    "public",
    "breaking",
)
PUBLIC_EXPORT_MARKER_PATTERNS = (
    re.compile(r"\bexport\s+default\b"),
    re.compile(r"\bexport\s*\{"),
    re.compile(r"\bexport\s+\*"),
    re.compile(r"\bexport\s+(?:async\s+)?function\b"),
    re.compile(r"\bexport\s+class\b"),
    re.compile(r"\bexport\s+(?:const|let|var)\b"),
    re.compile(r"\bexport\s+(?:interface|type|enum)\b"),
    re.compile(r"\bpublic\s+[A-Za-z_][A-Za-z0-9_]*\s*\("),
)
CODE_MARKER_PATTERN = re.compile(
    r"\b(?:const|let|var|function|class|switch|try|catch|throw|"
    r"import|export|interface|enum|def|async|await)\b|"
    r"\b(?:if|for|while)\s*\(|\bfrom\s+\S+\s+import\b|"
    r"=>|\?\.|===|!==|==|!=|&&|\|\|"
)
KEY_VALUE_PATTERN = re.compile(r"^['\"]?[$A-Za-z0-9_.-]+['\"]?\s*:\s*")
TEXT_LINE_PATTERN = re.compile(r"^[A-Za-z0-9 _.,:/()'\-]{8,}$")


def _extract_changed_paths(diff_text: str) -> list[str]:
    paths: list[str] = []
    for line in diff_text.splitlines():
        match = DIFF_GIT_HEADER.match(line.strip())
        if match:
            paths.append(match.group(2))
    return paths


def _paths_preview(paths: list[str], *, max_items: int = 2) -> str:
    normalized = [path.strip() for path in paths if path.strip()]
    if not normalized:
        return "changed files"
    shown = normalized[:max_items]
    if len(normalized) == 1:
        return shown[0]
    if len(normalized) <= max_items:
        return ", ".join(shown)
    return ", ".join(shown) + f", and {len(normalized) - max_items} more file(s)"


def _derive_internal_scope(paths: list[str]) -> str | None:
    normalized = [path.strip() for path in paths if path.strip()]
    if not normalized:
        return None
    preferred = next(
        (
            path
            for path in normalized
            if path.startswith("src/") and not path.startswith("src/tests/")
        ),
        normalized[0],
    )
    file_name = preferred.rsplit("/", 1)[-1]
    stem = file_name.rsplit(".", 1)[0].strip().lower()
    scope = re.sub(r"[^a-z0-9_-]+", "-", stem).strip("-_")
    return scope or None


def _internal_patch_changelog(paths: list[str]) -> str:
    normalized = [path.strip() for path in paths if path.strip()]
    scope = _derive_internal_scope(paths)
    target = ""
    if normalized:
        preferred = next(
            (
                path
                for path in normalized
                if path.startswith("src/") and not path.startswith("src/tests/")
            ),
            normalized[0],
        )
        target = preferred.rsplit("/", 1)[-1]
    if scope:
        if target:
            return f"fix({scope}): update internal behavior in {target}"
        return f"fix({scope}): update internal behavior"
    if target:
        return f"fix: update internal behavior in {target}"
    return "fix: update internal behavior"


def _looks_docs_or_config_only(paths: list[str]) -> bool:
    if not paths:
        return False
    normalized = [path.strip().lower() for path in paths if path.strip()]
    if not normalized:
        return False

    for path in normalized:
        if any(hint in path for hint in DOC_PATH_HINTS):
            continue
        if any(hint in path for hint in CONFIG_PATH_HINTS):
            continue
        return False
    return True


def _collect_added_removed_lines(diff_text: str) -> tuple[list[str], list[str]]:
    removed: list[str] = []
    added: list[str] = []
    for raw in diff_text.splitlines():
        if raw.startswith(("---", "+++")):
            continue
        if raw.startswith("-"):
            removed.append(raw[1:].strip())
        elif raw.startswith("+"):
            added.append(raw[1:].strip())
    return removed, added


def _extract_export_names(lines: list[str]) -> set[str]:
    names: set[str] = set()
    for line in lines:
        names.update(_extract_declared_export_names(line))
        names.update(_extract_braced_export_names(line))
    return names


def _extract_declared_export_names(line: str) -> set[str]:
    names: set[str] = set()
    for pattern in EXPORT_LINE_PATTERNS:
        match = pattern.search(line)
        if match:
            names.add(match.group(1))
    if "export default" in line:
        names.add("__default__")
    return names


def _extract_braced_export_names(line: str) -> set[str]:
    brace_match = re.search(r"\bexport\s*{\s*([^}]+)\s*}", line)
    if brace_match is None:
        return set()
    names: set[str] = set()
    for member in (item.strip() for item in brace_match.group(1).split(",")):
        if not member:
            continue
        names.add(member.split(" as ", 1)[-1].strip())
    return names


def _extract_symbol_signatures(
    lines: list[str],
    *,
    exported_only: bool,
) -> dict[str, set[str]]:
    signatures: dict[str, set[str]] = {}
    for line in lines:
        if exported_only and "export" not in line:
            continue
        for pattern in SIGNATURE_PATTERNS:
            for match in pattern.finditer(line):
                name = match.group(1)
                params = re.sub(r"\s+", "", match.group(2))
                signatures.setdefault(name, set()).add(params)
    return signatures


def _split_top_level_params(params: str) -> list[str]:
    text = params.strip()
    if not text:
        return []

    parts: list[str] = []
    current: list[str] = []
    stack: list[str] = []
    opening = {"(": ")", "[": "]", "{": "}", "<": ">"}
    closing = {v: k for k, v in opening.items()}

    for ch in text:
        if ch == "," and not stack:
            token = "".join(current).strip()
            if token:
                parts.append(token)
            current = []
            continue
        current.append(ch)
        if ch in opening:
            stack.append(ch)
        elif ch in closing and stack and stack[-1] == closing[ch]:
            stack.pop()

    token = "".join(current).strip()
    if token:
        parts.append(token)
    return parts


def _is_optional_parameter_token(token: str) -> bool:
    param = token.strip()
    if not param:
        return False
    if param.startswith("..."):
        return True
    if "=" in param:
        return True
    left = param.split(":", 1)[0]
    return left.endswith("?")


def _is_optional_param_widening(old_params: str, new_params: str) -> bool:
    old_list = _split_top_level_params(old_params)
    new_list = _split_top_level_params(new_params)
    if len(new_list) < len(old_list):
        return False
    if new_list[: len(old_list)] != old_list:
        return False
    extras = new_list[len(old_list) :]
    if not extras:
        return False
    return all(_is_optional_parameter_token(param) for param in extras)


def _classify_export_signature_change(
    removed: list[str], added: list[str], shared_exports: set[str]
) -> str | None:
    if not shared_exports:
        return None
    removed_signatures = _extract_symbol_signatures(removed, exported_only=True)
    added_signatures = _extract_symbol_signatures(added, exported_only=True)
    saw_non_breaking_widening = False
    for name in shared_exports:
        removed_candidates = removed_signatures.get(name, set())
        added_candidates = added_signatures.get(name, set())
        if not removed_candidates or not added_candidates:
            continue
        if removed_candidates == added_candidates:
            continue

        for old_sig in removed_candidates:
            if old_sig in added_candidates:
                continue
            if any(_is_optional_param_widening(old_sig, new_sig) for new_sig in added_candidates):
                saw_non_breaking_widening = True
                continue
            return "major"

    if saw_non_breaking_widening:
        return "minor"
    return None


def _surface_area_triggered(diff_text: str, surface_area_hints: list[str] | None) -> bool:
    if not surface_area_hints:
        return False
    lowered = diff_text.lower()
    for hint in surface_area_hints:
        normalized = hint.strip().lower().replace("**", "").strip("/")
        if normalized and normalized in lowered:
            return True
    return False


def _looks_docs_or_config_content_only(lines: list[str]) -> bool:
    changed_lines = [
        line.strip() for line in lines if line.strip() and not line.strip().startswith("@@")
    ]
    if not changed_lines:
        return False
    if any(CODE_MARKER_PATTERN.search(line) for line in changed_lines):
        return False

    for line in changed_lines:
        lowered = line.lower()
        if re.fullmatch(r"[{}\[\],]+", line):
            continue
        if any(hint in lowered for hint in DOC_CONTENT_HINTS):
            continue
        if any(hint in lowered for hint in CONFIG_CONTENT_HINTS):
            continue
        if KEY_VALUE_PATTERN.match(line):
            continue
        if TEXT_LINE_PATTERN.match(line):
            continue
        return False
    return True


def _looks_ambiguous_code_summary(lines: list[str]) -> bool:
    changed_lines = [
        line.strip() for line in lines if line.strip() and not line.strip().startswith("@@")
    ]
    if not changed_lines:
        return False
    if any(CODE_MARKER_PATTERN.search(line) for line in changed_lines):
        return False

    has_ambiguous_code_hint = False
    for line in changed_lines:
        lowered = line.lower()
        if any(hint in lowered for hint in DOC_CONTENT_HINTS + CONFIG_CONTENT_HINTS):
            continue
        if any(hint in lowered for hint in AMBIGUOUS_CODE_HINTS):
            has_ambiguous_code_hint = True
    return has_ambiguous_code_hint


def _has_public_export_markers(lines: list[str]) -> bool:
    for line in lines:
        candidate = line.strip()
        if not candidate:
            continue
        for pattern in PUBLIC_EXPORT_MARKER_PATTERNS:
            if pattern.search(candidate):
                return True
    return False


def classified_result(
    *,
    label: str,
    confidence: str,
    reasoning: str,
    changelog: str,
) -> dict[str, Any]:
    return {
        "status": "classified",
        "label": label,
        "confidence": confidence,
        "reasoning": reasoning,
        "changelog": changelog,
    }


def manual_review_result(*, reasoning: str) -> dict[str, Any]:
    return {
        "status": "manual_review",
        "label": None,
        "confidence": None,
        "reasoning": reasoning,
        "changelog": None,
    }


def semantic_fallback_recommendation(
    *,
    diff_text: str,
    surface_area_hints: list[str] | None,
    truncated: bool,
) -> dict[str, Any]:
    paths = _extract_changed_paths(diff_text)
    if _looks_docs_or_config_only(paths):
        reasoning = _with_truncation(
            "Semantic fallback classified this as docs/config-only because all changed paths "
            "match documentation or repository config patterns.",
            truncated,
        )
        return classified_result(
            label="NO_BUMP",
            confidence="high",
            reasoning=reasoning,
            changelog="chore: no release required",
        )

    removed_lines, added_lines = _collect_added_removed_lines(diff_text)
    changed_lines = removed_lines + added_lines
    removed_exports = _extract_export_names(removed_lines)
    added_exports = _extract_export_names(added_lines)
    export_result = _classify_export_changes(
        removed_lines=removed_lines,
        added_lines=added_lines,
        removed_exports=removed_exports,
        added_exports=added_exports,
        surface_area_hints=surface_area_hints,
        truncated=truncated,
    )
    if export_result is not None:
        return export_result
    return _classify_content_changes(
        diff_text=diff_text,
        paths=paths,
        changed_lines=changed_lines,
        removed_lines=removed_lines,
        added_lines=added_lines,
        surface_area_hints=surface_area_hints,
        truncated=truncated,
    )


def _classify_export_changes(
    *,
    removed_lines: list[str],
    added_lines: list[str],
    removed_exports: set[str],
    added_exports: set[str],
    surface_area_hints: list[str] | None,
    truncated: bool,
) -> dict[str, Any] | None:
    removed_only = sorted(removed_exports - added_exports)
    if removed_only:
        return classified_result(
            label="MAJOR",
            confidence="high",
            reasoning=_with_truncation(
                "Semantic fallback detected removed exported API symbols: "
                + ", ".join(removed_only)
                + ".",
                truncated,
            ),
            changelog="feat: remove exported api symbols",
        )

    shared_exports = removed_exports & added_exports
    signature_change = _classify_export_signature_change(removed_lines, added_lines, shared_exports)
    if signature_change == "major":
        return classified_result(
            label="MAJOR",
            confidence="medium",
            reasoning=_with_truncation(
                "Semantic fallback detected changed exported function signatures for existing API symbols.",
                truncated,
            ),
            changelog="feat: update exported api signatures",
        )
    if signature_change == "minor":
        return classified_result(
            label="MINOR",
            confidence="medium",
            reasoning=_with_truncation(
                "Semantic fallback detected a backward-compatible exported signature widening (optional parameter addition).",
                truncated,
            ),
            changelog="feat: widen exported api signature",
        )

    if surface_area_hints:
        removed_signatures = _extract_symbol_signatures(removed_lines, exported_only=False)
        added_signatures = _extract_symbol_signatures(added_lines, exported_only=False)
        for symbol in sorted(set(removed_signatures) & set(added_signatures)):
            if removed_signatures[symbol] != added_signatures[symbol]:
                return classified_result(
                    label="MAJOR",
                    confidence="medium",
                    reasoning=_with_truncation(
                        "Semantic fallback detected a signature change for symbol "
                        f"{symbol} while surface_area hints are configured, so this is treated as a public breaking change.",
                        truncated,
                    ),
                    changelog="feat: change surface-area api signature",
                )

    added_only = sorted(added_exports - removed_exports)
    if added_only:
        return classified_result(
            label="MINOR",
            confidence="high",
            reasoning=_with_truncation(
                "Semantic fallback detected newly exported API symbols: "
                + ", ".join(added_only)
                + ".",
                truncated,
            ),
            changelog="feat: add exported api symbols",
        )
    return None


def _classify_content_changes(
    *,
    diff_text: str,
    paths: list[str],
    changed_lines: list[str],
    removed_lines: list[str],
    added_lines: list[str],
    surface_area_hints: list[str] | None,
    truncated: bool,
) -> dict[str, Any]:
    if _looks_ambiguous_code_summary(changed_lines):
        return classified_result(
            label="PATCH",
            confidence="low",
            reasoning=_with_truncation(
                "Semantic fallback detected an ambiguous prose summary of runtime/API changes without concrete public symbol evidence.",
                truncated,
            ),
            changelog="fix: ambiguous runtime refactor",
        )
    if _looks_docs_or_config_content_only(changed_lines):
        return classified_result(
            label="NO_BUMP",
            confidence="high",
            reasoning=_with_truncation(
                "Semantic fallback classified this as docs/config-only content because the diff contains prose or metadata changes without code markers.",
                truncated,
            ),
            changelog="chore: no release required",
        )

    removed_signatures = _extract_symbol_signatures(removed_lines, exported_only=False)
    added_signatures = _extract_symbol_signatures(added_lines, exported_only=False)
    for symbol in sorted(set(removed_signatures) & set(added_signatures)):
        if removed_signatures[symbol] != added_signatures[symbol]:
            return classified_result(
                label="PATCH",
                confidence="low",
                reasoning=_with_truncation(
                    "Semantic fallback detected a non-exported signature change "
                    f"for symbol {symbol}, but public API status is unclear.",
                    truncated,
                ),
                changelog="fix: adjust internal helper signature",
            )
    if _surface_area_triggered(diff_text, surface_area_hints):
        return manual_review_result(
            reasoning="Semantic fallback detected changes in configured surface_area paths but could not confidently classify impact. Please review manually."
        )
    if changed_lines and not _has_public_export_markers(removed_lines + added_lines):
        return classified_result(
            label="PATCH",
            confidence="medium",
            reasoning=_with_truncation(
                "Semantic fallback detected internal code changes in "
                f"{_paths_preview(paths)} without public/export API markers, classifying as internal patch.",
                truncated,
            ),
            changelog=_internal_patch_changelog(paths),
        )
    return manual_review_result(
        reasoning="Semantic fallback could not confidently infer SemVer impact from this diff. Please review manually."
    )


def _with_truncation(reasoning: str, truncated: bool) -> str:
    return f"{reasoning} Diff was truncated." if truncated else reasoning


def stub_recommendation(truncated: bool) -> dict[str, Any]:
    reasoning = "stub response"
    if truncated:
        reasoning += " (diff truncated; review manually)"

    return classified_result(
        label="PATCH",
        confidence="high",
        reasoning=reasoning,
        changelog="chore: stub",
    )


def no_bump_recommendation(truncated: bool) -> dict[str, Any]:
    reasoning = "No release-triggering public API changes were detected in the analyzed diff."
    if truncated:
        reasoning += " (diff truncated; review manually)"

    return classified_result(
        label="NO_BUMP",
        confidence="high",
        reasoning=reasoning,
        changelog="chore: no release required",
    )
