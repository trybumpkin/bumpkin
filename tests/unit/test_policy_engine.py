from bumpkin.policies import classify_finding_boundary, summarize_boundary
from findings import Finding


def test_python_requires_floor_raise_counts_as_public_boundary_without_hints() -> None:
    finding = Finding(
        id="python_requires_floor_raised:1",
        severity="MAJOR",
        rule="python_requires_floor_raised",
        confidence="high",
        title="Raised supported Python floor: 3.9 -> 3.10",
        why="Raising the minimum supported Python version breaks older runtimes.",
        evidence=[{"path": "pyproject.toml", "snippet": 'requires-python = ">=3.10"'}],
        suggested_bump="MAJOR",
    )

    assert classify_finding_boundary(finding, public_hints=[]) == "public"
    assert summarize_boundary([finding], public_hints=[]) == {
        "public": 1,
        "internal": 0,
        "unknown": 0,
    }
