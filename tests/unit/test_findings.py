from pathlib import Path

from findings import (
    Finding,
    aggregate_findings,
    detect_js_ts_export_findings,
    detect_python_api_findings,
    detect_semver_findings,
)


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


def test_detect_python_findings_ignores_nested_pyproject_floor_raise() -> None:
    diff_text = """
diff --git a/packages/internal-tool/pyproject.toml b/packages/internal-tool/pyproject.toml
--- a/packages/internal-tool/pyproject.toml
+++ b/packages/internal-tool/pyproject.toml
@@ -1,2 +1,2 @@
-requires-python = ">=3.9"
+requires-python = ">=3.10"
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
    findings = detect_python_api_findings(diff_text)

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


def test_detect_python_findings_uses_workspace___all___contract_outside_hunk(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
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
    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_infers_constructor_class_from_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
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
    findings = detect_python_api_findings(diff_text)

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
    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("Client" in finding.title for finding in findings)
    assert any(finding.rule == "export_symbol_added" for finding in findings)
    assert any("ServiceClient" in finding.title for finding in findings)


def test_detect_python_findings_detects_absolute_api_module_reexport_rename_in_src_layout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
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
    findings = detect_python_api_findings(diff_text)

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


def test_detect_python_findings_ignores_unexported_import_only_api_module() -> None:
    diff_text = """
diff --git a/pkg/api.py b/pkg/api.py
--- a/pkg/api.py
+++ b/pkg/api.py
@@ -1,1 +1,1 @@
-from .compat import UserId
+from .compat import UserKey
"""

    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_detects_removed_export_with_workspace___all___outside_hunk(
    tmp_path: Path,
) -> None:
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

    findings = detect_python_api_findings(diff_text)

    assert any(finding.rule == "export_symbol_removed" for finding in findings)
    assert any("public_api" in finding.title for finding in findings)


def test_detect_python_findings_detects_constructor_tightening_when_body_anchor_changes(
    tmp_path: Path,
) -> None:
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

    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_signature_requiredness_tightening" and "A.__init__" in finding.title
        for finding in findings
    )


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


def test_detect_python_findings_ignores_internal_helpers_in_reexported_api_module(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
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

    findings = detect_python_api_findings(diff_text)

    assert findings == []


def test_detect_python_findings_detects_added_public_submodule_symbol_even_when_not_root_reexported(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
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

    findings = detect_python_api_findings(diff_text)

    assert any(
        finding.rule == "export_symbol_added" and "new_api" in finding.title for finding in findings
    )


def test_detect_python_findings_ignores_regular_module_relative_import_churn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
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

    findings = detect_python_api_findings(diff_text)

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


def test_detect_python_findings_ignores_internal_classes_outside_workspace___all__(
    tmp_path: Path,
) -> None:
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

    findings = detect_python_api_findings(diff_text)

    assert findings == []


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
