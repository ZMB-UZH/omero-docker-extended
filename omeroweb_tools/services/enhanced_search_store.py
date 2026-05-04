from __future__ import annotations

import logging
import weakref
from contextlib import contextmanager
from functools import cache
from typing import Any, Iterable

from omero_plugin_common.env_utils import ENV_FILE_OMEROWEB, get_env
from omero_plugin_common.logging_utils import sanitize_log_value, sanitized_exc_info

from .search_query_builder import build_postgres_prefix_tsquery


logger = logging.getLogger(__name__)

TABLE_IMAGE = "acquisition_search_image"
TABLE_CHANNEL = "acquisition_search_channel"
TABLE_ATTRIBUTE = "acquisition_search_attribute"
TABLE_SCOPE_ITEM = "acquisition_search_scope_item"
TABLE_SYNC_STATE = "acquisition_search_sync_state"
TABLE_SAVED_QUERY = "acquisition_search_saved_query"
TABLE_USER_SETTINGS = "acquisition_search_user_settings"

ENV_USER = "OMP_DATA_USER"
ENV_AUTH = "OMP_DATA_PASS"
ENV_HOST = "OMP_DATA_HOST"
ENV_DB = "OMP_DATA_DB"
ENV_PORT = "OMP_DATA_PORT"

_SCHEMA_READY_CONNECTIONS: weakref.WeakKeyDictionary[object, bool] = (
    weakref.WeakKeyDictionary()
)
_SCHEMA_READY_CONNECTION_IDS: set[int] = set()


class EnhancedSearchStoreError(Exception):
    """Raised when Tools enhanced-search persistence fails."""


USER_SETTINGS_NOT_PERSISTED_ERROR = "Enhanced-search user settings were not persisted."


def _schema_ready(conn) -> bool:
    """Schema ready.

    Inputs: `conn`. Output: `bool`.
    """
    try:
        return bool(_SCHEMA_READY_CONNECTIONS.get(conn))
    except TypeError:
        return id(conn) in _SCHEMA_READY_CONNECTION_IDS


def _mark_schema_ready(conn) -> None:
    """Mark schema ready.

    Inputs: `conn`. Output: None.
    """
    try:
        _SCHEMA_READY_CONNECTIONS[conn] = True
    except TypeError:
        _SCHEMA_READY_CONNECTION_IDS.add(id(conn))


def _clear_schema_ready(conn) -> None:
    """Clear schema ready.

    Inputs: `conn`. Output: None.
    """
    try:
        _SCHEMA_READY_CONNECTIONS.pop(conn, None)
    except TypeError:
        _SCHEMA_READY_CONNECTION_IDS.discard(id(conn))


@cache
def _load_psycopg2():
    """Load psycopg2.

    Inputs: none. Output: tuple. Raises on invalid or unavailable state.
    """
    try:
        import psycopg2
        from psycopg2 import extras
    except ImportError as exc:
        raise EnhancedSearchStoreError(
            "psycopg2 is required for enhanced search."
        ) from exc
    return psycopg2, extras


@cache
def _load_psycopg2_sql():
    """Load psycopg2 sql.

    Inputs: none. Output: `sql`. Raises on invalid or unavailable state.
    """
    try:
        from psycopg2 import sql
    except ImportError as exc:
        raise EnhancedSearchStoreError(
            "psycopg2 is required for enhanced search."
        ) from exc
    return sql


def _safe_query(template, *identifiers):
    """Return safe query.

    Inputs: `template`, `*identifiers`. Output: call result.
    """
    sql_mod = _load_psycopg2_sql()
    return sql_mod.SQL(template).format(*[sql_mod.Identifier(i) for i in identifiers])


def _db_params():
    """DB params.

    Inputs: none. Output: dict.
    """
    user = get_env(ENV_USER, env_file=ENV_FILE_OMEROWEB)
    password = get_env(ENV_AUTH, env_file=ENV_FILE_OMEROWEB)
    host = get_env(ENV_HOST, env_file=ENV_FILE_OMEROWEB)
    dbname = get_env(ENV_DB, env_file=ENV_FILE_OMEROWEB)
    port = int(get_env(ENV_PORT, env_file=ENV_FILE_OMEROWEB))
    return {
        "user": user,
        "password": password,
        "host": host,
        "dbname": dbname,
        "port": port,
    }


@contextmanager
def connect():
    """Open the connection.

    Inputs: none. Output: yielded values. Raises on invalid or unavailable state.
    """
    psycopg2, _ = _load_psycopg2()
    conn = None
    try:
        conn = psycopg2.connect(**_db_params())
    except EnhancedSearchStoreError:
        raise
    except Exception as exc:
        logger.error(
            "Enhanced-search database operation failed: %s",
            sanitize_log_value(exc),
            exc_info=sanitized_exc_info(exc),
        )
        raise EnhancedSearchStoreError(
            "Enhanced-search database operation failed."
        ) from exc
    try:
        yield conn
    finally:
        if conn is not None:
            _clear_schema_ready(conn)
            try:
                conn.close()
            except Exception:
                logger.debug(
                    "Suppressed non-fatal close error in enhanced-search store.",
                    exc_info=True,
                )


def ensure_schema(conn) -> None:
    """Ensure schema.

    Inputs: `conn`. Output: None.
    """
    if _schema_ready(conn):
        return
    _load_psycopg2_sql()
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    image_id BIGINT PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    group_name TEXT NOT NULL DEFAULT '',
                    group_can_read BOOLEAN NOT NULL DEFAULT FALSE,
                    owner_id BIGINT,
                    owner_name TEXT NOT NULL DEFAULT '',
                    image_name TEXT NOT NULL DEFAULT '',
                    dataset_id BIGINT,
                    dataset_name TEXT NOT NULL DEFAULT '',
                    project_id BIGINT,
                    project_name TEXT NOT NULL DEFAULT '',
                    schema_version INTEGER NOT NULL,
                    indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    acquisition_date TIMESTAMPTZ,
                    instrument_manufacturer TEXT NOT NULL DEFAULT '',
                    instrument_model TEXT NOT NULL DEFAULT '',
                    objective_model TEXT NOT NULL DEFAULT '',
                    objective_magnification DOUBLE PRECISION,
                    objective_na DOUBLE PRECISION,
                    detector_model TEXT NOT NULL DEFAULT '',
                    detector_binning TEXT NOT NULL DEFAULT '',
                    detector_gain DOUBLE PRECISION,
                    pixel_size_x_um DOUBLE PRECISION,
                    pixel_size_y_um DOUBLE PRECISION,
                    z_step_um DOUBLE PRECISION,
                    channel_summary TEXT NOT NULL DEFAULT '',
                    search_document TEXT NOT NULL DEFAULT ''
                );
                """,
                TABLE_IMAGE,
            )
        )
        cur.execute(
            _safe_query(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    image_id BIGINT NOT NULL REFERENCES {} (image_id) ON DELETE CASCADE,
                    channel_index INTEGER NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    excitation_nm DOUBLE PRECISION,
                    emission_nm DOUBLE PRECISION,
                    PRIMARY KEY (image_id, channel_index)
                );
                """,
                TABLE_CHANNEL,
                TABLE_IMAGE,
            )
        )
        cur.execute(
            _safe_query(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    image_id BIGINT NOT NULL REFERENCES {} (image_id) ON DELETE CASCADE,
                    attribute_key TEXT NOT NULL,
                    attribute_text TEXT NOT NULL DEFAULT '',
                    attribute_numeric DOUBLE PRECISION,
                    PRIMARY KEY (image_id, attribute_key)
                );
                """,
                TABLE_ATTRIBUTE,
                TABLE_IMAGE,
            )
        )
        cur.execute(
            _safe_query(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    scope_type TEXT NOT NULL,
                    scope_id BIGINT NOT NULL,
                    image_id BIGINT NOT NULL REFERENCES {} (image_id) ON DELETE CASCADE,
                    run_token TEXT NOT NULL DEFAULT '',
                    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (scope_type, scope_id, image_id)
                );
                """,
                TABLE_SCOPE_ITEM,
                TABLE_IMAGE,
            )
        )
        cur.execute(
            _safe_query(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    scope_type TEXT NOT NULL,
                    scope_id BIGINT NOT NULL,
                    scope_label TEXT NOT NULL DEFAULT '',
                    schema_version INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'idle',
                    requested_by TEXT NOT NULL DEFAULT '',
                    run_token TEXT NOT NULL DEFAULT '',
                    last_cursor_image_id BIGINT,
                    indexed_image_count INTEGER NOT NULL DEFAULT 0,
                    current_message TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    last_started_at TIMESTAMPTZ,
                    last_finished_at TIMESTAMPTZ,
                    last_successful_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (scope_type, scope_id)
                );
                """,
                TABLE_SYNC_STATE,
            )
        )
        cur.execute(
            _safe_query(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL,
                    query_name TEXT NOT NULL,
                    query_payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (username, query_name)
                );
                """,
                TABLE_SAVED_QUERY,
            )
        )
        cur.execute(
            _safe_query(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    settings JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """,
                TABLE_USER_SETTINGS,
            )
        )
        for index_name, table_name, columns in (
            (f"{TABLE_IMAGE}_group_idx", TABLE_IMAGE, "(group_id)"),
            (
                f"{TABLE_IMAGE}_acq_date_idx",
                TABLE_IMAGE,
                "(acquisition_date DESC NULLS LAST)",
            ),
            (f"{TABLE_SCOPE_ITEM}_image_idx", TABLE_SCOPE_ITEM, "(image_id)"),
            (f"{TABLE_SYNC_STATE}_status_idx", TABLE_SYNC_STATE, "(status)"),
            (f"{TABLE_SAVED_QUERY}_username_idx", TABLE_SAVED_QUERY, "(username)"),
            (f"{TABLE_USER_SETTINGS}_username_idx", TABLE_USER_SETTINGS, "(username)"),
        ):
            cur.execute(
                _safe_query(
                    f"CREATE INDEX IF NOT EXISTS {{}} ON {{}} {columns};",
                    index_name,
                    table_name,
                )
            )
        cur.execute(
            _safe_query(
                """
                CREATE INDEX IF NOT EXISTS {} ON {}
                USING GIN (to_tsvector('simple', search_document));
                """,
                f"{TABLE_IMAGE}_search_document_idx",
                TABLE_IMAGE,
            )
        )
        cur.execute(
            _safe_query(
                """
                CREATE INDEX IF NOT EXISTS {} ON {}
                USING GIN (
                    to_tsvector(
                        'simple',
                        replace(attribute_key, '_', ' ') || ' ' || attribute_text
                    )
                );
                """,
                f"{TABLE_ATTRIBUTE}_text_idx",
                TABLE_ATTRIBUTE,
            )
        )
        cur.execute(
            _safe_query(
                "CREATE INDEX IF NOT EXISTS {} ON {} (image_id);",
                f"{TABLE_ATTRIBUTE}_image_idx",
                TABLE_ATTRIBUTE,
            )
        )
    conn.commit()
    _mark_schema_ready(conn)


def ensure_sync_state_rows(
    conn, scopes: Iterable[dict[str, Any]], schema_version: int
) -> None:
    """Ensure sync state rows.

    Inputs: `conn`, `scopes`, `schema_version`. Output: None.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        for scope in scopes:
            cur.execute(
                _safe_query(
                    """
                    INSERT INTO {} (
                        scope_type,
                        scope_id,
                        scope_label,
                        schema_version,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (scope_type, scope_id)
                DO UPDATE SET
                    scope_label = EXCLUDED.scope_label,
                    schema_version = EXCLUDED.schema_version
                    """,
                    TABLE_SYNC_STATE,
                ),
                (
                    scope["scope_type"],
                    scope["scope_id"],
                    scope["label"],
                    schema_version,
                ),
            )
    conn.commit()


def list_sync_states(conn) -> list[dict[str, Any]]:
    """Return list sync states.

    Inputs: `conn`. Output: `list[dict[str, Any]]`.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                SELECT
                    scope_type,
                    scope_id,
                    scope_label,
                    schema_version,
                    status,
                    requested_by,
                    run_token,
                    last_cursor_image_id,
                    indexed_image_count,
                    current_message,
                    last_error,
                    last_started_at,
                    last_finished_at,
                    last_successful_at,
                    updated_at
                FROM {}
                ORDER BY scope_label ASC, scope_type ASC, scope_id ASC
                """,
                TABLE_SYNC_STATE,
            )
        )
        rows = cur.fetchall()
    columns = (
        "scope_type",
        "scope_id",
        "scope_label",
        "schema_version",
        "status",
        "requested_by",
        "run_token",
        "last_cursor_image_id",
        "indexed_image_count",
        "current_message",
        "last_error",
        "last_started_at",
        "last_finished_at",
        "last_successful_at",
        "updated_at",
    )
    return [dict(zip(columns, row)) for row in rows]


def try_start_scope_sync(
    conn,
    scope_type: str,
    scope_id: int,
    scope_label: str,
    schema_version: int,
    requested_by: str,
    run_token: str,
    stale_after_seconds: int,
) -> bool:
    """Try start scope sync.

    Inputs: `conn`, `scope_type`, `scope_id`, `scope_label`, `schema_version`,
    `requested_by`, `run_token`, `stale_after_seconds`. Output: `bool`.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                INSERT INTO {} (
                    scope_type,
                    scope_id,
                    scope_label,
                    schema_version,
                    status,
                    requested_by,
                    run_token,
                    current_message,
                    indexed_image_count,
                    last_error,
                    last_started_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, 'running', %s, %s, %s, 0, '', NOW(), NOW())
                ON CONFLICT (scope_type, scope_id)
                DO UPDATE SET
                    scope_label = EXCLUDED.scope_label,
                    schema_version = EXCLUDED.schema_version,
                    status = CASE
                        WHEN {}.status = 'running'
                         AND {}.updated_at > (NOW() - (%s * INTERVAL '1 second'))
                        THEN {}.status
                        ELSE 'running'
                    END,
                    requested_by = CASE
                        WHEN {}.status = 'running'
                         AND {}.updated_at > (NOW() - (%s * INTERVAL '1 second'))
                        THEN {}.requested_by
                        ELSE EXCLUDED.requested_by
                    END,
                    run_token = CASE
                        WHEN {}.status = 'running'
                         AND {}.updated_at > (NOW() - (%s * INTERVAL '1 second'))
                        THEN {}.run_token
                        ELSE EXCLUDED.run_token
                    END,
                    current_message = CASE
                        WHEN {}.status = 'running'
                         AND {}.updated_at > (NOW() - (%s * INTERVAL '1 second'))
                        THEN {}.current_message
                        ELSE EXCLUDED.current_message
                    END,
                    indexed_image_count = CASE
                        WHEN {}.status = 'running'
                         AND {}.updated_at > (NOW() - (%s * INTERVAL '1 second'))
                        THEN {}.indexed_image_count
                        ELSE 0
                    END,
                    last_error = CASE
                        WHEN {}.status = 'running'
                         AND {}.updated_at > (NOW() - (%s * INTERVAL '1 second'))
                        THEN {}.last_error
                        ELSE ''
                    END,
                    last_started_at = CASE
                        WHEN {}.status = 'running'
                         AND {}.updated_at > (NOW() - (%s * INTERVAL '1 second'))
                        THEN {}.last_started_at
                        ELSE NOW()
                    END,
                    updated_at = CASE
                        WHEN {}.status = 'running'
                         AND {}.updated_at > (NOW() - (%s * INTERVAL '1 second'))
                        THEN {}.updated_at
                        ELSE NOW()
                    END
                RETURNING status, run_token
                """,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
                TABLE_SYNC_STATE,
            ),
            (
                scope_type,
                scope_id,
                scope_label,
                schema_version,
                requested_by,
                run_token,
                "Indexing…",
                stale_after_seconds,
                stale_after_seconds,
                stale_after_seconds,
                stale_after_seconds,
                stale_after_seconds,
                stale_after_seconds,
                stale_after_seconds,
                stale_after_seconds,
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return bool(row and row[0] == "running" and row[1] == run_token)


def sync_run_is_active(
    conn,
    scope_type: str,
    scope_id: int,
    *,
    run_token: str,
) -> bool:
    """Sync run is active.

    Inputs: `conn`, `scope_type`, `scope_id`, `run_token`. Output: `bool`.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                SELECT 1
                FROM {}
                WHERE
                    scope_type = %s
                    AND scope_id = %s
                    AND status = 'running'
                    AND run_token = %s
                """,
                TABLE_SYNC_STATE,
            ),
            (
                scope_type,
                scope_id,
                run_token,
            ),
        )
        row = cur.fetchone()
    return bool(row and row[0] == 1)


def update_sync_progress(
    conn,
    scope_type: str,
    scope_id: int,
    *,
    commit: bool = True,
    run_token: str,
    indexed_image_count: int,
    current_message: str,
    last_cursor_image_id: int | None,
) -> None:
    """Update sync progress.

    Inputs: `conn`, `scope_type`, `scope_id`, `commit`, `run_token`,
    `indexed_image_count`, `current_message`, `last_cursor_image_id`. Output: None.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                UPDATE {}
                SET
                    indexed_image_count = %s,
                    current_message = %s,
                    last_cursor_image_id = %s,
                    updated_at = NOW()
                WHERE scope_type = %s AND scope_id = %s AND run_token = %s
                """,
                TABLE_SYNC_STATE,
            ),
            (
                indexed_image_count,
                current_message,
                last_cursor_image_id,
                scope_type,
                scope_id,
                run_token,
            ),
        )
    if commit:
        conn.commit()


def mark_sync_complete(
    conn,
    scope_type: str,
    scope_id: int,
    *,
    run_token: str,
    indexed_image_count: int,
    current_message: str,
) -> None:
    """Mark sync complete.

    Inputs: `conn`, `scope_type`, `scope_id`, `run_token`, `indexed_image_count`,
    `current_message`. Output: None.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                UPDATE {}
                SET
                    status = 'idle',
                    indexed_image_count = %s,
                    current_message = %s,
                    last_cursor_image_id = NULL,
                    last_error = '',
                    last_finished_at = NOW(),
                    last_successful_at = NOW(),
                    updated_at = NOW()
                WHERE scope_type = %s AND scope_id = %s AND run_token = %s
                """,
                TABLE_SYNC_STATE,
            ),
            (
                indexed_image_count,
                current_message,
                scope_type,
                scope_id,
                run_token,
            ),
        )
    conn.commit()


def mark_sync_error(
    conn,
    scope_type: str,
    scope_id: int,
    *,
    run_token: str,
    error_text: str,
    indexed_image_count: int,
) -> None:
    """Mark sync error.

    Inputs: `conn`, `scope_type`, `scope_id`, `run_token`, `error_text`,
    `indexed_image_count`. Output: None.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                UPDATE {}
                SET
                    status = 'error',
                    indexed_image_count = %s,
                    current_message = 'Indexing failed.',
                    last_error = %s,
                    last_finished_at = NOW(),
                    updated_at = NOW()
                WHERE scope_type = %s AND scope_id = %s AND run_token = %s
                """,
                TABLE_SYNC_STATE,
            ),
            (
                indexed_image_count,
                error_text,
                scope_type,
                scope_id,
                run_token,
            ),
        )
    conn.commit()


def upsert_search_document(
    conn,
    *,
    commit: bool = True,
    image_row: dict[str, Any],
    channels: Iterable[dict[str, Any]],
    attributes: Iterable[dict[str, Any]],
    scope_type: str,
    scope_id: int,
    run_token: str,
) -> None:
    """Upsert search document.

    Inputs: `conn`, `commit`, `image_row`, `channels`, `attributes`, `scope_type`,
    `scope_id`, `run_token`. Output: None.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                INSERT INTO {} (
                    image_id,
                    group_id,
                    group_name,
                    group_can_read,
                    owner_id,
                    owner_name,
                    image_name,
                    dataset_id,
                    dataset_name,
                    project_id,
                    project_name,
                    schema_version,
                    indexed_at,
                    acquisition_date,
                    instrument_manufacturer,
                    instrument_model,
                    objective_model,
                    objective_magnification,
                    objective_na,
                    detector_model,
                    detector_binning,
                    detector_gain,
                    pixel_size_x_um,
                    pixel_size_y_um,
                    z_step_um,
                    channel_summary,
                    search_document
                )
                VALUES (
                    %(image_id)s,
                    %(group_id)s,
                    %(group_name)s,
                    %(group_can_read)s,
                    %(owner_id)s,
                    %(owner_name)s,
                    %(image_name)s,
                    %(dataset_id)s,
                    %(dataset_name)s,
                    %(project_id)s,
                    %(project_name)s,
                    %(schema_version)s,
                    NOW(),
                    %(acquisition_date)s,
                    %(instrument_manufacturer)s,
                    %(instrument_model)s,
                    %(objective_model)s,
                    %(objective_magnification)s,
                    %(objective_na)s,
                    %(detector_model)s,
                    %(detector_binning)s,
                    %(detector_gain)s,
                    %(pixel_size_x_um)s,
                    %(pixel_size_y_um)s,
                    %(z_step_um)s,
                    %(channel_summary)s,
                    %(search_document)s
                )
                ON CONFLICT (image_id)
                DO UPDATE SET
                    group_id = EXCLUDED.group_id,
                    group_name = EXCLUDED.group_name,
                    group_can_read = EXCLUDED.group_can_read,
                    owner_id = EXCLUDED.owner_id,
                    owner_name = EXCLUDED.owner_name,
                    image_name = EXCLUDED.image_name,
                    dataset_id = EXCLUDED.dataset_id,
                    dataset_name = EXCLUDED.dataset_name,
                    project_id = EXCLUDED.project_id,
                    project_name = EXCLUDED.project_name,
                    schema_version = EXCLUDED.schema_version,
                    indexed_at = NOW(),
                    acquisition_date = EXCLUDED.acquisition_date,
                    instrument_manufacturer = EXCLUDED.instrument_manufacturer,
                    instrument_model = EXCLUDED.instrument_model,
                    objective_model = EXCLUDED.objective_model,
                    objective_magnification = EXCLUDED.objective_magnification,
                    objective_na = EXCLUDED.objective_na,
                    detector_model = EXCLUDED.detector_model,
                    detector_binning = EXCLUDED.detector_binning,
                    detector_gain = EXCLUDED.detector_gain,
                    pixel_size_x_um = EXCLUDED.pixel_size_x_um,
                    pixel_size_y_um = EXCLUDED.pixel_size_y_um,
                    z_step_um = EXCLUDED.z_step_um,
                    channel_summary = EXCLUDED.channel_summary,
                    search_document = EXCLUDED.search_document
                """,
                TABLE_IMAGE,
            ),
            image_row,
        )
        cur.execute(
            _safe_query("DELETE FROM {} WHERE image_id = %s", TABLE_CHANNEL),
            (image_row["image_id"],),
        )
        for channel in channels:
            cur.execute(
                _safe_query(
                    """
                    INSERT INTO {} (
                        image_id,
                        channel_index,
                        label,
                        excitation_nm,
                        emission_nm
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    TABLE_CHANNEL,
                ),
                (
                    image_row["image_id"],
                    channel["channel_index"],
                    channel["label"],
                    channel["excitation_nm"],
                    channel["emission_nm"],
                ),
            )
        cur.execute(
            _safe_query("DELETE FROM {} WHERE image_id = %s", TABLE_ATTRIBUTE),
            (image_row["image_id"],),
        )
        for attribute in attributes:
            cur.execute(
                _safe_query(
                    """
                    INSERT INTO {} (
                        image_id,
                        attribute_key,
                        attribute_text,
                        attribute_numeric
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    TABLE_ATTRIBUTE,
                ),
                (
                    image_row["image_id"],
                    attribute["attribute_key"],
                    attribute["attribute_text"],
                    attribute["attribute_numeric"],
                ),
            )
        cur.execute(
            _safe_query(
                """
                INSERT INTO {} (
                    scope_type,
                    scope_id,
                    image_id,
                    run_token,
                    last_seen_at
                )
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (scope_type, scope_id, image_id)
                DO UPDATE SET
                    run_token = EXCLUDED.run_token,
                    last_seen_at = NOW()
                """,
                TABLE_SCOPE_ITEM,
            ),
            (
                scope_type,
                scope_id,
                image_row["image_id"],
                run_token,
            ),
        )
    if commit:
        conn.commit()


def prune_scope_membership(conn, scope_type: str, scope_id: int, run_token: str) -> int:
    """Prune scope membership.

    Inputs: `conn`, `scope_type`, `scope_id`, `run_token`. Output: `int`.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                DELETE FROM {}
                WHERE scope_type = %s AND scope_id = %s AND run_token <> %s
                """,
                TABLE_SCOPE_ITEM,
            ),
            (scope_type, scope_id, run_token),
        )
        deleted = cur.rowcount or 0
    conn.commit()
    return deleted


def prune_orphan_documents(conn) -> int:
    """Prune orphan documents.

    Inputs: `conn`. Output: `int`.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                DELETE FROM {}
                WHERE NOT EXISTS (
                    SELECT 1 FROM {} scope_items
                    WHERE scope_items.image_id = {}.image_id
                )
                """,
                TABLE_IMAGE,
                TABLE_SCOPE_ITEM,
                TABLE_IMAGE,
            )
        )
        deleted = cur.rowcount or 0
    conn.commit()
    return deleted


_SEARCH_ROW_COLUMNS_SQL = """
            images.image_id,
            images.group_id,
            images.group_name,
            images.owner_id,
            images.owner_name,
            images.image_name,
            images.dataset_id,
            images.dataset_name,
            images.project_id,
            images.project_name,
            images.acquisition_date,
            images.instrument_manufacturer,
            images.instrument_model,
            images.objective_model,
            images.objective_magnification,
            images.objective_na,
            images.detector_model,
            images.detector_binning,
            images.detector_gain,
            images.pixel_size_x_um,
            images.pixel_size_y_um,
            images.z_step_um,
            images.channel_summary,
            images.indexed_at
"""

_SEARCH_FROM_WHERE_SQL = """
        FROM {} images
        JOIN {} scope_items ON scope_items.image_id = images.image_id
        WHERE
            (%s::text IS NULL OR scope_items.scope_type = %s)
            AND (%s::bigint IS NULL OR scope_items.scope_id = %s)
            AND
            (%s::bigint[] IS NULL OR images.group_id = ANY(%s::bigint[]))
            AND (
                (%s::bigint IS NULL AND images.group_can_read = TRUE)
                OR (
                    %s::bigint IS NOT NULL
                    AND (images.group_can_read = TRUE OR images.owner_id = %s)
                )
            )
            AND (
                %s = ''
                OR to_tsvector('simple', images.search_document)
                    @@ to_tsquery('simple', NULLIF(%s, ''))
                OR images.image_id IN (
                    SELECT attributes.image_id
                    FROM {} attributes
                    WHERE to_tsvector(
                            'simple',
                            replace(attributes.attribute_key, '_', ' ')
                            || ' '
                            || attributes.attribute_text
                          ) @@ to_tsquery('simple', NULLIF(%s, ''))
                )
            )
            AND (%s::timestamptz IS NULL OR images.acquisition_date >= %s)
            AND (%s::timestamptz IS NULL OR images.acquisition_date <= %s)
"""

_SEARCH_ORDER_SQL = """
        ORDER BY images.acquisition_date DESC NULLS LAST, images.image_id DESC
"""


def _search_count_sql():
    """Search count SQL.

    Inputs: none. Output: `_safe_query` result.
    """
    return _safe_query(
        f"""
        SELECT COUNT(DISTINCT images.image_id)
{_SEARCH_FROM_WHERE_SQL}
        """,
        TABLE_IMAGE,
        TABLE_SCOPE_ITEM,
        TABLE_ATTRIBUTE,
    )


def _search_rows_sql(*, paged: bool):
    """Search rows SQL.

    Inputs: `paged`. Output: `_safe_query` result.
    """
    pagination_sql = "\n        LIMIT %s OFFSET %s" if paged else ""
    return _safe_query(
        f"""
        SELECT DISTINCT
{_SEARCH_ROW_COLUMNS_SQL}
{_SEARCH_FROM_WHERE_SQL}
{_SEARCH_ORDER_SQL}{pagination_sql}
        """,
        TABLE_IMAGE,
        TABLE_SCOPE_ITEM,
        TABLE_ATTRIBUTE,
    )


def search_index_rows(
    conn,
    *,
    visible_group_ids: list[int] | None,
    current_user_id: int | None,
    scope_type: str | None = None,
    scope_id: int | None = None,
    query_text: str,
    filters: dict[str, Any],
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Search index rows.

    Inputs: `conn`, `visible_group_ids`, `current_user_id`, `scope_type`, `scope_id`,
    `query_text`, `filters`, `limit`, `offset`. Output: `tuple[list[dict[str, Any]],
    int]`.

    int]`.
    """
    ensure_schema(conn)
    if visible_group_ids is not None:
        if not visible_group_ids:
            return [], 0
        resolved_visible_group_ids: list[int] | None = list(visible_group_ids)
    else:
        resolved_visible_group_ids = None

    if current_user_id is not None:
        resolved_current_user_id: int | None = int(current_user_id)
    else:
        resolved_current_user_id = None
    resolved_scope_type = str(scope_type or "").strip() or None
    resolved_scope_id = int(scope_id) if scope_id is not None else None

    if query_text:
        tsquery = build_postgres_prefix_tsquery(query_text)
        if not tsquery:
            return [], 0
    else:
        tsquery = ""

    base_params: list[Any] = [
        resolved_scope_type,
        resolved_scope_type,
        resolved_scope_id,
        resolved_scope_id,
        resolved_visible_group_ids,
        resolved_visible_group_ids,
        resolved_current_user_id,
        resolved_current_user_id,
        resolved_current_user_id,
        tsquery,
        tsquery,
        tsquery,
        filters.get("acquisition_date_from"),
        filters.get("acquisition_date_from"),
        filters.get("acquisition_date_to"),
        filters.get("acquisition_date_to"),
    ]
    count_sql = _search_count_sql()
    paged_rows_sql = _search_rows_sql(paged=limit is not None)
    paged_params = list(base_params)
    if limit is not None:
        paged_params.extend([limit, offset])

    with conn.cursor() as cur:
        cur.execute(count_sql, base_params)
        count_row = cur.fetchone()
        total_count = int(count_row[0]) if count_row and count_row[0] is not None else 0
        cur.execute(paged_rows_sql, paged_params)
        rows = cur.fetchall()

    columns = (
        "image_id",
        "group_id",
        "group_name",
        "owner_id",
        "owner_name",
        "image_name",
        "dataset_id",
        "dataset_name",
        "project_id",
        "project_name",
        "acquisition_date",
        "instrument_manufacturer",
        "instrument_model",
        "objective_model",
        "objective_magnification",
        "objective_na",
        "detector_model",
        "detector_binning",
        "detector_gain",
        "pixel_size_x_um",
        "pixel_size_y_um",
        "z_step_um",
        "channel_summary",
        "indexed_at",
    )
    return [dict(zip(columns, row)) for row in rows], total_count


def load_user_settings(
    conn,
    username: str,
    *,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return load user settings.

    Inputs: `conn`, `username`, `defaults`. Output: `dict[str, Any]`.
    """
    ensure_schema(conn)
    resolved = dict(defaults or {})
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                SELECT settings
                FROM {}
                WHERE username = %s
                """,
                TABLE_USER_SETTINGS,
            ),
            (username,),
        )
        row = cur.fetchone()
    if row is None or not isinstance(row[0], dict):
        return resolved
    resolved.update(row[0])
    return resolved


def save_user_settings(
    conn, username: str, settings_payload: dict[str, Any]
) -> dict[str, Any]:
    """Save user settings.

    Inputs: `conn`, `username`, `settings_payload`. Output: `dict[str, Any]`. Raises on
    invalid or unavailable state.
    """
    _, extras = _load_psycopg2()
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                INSERT INTO {} (username, settings, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (username)
                DO UPDATE SET settings = EXCLUDED.settings, updated_at = NOW()
                """,
                TABLE_USER_SETTINGS,
            ),
            (username, extras.Json(settings_payload)),
        )
    conn.commit()
    stored = load_user_settings(conn, username)
    for key, value in settings_payload.items():
        if stored.get(key) != value:
            raise EnhancedSearchStoreError(USER_SETTINGS_NOT_PERSISTED_ERROR)
    verified = dict(settings_payload)
    verified.update(stored)
    return verified


def clear_scope_index(
    conn,
    scope_type: str,
    scope_id: int,
    *,
    current_message: str,
) -> dict[str, int]:
    """Clear scope index.

    Inputs: `conn`, `scope_type`, `scope_id`, `current_message`. Output: `dict[str,
    int]`.

    int]`.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                DELETE FROM {}
                WHERE scope_type = %s AND scope_id = %s
                """,
                TABLE_SCOPE_ITEM,
            ),
            (scope_type, scope_id),
        )
        deleted_scope_links = int(cur.rowcount or 0)
        cur.execute(
            _safe_query(
                """
                UPDATE {}
                SET
                    status = 'idle',
                    requested_by = '',
                    run_token = '',
                    last_cursor_image_id = NULL,
                    indexed_image_count = 0,
                    current_message = %s,
                    last_error = '',
                    last_started_at = NULL,
                    last_finished_at = NOW(),
                    last_successful_at = NULL,
                    updated_at = NOW()
                WHERE scope_type = %s AND scope_id = %s
                """,
                TABLE_SYNC_STATE,
            ),
            (current_message, scope_type, scope_id),
        )
    conn.commit()
    deleted_documents = prune_orphan_documents(conn)
    return {
        "deleted_scope_links": deleted_scope_links,
        "deleted_documents": deleted_documents,
    }


def list_saved_queries(conn, username: str) -> list[dict[str, Any]]:
    """Return list saved queries.

    Inputs: `conn`, `username`. Output: `list[dict[str, Any]]`.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                SELECT id, query_name, query_payload, created_at, updated_at
                FROM {}
                WHERE username = %s
                ORDER BY updated_at DESC, query_name ASC
                """,
                TABLE_SAVED_QUERY,
            ),
            (username,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "query_name": row[1],
            "query_payload": row[2],
            "created_at": row[3],
            "updated_at": row[4],
        }
        for row in rows
    ]


def save_saved_query(
    conn, username: str, query_name: str, query_payload: dict[str, Any]
) -> None:
    """Save saved query.

    Inputs: `conn`, `username`, `query_name`, `query_payload`. Output: None.
    """
    _, extras = _load_psycopg2()
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                """
                INSERT INTO {} (username, query_name, query_payload, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (username, query_name)
                DO UPDATE SET query_payload = EXCLUDED.query_payload, updated_at = NOW()
                """,
                TABLE_SAVED_QUERY,
            ),
            (
                username,
                query_name,
                extras.Json(query_payload),
            ),
        )
    conn.commit()


def delete_saved_query(conn, username: str, query_id: int) -> bool:
    """Delete saved query.

    Inputs: `conn`, `username`, `query_id`. Output: `bool`.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            _safe_query(
                "DELETE FROM {} WHERE username = %s AND id = %s",
                TABLE_SAVED_QUERY,
            ),
            (username, query_id),
        )
        deleted = cur.rowcount or 0
    conn.commit()
    return deleted > 0
