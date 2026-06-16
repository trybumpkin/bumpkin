from language import detect_language_groups, detect_language_hints


def test_detect_language_hints_for_multiple_languages() -> None:
    hints = detect_language_hints(["src/api.ts", "pkg/service.py", "cmd/main.go"])
    assert len(hints) == 3
    assert any("JavaScript/TypeScript" in hint for hint in hints)
    assert any("Python" in hint for hint in hints)
    assert any("Go" in hint for hint in hints)


def test_detect_language_hints_empty_for_unknown_extensions() -> None:
    hints = detect_language_hints(["README.md", "assets/logo.svg"])
    assert hints == []


def test_detect_language_groups_treats_stub_files_as_python() -> None:
    groups = detect_language_groups(["pkg/api.pyi"])
    assert groups == ["python"]


def test_detect_language_groups_treats_pyw_files_as_python() -> None:
    groups = detect_language_groups(["tools/release.pyw"])
    assert groups == ["python"]


def test_detect_language_groups_does_not_treat_packaging_metadata_alone_as_python() -> None:
    groups = detect_language_groups(["pyproject.toml", "setup.cfg"])
    assert groups == []


def test_detect_language_groups_keeps_python_when_metadata_changes_with_python_files() -> None:
    groups = detect_language_groups(["pyproject.toml", "pkg/service.py", "setup.cfg"])
    assert groups == ["python"]
