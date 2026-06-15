import diff
from bumpkin.providers.semantic import semantic_fallback_recommendation


def test_build_diff_text_uses_git_diff_when_difftastic_disabled(monkeypatch) -> None:
    monkeypatch.setattr(diff, "_run_git", lambda args: "git-diff-output")
    out, notes = diff._build_diff_text("a", "b", ["src/api.js"], use_difftastic=False)
    assert out == "git-diff-output"
    assert notes == []


def test_build_diff_text_falls_back_when_difftastic_missing(monkeypatch) -> None:
    monkeypatch.setattr(diff, "_difftastic_available", lambda: False)
    monkeypatch.setattr(diff, "_run_git", lambda args: "git-diff-output")
    out, notes = diff._build_diff_text("a", "b", ["src/api.js"], use_difftastic=True)
    assert out == "git-diff-output"
    assert any("not installed" in note for note in notes)


def test_build_diff_text_falls_back_when_difftastic_fails(monkeypatch) -> None:
    monkeypatch.setattr(diff, "_difftastic_available", lambda: True)
    monkeypatch.setattr(
        diff, "_run_command", lambda args: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(diff, "_run_git", lambda args: "git-diff-output")
    out, notes = diff._build_diff_text("a", "b", ["src/api.js"], use_difftastic=True)
    assert out == "git-diff-output"
    assert any("Difftastic failed" in note for note in notes)


def test_cap_diff_per_file_limits_large_section() -> None:
    large_body = "x" * (diff.PER_FILE_CHAR_CAP + 200)
    raw = (
        "diff --git a/src/huge.ts b/src/huge.ts\n"
        "--- a/src/huge.ts\n"
        "+++ b/src/huge.ts\n"
        f"+{large_body}\n"
        "diff --git a/src/small.ts b/src/small.ts\n"
        "--- a/src/small.ts\n"
        "+++ b/src/small.ts\n"
        "+ok\n"
    )
    capped, count = diff._cap_diff_per_file(raw, diff.PER_FILE_CHAR_CAP)
    assert count == 1
    assert "[Bumpkin: per-file diff capped]" in capped
    assert "diff --git a/src/small.ts b/src/small.ts" in capped


def test_build_diff_respects_extended_default_ignores(monkeypatch) -> None:
    monkeypatch.setattr(diff, "_repository_root", lambda: "C:/repo-root")
    monkeypatch.setattr(
        diff,
        "_changed_files",
        lambda _from, _to: [
            "worker/.wrangler/tmp/index.js",
            "test-projects/nest-10/pnpm-lock.yaml",
            "src/app.ts",
        ],
    )
    monkeypatch.setattr(
        diff,
        "_build_diff_text",
        lambda from_ref, to_ref, files, use_difftastic: (
            "diff --git a/src/app.ts b/src/app.ts\n+export const x = 1\n",
            [],
        ),
    )

    result = diff.build_diff("a", "b")
    assert result.repo_root == "C:/repo-root"
    assert result.analyzed_files == ["src/app.ts"]
    assert result.changed_files_total == 3
    assert result.ignored_files_total == 2


def test_diff_result_keeps_backward_compatible_positional_constructor() -> None:
    result = diff.DiffResult(
        "base",
        "head",
        "diff --git a/src/app.ts b/src/app.ts\n",
        "diff --git a/src/app.ts b/src/app.ts\n",
        False,
        ["src/app.ts"],
        [],
        1,
        0,
        12,
        12,
        0,
        0,
        1,
        0,
        0,
        [],
    )

    assert result.repo_root is None
    assert result.analyzed_files == ["src/app.ts"]


def test_build_diff_ignores_common_lockfile_formats(monkeypatch) -> None:
    monkeypatch.setattr(
        diff,
        "_changed_files",
        lambda _from, _to: [
            "pnpm-lock.yaml",
            "package-lock.json",
            "npm-shrinkwrap.json",
            "bun.lockb",
            "src/index.ts",
        ],
    )
    monkeypatch.setattr(
        diff,
        "_build_diff_text",
        lambda from_ref, to_ref, files, use_difftastic: (
            "diff --git a/src/index.ts b/src/index.ts\n+export const x = 1\n",
            [],
        ),
    )

    result = diff.build_diff("a", "b")
    assert result.analyzed_files == ["src/index.ts"]
    assert result.changed_files_total == 5
    assert result.ignored_files_total == 4


def test_build_diff_applies_pr_allowlist_and_tracks_scope_counts(monkeypatch) -> None:
    monkeypatch.setattr(
        diff,
        "_changed_files",
        lambda _from, _to: ["src/a.ts", "src/b.ts", "docs/readme.md"],
    )
    monkeypatch.setattr(
        diff,
        "_build_diff_text",
        lambda from_ref, to_ref, files, use_difftastic: (
            "diff --git a/src/a.ts b/src/a.ts\n+export const a = 1\n"
            "diff --git a/src/b.ts b/src/b.ts\n+export const b = 1\n",
            [],
        ),
    )

    result = diff.build_diff("a", "b", allowed_files=["src/a.ts", "src/b.ts"])
    assert result.analyzed_files == ["src/a.ts", "src/b.ts"]
    assert result.changed_files_total == 3
    assert result.scope_allowlist_files_total == 2
    assert result.scope_overlap_files == 2
    assert result.scope_unexpected_files == 1
    assert result.scope_missing_files == 0


def test_build_diff_tracks_missing_pr_files_from_allowlist(monkeypatch) -> None:
    monkeypatch.setattr(diff, "_changed_files", lambda _from, _to: ["src/a.ts"])
    monkeypatch.setattr(
        diff,
        "_build_diff_text",
        lambda from_ref, to_ref, files, use_difftastic: (
            "diff --git a/src/a.ts b/src/a.ts\n+export const a = 1\n",
            [],
        ),
    )

    result = diff.build_diff("a", "b", allowed_files=["src/a.ts", "src/b.ts"])
    assert result.scope_allowlist_files_total == 2
    assert result.scope_overlap_files == 1
    assert result.scope_unexpected_files == 0
    assert result.scope_missing_files == 1


def test_build_diff_keeps_full_text_when_chunking_enabled(monkeypatch) -> None:
    monkeypatch.setattr(diff, "_changed_files", lambda _from, _to: ["src/a.ts"])
    monkeypatch.setattr(
        diff,
        "_build_diff_text",
        lambda from_ref, to_ref, files, use_difftastic: (
            "diff --git a/src/a.ts b/src/a.ts\n+" + ("x" * 8000) + "\n",
            [],
        ),
    )

    result = diff.build_diff("a", "b", token_cap=100, chunking_enabled=True)
    assert result.truncated is False
    assert result.diff_text == result.full_diff_text
    assert any("full per-file coverage was kept" in note for note in result.notes)


def test_build_diff_truncates_when_chunking_disabled(monkeypatch) -> None:
    monkeypatch.setattr(diff, "_changed_files", lambda _from, _to: ["src/a.ts"])
    monkeypatch.setattr(
        diff,
        "_build_diff_text",
        lambda from_ref, to_ref, files, use_difftastic: (
            "diff --git a/src/a.ts b/src/a.ts\n+" + ("x" * 8000) + "\n",
            [],
        ),
    )

    result = diff.build_diff("a", "b", token_cap=100, chunking_enabled=False)
    assert result.truncated is True
    assert len(result.diff_text) < len(result.full_diff_text)


def test_build_diff_preserves_multi_file_headers_for_semantic_classifier(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        diff,
        "_changed_files",
        lambda _from, _to: [
            ".github/workflows/ci.yml",
            "src/bumpkin/orchestrator/court.py",
        ],
    )

    def _fake_build_diff_text(from_ref, to_ref, files, use_difftastic):
        path = files[0]
        if path == ".github/workflows/ci.yml":
            return (
                "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
                "@@ -1,2 +1,2 @@\n"
                "-name: CI\n"
                "+name: CI Pipeline",
                [],
            )
        return (
            "diff --git a/src/bumpkin/orchestrator/court.py b/src/bumpkin/orchestrator/court.py\n"
            "@@ -10,2 +10,3 @@\n"
            "+def _extract_json_payload(content: str) -> dict[str, object]:\n"
            "+    return {}\n",
            [],
        )

    monkeypatch.setattr(diff, "_build_diff_text", _fake_build_diff_text)

    result = diff.build_diff("a", "b", chunking_enabled=True)
    recommendation = semantic_fallback_recommendation(
        diff_text=result.diff_text,
        surface_area_hints=None,
        truncated=False,
    )

    assert (
        "diff --git a/src/bumpkin/orchestrator/court.py b/src/bumpkin/orchestrator/court.py"
        in result.diff_text
    )
    assert recommendation["label"] == "PATCH"


def test_semantic_fallback_ignores_shell_export_lines_as_public_api_markers() -> None:
    diff_text = (
        "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
        "@@ -1,2 +1,4 @@\n"
        '+export MODELS_TOKEN="${GITHUB_MODELS_TOKEN}"\n'
        '+export BUMPKIN_MODELS_ENDPOINT="https://models.github.ai/inference/chat/completions"\n'
        "diff --git a/src/eval.py b/src/eval.py\n"
        "@@ -10,2 +10,4 @@\n"
        '+parser.add_argument("--continue-on-preflight-failure", action="store_true")\n'
    )

    recommendation = semantic_fallback_recommendation(
        diff_text=diff_text,
        surface_area_hints=None,
        truncated=False,
    )

    assert recommendation["status"] == "classified"
    assert recommendation["label"] == "PATCH"


def test_semantic_fallback_internal_patch_includes_file_context_and_scoped_changelog() -> None:
    diff_text = (
        "diff --git a/src/bumpkin/orchestrator/core.py b/src/bumpkin/orchestrator/core.py\n"
        "@@ -10,2 +10,4 @@\n"
        "+def _helper() -> None:\n"
        "+    return None\n"
    )
    recommendation = semantic_fallback_recommendation(
        diff_text=diff_text,
        surface_area_hints=None,
        truncated=False,
    )

    assert recommendation["status"] == "classified"
    assert recommendation["label"] == "PATCH"
    assert "src/bumpkin/orchestrator/core.py" in str(recommendation["reasoning"])
    assert recommendation["changelog"] == "fix(core): update internal behavior in core.py"
