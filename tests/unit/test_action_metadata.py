from __future__ import annotations

from pathlib import Path

import yaml


def test_composite_action_exposes_release_operations_and_outputs() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    action = yaml.safe_load((repo_root / "action.yml").read_text(encoding="utf-8"))

    inputs = action["inputs"]
    assert inputs["operation"]["default"] == "pr_recommendation"
    assert "release_preview" in inputs["operation"]["description"]
    assert "release_publish" in inputs["operation"]["description"]
    assert "target_ref" in inputs
    assert "base_tag" in inputs
    assert "output_markdown" in inputs
    assert "candidate_output" in inputs
    assert "preview_run_id" in inputs
    assert inputs["model"]["required"] is True
    assert inputs["models_endpoint"]["required"] is True
    assert inputs["models_token"]["required"] is True

    outputs = action["outputs"]
    assert "release_status" in outputs
    assert "release_previous_tag" in outputs
    assert "release_next_tag" in outputs
    assert "release_label" in outputs
    assert "release_notes_path" in outputs
    assert "release_candidate_path" in outputs
    assert "release_candidate_fingerprint" in outputs
    assert "release_candidate_run_id" in outputs
    assert "release_candidate_artifact_name" in outputs
    assert "release_url" in outputs
    assert "tag_url" in outputs


def test_example_release_workflow_uses_release_scoped_operation() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load(
        (repo_root / ".github" / "workflows" / "bumpkin.yml").read_text(encoding="utf-8")
    )

    assert "Bumpkin Publish" in workflow["run-name"]
    assert "Bumpkin Preview" in workflow["run-name"]

    workflow_on = workflow.get("on", workflow.get(True))
    assert workflow_on is not None
    dispatch_inputs = workflow_on["workflow_dispatch"]["inputs"]
    assert dispatch_inputs["operation"]["default"] == "release_preview"
    assert "release_preview" in dispatch_inputs["operation"]["options"]
    assert "release_publish" in dispatch_inputs["operation"]["options"]
    assert "preview_run_id" in dispatch_inputs

    permissions = workflow["permissions"]
    assert permissions["actions"] == "read"
    release_job = workflow["jobs"]["release"]
    steps = release_job["steps"]
    bumpkin_step = next(step for step in steps if step.get("id") == "bumpkin")
    assert bumpkin_step["with"]["operation"] == "${{ inputs.operation }}"
    assert bumpkin_step["with"]["preview_run_id"] == "${{ inputs.preview_run_id }}"
    assert bumpkin_step["with"]["model"] == "${{ secrets.BUMPKIN_MODEL }}"
    assert bumpkin_step["with"]["models_endpoint"] == "${{ secrets.BUMPKIN_MODELS_ENDPOINT }}"
    assert bumpkin_step["with"]["models_token"] == "${{ secrets.MODELS_TOKEN }}"  # noqa: S105
    assert "provider" not in bumpkin_step["with"]
    assert any(step.get("name") == "Upload release candidate artifact" for step in steps)


def test_action_runtime_and_ci_use_separate_requirements_files() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    action_text = (repo_root / "action.yml").read_text(encoding="utf-8")
    ci_text = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "requirements.txt" in action_text
    assert "requirements-dev.txt" in ci_text


def test_ci_and_evals_workflows_are_separated() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    ci = yaml.safe_load(
        (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    evals = yaml.safe_load(
        (repo_root / ".github" / "workflows" / "evals.yml").read_text(encoding="utf-8")
    )

    assert list(ci["jobs"].keys()) == ["safety-floor"]
    assert "workflow_dispatch" in ci.get("on", ci.get(True))

    evals_on = evals.get("on", evals.get(True))
    assert "workflow_dispatch" in evals_on
    assert "run_provider_eval" in evals_on["workflow_dispatch"]["inputs"]
    assert "run_multilanguage_eval" in evals_on["workflow_dispatch"]["inputs"]
    assert "run_batch_eval" in evals_on["workflow_dispatch"]["inputs"]
