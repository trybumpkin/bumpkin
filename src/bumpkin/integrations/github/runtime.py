from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppRuntimeConfig:
    webhook_secret: str
    app_mode: str
    db_path: str | None
    database_url: str | None
    provider_token: str | None
    github_app_id: str | None
    github_app_private_key: str | None
    license_key: str | None
    feature_private_automation: bool
    ingress_timeout_seconds: int
    bump_mismatch_policy: str
    self_repository: str | None
    deployment_revision: str | None
    defer_self_merge_recommendation_until_new_deploy: bool
    release_workflow_file: str
    release_workflow_ref: str | None


BUMP_MISMATCH_POLICY_ALLOW_WITH_WARNING = "allow_with_warning"
BUMP_MISMATCH_POLICY_BLOCK = "block"
APP_MODE_SHELL = "shell"
APP_MODE_LEGACY = "legacy"
_VALID_BUMP_MISMATCH_POLICIES = frozenset(
    {BUMP_MISMATCH_POLICY_ALLOW_WITH_WARNING, BUMP_MISMATCH_POLICY_BLOCK}
)
_VALID_APP_MODES = frozenset({APP_MODE_SHELL, APP_MODE_LEGACY})


def _non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _first_non_empty(source: Mapping[str, str], *keys: str) -> str | None:
    for key in keys:
        candidate = _non_empty(source.get(key))
        if candidate is not None:
            return candidate
    return None


def _parse_bool(value: str | None, *, default: bool) -> bool:
    normalized = _non_empty(value)
    if normalized is None:
        return default
    lowered = normalized.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError("Invalid app runtime config: boolean value is invalid.")


def _parse_positive_int(value: str | None, *, default: int, field: str) -> int:
    normalized = _non_empty(value)
    if normalized is None:
        return default
    try:
        parsed = int(normalized)
    except ValueError as err:
        raise ValueError(
            f"Invalid app runtime config: `{field}` must be a positive integer."
        ) from err
    if parsed <= 0:
        raise ValueError(f"Invalid app runtime config: `{field}` must be a positive integer.")
    return parsed


def _parse_choice(
    value: str | None,
    *,
    default: str,
    field: str,
    allowed: frozenset[str],
) -> str:
    normalized = _non_empty(value)
    if normalized is None:
        return default
    lowered = normalized.lower()
    if lowered not in allowed:
        options = ", ".join(sorted(allowed))
        raise ValueError(f"Invalid app runtime config: `{field}` must be one of: {options}.")
    return lowered


def _read_private_key_file(path_value: str) -> str:
    path = Path(path_value).expanduser()
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as err:
        raise ValueError(
            "Invalid app runtime config: unable to read GitHub App private key file."
        ) from err
    normalized = _non_empty(content)
    if normalized is None:
        raise ValueError("Invalid app runtime config: GitHub App private key file is empty.")
    return normalized


def _normalize_private_key(value: str | None) -> str | None:
    normalized = _non_empty(value)
    if normalized is None:
        return None
    return normalized.replace("\\n", "\n")


def load_app_runtime_config(environ: Mapping[str, str] | None = None) -> AppRuntimeConfig:
    source = environ if environ is not None else os.environ
    webhook_secret = _non_empty(source.get("BUMPKIN_APP_WEBHOOK_SECRET"))
    app_mode = _parse_choice(
        source.get("BUMPKIN_APP_MODE"),
        default=APP_MODE_SHELL,
        field="BUMPKIN_APP_MODE",
        allowed=_VALID_APP_MODES,
    )
    db_path = _non_empty(source.get("BUMPKIN_APP_DB_PATH"))
    database_url = _first_non_empty(source, "BUMPKIN_APP_DATABASE_URL", "DATABASE_URL")
    github_app_id = _first_non_empty(source, "BUMPKIN_APP_GITHUB_APP_ID", "GITHUB_APP_ID")
    private_key_inline = _first_non_empty(
        source,
        "BUMPKIN_APP_GITHUB_PRIVATE_KEY",
        "GITHUB_PRIVATE_KEY",
    )
    private_key_path = _first_non_empty(
        source,
        "BUMPKIN_APP_GITHUB_PRIVATE_KEY_PATH",
        "GITHUB_PRIVATE_KEY_PATH",
    )
    github_app_private_key = _normalize_private_key(private_key_inline)
    if github_app_private_key is None and private_key_path is not None:
        github_app_private_key = _normalize_private_key(_read_private_key_file(private_key_path))

    missing: list[str] = []
    if webhook_secret is None:
        missing.append("BUMPKIN_APP_WEBHOOK_SECRET")
    if app_mode == APP_MODE_LEGACY and db_path is None and database_url is None:
        missing.append("BUMPKIN_APP_DB_PATH or DATABASE_URL")
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Invalid app runtime config: missing required env vars: {joined}.")
    if (github_app_id is None) != (github_app_private_key is None):
        raise ValueError(
            "Invalid app runtime config: "
            "`BUMPKIN_APP_GITHUB_APP_ID` and GitHub App private key must be set together."
        )
    assert webhook_secret is not None

    return AppRuntimeConfig(
        webhook_secret=webhook_secret,
        app_mode=app_mode,
        db_path=db_path,
        database_url=database_url,
        provider_token=_non_empty(source.get("BUMPKIN_APP_PROVIDER_TOKEN")),
        github_app_id=github_app_id,
        github_app_private_key=github_app_private_key,
        license_key=_non_empty(source.get("BUMPKIN_LICENSE_KEY")),
        feature_private_automation=_parse_bool(
            source.get("BUMPKIN_APP_FEATURE_PRIVATE_AUTOMATION"),
            default=False,
        ),
        ingress_timeout_seconds=_parse_positive_int(
            source.get("BUMPKIN_APP_INGRESS_TIMEOUT_SECONDS"),
            default=15,
            field="BUMPKIN_APP_INGRESS_TIMEOUT_SECONDS",
        ),
        bump_mismatch_policy=_parse_choice(
            source.get("BUMPKIN_APP_BUMP_MISMATCH_POLICY"),
            default=BUMP_MISMATCH_POLICY_ALLOW_WITH_WARNING,
            field="BUMPKIN_APP_BUMP_MISMATCH_POLICY",
            allowed=_VALID_BUMP_MISMATCH_POLICIES,
        ),
        self_repository=_first_non_empty(
            source, "BUMPKIN_APP_SELF_REPOSITORY", "GITHUB_REPOSITORY"
        ),
        deployment_revision=_first_non_empty(
            source, "BUMPKIN_APP_DEPLOYMENT_REVISION", "SOURCE_VERSION"
        ),
        defer_self_merge_recommendation_until_new_deploy=_parse_bool(
            source.get("BUMPKIN_APP_DEFER_SELF_MERGE_RECOMMENDATION_UNTIL_NEW_DEPLOY"),
            default=True,
        ),
        release_workflow_file=(
            _first_non_empty(
                source,
                "BUMPKIN_APP_RELEASE_WORKFLOW_FILE",
                "BUMPKIN_APP_RELEASE_WORKFLOW",
            )
            or ".github/workflows/bumpkin.yml"
        ),
        release_workflow_ref=_first_non_empty(
            source,
            "BUMPKIN_APP_RELEASE_WORKFLOW_REF",
            "BUMPKIN_APP_WORKFLOW_REF",
        ),
    )
