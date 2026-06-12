from __future__ import annotations

import json
import re
from pathlib import Path

EXPECTED_CANARY_FIXTURES = [
    "major_signature_change_real",
    "minor_add_export_formal_real",
    "low_confidence_ambiguous",
    "patch_docs_config_noise_real",
]

EXPECTED_CATEGORY_PASS_RATES = {
    "ambiguous_public_surface",
    "hybrid_floor_raise",
    "hybrid_large_real_full",
    "hybrid_large_real_truncated",
    "hybrid_major_override",
    "hybrid_model_path",
    "major_export_removed",
    "major_signature_change",
    "minor_export_added",
    "mixed_major_minor",
    "patch_internal_refactor",
    "surface_area_required",
}

EXPECTED_MULTILANGUAGE_BASELINES = {
    "python-v1.json": "python",
    "go-v1.json": "go",
    "rust-v1.json": "rust",
    "java-kotlin-v1.json": "java-kotlin",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_js_ts_prompt_gate_baseline_is_locked() -> None:
    repo_root = _repo_root()
    baseline_path = repo_root / "test-diffs" / "baselines" / "js-ts-v1.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    assert baseline["prompt_version"] == "js-ts-v1"
    assert baseline["language_group"] == "javascript-typescript"
    assert baseline["promotion_status"] == "promoted"
    assert baseline["fixture_set"] == "test-diffs"
    assert baseline["min_overall_pass_rate"] == 0.7
    assert baseline["required_schema_valid_rate"] == 1.0
    assert baseline["min_ambiguous_low_confidence_rate"] == 1.0

    assert set(baseline["min_category_pass_rates"]) == EXPECTED_CATEGORY_PASS_RATES
    distribution = baseline["required_fixture_distribution"]
    assert distribution["labeled_fixture_min"] == 20
    assert distribution["mixed_fixture_min"] == 3
    assert distribution["label_mins"] == {
        "NO_BUMP": 4,
        "PATCH": 4,
        "MINOR": 5,
        "MAJOR": 5,
    }


def test_ci_eval_canary_contract_is_locked() -> None:
    repo_root = _repo_root()
    ci_text = (repo_root / ".github" / "workflows" / "evals.yml").read_text(encoding="utf-8")

    assert "--prompt-gate-baseline test-diffs/baselines/js-ts-v1.json \\" in ci_text
    assert "if evaluated != 4:" in ci_text

    match = re.search(
        r"for name in (?P<fixtures>.+?); do",
        ci_text,
        flags=re.MULTILINE,
    )
    assert match is not None
    fixtures = [token.strip() for token in match.group("fixtures").split()]
    assert fixtures == EXPECTED_CANARY_FIXTURES


def test_ci_canary_fixtures_exist() -> None:
    repo_root = _repo_root()
    for fixture in EXPECTED_CANARY_FIXTURES:
        fixture_dir = repo_root / "test-diffs" / fixture
        assert fixture_dir.is_dir(), f"Missing canary fixture directory: {fixture_dir}"
        assert (fixture_dir / "diff.txt").is_file(), f"Missing diff.txt in {fixture_dir}"
        assert (fixture_dir / "expected.json").is_file(), f"Missing expected.json in {fixture_dir}"


def test_multilanguage_baselines_exist_and_match_language_group() -> None:
    repo_root = _repo_root()
    baselines_root = repo_root / "test-diffs" / "baselines"
    for filename, language_group in EXPECTED_MULTILANGUAGE_BASELINES.items():
        path = baselines_root / filename
        assert path.is_file(), f"Missing baseline file: {path}"
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected_prompt_version = "python-v1" if language_group == "python" else "generic-v0"
        assert payload["prompt_version"] == expected_prompt_version
        assert payload["language_group"] == language_group
        assert payload["min_overall_pass_rate"] == 0.0


def test_ci_multilanguage_lane_contract_is_present() -> None:
    repo_root = _repo_root()
    ci_text = (repo_root / ".github" / "workflows" / "evals.yml").read_text(encoding="utf-8")

    assert "eval-language-lanes:" in ci_text
    assert "language_group: python" in ci_text
    assert "language_group: go" in ci_text
    assert "language_group: rust" in ci_text
    assert "language_group: java-kotlin" in ci_text
    assert '--prompt-gate-baseline "${{ matrix.baseline }}" \\' in ci_text
    assert "scripts/ci/run_rollout_gates.py" in ci_text


def test_rollout_gate_artifacts_exist() -> None:
    repo_root = _repo_root()
    assert (repo_root / "scripts" / "ci" / "run_rollout_gates.py").is_file()
