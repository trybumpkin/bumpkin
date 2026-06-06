from __future__ import annotations

from pathlib import Path


def test_readme_frames_release_scoped_flow_as_primary_story() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    assert "assets/hero.svg" in readme
    assert "release assistant" in readme
    assert "GitHub Action" in readme
    assert "run-name:" in readme
    assert "operation: ${{ inputs.operation }}" in readme
    assert "release_preview" in readme
    assert "release_publish" in readme
    assert "preview_run_id" in readme
    assert "actions: read" in readme
    assert "MODELS_TOKEN" in readme
    assert "BUMPKIN_MODEL" in readme
    assert "BUMPKIN_MODELS_ENDPOINT" in readme
    assert "uses: trybumpkin/bumpkin@v1" in readme
    assert "maintainer briefing" in readme
    assert "precomputed public changelog" in readme
    assert "ROADMAP.md" in readme
    assert "CONTRIBUTING.md" in readme
    assert "SECURITY.md" in readme


def test_internal_markdown_is_gitignored() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")

    assert "*.md" in gitignore
    assert "!README.md" in gitignore
    assert "!CHANGELOG.md" in gitignore
    assert "!SECURITY.md" in gitignore
    assert "!ROADMAP.md" in gitignore
    assert "!CONTRIBUTING.md" in gitignore


def test_env_example_marks_app_runtime_as_optional() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")

    assert "BUMPKIN_MODEL=your_model_name_here" in env_example
    assert "BUMPKIN_FALLBACK_MODEL=" in env_example
    assert (
        "BUMPKIN_MODELS_ENDPOINT=https://your-provider.example/v1/chat/completions" in env_example
    )
    assert "BUMPKIN_APP_MODE=shell" not in env_example


def test_roadmap_is_public_and_mentions_language_expansion() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
    roadmap = (repo_root / "ROADMAP.md").read_text(encoding="utf-8")

    assert "!ROADMAP.md" in gitignore
    assert "Better support for Python" in roadmap
    assert "Go" in roadmap
    assert "Rust" in roadmap
    assert "Java/Kotlin" in roadmap


def test_community_docs_are_public_and_linked() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    contributing = (repo_root / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "CONTRIBUTING.md" in readme
    assert "Action-first" in contributing
    assert "Heavy eval workflows live separately" in contributing
