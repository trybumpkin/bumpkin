"""Bumpkin internal package layout.

The legacy flat modules under ``src/`` remain supported for backwards compatibility.
New code should prefer package imports under ``bumpkin.*``.
"""

from . import (
    analysis,
    contracts,
    eval,
    integrations,
    io,
    licensing,
    orchestrator,
    planner,
    policies,
    providers,
    release_job,
    versioning,
)

__all__ = [
    "analysis",
    "contracts",
    "eval",
    "integrations",
    "io",
    "licensing",
    "orchestrator",
    "planner",
    "policies",
    "providers",
    "release_job",
    "versioning",
]
