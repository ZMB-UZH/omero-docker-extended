import logging
import os
from contextlib import contextmanager

from ..strings import errors

logger = logging.getLogger(__name__)

TABLE_NAME_USER_SETTINGS = "upload_user_settings"
TABLE_NAME_SPECIAL_METHOD_SETTINGS = "upload_special_method_settings"
ENV_USER = "OMP_DATA_USER"
ENV_PASS = "OMP_DATA_PASS"
ENV_HOST = "OMP_DATA_HOST"
ENV_DB = "OMP_DATA_DB"
ENV_PORT = "OMP_DATA_PORT"


class UserSettingsStoreError(Exception):
    """Raised when user settings persistence fails."""


_psycopg2_mod = None
_psycopg2_extras = None
_psycopg2_sql = None


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


def _load_psycopg2_sql():
    global _psycopg2_sql

    if _psycopg2_sql is not None:
        return _psycopg2_sql

    try:
        from psycopg2 import sql  # type: ignore
    except ImportError:
        raise UserSettingsStoreError(errors.psycopg2_missing())

    _psycopg2_sql = sql
    return _psycopg2_sql


def _db_params():
    user = os.environ.get(ENV_USER)
    password = os.environ.get(ENV_PASS)
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
    sql = _load_psycopg2_sql()
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    settings JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            ).format(sql.Identifier(TABLE_NAME_USER_SETTINGS))
        )
        cur.execute(
            sql.SQL(
                """
                CREATE INDEX IF NOT EXISTS {} ON {} (username);
                """
            ).format(
                sql.Identifier(f"{TABLE_NAME_USER_SETTINGS}_username_idx"),
                sql.Identifier(TABLE_NAME_USER_SETTINGS),
            )
        )
    conn.commit()


def _ensure_special_method_settings_schema(conn):
    sql = _load_psycopg2_sql()
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
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
                """
            ).format(sql.Identifier(TABLE_NAME_SPECIAL_METHOD_SETTINGS))
        )
        cur.execute(
            sql.SQL(
                """
                CREATE INDEX IF NOT EXISTS {} ON {} (username);
                """
            ).format(
                sql.Identifier(f"{TABLE_NAME_SPECIAL_METHOD_SETTINGS}_username_idx"),
                sql.Identifier(TABLE_NAME_SPECIAL_METHOD_SETTINGS),
            )
        )
        cur.execute(
            sql.SQL(
                """
                CREATE INDEX IF NOT EXISTS {} ON {} (method_key);
                """
            ).format(
                sql.Identifier(f"{TABLE_NAME_SPECIAL_METHOD_SETTINGS}_method_idx"),
                sql.Identifier(TABLE_NAME_SPECIAL_METHOD_SETTINGS),
            )
        )
    conn.commit()


def save_user_settings(username, settings_payload):
    try:
        _, extras = _load_psycopg2()
        sql = _load_psycopg2_sql()
        json_payload = extras.Json(settings_payload)
        with _connect() as conn:
            _ensure_user_settings_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {} (username, settings, updated_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (username)
                        DO UPDATE SET settings = EXCLUDED.settings, updated_at = NOW()
                        """
                    ).format(sql.Identifier(TABLE_NAME_USER_SETTINGS)),
                    (username, json_payload),
                )
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT settings
                        FROM {}
                        WHERE username = %s
                        """
                    ).format(sql.Identifier(TABLE_NAME_USER_SETTINGS)),
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


def save_special_method_settings(username, method_key, settings_payload):
    try:
        _, extras = _load_psycopg2()
        sql = _load_psycopg2_sql()
        json_payload = extras.Json(settings_payload)
        with _connect() as conn:
            _ensure_special_method_settings_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {} (username, method_key, settings, updated_at)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (username, method_key)
                        DO UPDATE SET settings = EXCLUDED.settings, updated_at = NOW()
                        """
                    ).format(sql.Identifier(TABLE_NAME_SPECIAL_METHOD_SETTINGS)),
                    (username, method_key, json_payload),
                )
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT settings
                        FROM {}
                        WHERE username = %s AND method_key = %s
                        """
                    ).format(sql.Identifier(TABLE_NAME_SPECIAL_METHOD_SETTINGS)),
                    (username, method_key),
                )
                row = cur.fetchone()
                if row is None:
                    raise UserSettingsStoreError(errors.special_method_settings_not_persisted())
    except UserSettingsStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to save special method settings for %s: %s", username, e)
        raise UserSettingsStoreError(errors.special_method_settings_save_failed())


def load_special_method_settings(username, method_key):
    try:
        sql = _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_special_method_settings_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT settings
                        FROM {}
                        WHERE username = %s AND method_key = %s
                        """
                    ).format(sql.Identifier(TABLE_NAME_SPECIAL_METHOD_SETTINGS)),
                    (username, method_key),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return row[0]
    except UserSettingsStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to load special method settings for %s: %s", username, e)
        raise UserSettingsStoreError(errors.db_connection_failed())
