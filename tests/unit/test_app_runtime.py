from __future__ import annotations

import pytest

from bumpkin.integrations.github.runtime import load_app_runtime_config


def test_load_app_runtime_config_requires_secret_only_in_shell_mode() -> None:
    with pytest.raises(ValueError) as exc_info:
        load_app_runtime_config({})
    message = str(exc_info.value)
    assert "BUMPKIN_APP_WEBHOOK_SECRET" in message
    assert "BUMPKIN_APP_DB_PATH or DATABASE_URL" not in message


def test_load_app_runtime_config_parses_required_and_optional_values() -> None:
    env = {
        "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
        "BUMPKIN_APP_PROVIDER_TOKEN": "provider-key-1",
        "BUMPKIN_APP_GITHUB_APP_ID": "123456",
        "BUMPKIN_APP_GITHUB_PRIVATE_KEY": "-----BEGIN KEY-----\\nabc\\n-----END KEY-----",
        "BUMPKIN_LICENSE_KEY": "license-key-1",
        "BUMPKIN_APP_FEATURE_PRIVATE_AUTOMATION": "true",
        "BUMPKIN_APP_INGRESS_TIMEOUT_SECONDS": "45",
        "BUMPKIN_APP_BUMP_MISMATCH_POLICY": "block",
        "BUMPKIN_APP_SELF_REPOSITORY": "trybumpkin/bumpkin",
        "BUMPKIN_APP_DEPLOYMENT_REVISION": "abc123",
        "BUMPKIN_APP_DEFER_SELF_MERGE_RECOMMENDATION_UNTIL_NEW_DEPLOY": "false",
        "BUMPKIN_APP_RELEASE_WORKFLOW_FILE": ".github/workflows/bumpkin.yml",
        "BUMPKIN_APP_RELEASE_WORKFLOW_REF": "main",
    }
    config = load_app_runtime_config(env)
    assert config.webhook_secret == env["BUMPKIN_APP_WEBHOOK_SECRET"]
    assert config.app_mode == "shell"
    assert config.db_path is None
    assert config.database_url is None
    assert config.provider_token == env["BUMPKIN_APP_PROVIDER_TOKEN"]
    assert config.github_app_id == env["BUMPKIN_APP_GITHUB_APP_ID"]
    assert config.github_app_private_key == "-----BEGIN KEY-----\nabc\n-----END KEY-----"
    assert config.license_key == env["BUMPKIN_LICENSE_KEY"]
    assert config.feature_private_automation is True
    assert config.ingress_timeout_seconds == 45
    assert config.bump_mismatch_policy == "block"
    assert config.self_repository == "trybumpkin/bumpkin"
    assert config.deployment_revision == "abc123"
    assert config.defer_self_merge_recommendation_until_new_deploy is False
    assert config.release_workflow_file == ".github/workflows/bumpkin.yml"
    assert config.release_workflow_ref == "main"


def test_load_app_runtime_config_defaults_optional_values() -> None:
    config = load_app_runtime_config(
        {
            "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
        }
    )
    assert config.app_mode == "shell"
    assert config.provider_token is None
    assert config.github_app_id is None
    assert config.github_app_private_key is None
    assert config.db_path is None
    assert config.database_url is None
    assert config.license_key is None
    assert config.feature_private_automation is False
    assert config.ingress_timeout_seconds == 15
    assert config.bump_mismatch_policy == "allow_with_warning"
    assert config.self_repository is None
    assert config.deployment_revision is None
    assert config.defer_self_merge_recommendation_until_new_deploy is True
    assert config.release_workflow_file == ".github/workflows/bumpkin.yml"
    assert config.release_workflow_ref is None


def test_load_app_runtime_config_requires_database_in_legacy_mode() -> None:
    with pytest.raises(ValueError) as exc_info:
        load_app_runtime_config(
            {
                "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
                "BUMPKIN_APP_MODE": "legacy",
            }
        )

    assert "BUMPKIN_APP_DB_PATH or DATABASE_URL" in str(exc_info.value)


def test_load_app_runtime_config_rejects_invalid_boolean() -> None:
    with pytest.raises(ValueError):
        load_app_runtime_config(
            {
                "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
                "BUMPKIN_APP_DB_PATH": "var/bumpkin.sqlite3",
                "BUMPKIN_APP_FEATURE_PRIVATE_AUTOMATION": "maybe",
            }
        )


def test_load_app_runtime_config_rejects_invalid_timeout() -> None:
    with pytest.raises(ValueError):
        load_app_runtime_config(
            {
                "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
                "BUMPKIN_APP_DB_PATH": "var/bumpkin.sqlite3",
                "BUMPKIN_APP_INGRESS_TIMEOUT_SECONDS": "0",
            }
        )


def test_load_app_runtime_config_rejects_invalid_bump_mismatch_policy() -> None:
    with pytest.raises(ValueError):
        load_app_runtime_config(
            {
                "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
                "BUMPKIN_APP_DB_PATH": "var/bumpkin.sqlite3",
                "BUMPKIN_APP_BUMP_MISMATCH_POLICY": "ask_human",
            }
        )


def test_load_app_runtime_config_reads_github_app_private_key_from_path(tmp_path) -> None:
    key_path = tmp_path / "app-private-key.pem"
    key_path.write_text("-----BEGIN KEY-----\nabc\n-----END KEY-----\n", encoding="utf-8")
    config = load_app_runtime_config(
        {
            "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
            "BUMPKIN_APP_DB_PATH": "var/bumpkin.sqlite3",
            "BUMPKIN_APP_GITHUB_APP_ID": "123456",
            "BUMPKIN_APP_GITHUB_PRIVATE_KEY_PATH": str(key_path),
        }
    )

    assert config.github_app_id == "123456"
    assert config.github_app_private_key == "-----BEGIN KEY-----\nabc\n-----END KEY-----"


def test_load_app_runtime_config_rejects_partial_github_app_config() -> None:
    with pytest.raises(ValueError):
        load_app_runtime_config(
            {
                "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
                "BUMPKIN_APP_DB_PATH": "var/bumpkin.sqlite3",
                "BUMPKIN_APP_GITHUB_APP_ID": "123456",
            }
        )

    with pytest.raises(ValueError):
        load_app_runtime_config(
            {
                "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
                "BUMPKIN_APP_DB_PATH": "var/bumpkin.sqlite3",
                "BUMPKIN_APP_GITHUB_PRIVATE_KEY": "-----BEGIN KEY-----\\nabc\\n-----END KEY-----",
            }
        )


def test_load_app_runtime_config_accepts_database_url_without_sqlite_path() -> None:
    config = load_app_runtime_config(
        {
            "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
            "DATABASE_URL": "postgresql://user:pass@db.example.com:5432/postgres",
        }
    )

    assert config.db_path is None
    assert config.database_url == "postgresql://user:pass@db.example.com:5432/postgres"


def test_load_app_runtime_config_uses_github_and_source_version_fallbacks() -> None:
    config = load_app_runtime_config(
        {
            "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
            "BUMPKIN_APP_DB_PATH": "var/bumpkin.sqlite3",
            "GITHUB_REPOSITORY": "trybumpkin/bumpkin",
            "SOURCE_VERSION": "def456",
        }
    )

    assert config.self_repository == "trybumpkin/bumpkin"
    assert config.deployment_revision == "def456"
