from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from psycopg import Connection as PsycopgConnection

MIGRATION_0001 = """
CREATE TABLE IF NOT EXISTS app_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    action TEXT,
    repository TEXT,
    pull_request_number INTEGER,
    sender_login TEXT,
    received_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    headers_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, provider_event_id)
);
CREATE INDEX IF NOT EXISTS idx_app_events_repo_pr
    ON app_events(repository, pull_request_number);

CREATE TABLE IF NOT EXISTS app_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository TEXT NOT NULL,
    pull_request_number INTEGER NOT NULL,
    label TEXT NOT NULL,
    current_version TEXT,
    source TEXT NOT NULL,
    source_event_id TEXT,
    recorded_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(repository, pull_request_number)
);
CREATE INDEX IF NOT EXISTS idx_app_recommendations_repo_pr_time
    ON app_recommendations(repository, pull_request_number, recorded_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS app_release_backlog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository TEXT NOT NULL,
    pull_request_number INTEGER NOT NULL,
    merge_commit_sha TEXT NOT NULL,
    recommended_label TEXT NOT NULL,
    recommended_current_version TEXT,
    pull_request_title TEXT,
    pull_request_author_login TEXT,
    pull_request_url TEXT,
    release_summary TEXT,
    source_event_id TEXT,
    merged_at TEXT NOT NULL,
    included_in_release_tag TEXT,
    included_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(repository, pull_request_number)
);
CREATE INDEX IF NOT EXISTS idx_app_release_backlog_unreleased
    ON app_release_backlog(repository, included_in_release_tag, merged_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS app_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository TEXT NOT NULL,
    pull_request_number INTEGER NOT NULL,
    commit_sha TEXT NOT NULL,
    approved_label TEXT NOT NULL,
    recommendation_hash TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    source_event_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_app_approvals_repo_pr_time
    ON app_approvals(repository, pull_request_number, approved_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS publish_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository TEXT NOT NULL,
    pull_request_number INTEGER NOT NULL,
    commit_sha TEXT NOT NULL,
    allowed INTEGER NOT NULL,
    reason TEXT NOT NULL,
    guard_reasons TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    policy_snapshot TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_publish_decisions_repo_pr_time
    ON publish_decisions(repository, pull_request_number, evaluated_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    details TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity
    ON audit_log(entity_type, entity_id, timestamp DESC, id DESC);
"""

POSTGRES_MIGRATION_0001 = """
CREATE TABLE IF NOT EXISTS app_events (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    action TEXT,
    repository TEXT,
    pull_request_number BIGINT,
    sender_login TEXT,
    received_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    headers_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(provider, provider_event_id)
);
CREATE INDEX IF NOT EXISTS idx_app_events_repo_pr
    ON app_events(repository, pull_request_number);

CREATE TABLE IF NOT EXISTS app_recommendations (
    id BIGSERIAL PRIMARY KEY,
    repository TEXT NOT NULL,
    pull_request_number BIGINT NOT NULL,
    label TEXT NOT NULL,
    current_version TEXT,
    source TEXT NOT NULL,
    source_event_id TEXT,
    recorded_at TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(repository, pull_request_number)
);
CREATE INDEX IF NOT EXISTS idx_app_recommendations_repo_pr_time
    ON app_recommendations(repository, pull_request_number, recorded_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS app_release_backlog (
    id BIGSERIAL PRIMARY KEY,
    repository TEXT NOT NULL,
    pull_request_number BIGINT NOT NULL,
    merge_commit_sha TEXT NOT NULL,
    recommended_label TEXT NOT NULL,
    recommended_current_version TEXT,
    pull_request_title TEXT,
    pull_request_author_login TEXT,
    pull_request_url TEXT,
    release_summary TEXT,
    source_event_id TEXT,
    merged_at TEXT NOT NULL,
    included_in_release_tag TEXT,
    included_at TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(repository, pull_request_number)
);
CREATE INDEX IF NOT EXISTS idx_app_release_backlog_unreleased
    ON app_release_backlog(repository, included_in_release_tag, merged_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS app_approvals (
    id BIGSERIAL PRIMARY KEY,
    repository TEXT NOT NULL,
    pull_request_number BIGINT NOT NULL,
    commit_sha TEXT NOT NULL,
    approved_label TEXT NOT NULL,
    recommendation_hash TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    source_event_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_app_approvals_repo_pr_time
    ON app_approvals(repository, pull_request_number, approved_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS publish_decisions (
    id BIGSERIAL PRIMARY KEY,
    repository TEXT NOT NULL,
    pull_request_number BIGINT NOT NULL,
    commit_sha TEXT NOT NULL,
    allowed BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    guard_reasons TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    policy_snapshot TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_publish_decisions_repo_pr_time
    ON publish_decisions(repository, pull_request_number, evaluated_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    details TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity
    ON audit_log(entity_type, entity_id, timestamp DESC, id DESC);
"""


def sqlite_table_has_column(
    connection: sqlite3.Connection, table_name: str, column_name: str
) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row[1]) == column_name for row in rows)


def sqlite_add_column_if_missing(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    if sqlite_table_has_column(connection, table_name, column_name):
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}")


def postgres_table_has_column(
    connection: PsycopgConnection[Any], *, table_name: str, column_name: str
) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = %s
              AND column_name = %s
            LIMIT 1
            """,
            (table_name, column_name),
        )
        return cursor.fetchone() is not None


def postgres_add_column_if_missing(
    connection: PsycopgConnection[Any],
    *,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    if postgres_table_has_column(connection, table_name=table_name, column_name=column_name):
        return
    with connection.cursor() as cursor:
        cursor.execute(
            cast("Any", f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_definition}")
        )


def apply_sqlite_migrations(connection: sqlite3.Connection) -> None:
    connection.executescript(MIGRATION_0001)
    sqlite_add_column_if_missing(
        connection,
        table_name="app_release_backlog",
        column_name="pull_request_title",
        column_definition="pull_request_title TEXT",
    )
    sqlite_add_column_if_missing(
        connection,
        table_name="app_release_backlog",
        column_name="pull_request_author_login",
        column_definition="pull_request_author_login TEXT",
    )
    sqlite_add_column_if_missing(
        connection,
        table_name="app_release_backlog",
        column_name="pull_request_url",
        column_definition="pull_request_url TEXT",
    )
    sqlite_add_column_if_missing(
        connection,
        table_name="app_release_backlog",
        column_name="release_summary",
        column_definition="release_summary TEXT",
    )
    connection.commit()


def apply_postgres_migrations(connection: PsycopgConnection[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(POSTGRES_MIGRATION_0001)
    postgres_add_column_if_missing(
        connection,
        table_name="app_release_backlog",
        column_name="pull_request_title",
        column_definition="pull_request_title TEXT",
    )
    postgres_add_column_if_missing(
        connection,
        table_name="app_release_backlog",
        column_name="pull_request_author_login",
        column_definition="pull_request_author_login TEXT",
    )
    postgres_add_column_if_missing(
        connection,
        table_name="app_release_backlog",
        column_name="pull_request_url",
        column_definition="pull_request_url TEXT",
    )
    postgres_add_column_if_missing(
        connection,
        table_name="app_release_backlog",
        column_name="release_summary",
        column_definition="release_summary TEXT",
    )
    connection.commit()
