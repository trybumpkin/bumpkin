from bumpkin.policies import classify_finding_boundary, summarize_boundary
from bumpkin.policies.engine import summarize_evidence
from findings import Finding


def _python_floor_finding(path: str) -> Finding:
    return Finding(
        id="python_requires_floor_raised:1",
        severity="MAJOR",
        rule="python_requires_floor_raised",
        confidence="high",
        title="Raised supported Python floor: 3.9 -> 3.10",
        why="Raising the minimum supported Python version breaks older runtimes.",
        evidence=[{"path": path, "snippet": 'requires-python = ">=3.10"'}],
        suggested_bump="MAJOR",
    )


def test_python_requires_floor_raise_is_unknown_without_public_hints() -> None:
    finding = _python_floor_finding("pyproject.toml")

    assert classify_finding_boundary(finding, public_hints=[]) == "public"
    assert summarize_boundary([finding], public_hints=[]) == {
        "public": 1,
        "internal": 0,
        "unknown": 0,
    }


def test_python_requires_floor_raise_respects_public_hints() -> None:
    finding = _python_floor_finding("src/pkg/pyproject.toml")

    assert classify_finding_boundary(finding, public_hints=["src/pkg/**"]) == "public"
    assert summarize_boundary([finding], public_hints=["src/pkg/**"]) == {
        "public": 1,
        "internal": 0,
        "unknown": 0,
    }


def test_python_requires_floor_raise_in_root_metadata_counts_as_public_with_hints() -> None:
    finding = _python_floor_finding("pyproject.toml")

    assert classify_finding_boundary(finding, public_hints=["src/**"]) == "public"
    assert summarize_boundary([finding], public_hints=["src/**"]) == {
        "public": 1,
        "internal": 0,
        "unknown": 0,
    }


def test_python_requires_floor_raise_stays_internal_for_internal_tool_path() -> None:
    finding = _python_floor_finding("tools/internal/pyproject.toml")

    assert classify_finding_boundary(finding, public_hints=["src/**"]) == "internal"
    assert summarize_boundary([finding], public_hints=["src/**"]) == {
        "public": 0,
        "internal": 1,
        "unknown": 0,
    }


def test_python_requires_floor_raise_only_counts_as_public_evidence_when_boundary_is_public() -> (
    None
):
    public_finding = _python_floor_finding("src/pkg/pyproject.toml")
    internal_finding = _python_floor_finding("tools/internal/pyproject.toml")
    unknown_finding = _python_floor_finding("pyproject.toml")

    public_summary = summarize_evidence(
        [public_finding],
        public_hints=["src/pkg/**"],
        contract_signals={},
    )
    internal_summary = summarize_evidence(
        [internal_finding],
        public_hints=["src/pkg/**"],
        contract_signals={},
    )
    unknown_summary = summarize_evidence(
        [unknown_finding],
        public_hints=[],
        contract_signals={},
    )

    assert public_summary["export_public_evidence"] == 1
    assert public_summary["export_breaking_evidence"] == 1
    assert public_summary["unknown_impactful_findings"] == 0

    assert internal_summary["export_public_evidence"] == 0
    assert internal_summary["export_breaking_evidence"] == 0
    assert internal_summary["unknown_impactful_findings"] == 0

    assert unknown_summary["export_public_evidence"] == 1
    assert unknown_summary["export_breaking_evidence"] == 1
    assert unknown_summary["unknown_impactful_findings"] == 0


def test_python_api_manual_review_rules_count_as_public_evidence_when_boundary_is_public() -> None:
    local_surface = Finding(
        id="python_api_module_local_surface_changed:1",
        severity="MANUAL_REVIEW",
        rule="python_api_module_local_surface_changed",
        confidence="low",
        title="Changed local api.py public-surface candidate requires manual review: helper",
        why="test",
        evidence=[{"path": "src/pkg/api.py", "snippet": "def helper(x):"}],
        suggested_bump=None,
    )
    constructor = Finding(
        id="python_constructor_ambiguous:1",
        severity="MANUAL_REVIEW",
        rule="python_constructor_ambiguous",
        confidence="low",
        title="Changed Python constructor requires manual review",
        why="test",
        evidence=[{"path": "src/pkg/api.py", "snippet": "def __init__(self, x):"}],
        suggested_bump=None,
    )

    summary = summarize_evidence(
        [local_surface, constructor],
        public_hints=["src/pkg/**"],
        contract_signals={},
    )

    assert summary["export_public_evidence"] == 2
    assert summary["export_breaking_evidence"] == 1
    assert summary["unknown_impactful_findings"] == 0
