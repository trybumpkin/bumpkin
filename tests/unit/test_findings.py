from collections.abc import Callable
from pathlib import Path

from findings import (
    Finding,
    aggregate_findings,
    build_filesystem_workspace_loader,
    detect_js_ts_export_findings,
    detect_python_api_findings,
    detect_semver_findings,
)


def _workspace_loader(root: Path) -> Callable[[str], list[str] | None]:
    return build_filesystem_workspace_loader(root)


def test_detect_findings_removed_export_is_major() -> None:
    diff_text = """
diff --git a/src/api.ts b/src/api.ts
--- a/src/api.ts
+++ b/src/api.ts
@@ -1,3 +1,2 @@
-export function oldApi(id: string): string { return id; }
+function oldApi(id: string): string { return id; }
"""
    findings = detect_js_ts_export_findings(diff_text)
    assert findings
    assert any(finding.severity == "MAJOR" for finding in findings)
    assert any(finding.rule == "export_symbol_removed" for finding in findings)


def test_detect_findings_optional_param_widening_is_minor() -> None:
    diff_text = """
diff --git a/src/api.ts b/src/api.ts
--- a/src/api.ts
+++ b/src/api.ts
@@ -1,3 +1,3 @@
-export function normalizeTag(tag: string): string { return tag.toLowerCase(); }
+export function normalizeTag(tag: string, opts?: { preserveCase?: boolean }): string { return opts?.preserveCase ? tag : tag.toLowerCase(); }
"""
    findings = detect_js_ts_export_findings(diff_text)
    assert any(finding.rule == "export_signature_optional_widening" for finding in findings)
    assert any(finding.severity == "MINOR" for finding in findings)


def test_detect_findings_required_param_addition_is_major() -> None:
    diff_text = """
diff --git a/src/api.ts b/src/api.ts
--- a/src/api.ts
+++ b/src/api.ts
@@ -1,3 +1,3 @@
-export function normalizeTag(tag: string): string { return tag.toLowerCase(); }
+export function normalizeTag(tag: string, mode: "strict" | "loose"): string { return mode === "strict" ? tag : tag.toLowerCase(); }
"""
    findings = detect_js_ts_export_findings(diff_text)
    assert any(finding.rule == "export_signature_requiredness_tightening" for finding in findings)
    assert any(finding.severity == "MAJOR" for finding in findings)


def test_detect_findings_required_param_tightening_is_major() -> None:
    diff_text = """
diff --git a/src/api.ts b/src/api.ts
--- a/src/api.ts
+++ b/src/api.ts
@@ -1,3 +1,3 @@
-export function normalizeTag(tag?: string): string { return tag ?? ""; }
+export function normalizeTag(tag: string): string { return tag; }
"""
    findings = detect_js_ts_export_findings(diff_text)
    assert any(finding.rule == "export_signature_requiredness_tightening" for finding in findings)
    assert any(finding.severity == "MAJOR" for finding in findings)


def test_detect_findings_return_type_change_is_major() -> None:
    diff_text = """
diff --git a/src/api.ts b/src/api.ts
--- a/src/api.ts
+++ b/src/api.ts
@@ -1,3 +1,3 @@
-export function getStatus(): "ok" | "error" { return "ok"; }
+export function getStatus(): "ok" { return "ok"; }
"""
    findings = detect_js_ts_export_findings(diff_text)
    assert any(finding.rule == "export_return_type_changed" for finding in findings)
    assert any(finding.severity == "MAJOR" for finding in findings)


def test_detect_findings_export_rename_with_same_signature_is_single_major() -> None:
    diff_text = """
diff --git a/src/api.ts b/src/api.ts
--- a/src/api.ts
+++ b/src/api.ts
@@ -1,3 +1,3 @@
-export function oldName(id: string): string { return id; }
+export function newName(id: string): string { return id; }
"""
    findings = detect_js_ts_export_findings(diff_text)
    assert len(findings) == 1
    assert findings[0].severity == "MAJOR"
    assert findings[0].rule == "export_symbol_renamed"


def test_detect_findings_export_markers_without_rule_match_requests_manual_review() -> None:
    diff_text = """
diff --git a/src/index.ts b/src/index.ts
--- a/src/index.ts
+++ b/src/index.ts
@@ -1,2 +1,2 @@
-export { helper }
+export { helper as helper }
"""
    findings = detect_js_ts_export_findings(diff_text)
    assert len(findings) == 1
    assert findings[0].severity == "MANUAL_REVIEW"
    assert findings[0].rule == "export_change_unclassified"


def test_detect_findings_export_behavior_change_without_signature_delta_is_patch() -> None:
    diff_text = """
diff --git a/src/api.ts b/src/api.ts
--- a/src/api.ts
+++ b/src/api.ts
@@ -1,2 +1,2 @@
-export function health(): string { return "ok"; }
+export function health(): string { return "healthy"; }
"""
    findings = detect_js_ts_export_findings(diff_text)
    assert len(findings) == 1
    assert findings[0].severity == "PATCH"
    assert findings[0].rule == "export_behavior_change_no_signature_delta"


def test_detect_findings_ignores_non_js_ts_files() -> None:
    diff_text = """
diff --git a/src/api.py b/src/api.py
--- a/src/api.py
+++ b/src/api.py
@@ -1,2 +1,2 @@
-def helper() -> str: return "ok"
+def helper() -> str: return "fine"
"""
    findings = detect_js_ts_export_findings(diff_text)
    assert findings == []


def test_detect_python_findings_public_function_removed_is_major() -> None:
    diff_text = """
diff --git a/pydantic_settings/api.py b/pydantic_settings/api.py
--- a/pydantic_settings/api.py
+++ b/pydantic_settings/api.py
@@ -1,3 +1,2 @@
-def load_settings(path: str) -> str:
-    return path
+pass
"""
    findings = detect_python_api_findings(diff_text)
    assert any(finding.severity == "MAJOR" for finding in findings)
    assert any(finding.rule == "export_symbol_removed" for finding in findings)


def test_detect_python_findings_public_constructor_optional_widening_is_minor() -> None:
    diff_text = """
diff --git a/pydantic_settings/sources/providers/toml.py b/pydantic_settings/sources/providers/toml.py
--- a/pydantic_settings/sources/providers/toml.py
+++ b/pydantic_settings/sources/providers/toml.py
@@ -1,3 +1,3 @@
 class TomlConfigSettingsSource:
-    def __init__(self, settings_cls: type[BaseSettings], toml_file: PathType | None = DEFAULT_PATH):
+    def __init__(self, settings_cls: type[BaseSettings], toml_file: PathType | None = DEFAULT_PATH, toml_table_header: tuple[str, ...] = ()):
         pass
"""
    findings = detect_python_api_findings(diff_text)
    assert any(finding.rule == "export_signature_optional_widening" for finding in findings)
    assert any(finding.severity == "MINOR" for finding in findings)


def test_detect_python_findings_support_floor_raise_is_major() -> None:
    diff_text = """
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,2 +1,2 @@
-requires-python = ">=3.9"
+requires-python = ">=3.10"
"""
    findings = detect_python_api_findings(diff_text)
    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_support_floor_raise_in_nested_pyproject() -> None:
    diff_text = """
diff --git a/packages/internal-tool/pyproject.toml b/packages/internal-tool/pyproject.toml
--- a/packages/internal-tool/pyproject.toml
+++ b/packages/internal-tool/pyproject.toml
@@ -1,2 +1,2 @@
-requires-python = ">=3.9"
+requires-python = ">=3.10"
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_support_floor_raise_in_python_source_root_pyproject() -> None:
    diff_text = """
diff --git a/python/acme/pyproject.toml b/python/acme/pyproject.toml
--- a/python/acme/pyproject.toml
+++ b/python/acme/pyproject.toml
@@ -1,2 +1,2 @@
-requires-python = ">=3.9"
+requires-python = ">=3.10"
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_support_floor_raise_in_lib_source_root_setup_cfg() -> None:
    diff_text = """
diff --git a/lib/demo/setup.cfg b/lib/demo/setup.cfg
--- a/lib/demo/setup.cfg
+++ b/lib/demo/setup.cfg
@@ -1,2 +1,2 @@
 [options]
-python_requires = >=3.9
+python_requires = >=3.10
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_support_floor_raise_in_services_setup_py() -> None:
    diff_text = """
diff --git a/services/api/setup.py b/services/api/setup.py
--- a/services/api/setup.py
+++ b/services/api/setup.py
@@ -1,3 +1,3 @@
 setup(
-    python_requires=">=3.9",
+    python_requires=">=3.10",
 )
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_support_floor_raise_in_root_setup_cfg() -> None:
    diff_text = """
diff --git a/setup.cfg b/setup.cfg
--- a/setup.cfg
+++ b/setup.cfg
@@ -1,2 +1,2 @@
 [options]
-python_requires = >=3.9
+python_requires = >=3.10
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_support_floor_raise_in_root_poetry_pyproject() -> None:
    diff_text = """
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,3 +1,3 @@
 [tool.poetry.dependencies]
-python = ">=3.9,<4.0"
+python = ">=3.10,<4.0"
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_ignores_custom_pyproject_requires_python_metadata() -> None:
    diff_text = """
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,3 +1,3 @@
 [tool.custom]
-requires-python = ">=3.9"
+requires-python = ">=3.10"
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_support_floor_raise_in_project_pyproject() -> None:
    diff_text = """
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,3 +1,3 @@
 [project]
-requires-python = ">=3.9"
+requires-python = ">=3.10"
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_support_floor_raise_with_compatible_release_constraint() -> None:
    diff_text = """
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,2 +1,2 @@
-requires-python = "~=3.8"
+requires-python = "~=3.9"
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_support_floor_raise_with_strict_greater_than_constraint() -> None:
    diff_text = """
diff --git a/setup.cfg b/setup.cfg
--- a/setup.cfg
+++ b/setup.cfg
@@ -1,2 +1,2 @@
 [options]
-python_requires = >3.8
+python_requires = >3.9
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_support_floor_raise_with_poetry_caret_constraint() -> None:
    diff_text = """
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,3 +1,3 @@
 [tool.poetry.dependencies]
-python = "^3.9"
+python = "^3.10"
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_support_floor_raise_with_wildcard_equality_constraint() -> None:
    diff_text = """
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,2 +1,2 @@
-requires-python = "==3.9.*"
+requires-python = "==3.10.*"
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_support_floor_raise_in_root_setup_py() -> None:
    diff_text = """
diff --git a/setup.py b/setup.py
--- a/setup.py
+++ b/setup.py
@@ -1,3 +1,3 @@
 setup(
-    python_requires=">=3.9",
+    python_requires=">=3.10",
 )
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_support_floor_raise_in_setup_py_named_constant() -> None:
    diff_text = """
diff --git a/setup.py b/setup.py
--- a/setup.py
+++ b/setup.py
@@ -1,4 +1,4 @@
-PY_REQ = ">=3.9"
+PY_REQ = ">=3.10"
 setup(
     python_requires=PY_REQ,
 )
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_support_floor_raise_in_setup_py_helper_return() -> None:
    diff_text = """
diff --git a/setup.py b/setup.py
--- a/setup.py
+++ b/setup.py
@@ -1,6 +1,6 @@
 def py_req():
-    return ">=3.9"
+    return ">=3.10"

 setup(
     python_requires=py_req(),
 )
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_detects_reexported_private_helper_from_parent_package_under_python_source_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "python" / "acme" / "pkg"
    package_dir.mkdir(parents=True)
    (tmp_path / "python" / "acme" / "__init__.py").write_text(
        "from .pkg.client import _create_client as Client\n",
        encoding="utf-8",
    )
    target = package_dir / "client.py"
    target.write_text(
        "def _create_client(timeout: int = 1) -> int:\n    return timeout\n",
        encoding="utf-8",
    )
    rel = target.relative_to(tmp_path).as_posix()
    diff_text = f"""
diff --git a/{rel} b/{rel}
--- a/{rel}
+++ b/{rel}
@@ -1,2 +1,2 @@
-def _create_client(timeout: int = 1) -> int:
+def _create_client(timeout: int) -> int:
     return timeout
"""
    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_signature_requiredness_tightening"
        and "_create_client" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_reexported_private_helper_from_parent_package_under_packages_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "packages" / "foo"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from foo.client import _create_client as Client\n",
        encoding="utf-8",
    )
    target = package_dir / "client.py"
    target.write_text(
        "def _create_client(timeout: int = 1) -> int:\n    return timeout\n",
        encoding="utf-8",
    )
    rel = target.relative_to(tmp_path).as_posix()
    diff_text = f"""
diff --git a/{rel} b/{rel}
--- a/{rel}
+++ b/{rel}
@@ -1,2 +1,2 @@
-def _create_client(timeout: int = 1) -> int:
+def _create_client(timeout: int) -> int:
     return timeout
"""
    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_signature_requiredness_tightening"
        and "_create_client" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_reexported_private_helper_from_api_facade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "api.py").write_text(
        "from .client import _create_client as Client\n",
        encoding="utf-8",
    )
    target = package_dir / "client.py"
    target.write_text(
        "def _create_client(timeout: int = 1) -> int:\n    return timeout\n",
        encoding="utf-8",
    )
    rel = target.relative_to(tmp_path).as_posix()
    diff_text = f"""
diff --git a/{rel} b/{rel}
--- a/{rel}
+++ b/{rel}
@@ -1,2 +1,2 @@
-def _create_client(timeout: int = 1) -> int:
+def _create_client(timeout: int) -> int:
     return timeout
"""
    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_signature_requiredness_tightening"
        and "_create_client" in finding.title
        for finding in findings
    )


def test_detect_python_findings_treats_pyw_diffs_as_python() -> None:
    diff_text = """
diff --git a/tools/release.pyw b/tools/release.pyw
--- a/tools/release.pyw
+++ b/tools/release.pyw
@@ -1,2 +1,2 @@
-def public_api(timeout: int = 1) -> int:
+def public_api(timeout: int) -> int:
     return timeout
"""
    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_signature_requiredness_tightening" and "public_api" in finding.title
        for finding in findings
    )


def test_detect_python_findings_ignores_internal_api_modules_without_reexport_evidence() -> None:
    diff_text = """
diff --git a/src/internal/api.py b/src/internal/api.py
--- a/src/internal/api.py
+++ b/src/internal/api.py
@@ -1,2 +1,2 @@
-def helper() -> int:
+def helper_v2() -> int:
     return 1
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_ignores_nested_classes_under_private_intermediate_scope() -> None:
    diff_text = """
diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,4 +1,4 @@
 class Public:
     class _Private:
-        class Nested:
+        class RenamedNested:
             pass
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_ignores_private_methods_on_public_classes() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,3 +1,3 @@
 class Public:
-    def _helper(self, timeout: int = 1) -> int:
+    def _helper(self, timeout: int) -> int:
         return timeout
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_ignores_setup_py_python_requires_comments() -> None:
    diff_text = """
diff --git a/setup.py b/setup.py
--- a/setup.py
+++ b/setup.py
@@ -1,1 +1,1 @@
-# python_requires=">=3.9"
+# python_requires=">=3.10"
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_support_floor_raise_in_setup_cfg_continuation_line() -> None:
    diff_text = """
diff --git a/setup.cfg b/setup.cfg
--- a/setup.cfg
+++ b/setup.cfg
@@ -1,3 +1,3 @@
 [options]
 python_requires =
-    >=3.9
+    >=3.10
"""
    findings = detect_python_api_findings(diff_text)

    assert len(findings) == 1
    assert findings[0].rule == "python_requires_floor_raised"
    assert findings[0].severity == "MAJOR"


def test_detect_python_findings_ignores_setup_py_python_requires_in_multiline_string() -> None:
    diff_text = """
diff --git a/setup.py b/setup.py
--- a/setup.py
+++ b/setup.py
@@ -1,6 +1,6 @@
 LONG_DESCRIPTION = \"\"\"
-python_requires=\">=3.9\"
+python_requires=\">=3.10\"
 \"\"\"
 setup(
     name=\"demo\",
 )
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_semver_findings_combines_language_detectors() -> None:
    diff_text = """
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,2 +1,2 @@
-requires-python = ">=3.9"
+requires-python = ">=3.10"
"""
    findings = detect_semver_findings(diff_text)
    assert any(finding.rule == "python_requires_floor_raised" for finding in findings)


def test_detect_semver_findings_assigns_unique_ids_across_languages() -> None:
    diff_text = """
diff --git a/src/api.ts b/src/api.ts
--- a/src/api.ts
+++ b/src/api.ts
@@ -0,0 +1 @@
+export function alpha() {}
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -0,0 +1,2 @@
+def beta():
+    return 1
"""
    findings = detect_semver_findings(diff_text)

    assert len(findings) == 2
    assert len({finding.id for finding in findings}) == 2


def test_detect_python_findings_keeps_constructor_changes_bound_to_their_own_classes() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,8 +1,8 @@
 class A:
-    def __init__(self, value: str):
+    def __init__(self, value: str, extra: str | None = None):
         self.value = value

 class B:
-    def __init__(self, count: int = 0):
+    def __init__(self, count: int):
         self.count = count
"""
    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_signature_optional_widening" and "A.__init__" in finding.title
        for finding in findings
    )
    assert any(
        finding.rule == "export_signature_requiredness_tightening" and "B.__init__" in finding.title
        for finding in findings
    )


def test_detect_python_findings_ignores_nested_internal_class_changes() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,6 +1,6 @@
 def outer():
     class InternalThing:
-        def __init__(self, value: str):
+        def __init__(self, value: str, strict: bool):
             self.value = value
     return InternalThing
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_respects_unchanged___all___exports() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,4 @@
 __all__ = ["public_api"]
-def helper(value: str = "x") -> str:
+def helper(value: str) -> str:
     return value
 def public_api() -> str:
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_detects_multiline_public_function_tightening() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,5 +1,5 @@
 def public_api(
     name: str,
-    enabled: bool = True,
+    enabled: bool,
 ) -> str:
     return name
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_signature_requiredness_tightening" for finding in findings)
    assert any(finding.severity == "MAJOR" for finding in findings)


def test_detect_python_findings_detects_multiline_constructor_tightening() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,6 +1,6 @@
 class Config:
     def __init__(
         self,
-        enabled: bool = True,
+        enabled: bool,
     ) -> None:
         self.enabled = enabled
"""
    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_signature_requiredness_tightening"
        and "Config.__init__" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_async_public_function_tightening() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,2 +1,2 @@
-async def fetch_user(user_id: str, expand: bool = False) -> dict:
+async def fetch_user(user_id: str, expand: bool) -> dict:
     return {"id": user_id}
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_signature_requiredness_tightening" for finding in findings)
    assert any("fetch_user" in finding.title for finding in findings)


def test_detect_python_findings_detects_async_contract_flip() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,2 +1,2 @@
-async def fetch_user(user_id: str) -> dict:
+def fetch_user(user_id: str) -> dict:
     return {"id": user_id}
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_async_contract_changed" for finding in findings)
    assert any("fetch_user" in finding.title for finding in findings)


def test_detect_python_findings_prioritizes_async_flip_over_optional_widening() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,2 +1,2 @@
-async def fetch_user(user_id: str) -> dict:
+def fetch_user(user_id: str, expand: bool = False) -> dict:
     return {"id": user_id}
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_async_contract_changed" for finding in findings)
    assert not any(finding.rule == "export_signature_optional_widening" for finding in findings)


def test_detect_python_findings_detects_async_public_function_removal() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,2 +1,1 @@
-async def fetch_user(user_id: str) -> dict:
-    return {"id": user_id}
+pass
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any(finding.severity == "MAJOR" for finding in findings)


def test_detect_python_findings_detects_return_type_only_change() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,2 +1,2 @@
-def public_api(x: int) -> int:
+def public_api(x: int) -> str:
     return x
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_return_type_changed" for finding in findings)
    assert any("public_api" in finding.title for finding in findings)


def test_detect_python_findings_treats_required_to_optional_as_widening() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,2 +1,2 @@
-def public_api(x: int) -> int:
+def public_api(x: int = 1) -> int:
     return x
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_signature_optional_widening" for finding in findings)
    assert not any(finding.rule == "export_signature_incompatible_change" for finding in findings)


def test_detect_python_findings_detects_public_class_method_tightening() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,3 +1,3 @@
 class Client:
-    def fetch(self, user_id: str = "1") -> dict:
+    def fetch(self, user_id: str) -> dict:
         return {"id": user_id}
"""
    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_signature_requiredness_tightening"
        and "Client.fetch" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_public_class_method_rename() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,3 +1,3 @@
 class Client:
-    def fetch(self, user_id: str) -> dict:
+    def parse(self, user_id: str) -> dict:
         return {"id": user_id}
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_renamed" for finding in findings)
    assert any("Client.fetch -> Client.parse" in finding.title for finding in findings)


def test_detect_python_findings_detects_staticmethod_tightening() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,4 @@
 class Client:
     @staticmethod
-    def parse(value: str = "x") -> str:
+    def parse(value: str) -> str:
         return value
"""
    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_signature_requiredness_tightening"
        and "Client.parse" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_staticmethod_to_instance_binding_change() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,3 @@
 class Client:
-    @staticmethod
     def parse(value: str) -> str:
         return value
"""
    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_method_binding_changed" and "Client.parse" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_classmethod_to_instance_binding_change() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,3 @@
 class Client:
-    @classmethod
     def parse(cls, value: str) -> str:
         return value
"""
    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_method_binding_changed" and "Client.parse" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_property_to_method_binding_change() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,3 @@
 class Client:
-    @property
     def status(self) -> str:
         return "ok"
"""
    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_method_binding_changed" and "Client.status" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_property_setter_to_method_binding_change() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,3 @@
 class Client:
-    @status.setter
     def status(self, value: str) -> None:
         self._status = value
"""
    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_method_binding_changed" and "Client.status" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_nested_public_class_method_tightening() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,4 @@
 class Outer:
     class Inner:
-        def api(self, value: int = 1) -> int:
+        def api(self, value: int) -> int:
             return value
"""
    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_signature_requiredness_tightening"
        and "Outer.Inner.api" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_nested_public_class_removal() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,2 @@
 class Outer:
-    class Inner:
-        pass
     pass
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Outer.Inner" in finding.title for finding in findings)


def test_detect_python_findings_detects_nested_public_class_addition() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,2 +1,4 @@
 class Outer:
+    class Inner:
+        pass
     pass
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("Outer.Inner" in finding.title for finding in findings)


def test_detect_python_findings_respects_multiline___all___exports() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,7 +1,7 @@
 __all__ = [
-    "old_api",
+    "new_api",
 ]
-def old_api() -> str:
+def new_api() -> str:
     return "old"
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_renamed" for finding in findings)
    assert any(finding.severity == "MAJOR" for finding in findings)


def test_detect_python_findings_respects_explicit_empty___all__() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,2 @@
 __all__ = []
-def helper() -> str:
-    return "x"
+pass
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_respects_private_only___all__() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,2 @@
 __all__ = ["_internal"]
-def helper() -> str:
-    return "x"
+pass
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_respects_explicit_underscore___all___exports() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,4 @@
 __all__ = ["_legacy"]
-def _legacy(timeout: int = 1) -> int:
+def _legacy(timeout: int) -> int:
     return timeout
"""
    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_signature_requiredness_tightening" and "_legacy" in finding.title
        for finding in findings
    )


def test_detect_python_findings_preserves_removed_exports_when___all___is_introduced() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,2 +1,4 @@
+__all__ = []
+
-def removed_api() -> int:
-    return 1
+pass
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("removed_api" in finding.title for finding in findings)


def test_detect_python_findings_detects_reexport_target_change_under_explicit___all__() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,2 +1,2 @@
 __all__ = ["Client"]
-from .client import Client
+from .client import ServiceClient as Client
"""
    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_reexport_target_changed" and "Client" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_removed_explicit_reexport_binding_under___all__() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,2 +1,2 @@
 __all__ = ["Client"]
-from .client import Client
+from .client import Client as ServiceClient
"""
    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_symbol_removed" and "Client" in finding.title
        for finding in findings
    )


def test_detect_python_findings_ignores_comment_only_class_mentions() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-# class LegacyApi handles old clients
+# class ModernApi handles old clients
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_ignores_docstring_class_mentions() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-\"\"\"Compatibility note: class LegacyApi is gone.\"\"\"
+\"\"\"Compatibility note: class ModernApi is gone.\"\"\"
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_filters_class_fallback_through___all__() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,7 @@
 __all__ = ["public_api"]
+
+class InternalHelper:
+    pass
 def public_api() -> str:
     return "ok"
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_filters_removed_class_fallback_through___all__() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,7 +1,4 @@
 __all__ = ["public_api"]
-class InternalHelper:
-    pass
 def public_api() -> str:
     return "ok"
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_detects_public_constant_removal_without___all__() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,3 +1,1 @@
-PUBLIC_TIMEOUT = 30
-
 def public_api() -> str:
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("PUBLIC_TIMEOUT" in finding.title for finding in findings)


def test_detect_python_findings_detects_public_type_alias_removal_without___all__() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,3 +1,1 @@
-UserId = str
-
 def public_api() -> str:
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("UserId" in finding.title for finding in findings)


def test_detect_python_findings_detects_public_constant_addition_without___all__() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,3 @@
+DEFAULT_TIMEOUT = 30
+
 def public_api() -> str:
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("DEFAULT_TIMEOUT" in finding.title for finding in findings)


def test_detect_python_findings_does_not_suppress_real_additions_with_workspace_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    target = tmp_path / "pkg" / "api.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        'DEFAULT_TIMEOUT = 30\n\ndef public_api() -> str:\n    return "ok"\n',
        encoding="utf-8",
    )
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,3 @@
+DEFAULT_TIMEOUT = 30
+
 def public_api() -> str:
"""
    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("DEFAULT_TIMEOUT" in finding.title for finding in findings)


def test_detect_python_findings_requests_manual_review_when___all___is_dynamic() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,4 @@
 __all__ = [name for name in ("public_api",)]
-def public_api(value: str = "x") -> str:
+def public_api(value: str) -> str:
     return value
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "python_all_unresolved" for finding in findings)
    assert any(finding.severity == "MANUAL_REVIEW" for finding in findings)


def test_detect_python_findings_keeps_deterministic_changes_alongside_unresolved___all__() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,6 +1,6 @@
 __all__ = compute_exports("v1")

-def public_api(x: int = 1) -> int:
+def public_api(x: int) -> int:
     return x

 def helper():
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "python_all_unresolved" for finding in findings)
    assert any(
        finding.rule == "export_signature_requiredness_tightening" and "public_api" in finding.title
        for finding in findings
    )


def test_detect_python_findings_does_not_promote_helper_changes_when___all___is_dynamic() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,6 +1,6 @@
 __all__ = [name for name in ("public_api",)]

-def helper(value: str = "x") -> str:
+def helper(value: str) -> str:
     return value

 def public_api() -> str:
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "python_all_unresolved" for finding in findings)
    assert not any("helper" in finding.title for finding in findings)


def test_detect_python_findings_requests_manual_review_for_private_change_with_dynamic___all__() -> (
    None
):
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,4 @@
 __all__ = compute_exports()
-def _helper(x: int = 1) -> int:
+def _helper(x: int) -> int:
     return x
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "python_all_unresolved" for finding in findings)
    assert not any("_helper" in finding.title for finding in findings)


def test_detect_python_findings_uses_workspace___all___contract_outside_hunk(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    target = tmp_path / "pkg" / "api.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '__all__ = ["public_api"]\n\n'
        "def helper(value: str) -> str:\n"
        "    return value\n\n"
        "def public_api() -> str:\n"
        '    return "ok"\n',
        encoding="utf-8",
    )
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -20,3 +20,3 @@
-def helper(value: str = "x") -> str:
+def helper(value: str) -> str:
     return value
"""
    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert findings == []


def test_detect_python_findings_infers_constructor_class_from_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    target = tmp_path / "pkg" / "api.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "class Example:\n"
        '    """docstring"""\n'
        "\n"
        "    flag = True\n"
        "\n"
        "    def __init__(self, count: int):\n"
        "        self.count = count\n",
        encoding="utf-8",
    )
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -10,4 +10,4 @@
-    def __init__(self, count: int = 0):
+    def __init__(self, count: int):
         self.count = count
"""
    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(finding.rule == "export_signature_requiredness_tightening" for finding in findings)
    assert any("Example.__init__" in finding.title for finding in findings)


def test_detect_python_findings_detects_top_level_reexport_rename_without___all__() -> None:
    diff_text = """
diff --git a/pkg/__init__.py b/pkg/__init__.py
--- a/pkg/__init__.py
+++ b/pkg/__init__.py
@@ -1,1 +1,1 @@
-from .api import Client
+from .api import ServiceClient
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_detects_api_module_reexport_rename_without___all__(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from .api import ServiceClient\n",
        encoding="utf-8",
    )
    target = package_dir / "api.py"
    target.write_text("from .client import ServiceClient\n", encoding="utf-8")
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -1,1 +1,1 @@
-from .client import Client
+from .client import ServiceClient
"""
    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_ignores_private_nested_class_methods_in_hunk() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,5 +1,5 @@
 class Public:
     class _Helper:
-        def do(self, x: int = 1) -> int:
+        def do(self, x: int) -> int:
             return x
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_ignores_private_nested_class_methods_via_workspace_inference(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    target = tmp_path / "pkg" / "api.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "class Public:\n"
        "    class _Helper:\n"
        "        def do(self, x: int) -> int:\n"
        "            return x\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -3,2 +3,2 @@
-        def do(self, x: int = 1) -> int:
+        def do(self, x: int) -> int:
             return x
"""
    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert findings == []


def test_detect_python_findings_detects_direct_api_facade_import_rename_without_root_reexport() -> (
    None
):
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-from .client import Client
+from .client import ServiceClient
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_detects_api_facade_import_rename_with_metadata() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,2 +1,2 @@
 __version__ = "1.0"
-from .client import Client
+from .client import ServiceClient
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_detects_absolute_api_module_reexport_rename(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from pkg.api import ServiceClient\n",
        encoding="utf-8",
    )
    target = package_dir / "api.py"
    target.write_text("from pkg.client import ServiceClient\n", encoding="utf-8")
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-from pkg.client import Client
+from pkg.client import ServiceClient
"""
    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_detects_nested_src_absolute_api_reexport_rename(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "src" / "myorg" / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from myorg.pkg.api import ServiceClient\n",
        encoding="utf-8",
    )
    target = package_dir / "api.py"
    target.write_text("from myorg.pkg.client import ServiceClient\n", encoding="utf-8")
    diff_text = """
diff --git a/src/myorg/pkg/api.py b/src/myorg/pkg/api.py
--- a/src/myorg/pkg/api.py
+++ b/src/myorg/pkg/api.py
@@ -1,1 +1,1 @@
-from myorg.pkg.client import Client
+from myorg.pkg.client import ServiceClient
"""
    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_detects_absolute_api_module_reexport_rename_in_src_layout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "src" / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from pkg.api import ServiceClient\n",
        encoding="utf-8",
    )
    target = package_dir / "api.py"
    target.write_text("from pkg.client import ServiceClient\n", encoding="utf-8")
    diff_text = """
diff --git a/src/pkg/api.py b/src/pkg/api.py
--- a/src/pkg/api.py
+++ b/src/pkg/api.py
@@ -1,1 +1,1 @@
-from pkg.client import Client
+from pkg.client import ServiceClient
"""
    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_detects_absolute_init_reexport_rename() -> None:
    diff_text = """
diff --git a/pkg/__init__.py b/pkg/__init__.py
--- a/pkg/__init__.py
+++ b/pkg/__init__.py
@@ -1,1 +1,1 @@
-from pkg.client import Client
+from pkg.client import ServiceClient
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_ignores_ordinary_top_level_import_swaps() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,3 +1,3 @@
-import os
+import pathlib
 def public_api() -> str:
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_ignores_regular_module_typing_import_churn() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,3 +1,3 @@
-from typing import Any
+from typing import Any, Literal
 def public_api() -> str:
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_ignores_optional_default_only_change() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-def public_api(limit: int = 10) -> int:
+def public_api(limit: int = 20) -> int:
"""

    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_treats_keyword_only_optional_addition_as_widening() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-def public_api(limit: int = 10) -> int:
+def public_api(limit: int = 10, *, verbose: bool = False) -> int:
"""

    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_signature_optional_widening" for finding in findings)
    assert not any(
        finding.rule == "export_signature_requiredness_tightening" for finding in findings
    )


def test_detect_python_findings_ignores_unexported_import_only_regular_module() -> None:
    diff_text = """
diff --git a/pkg/models.py b/pkg/models.py
--- a/pkg/models.py
+++ b/pkg/models.py
@@ -1,1 +1,1 @@
-from .compat import UserId
+from .compat import UserKey
"""

    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_ignores_unexported_regular_module_signature_changes_with_workspace(
    tmp_path: Path,
) -> None:
    workspace_loader = _workspace_loader(tmp_path)
    target = tmp_path / "pkg" / "utils.py"
    target.parent.mkdir(parents=True)
    target.write_text("def helper(x):\n    return x\n", encoding="utf-8")
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -1,2 +1,2 @@
-def helper(x=1):
+def helper(x):
     return x
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert findings == []


def test_detect_python_findings_ignores_test_module_signature_changes_with_workspace(
    tmp_path: Path,
) -> None:
    workspace_loader = _workspace_loader(tmp_path)
    target = tmp_path / "tests" / "test_utils.py"
    target.parent.mkdir(parents=True)
    target.write_text("def helper(x):\n    return x\n", encoding="utf-8")
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -1,2 +1,2 @@
-def helper(x=1):
+def helper(x):
     return x
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert findings == []


def test_detect_python_findings_detects_removed_export_with_workspace___all___outside_hunk(
    tmp_path: Path,
) -> None:
    workspace_loader = _workspace_loader(tmp_path)
    target = tmp_path / "pkg" / "api.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        '__all__ = ["public_api"]\n\n\ndef keep() -> int:\n    return 1\n', encoding="utf-8"
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -3,4 +3,2 @@
-def public_api() -> int:
-    return 1
-
 def keep() -> int:
     return 1
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("public_api" in finding.title for finding in findings)


def test_detect_python_findings_detects_constructor_tightening_when_body_anchor_changes(
    tmp_path: Path,
) -> None:
    workspace_loader = _workspace_loader(tmp_path)
    target = tmp_path / "pkg" / "api.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "class A:\n    def __init__(self, x):\n        self.value = int(x)\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -2,2 +2,2 @@
-    def __init__(self, x=1):
-        self.value = x
+    def __init__(self, x):
+        self.value = int(x)
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_signature_requiredness_tightening" and "A.__init__" in finding.title
        for finding in findings
    )


def test_detect_python_findings_requests_manual_review_for_nested_constructor_change() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,4 @@
 class Outer:
     class Inner:
-        def __init__(self, value: int = 0):
+        def __init__(self, value: int):
             self.value = value
"""

    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "python_nested_constructor_changed" for finding in findings)
    assert not any("Outer.__init__" in finding.title for finding in findings)


def test_detect_python_findings_keeps_nested_constructor_review_alongside_other_findings() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,7 @@
 class Outer:
     class Inner:
-        def __init__(self, value: int = 0):
+        def __init__(self, value: int):
             self.value = value
+
+def public_api():
+    return 1
"""

    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_symbol_added" and "public_api" in finding.title
        for finding in findings
    )
    assert any(finding.rule == "python_nested_constructor_changed" for finding in findings)


def test_detect_python_findings_requests_manual_review_for_ambiguous_constructor_match(
    tmp_path: Path,
) -> None:
    workspace_loader = _workspace_loader(tmp_path)
    target = tmp_path / "pkg" / "api.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "class A:\n    def __init__(self, x=1):\n        self.value = int(x)\n\n"
        "class B:\n    def __init__(self, x=1):\n        self.value = int(x)\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -2,2 +2,2 @@
-    def __init__(self, x=1):
-        self.value = int(x)
+    def __init__(self, x):
+        self.value = int(x)
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(finding.rule == "python_constructor_ambiguous" for finding in findings)


def test_detect_python_findings_keeps_ambiguous_constructor_review_alongside_other_findings(
    tmp_path: Path,
) -> None:
    workspace_loader = _workspace_loader(tmp_path)
    target = tmp_path / "pkg" / "api.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "class A:\n    def __init__(self, x=1):\n        self.value = int(x)\n\n"
        "class B:\n    def __init__(self, x=1):\n        self.value = int(x)\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -2,2 +2,5 @@
-    def __init__(self, x=1):
-        self.value = int(x)
+    def __init__(self, x):
+        self.value = int(x)
+
+def public_api():
+    return 1
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_symbol_added" and "public_api" in finding.title
        for finding in findings
    )
    assert any(finding.rule == "python_constructor_ambiguous" for finding in findings)


def test_detect_python_findings_does_not_treat_newly_public_symbol_as_old_signature_break() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,6 +1,6 @@
-__all__ = ["public_api"]
+__all__ = ["public_api", "helper"]

 def public_api(x=1):
     return x

-def helper(x=1, y=2):
+def helper(x, y):
     return x + y
"""

    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_symbol_added" and "helper" in finding.title for finding in findings
    )
    assert not any(
        finding.rule == "export_signature_requiredness_tightening" and "helper" in finding.title
        for finding in findings
    )


def test_detect_python_findings_ignores_internal_api_module_reexport_churn() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,4 @@
-from .compat import UserId
+from .compat import UserKey
 def public_api() -> str:
     return "ok"
"""

    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_requests_manual_review_for_dynamic___all___only_change() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-__all__ = compute_exports("v1")
+__all__ = compute_exports("v2")
"""

    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "python_all_unresolved" for finding in findings)


def test_detect_python_findings_supports_multiline___all___set_literals() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,5 +1,5 @@
 __all__ = {
     "public_api",
 }
-def public_api(x: int = 1) -> int:
+def public_api(x: int) -> int:
     return x
"""

    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_signature_requiredness_tightening" and "public_api" in finding.title
        for finding in findings
    )
    assert not any(finding.rule == "python_all_unresolved" for finding in findings)


def test_detect_python_findings_respects_annotated___all___contracts() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,4 @@
 __all__: list[str] = ["public_api"]
-def helper(x=1):
+def helper(x):
     return x
"""

    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_detects_stub_file_signature_tightening() -> None:
    diff_text = """
diff --git a/pkg/api.pyi b/pkg/api.pyi
--- a/pkg/api.pyi
+++ b/pkg/api.pyi
@@ -1,1 +1,1 @@
-def public_api(x: int = ...) -> int: ...
+def public_api(x: int) -> int: ...
"""

    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_signature_requiredness_tightening" for finding in findings)
    assert any("public_api" in finding.title for finding in findings)


def test_detect_python_findings_targets_changed_stub_symbol_not_previous_single_line_def() -> None:
    diff_text = """
diff --git a/pkg/api.pyi b/pkg/api.pyi
--- a/pkg/api.pyi
+++ b/pkg/api.pyi
@@ -1,2 +1,2 @@
 def stable() -> int: ...
-def changed(x: int = ...) -> int: ...
+def changed(x: int) -> int: ...
"""

    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_signature_requiredness_tightening" and "changed" in finding.title
        for finding in findings
    )
    assert not any("stable" in finding.title for finding in findings)


def test_detect_python_findings_ignores_inline_comment_only_signature_edits_in_stubs() -> None:
    diff_text = """
diff --git a/pkg/api.pyi b/pkg/api.pyi
--- a/pkg/api.pyi
+++ b/pkg/api.pyi
@@ -1,2 +1,2 @@
-def stable() -> int: ...
+def stable() -> int: ...  # stable helper
 def changed(x: int = ...) -> int: ...
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_detects_removed_stub_overload() -> None:
    diff_text = """
diff --git a/pkg/api.pyi b/pkg/api.pyi
--- a/pkg/api.pyi
+++ b/pkg/api.pyi
@@ -1,2 +1,1 @@
 def public_api(x: int) -> int: ...
-def public_api(x: str) -> int: ...
"""

    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_overload_removed" for finding in findings)
    assert any("public_api" in finding.title for finding in findings)


def test_detect_python_findings_detects_stub_package_reexport_rename() -> None:
    diff_text = """
diff --git a/pkg/__init__.pyi b/pkg/__init__.pyi
--- a/pkg/__init__.pyi
+++ b/pkg/__init__.pyi
@@ -1,1 +1,1 @@
-from .client import Client
+from .client import ServiceClient
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_detects_root_api_absolute_import_alias_rename() -> None:
    diff_text = """
diff --git a/api.py b/api.py
--- a/api.py
+++ b/api.py
@@ -1,1 +1,1 @@
-import project.client as Client
+import project.client as ServiceClient
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_detects_src_api_absolute_import_alias_rename() -> None:
    diff_text = """
diff --git a/src/api.py b/src/api.py
--- a/src/api.py
+++ b/src/api.py
@@ -1,1 +1,1 @@
-import src.client as Client
+import src.client as ServiceClient
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_detects_stub_api_facade_reexport_rename(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.pyi").write_text(
        "from .api import Client\n",
        encoding="utf-8",
    )
    target = package_dir / "api.pyi"
    target.write_text("from .client import ServiceClient\n", encoding="utf-8")
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -1,1 +1,1 @@
-from .client import Client
+from .client import ServiceClient
"""
    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_prefers_stub_package_exports_for_mixed_api_pyi_modules(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "__init__.pyi").write_text(
        "from .api import Client\n",
        encoding="utf-8",
    )
    target = package_dir / "api.pyi"
    target.write_text(
        "from .client import ServiceClient as Client\n\nHELPER: int\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -1,3 +1,3 @@
-from .client import Client
+from .client import ServiceClient as Client

 HELPER: int
"""
    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_reexport_target_changed" and "Client" in finding.title
        for finding in findings
    )


def test_detect_python_findings_requests_manual_review_for_internal_helpers_in_reexported_api_module(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from .api import public_api\n",
        encoding="utf-8",
    )
    target = package_dir / "api.py"
    target.write_text(
        "def public_api():\n    return 1\n\ndef helper(x):\n    return x\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -4,2 +4,2 @@
-def helper(x=1):
+def helper(x):
     return x
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(finding.rule == "python_api_module_local_surface_changed" for finding in findings)
    assert any("helper" in finding.title for finding in findings)


def test_detect_python_findings_detects_mixed_api_import_binding_change_with_root_reexport(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from .api import Client\n",
        encoding="utf-8",
    )
    target = package_dir / "api.py"
    target.write_text(
        "from .client import ServiceClient as Client\n\nX = 1\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -1,3 +1,3 @@
-from .client import Client
+from .client import ServiceClient as Client

 X = 1
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_reexport_target_changed" and "Client" in finding.title
        for finding in findings
    )


def test_detect_python_findings_ignores_internal_dependency_swap_in_mixed_api_module(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    target = package_dir / "api.py"
    target.write_text(
        'import orjson as json\n\n\ndef public_api() -> str:\n    return "ok"\n',
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -1,4 +1,4 @@
-import json
+import orjson as json

 def public_api() -> str:
     return "ok"
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert findings == []


def test_detect_python_findings_requests_manual_review_for_mixed_api_import_surface_rename(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    target = package_dir / "api.py"
    target.write_text(
        "from .client import ServiceClient\n\n\ndef helper() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -1,4 +1,4 @@
-from .client import Client
+from .client import ServiceClient


 def helper() -> int:
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "python_api_module_import_surface_changed"
        and "Client" in finding.title
        and "ServiceClient" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_reexported_private_helper_in_non_api_module(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from .client import _create_client as Client\n",
        encoding="utf-8",
    )
    target = package_dir / "client.py"
    target.write_text(
        "def _create_client(timeout: int = 1) -> int:\n    return timeout\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -1,2 +1,2 @@
-def _create_client(timeout: int = 1) -> int:
+def _create_client(timeout: int) -> int:
     return timeout
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_signature_requiredness_tightening"
        and "_create_client" in finding.title
        for finding in findings
    )


def test_detect_python_findings_merges_runtime_and_stub_package_reexports_for_py_modules(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "__init__.pyi").write_text(
        "from .client import _create_client as Client\n",
        encoding="utf-8",
    )
    target = package_dir / "client.py"
    target.write_text(
        "def _create_client(timeout: int) -> int:\n    return timeout\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -1,2 +1,2 @@
-def _create_client(timeout: int = 1) -> int:
+def _create_client(timeout: int) -> int:
     return timeout
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_signature_requiredness_tightening"
        and "_create_client" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_reexport_target_change_in_mixed_api_module(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from .api import Client\n",
        encoding="utf-8",
    )
    target = package_dir / "api.py"
    target.write_text(
        "from .client import ServiceClient as Client\n\nHELPER = 1\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -1,3 +1,3 @@
-from .client import Client
+from .client import ServiceClient as Client

 HELPER = 1
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_reexport_target_changed" and "Client" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_added_public_submodule_symbol_even_when_not_root_reexported(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from .api import public_api\n",
        encoding="utf-8",
    )
    target = package_dir / "api.py"
    target.write_text(
        "def public_api():\n    return 1\n\ndef new_api():\n    return 2\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -2,0 +3,2 @@
+def new_api():
+    return 2
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_symbol_added" and "new_api" in finding.title for finding in findings
    )


def test_detect_python_findings_requests_manual_review_for_local_api_change_in_reexported_api_module(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from .api import root_api\n",
        encoding="utf-8",
    )
    target = package_dir / "api.py"
    target.write_text(
        "def root_api(x: int = 1) -> int:\n    return x\n\n"
        "def local_public(flag: bool = False) -> bool:\n    return flag\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -4,2 +4,2 @@
-def local_public(flag: bool = False) -> bool:
+def local_public(flag: bool) -> bool:
     return flag
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "python_api_module_local_surface_changed"
        and "local_public" in finding.title
        for finding in findings
    )


def test_detect_python_findings_keeps_explicit___all___locals_deterministic_with_root_reexports(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from .api import public_api\n",
        encoding="utf-8",
    )
    target = package_dir / "api.py"
    target.write_text(
        '__all__ = ["public_api", "helper"]\n\n'
        "def public_api() -> int:\n    return 1\n\n"
        "def helper(x: int) -> int:\n    return x\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -5,2 +5,2 @@
-def helper(x: int = 1) -> int:
+def helper(x: int) -> int:
     return x
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_signature_requiredness_tightening" and "helper" in finding.title
        for finding in findings
    )
    assert not any(
        finding.rule == "python_api_module_local_surface_changed" for finding in findings
    )


def test_detect_python_findings_detects_import_alias_reexport_rename() -> None:
    diff_text = """
diff --git a/pkg/__init__.py b/pkg/__init__.py
--- a/pkg/__init__.py
+++ b/pkg/__init__.py
@@ -1,1 +1,1 @@
-import pkg.client as Client
+import pkg.client as ServiceClient
"""

    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_detects_plain_import_reexport_rename() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-import client
+import service_client
"""

    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("service_client" in finding.title for finding in findings)


def test_detect_python_findings_detects_dotted_import_reexport_target_change() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-import pkg.client
+import pkg.service_client
"""

    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_reexport_target_changed" for finding in findings)
    assert any("pkg" in finding.title for finding in findings)


def test_detect_python_findings_ignores_regular_module_relative_import_churn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    target = package_dir / "models.py"
    target.write_text("from .types import UserKey\n", encoding="utf-8")
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -1,1 +1,1 @@
-from .types import UserId
+from .types import UserKey
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert findings == []


def test_detect_python_findings_requests_manual_review_for_star_reexport_change() -> None:
    diff_text = """
diff --git a/pkg/__init__.py b/pkg/__init__.py
--- a/pkg/__init__.py
+++ b/pkg/__init__.py
@@ -1,1 +1,1 @@
-from .api import *
+from .compat import *
"""

    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "python_star_reexport_changed" for finding in findings)


def test_detect_python_findings_keeps_deterministic_changes_alongside_star_reexport_review() -> (
    None
):
    diff_text = """
diff --git a/pkg/__init__.py b/pkg/__init__.py
--- a/pkg/__init__.py
+++ b/pkg/__init__.py
@@ -1,4 +1,4 @@
-from .api import *
+from .compat import *

-def public_api(x: int = 1) -> int:
+def public_api(x: int) -> int:
     return x
"""

    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "python_star_reexport_changed" for finding in findings)
    assert any(
        finding.rule == "export_signature_requiredness_tightening" and "public_api" in finding.title
        for finding in findings
    )


def test_detect_python_findings_treats_keyword_only_to_optional_positional_as_compatible() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-def public_api(*, verbose=False):
+def public_api(verbose=False):
"""

    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_ignores_positional_only_parameter_rename() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-def public_api(value, /):
+def public_api(item, /):
"""

    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_ignores_vararg_parameter_rename() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-def public_api(*values):
+def public_api(*items):
"""

    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_ignores_varkw_parameter_rename() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-def public_api(**values):
+def public_api(**items):
"""

    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_detects_api_module_alias_reexport_rename_with_root_subset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from .api import RootApi\n",
        encoding="utf-8",
    )
    target = package_dir / "api.py"
    target.write_text(
        "from .client import RootApi\nfrom .client import ServiceClient as ServiceClient\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -2,1 +2,1 @@
-from .client import Client as Client
+from .client import ServiceClient as ServiceClient
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_symbol_removed" and "Client" in finding.title
        for finding in findings
    )
    assert any(
        finding.rule == "export_symbol_added" and "ServiceClient" in finding.title
        for finding in findings
    )


def test_detect_python_findings_detects_api_module_reexport_rename_with_root_subset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from .api import RootApi\n",
        encoding="utf-8",
    )
    target = package_dir / "api.py"
    target.write_text(
        "from .client import RootApi\nfrom .client import ServiceClient\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -2,1 +2,1 @@
-from .client import Client
+from .client import ServiceClient
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_symbol_removed" and "Client" in finding.title
        for finding in findings
    )
    assert any(
        finding.rule == "export_symbol_added" and "ServiceClient" in finding.title
        for finding in findings
    )


def test_detect_python_findings_ignores_internal_classes_outside_workspace___all__(
    tmp_path: Path,
) -> None:
    workspace_loader = _workspace_loader(tmp_path)
    target = tmp_path / "pkg" / "api.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        '__all__ = ["public_api"]\n\nclass InternalNew:\n    pass\n', encoding="utf-8"
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -3,0 +4,2 @@
+class InternalNew:
+    pass
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert findings == []


def test_detect_python_findings_does_not_read_live_workspace_by_default(
    tmp_path: Path,
) -> None:
    target = tmp_path / "pkg" / "api.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "class A:\n    def __init__(self, x=1):\n        self.value = int(x)\n\n"
        "class B:\n    def __init__(self, x=1):\n        self.value = int(x)\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -2,2 +2,2 @@
-    def __init__(self, x=1):
+    def __init__(self, x):
     self.value = int(x)
"""

    baseline = detect_python_api_findings(diff_text)
    target.write_text(
        "class A:\n    def __init__(self, x=1):\n        self.value = int(x)\n",
        encoding="utf-8",
    )
    changed = detect_python_api_findings(diff_text)

    assert [(finding.rule, finding.title) for finding in changed] == [
        (finding.rule, finding.title) for finding in baseline
    ]
    assert any(finding.rule == "python_constructor_ambiguous" for finding in baseline)


def test_detect_python_findings_keeps_implicit_public_modules_with_workspace_loader(
    tmp_path: Path,
) -> None:
    workspace_loader = _workspace_loader(tmp_path)
    target = tmp_path / "pkg" / "client.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "def public_api(timeout: int) -> int:\n    return timeout\n",
        encoding="utf-8",
    )
    diff_text = f"""
diff --git a/{target.as_posix()} b/{target.as_posix()}
--- a/{target.as_posix()}
+++ b/{target.as_posix()}
@@ -1,2 +1,2 @@
-def public_api(timeout: int = 1) -> int:
+def public_api(timeout: int) -> int:
     return timeout
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert any(
        finding.rule == "export_signature_requiredness_tightening" and "public_api" in finding.title
        for finding in findings
    )


def test_detect_python_findings_keeps_internal_modules_internal_despite_package_reexports(
    tmp_path: Path,
) -> None:
    workspace_loader = _workspace_loader(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "from .client import public_api\n",
        encoding="utf-8",
    )
    target = package_dir / "internal.py"
    target.write_text(
        "def helper(timeout: int = 1) -> int:\n    return timeout\n",
        encoding="utf-8",
    )
    rel = target.relative_to(tmp_path).as_posix()
    diff_text = f"""
diff --git a/{rel} b/{rel}
--- a/{rel}
+++ b/{rel}
@@ -1,2 +1,2 @@
-def helper(timeout: int = 1) -> int:
+def helper(timeout: int) -> int:
     return timeout
"""

    findings = detect_python_api_findings(diff_text, workspace_loader=workspace_loader)

    assert findings == []


def test_build_filesystem_workspace_loader_blocks_parent_escape(tmp_path: Path) -> None:
    loader = build_filesystem_workspace_loader(tmp_path)
    outside = tmp_path.parent / "bumpkin-loader-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        assert loader(f"../{outside.name}") is None
        assert loader(str(outside)) is None
    finally:
        outside.unlink(missing_ok=True)


def test_build_filesystem_workspace_loader_ignores_non_utf8_files(tmp_path: Path) -> None:
    loader = build_filesystem_workspace_loader(tmp_path)
    target = tmp_path / "pkg" / "api.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\xff\xfe\x00")

    assert loader("pkg/api.py") is None


def test_detect_python_findings_respects_incremental___all___additions() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,3 +1,4 @@
 __all__ = ["A"]
+__all__ += ["B"]
 def A() -> str:
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("B" in finding.title for finding in findings)


def test_detect_python_findings_respects_incremental___all___removals() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,4 +1,3 @@
 __all__ = ["A"]
-__all__ += ["B"]
 def A() -> str:
"""
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("B" in finding.title for finding in findings)


def test_detect_python_findings_ignores_commented_requires_python_examples() -> None:
    diff_text = """
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,2 +1,2 @@
-# requires-python = ">=3.9"
+# requires-python = ">=3.10"
"""
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_detects_added_requires_python_floor() -> None:
    diff_text = """
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,1 +1,2 @@
 [project]
+requires-python = ">=3.10"
"""

    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_findings_ignores_js_ts_internal_only_changes() -> None:
    diff_text = """
diff --git a/src/internal.ts b/src/internal.ts
--- a/src/internal.ts
+++ b/src/internal.ts
@@ -1,2 +1,2 @@
-const timeoutMs = 200
+const timeoutMs = 300
"""
    findings = detect_js_ts_export_findings(diff_text)
    assert findings == []


def test_aggregate_findings_precedence_major_over_minor_patch() -> None:
    findings = [
        Finding(
            id="one",
            severity="PATCH",
            rule="patch_rule",
            confidence="high",
            title="patch",
            why="patch",
            evidence=[{"path": "src/a.ts", "snippet": "x"}],
            suggested_bump="PATCH",
        ),
        Finding(
            id="two",
            severity="MINOR",
            rule="minor_rule",
            confidence="medium",
            title="minor",
            why="minor",
            evidence=[{"path": "src/b.ts", "snippet": "y"}],
            suggested_bump="MINOR",
        ),
        Finding(
            id="three",
            severity="MAJOR",
            rule="major_rule",
            confidence="high",
            title="major",
            why="major",
            evidence=[{"path": "src/c.ts", "snippet": "z"}],
            suggested_bump="MAJOR",
        ),
    ]
    aggregated = aggregate_findings(findings)
    assert aggregated is not None
    assert aggregated.status == "classified"
    assert aggregated.label == "MAJOR"


def test_aggregate_findings_no_bump_when_only_no_bump_findings() -> None:
    findings = [
        Finding(
            id="only-no-bump",
            severity="NO_BUMP",
            rule="no_release_change",
            confidence="high",
            title="No release change",
            why="Only docs changed.",
            evidence=[{"path": "README.md", "snippet": "docs"}],
            suggested_bump="NO_BUMP",
        )
    ]
    aggregated = aggregate_findings(findings)
    assert aggregated is not None
    assert aggregated.status == "classified"
    assert aggregated.label == "NO_BUMP"


def test_aggregate_findings_manual_review_when_no_bump_severity_present() -> None:
    findings = [
        Finding(
            id="only-manual",
            severity="MANUAL_REVIEW",
            rule="export_change_unclassified",
            confidence="low",
            title="manual",
            why="manual",
            evidence=[{"path": "src/index.ts", "snippet": "export { x as y }"}],
            suggested_bump=None,
        )
    ]
    aggregated = aggregate_findings(findings)
    assert aggregated is not None
    assert aggregated.status == "manual_review"
    assert aggregated.label is None
