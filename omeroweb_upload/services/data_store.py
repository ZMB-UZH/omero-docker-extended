import logging
import os
from contextlib import contextmanager

from ..strings import errors

logger = logging.getLogger(__name__)

TABLE_NAME_USER_SETTINGS = "upload_user_settings"
ENV_USER = "OMP_DATA_USER"
ENV_PASS = "OMP_DATA_PASS"
ENV_HOST = "OMP_DATA_HOST"
ENV_DB = "OMP_DATA_DB"
ENV_PORT = "OMP_DATA_PORT"


class UserSettingsStoreError(Exception):
    """Raised when user settings persistence fails."""


_psycopg2_mod = None
_psycopg2_extras = None


def _load_psycopg2():
    global _psycopg2_mod, _psycopg2_extras

    if _psycopg2_mod is not None and _psycopg2_extras is not None:
        return _psycopg2_mod, _psycopg2_extras

    try:
        import psycopg2  # type: ignore
        from psycopg2 import extras  # type: ignore
    except ImportError:
        raise UserSettingsStoreError(errors.psycopg2_missing())

    _psycopg2_mod = psycopg2
    _psycopg2_extras = extras
    return _psycopg2_mod, _psycopg2_extras


def _db_params():
    user = os.environ.get(ENV_USER)
    password = os.environ.get(ENV_PASS)
    host = os.environ.get(ENV_HOST, "database_plugin")
    dbname = os.environ.get(ENV_DB, "omp-plugin")

    if not user or not password:
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
            logger.warning("Ignoring invalid port value '%s' for database.", candidate_str)
            continue

        if port not in port_candidates:
            port_candidates.append(port)

    if not port_candidates:
        port_candidates.append(5432)

    base_params = {
        "user": user,
        "password": password,
        "host": host,
        "dbname": dbname,
    }

    return [{**base_params, "port": port} for port in port_candidates]


@contextmanager
def _connect():
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
                params.get("host"),
                params.get("port"),
                e,
            )
            last_error = e

    if conn is None:
        logger.exception("Database connection failed for all configured hosts/ports: %s", last_error)
        raise UserSettingsStoreError(errors.db_connection_failed())

    try:
        yield conn
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _ensure_user_settings_schema(conn):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME_USER_SETTINGS} (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                settings JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {TABLE_NAME_USER_SETTINGS}_username_idx
                ON {TABLE_NAME_USER_SETTINGS} (username);
            """
        )
    conn.commit()


def save_user_settings(username, settings_payload):
    try:
        _, extras = _load_psycopg2()
        json_payload = extras.Json(settings_payload)
        with _connect() as conn:
            _ensure_user_settings_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {TABLE_NAME_USER_SETTINGS} (username, settings, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (username)
                    DO UPDATE SET settings = EXCLUDED.settings, updated_at = NOW()
                    """,
                    (username, json_payload),
                )
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT settings
                    FROM {TABLE_NAME_USER_SETTINGS}
                    WHERE username = %s
                    """,
                    (username,),
                )
                row = cur.fetchone()
                if row is None:
                    raise UserSettingsStoreError(errors.user_settings_not_persisted())
    except UserSettingsStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to save user settings for %s: %s", username, e)
        raise UserSettingsStoreError(errors.user_settings_save_failed())
