from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class BumpkinConfig:
    ignore_paths: list[str]
    surface_area: list[str]
    public_api_entrypoints: list[str]
    public_api_paths: list[str]
    policy_mode: str
    bugfix_patch_bias: bool
    use_difftastic: bool
    semantic_fallback: bool
    pre_1_0_breaking_as_minor: bool
    docs_only_label: str
    large_pr_max_files: int
    large_pr_max_tokens: int
    truncated_no_bump_policy: str
    chunking_enabled: bool
    chunk_max_tokens: int
    chunk_max_count: int
    chunk_failure_policy: str
    impact_evidence_threshold: str = "moderate"
    unknown_boundary_policy: str = "patch_if_bugfix"
    behavior_contract_policy: str = "path_signals"
    noise_suppression_policy: str = "balanced"
    override_governance_policy: str = "strict_audit"
    degraded_provider_policy: str = "MANUAL_REVIEW"
    decision_authority_mode: str = "court"


def _ensure_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Invalid bumpkin.yml: `{field_name}` must be a list of strings.")
    bad = [item for item in value if not isinstance(item, str)]
    if bad:
        raise ValueError(f"Invalid bumpkin.yml: `{field_name}` must contain only strings.")
    return [item.strip() for item in value if item.strip()]


def _ensure_bool(value: Any, field_name: str) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"Invalid bumpkin.yml: `{field_name}` must be a boolean.")


def _ensure_policy_mode(value: Any) -> str:
    if value is None:
        return "pragmatic"
    if not isinstance(value, str):
        raise ValueError("Invalid bumpkin.yml: `policy_mode` must be a string.")
    normalized = value.strip().lower()
    if normalized not in {"pragmatic", "strict_semver", "manual_first"}:
        raise ValueError(
            "Invalid bumpkin.yml: `policy_mode` must be pragmatic, strict_semver, or manual_first."
        )
    return normalized


def _ensure_public_api(value: Any) -> tuple[list[str], list[str]]:
    if value is None:
        return [], []
    if not isinstance(value, dict):
        raise ValueError("Invalid bumpkin.yml: `public_api` must be a mapping.")
    entrypoints = _ensure_string_list(value.get("entrypoints"), "public_api.entrypoints")
    paths = _ensure_string_list(value.get("paths"), "public_api.paths")
    return entrypoints, paths


def _ensure_docs_only_label(value: Any) -> str:
    if value is None:
        return "NO_BUMP"
    if not isinstance(value, str):
        raise ValueError("Invalid bumpkin.yml: `docs_only_label` must be a string.")
    normalized = value.strip().upper()
    if normalized not in {"NO_BUMP", "PATCH"}:
        raise ValueError("Invalid bumpkin.yml: `docs_only_label` must be NO_BUMP or PATCH.")
    return normalized


def _ensure_positive_int(value: Any, field_name: str, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"Invalid bumpkin.yml: `{field_name}` must be a positive integer.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = int(value.strip())
        except ValueError as err:
            raise ValueError(
                f"Invalid bumpkin.yml: `{field_name}` must be a positive integer."
            ) from err
    else:
        raise ValueError(f"Invalid bumpkin.yml: `{field_name}` must be a positive integer.")
    if parsed <= 0:
        raise ValueError(f"Invalid bumpkin.yml: `{field_name}` must be a positive integer.")
    return parsed


def _ensure_choice(
    value: Any,
    field_name: str,
    *,
    default: str,
    allowed: set[str],
    case: str,
    allowed_text: str,
) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"Invalid bumpkin.yml: `{field_name}` must be a string.")
    normalized = value.strip()
    normalized = normalized.upper() if case == "upper" else normalized.lower()
    if normalized not in allowed:
        raise ValueError(f"Invalid bumpkin.yml: `{field_name}` must be {allowed_text}.")
    return normalized


def _ensure_truncated_no_bump_policy(value: Any) -> str:
    return _ensure_choice(
        value,
        "truncated_no_bump_policy",
        default="MANUAL_REVIEW",
        allowed={"MANUAL_REVIEW", "PATCH"},
        case="upper",
        allowed_text="MANUAL_REVIEW or PATCH",
    )


def _ensure_chunk_failure_policy(value: Any) -> str:
    return _ensure_choice(
        value,
        "chunk_failure_policy",
        default="MANUAL_REVIEW",
        allowed={"MANUAL_REVIEW", "PATCH"},
        case="upper",
        allowed_text="MANUAL_REVIEW or PATCH",
    )


def _ensure_impact_evidence_threshold(value: Any) -> str:
    return _ensure_choice(
        value,
        "impact_evidence_threshold",
        default="moderate",
        allowed={"lenient", "moderate", "strict"},
        case="lower",
        allowed_text="lenient, moderate, or strict",
    )


def _default_unknown_boundary_policy(*, policy_mode: str, bugfix_patch_bias: bool) -> str:
    if policy_mode == "manual_first":
        return "manual_review"
    if policy_mode == "pragmatic" and bugfix_patch_bias:
        return "patch_if_bugfix"
    return "confidence_low"


def _ensure_unknown_boundary_policy(
    value: Any,
    *,
    policy_mode: str,
    bugfix_patch_bias: bool,
) -> str:
    if value is None:
        return _default_unknown_boundary_policy(
            policy_mode=policy_mode,
            bugfix_patch_bias=bugfix_patch_bias,
        )
    if not isinstance(value, str):
        raise ValueError("Invalid bumpkin.yml: `unknown_boundary_policy` must be a string.")
    normalized = value.strip().lower()
    if normalized not in {"confidence_low", "patch_if_bugfix", "manual_review"}:
        raise ValueError(
            "Invalid bumpkin.yml: `unknown_boundary_policy` must be confidence_low, patch_if_bugfix, or manual_review."
        )
    return normalized


def _ensure_behavior_contract_policy(value: Any) -> str:
    return _ensure_choice(
        value,
        "behavior_contract_policy",
        default="path_signals",
        allowed={"off", "path_signals"},
        case="lower",
        allowed_text="off or path_signals",
    )


def _ensure_noise_suppression_policy(value: Any) -> str:
    return _ensure_choice(
        value,
        "noise_suppression_policy",
        default="balanced",
        allowed={"off", "balanced", "strict"},
        case="lower",
        allowed_text="off, balanced, or strict",
    )


def _ensure_override_governance_policy(value: Any) -> str:
    return _ensure_choice(
        value,
        "override_governance_policy",
        default="strict_audit",
        allowed={"strict_audit", "severity_precedence"},
        case="lower",
        allowed_text="strict_audit or severity_precedence",
    )


def _ensure_degraded_provider_policy(value: Any) -> str:
    return _ensure_choice(
        value,
        "degraded_provider_policy",
        default="MANUAL_REVIEW",
        allowed={"MANUAL_REVIEW", "PATCH"},
        case="upper",
        allowed_text="MANUAL_REVIEW or PATCH",
    )


def _ensure_decision_authority_mode(value: Any) -> str:
    return _ensure_choice(
        value,
        "decision_authority_mode",
        default="court",
        allowed={"deterministic", "court"},
        case="lower",
        allowed_text="deterministic or court",
    )


def _default_bumpkin_config() -> BumpkinConfig:
    return BumpkinConfig(
        ignore_paths=[],
        surface_area=[],
        public_api_entrypoints=[],
        public_api_paths=[],
        policy_mode="pragmatic",
        bugfix_patch_bias=True,
        use_difftastic=False,
        semantic_fallback=True,
        pre_1_0_breaking_as_minor=True,
        docs_only_label="NO_BUMP",
        large_pr_max_files=30,
        large_pr_max_tokens=6000,
        truncated_no_bump_policy="MANUAL_REVIEW",
        chunking_enabled=True,
        chunk_max_tokens=1200,
        chunk_max_count=24,
        chunk_failure_policy="MANUAL_REVIEW",
        impact_evidence_threshold="moderate",
        unknown_boundary_policy="patch_if_bugfix",
        behavior_contract_policy="path_signals",
        noise_suppression_policy="balanced",
        override_governance_policy="strict_audit",
        degraded_provider_policy="MANUAL_REVIEW",
        decision_authority_mode="court",
    )


def load_bumpkin_config(path: Path | None = None) -> BumpkinConfig:
    config_path = path or Path("bumpkin.yml")
    if not config_path.exists():
        return _default_bumpkin_config()

    parsed = yaml.safe_load(config_path.read_text())
    if parsed is None:
        return _default_bumpkin_config()
    if not isinstance(parsed, dict):
        raise ValueError("Invalid bumpkin.yml: top-level content must be a mapping.")

    ignore_paths = _ensure_string_list(parsed.get("ignore_paths"), "ignore_paths")
    surface_area = _ensure_string_list(parsed.get("surface_area"), "surface_area")
    public_api_entrypoints, public_api_paths = _ensure_public_api(parsed.get("public_api"))
    policy_mode = _ensure_policy_mode(parsed.get("policy_mode"))
    bugfix_patch_bias = (
        _ensure_bool(parsed.get("bugfix_patch_bias"), "bugfix_patch_bias")
        if "bugfix_patch_bias" in parsed
        else True
    )
    use_difftastic = _ensure_bool(parsed.get("use_difftastic"), "use_difftastic")
    semantic_fallback = _ensure_bool(parsed.get("semantic_fallback"), "semantic_fallback")
    pre_1_0_breaking_as_minor = _ensure_bool(
        parsed.get("pre_1_0_breaking_as_minor"),
        "pre_1_0_breaking_as_minor",
    )
    docs_only_label = _ensure_docs_only_label(parsed.get("docs_only_label"))
    large_pr_max_files = _ensure_positive_int(
        parsed.get("large_pr_max_files"),
        "large_pr_max_files",
        default=30,
    )
    large_pr_max_tokens = _ensure_positive_int(
        parsed.get("large_pr_max_tokens"),
        "large_pr_max_tokens",
        default=6000,
    )
    truncated_no_bump_policy = _ensure_truncated_no_bump_policy(
        parsed.get("truncated_no_bump_policy")
    )
    chunking_enabled = _ensure_bool(parsed.get("chunking_enabled"), "chunking_enabled")
    chunk_max_tokens = _ensure_positive_int(
        parsed.get("chunk_max_tokens"),
        "chunk_max_tokens",
        default=1200,
    )
    chunk_max_count = _ensure_positive_int(
        parsed.get("chunk_max_count"),
        "chunk_max_count",
        default=24,
    )
    chunk_failure_policy = _ensure_chunk_failure_policy(parsed.get("chunk_failure_policy"))
    impact_evidence_threshold = _ensure_impact_evidence_threshold(
        parsed.get("impact_evidence_threshold")
    )
    unknown_boundary_policy = _ensure_unknown_boundary_policy(
        parsed.get("unknown_boundary_policy"),
        policy_mode=policy_mode,
        bugfix_patch_bias=bugfix_patch_bias,
    )
    behavior_contract_policy = _ensure_behavior_contract_policy(
        parsed.get("behavior_contract_policy")
    )
    noise_suppression_policy = _ensure_noise_suppression_policy(
        parsed.get("noise_suppression_policy")
    )
    override_governance_policy = _ensure_override_governance_policy(
        parsed.get("override_governance_policy")
    )
    degraded_provider_policy = _ensure_degraded_provider_policy(
        parsed.get("degraded_provider_policy")
    )
    decision_authority_mode = _ensure_decision_authority_mode(parsed.get("decision_authority_mode"))
    return BumpkinConfig(
        ignore_paths=ignore_paths,
        surface_area=surface_area,
        public_api_entrypoints=public_api_entrypoints,
        public_api_paths=public_api_paths,
        policy_mode=policy_mode,
        bugfix_patch_bias=bugfix_patch_bias,
        use_difftastic=use_difftastic,
        semantic_fallback=semantic_fallback if "semantic_fallback" in parsed else True,
        pre_1_0_breaking_as_minor=pre_1_0_breaking_as_minor
        if "pre_1_0_breaking_as_minor" in parsed
        else True,
        docs_only_label=docs_only_label,
        large_pr_max_files=large_pr_max_files,
        large_pr_max_tokens=large_pr_max_tokens,
        truncated_no_bump_policy=truncated_no_bump_policy,
        chunking_enabled=chunking_enabled if "chunking_enabled" in parsed else True,
        chunk_max_tokens=chunk_max_tokens,
        chunk_max_count=chunk_max_count,
        chunk_failure_policy=chunk_failure_policy,
        impact_evidence_threshold=impact_evidence_threshold,
        unknown_boundary_policy=unknown_boundary_policy,
        behavior_contract_policy=behavior_contract_policy,
        noise_suppression_policy=noise_suppression_policy,
        override_governance_policy=override_governance_policy,
        degraded_provider_policy=degraded_provider_policy,
        decision_authority_mode=decision_authority_mode,
    )
