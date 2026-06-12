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
        finding.rule == "export_signature_requiredness_tightening"
        and "B.__init__" in finding.title
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
