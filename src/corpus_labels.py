from __future__ import annotations

import re

EXPECTED_LABEL_RE = re.compile(
    r"<!--\s*bumpkin:expected-label:(MAJOR|MINOR|PATCH|NO_BUMP)\s*-->",
    re.IGNORECASE,
)
DOC_CONFIG_HINTS = (
    "docs/",
    ".md",
    ".rst",
    ".txt",
    ".github/",
    "renovate.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    ".editorconfig",
)
JS_TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def _looks_docs_or_config_only(paths: list[str]) -> bool:
    if not paths:
        return False
    for path in paths:
        normalized = path.strip().lower()
        if not normalized:
            continue
        if any(hint in normalized for hint in DOC_CONFIG_HINTS):
            continue
        if normalized.endswith(JS_TS_EXTENSIONS):
            return False
        if "/src/" in f"/{normalized}" or normalized.startswith("src/"):
            return False
        if normalized.endswith((".py", ".go", ".rs", ".java", ".kt")):
            return False
    return True


def infer_expected_label(subject: str, files: list[str]) -> tuple[str, str]:
    lowered = subject.strip().lower()
    if _looks_docs_or_config_only(files):
        return "NO_BUMP", "docs_config_only"
    if "breaking change" in lowered or "!: " in lowered or lowered.startswith("feat!"):
        return "MAJOR", "breaking_subject"
    if lowered.startswith("feat"):
        return "MINOR", "feature_subject"
    if any(token in lowered for token in ("remove export", "drop api", "rename export")):
        return "MAJOR", "likely_breaking_api"
    if any(token in lowered for token in ("add export", "new api", "add endpoint")):
        return "MINOR", "likely_additive_api"
    return "PATCH", "default_patch"


def parse_expected_label_from_body(body: str) -> str:
    match = EXPECTED_LABEL_RE.search(body or "")
    return match.group(1).upper() if match else "UNKNOWN"
