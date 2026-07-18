import logging
import os
from contextlib import contextmanager
from typing import Any

from omero_plugin_common.logging_utils import sanitize_log_value, sanitized_exc_info

from ..strings import errors

logger = logging.getLogger(__name__)

TABLE_NAME_USER_SETTINGS = "upload_user_settings"
TABLE_NAME_SPECIAL_METHOD_SETTINGS = "upload_special_method_settings"
ENV_USER = "OMP_DATA_USER"
ENV_AUTH = "OMP_DATA_PASS"
ENV_HOST = "OMP_DATA_HOST"
ENV_DB = "OMP_DATA_DB"
ENV_PORT = "OMP_DATA_PORT"


class UserSettingsStoreError(Exception):
    """Raised when user settings persistence fails."""


_psycopg2_mod: Any | None = None
_psycopg2_extras: Any | None = None
_psycopg2_sql: Any | None = None


def _load_psycopg2():
    """Load the psycopg2.

    Inputs: none. Output: `tuple`. Raises: UserSettingsStoreError when validation or
    external operations fail.
    """
    if _psycopg2_mod is not None and _psycopg2_extras is not None:
        return _psycopg2_mod, _psycopg2_extras

    try:
        import psycopg2
        from psycopg2 import extras
    except ImportError as exc:
        raise UserSettingsStoreError(errors.psycopg2_missing()) from exc

    return psycopg2, extras


def _load_psycopg2_sql():
    """Load psycopg2 SQL helpers or raise the plugin store error.

    Inputs: none. Output: `sql`. Raises: UserSettingsStoreError when validation or
    external operations fail.
    """
    if _psycopg2_sql is not None:
        return _psycopg2_sql

    try:
        from psycopg2 import sql
    except ImportError as exc:
        raise UserSettingsStoreError(errors.psycopg2_missing()) from exc

    return sql


def _safe_query(template, *identifiers):
    """Compose a parameterized SQL query with safe psycopg2.sql identifiers.

    Inputs: `template`, `*identifiers`. Output: `format` result.
    """
    sql_mod = _load_psycopg2_sql()
    return sql_mod.SQL(template).format(*[sql_mod.Identifier(i) for i in identifiers])


def _db_params():
    """Return the db params.

    Inputs: none. Output: db params result. Raises: UserSettingsStoreError when validation or
    the called operation fails.
    """
    user = os.environ.get(ENV_USER)
    password = os.environ.get(ENV_AUTH)
    host = os.environ.get(ENV_HOST)
    dbname = os.environ.get(ENV_DB)

    if not user or not password or not host or not dbname:
        raise UserSettingsStoreError(errors.missing_db_credentials())

    port_candidates = []
    for candidate in (
        os.environ.get(ENV_PORT),
        os.environ.get("PGPORT"),
        "5433",
        "5432",
    ):
        if not candidate:
            continue

        candidate_str = str(candidate).strip()
        if not candidate_str:
            continue

        try:
            port = int(candidate_str)
        except ValueError:
            logger.warning(
                "Ignoring invalid port value '%s' for database.", candidate_str
            )
            continue

        if port not in port_candidates:
            port_candidates.append(port)

    base_params = {
        "user": user,
        "password": password,
        "host": host,
        "dbname": dbname,
    }

    return [{**base_params, "port": port} for port in port_candidates]


@contextmanager
def _connect():
    """Open the connection for `omeroweb_import.services.data_store`.

    Inputs: none. Output: iterator of yielded items. Raises: UserSettingsStoreError when
    validation or the called operation fails.
    """
    psycopg2, _ = _load_psycopg2()
    param_options = _db_params()
    conn = None
    last_error = None

    for params in param_options:
        try:
            conn = psycopg2.connect(**params)
            break
        except UserSettingsStoreError:
            raise
        except Exception as e:
            logger.warning(
                "Database connection failed for %s:%s: %s",
                sanitize_log_value(params.get("host")),
                sanitize_log_value(params.get("port")),
                sanitize_log_value(e),
            )
            last_error = e

    if conn is None:
        if last_error is not None:
            logger.error(
                "Database connection failed for all configured hosts/ports: %s",
                sanitize_log_value(last_error),
                exc_info=sanitized_exc_info(last_error),
            )
        else:
            logger.error("Database connection failed for all configured hosts/ports.")
        raise UserSettingsStoreError(errors.db_connection_failed())

    try:
        yield conn
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in data_store.py", exc_info=exc
                )


def _ensure_user_settings_schema(conn):
    """Ensure the user settings schema.

    Inputs: `conn` OMERO gateway connection. Output: None.
    """
    _load_psycopg2_sql()
    with conn.cursor() as cur:
        stmt = _safe_query(
            """
            CREATE TABLE IF NOT EXISTS {} (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                settings JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            """,
            TABLE_NAME_USER_SETTINGS,
        )
        cur.execute(stmt)
        stmt = _safe_query(
            """
            CREATE INDEX IF NOT EXISTS {} ON {} (username);
            """,
            f"{TABLE_NAME_USER_SETTINGS}_username_idx",
            TABLE_NAME_USER_SETTINGS,
        )
        cur.execute(stmt)
    conn.commit()


def _ensure_special_method_settings_schema(conn):
    """Ensure the special method settings schema.

    Inputs: `conn` OMERO gateway connection. Output: None.
    """
    _load_psycopg2_sql()
    with conn.cursor() as cur:
        stmt = _safe_query(
            """
                CREATE TABLE IF NOT EXISTS {} (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL,
                    method_key TEXT NOT NULL,
                    settings JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (username, method_key)
                );
                """,
            TABLE_NAME_SPECIAL_METHOD_SETTINGS,
        )
        cur.execute(stmt)
        stmt = _safe_query(
            """
                CREATE INDEX IF NOT EXISTS {} ON {} (username);
                """,
            f"{TABLE_NAME_SPECIAL_METHOD_SETTINGS}_username_idx",
            TABLE_NAME_SPECIAL_METHOD_SETTINGS,
        )
        cur.execute(stmt)
        stmt = _safe_query(
            """
                CREATE INDEX IF NOT EXISTS {} ON {} (method_key);
                """,
            f"{TABLE_NAME_SPECIAL_METHOD_SETTINGS}_method_idx",
            TABLE_NAME_SPECIAL_METHOD_SETTINGS,
        )
        cur.execute(stmt)
    conn.commit()


def save_user_settings(username, settings_payload):
    """Save the user settings.

    Inputs: `username` username, `settings_payload`. Output: None. Raises:
    UserSettingsStoreError when validation or the called operation fails.
    """
    try:
        _, extras = _load_psycopg2()
        _load_psycopg2_sql()
        json_payload = extras.Json(settings_payload)
        with _connect() as conn:
            _ensure_user_settings_schema(conn)
            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        INSERT INTO {} (username, settings, updated_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (username)
                        DO UPDATE SET settings = EXCLUDED.settings, updated_at = NOW()
                        """,
                    TABLE_NAME_USER_SETTINGS,
                )
                cur.execute(stmt, (username, json_payload))
            conn.commit()

            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        SELECT settings
                        FROM {}
                        WHERE username = %s
                        """,
                    TABLE_NAME_USER_SETTINGS,
                )
                cur.execute(stmt, (username,))
                row = cur.fetchone()
                if row is None:
                    raise UserSettingsStoreError(errors.user_settings_not_persisted())
    except UserSettingsStoreError:
        raise
    except Exception as e:
        logger.error(
            "Failed to save user settings for %s: %s",
            sanitize_log_value(username),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise UserSettingsStoreError(errors.user_settings_save_failed()) from None


def save_special_method_settings(username, method_key, settings_payload):
    """Save the special method settings.

    Inputs: `username` username, `method_key`, `settings_payload`. Output: None. Raises:
    UserSettingsStoreError when validation or the called operation fails.
    """
    try:
        _, extras = _load_psycopg2()
        _load_psycopg2_sql()
        json_payload = extras.Json(settings_payload)
        with _connect() as conn:
            _ensure_special_method_settings_schema(conn)
            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        INSERT INTO {} (username, method_key, settings, updated_at)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (username, method_key)
                        DO UPDATE SET settings = EXCLUDED.settings, updated_at = NOW()
                        """,
                    TABLE_NAME_SPECIAL_METHOD_SETTINGS,
                )
                cur.execute(stmt, (username, method_key, json_payload))
            conn.commit()

            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        SELECT settings
                        FROM {}
                        WHERE username = %s AND method_key = %s
                        """,
                    TABLE_NAME_SPECIAL_METHOD_SETTINGS,
                )
                cur.execute(stmt, (username, method_key))
                row = cur.fetchone()
                if row is None:
                    raise UserSettingsStoreError(
                        errors.special_method_settings_not_persisted()
                    )
    except UserSettingsStoreError:
        raise
    except Exception as e:
        logger.error(
            "Failed to save special method settings for %s: %s",
            sanitize_log_value(username),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise UserSettingsStoreError(
            errors.special_method_settings_save_failed()
        ) from None


def load_special_method_settings(username, method_key):
    """Return load special method settings.

    Inputs: `username` username, `method_key`. Output: settings mapping. Raises:
    UserSettingsStoreError when validation or the called operation fails.
    """
    try:
        _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_special_method_settings_schema(conn)
            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        SELECT settings
                        FROM {}
                        WHERE username = %s AND method_key = %s
                        """,
                    TABLE_NAME_SPECIAL_METHOD_SETTINGS,
                )
                cur.execute(stmt, (username, method_key))
                row = cur.fetchone()
                if row is None:
                    return None
                return row[0]
    except UserSettingsStoreError:
        raise
    except Exception as e:
        logger.error(
            "Failed to load special method settings for %s: %s",
            sanitize_log_value(username),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise UserSettingsStoreError(errors.db_connection_failed()) from None
