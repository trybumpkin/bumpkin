from __future__ import annotations

import ast
import json
from pathlib import Path

LEGACY_MODULE_ROOTS = {
    "comment",
    "config",
    "diff",
    "findings",
    "impact",
    "language",
    "llm",
    "prompt_pack",
    "token_env",
    "version",
}

EXPECTED_REVERSE_IMPORTS: set[tuple[str, str]] = set()

EXPECTED_LEGACY_TO_PACKAGE_IMPORTS = {
    ("src/comment.py", "bumpkin.io.comments"),
    ("src/config.py", "bumpkin.config"),
    ("src/diff.py", "bumpkin.analysis"),
    ("src/eval.py", "bumpkin.eval"),
    ("src/eval.py", "bumpkin.orchestrator"),
    ("src/eval.py", "bumpkin.planner"),
    ("src/eval.py", "bumpkin.policies"),
    ("src/findings.py", "bumpkin.analysis.findings"),
    ("src/impact.py", "bumpkin.analysis.impact"),
    ("src/language.py", "bumpkin.analysis.language"),
    ("src/llm.py", "bumpkin.providers.llm"),
    ("src/main.py", "bumpkin.orchestrator"),
    ("src/main.py", "bumpkin.policies"),
    ("src/prompt_pack.py", "bumpkin.prompt_pack"),
    ("src/release_job.py", "bumpkin.release_job"),
    ("src/token_env.py", "bumpkin.io.tokens"),
    ("src/version.py", "bumpkin.versioning.tags"),
}

GITHUB_INTEGRATION_ALLOWED_BUMPKIN_IMPORT_PREFIXES = (
    "bumpkin.integrations.github",
    "bumpkin.io.github_http",
    "bumpkin.licensing",
)
LICENSING_ALLOWED_BUMPKIN_IMPORT_PREFIXES = ("bumpkin.licensing",)
GITHUB_INTEGRATION_MODULE_ALLOWED_IMPORT_PREFIXES = {
    "recommendations.py": (
        *GITHUB_INTEGRATION_ALLOWED_BUMPKIN_IMPORT_PREFIXES,
        "bumpkin.io",
        "bumpkin.orchestrator",
    ),
}


def _collect_reverse_imports(repo_root: Path) -> set[tuple[str, str]]:
    observed: set[tuple[str, str]] = set()
    package_root = repo_root / "src" / "bumpkin"
    for path in sorted(package_root.rglob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                module_root = node.module.split(".", 1)[0]
                if module_root in LEGACY_MODULE_ROOTS:
                    observed.add((rel, module_root))
                continue
            if not isinstance(node, ast.Import):
                continue
            for alias in node.names:
                module_root = alias.name.split(".", 1)[0]
                if module_root in LEGACY_MODULE_ROOTS:
                    observed.add((rel, module_root))
    return observed


def _collect_legacy_to_package_imports(repo_root: Path) -> set[tuple[str, str]]:
    observed: set[tuple[str, str]] = set()
    src_root = repo_root / "src"
    for path in sorted(src_root.glob("*.py")):
        if path.name == "__init__.py":
            continue
        module = ast.parse(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                module_root = node.module.split(".", 1)[0]
                if module_root == "bumpkin":
                    observed.add((rel, node.module))
                continue
            if not isinstance(node, ast.Import):
                continue
            for alias in node.names:
                if alias.name.split(".", 1)[0] == "bumpkin":
                    observed.add((rel, alias.name))
    return observed


def _collect_bumpkin_imports(path: Path) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    observed: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            if node.level > 0 or not node.module:
                continue
            if node.module.split(".", 1)[0] == "bumpkin":
                observed.add(node.module)
            continue
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            if alias.name.split(".", 1)[0] == "bumpkin":
                observed.add(alias.name)
    return observed


def test_reverse_import_allowlist_is_stable() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    observed = _collect_reverse_imports(repo_root)
    added = sorted(observed - EXPECTED_REVERSE_IMPORTS)
    removed = sorted(EXPECTED_REVERSE_IMPORTS - observed)
    assert not added and not removed, (
        "Reverse import boundary changed.\n"
        f"Added: {added}\n"
        f"Removed: {removed}\n"
        "If this is intentional, update EXPECTED_REVERSE_IMPORTS in this test."
    )


def test_legacy_to_package_inventory_is_stable() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    observed = _collect_legacy_to_package_imports(repo_root)
    added = sorted(observed - EXPECTED_LEGACY_TO_PACKAGE_IMPORTS)
    removed = sorted(EXPECTED_LEGACY_TO_PACKAGE_IMPORTS - observed)
    assert not added and not removed, (
        "Legacy-to-package import inventory changed.\n"
        f"Added: {added}\n"
        f"Removed: {removed}\n"
        "If intentional, update EXPECTED_LEGACY_TO_PACKAGE_IMPORTS."
    )


def test_pyright_config_keeps_quality_floor() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config = json.loads((repo_root / "pyrightconfig.json").read_text(encoding="utf-8"))
    assert config.get("typeCheckingMode") in {"basic", "strict"}

    extra_paths = config.get("extraPaths", [])
    assert isinstance(extra_paths, list)
    assert "./src" in {str(item) for item in extra_paths}


def test_control_and_licensing_import_boundaries() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    violations: list[str] = []

    github_integration_root = repo_root / "src" / "bumpkin" / "integrations" / "github"
    for path in sorted(github_integration_root.glob("*.py")):
        allowed_prefixes = GITHUB_INTEGRATION_MODULE_ALLOWED_IMPORT_PREFIXES.get(
            path.name,
            GITHUB_INTEGRATION_ALLOWED_BUMPKIN_IMPORT_PREFIXES,
        )
        imports = _collect_bumpkin_imports(path)
        for module_name in sorted(imports):
            if module_name.startswith(allowed_prefixes):
                continue
            violations.append(
                f"{path.relative_to(repo_root)} imports disallowed module {module_name!r}"
            )

    licensing_root = repo_root / "src" / "bumpkin" / "licensing"
    for path in sorted(licensing_root.glob("*.py")):
        imports = _collect_bumpkin_imports(path)
        for module_name in sorted(imports):
            if module_name.startswith(LICENSING_ALLOWED_BUMPKIN_IMPORT_PREFIXES):
                continue
            violations.append(
                f"{path.relative_to(repo_root)} imports disallowed module {module_name!r}"
            )

    assert not violations, "Control/licensing import boundary changed:\n" + "\n".join(violations)
