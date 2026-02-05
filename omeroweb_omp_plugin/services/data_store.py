import logging
import re
from contextlib import contextmanager

from ..strings import errors
from omero_plugin_common.env_utils import ENV_FILE_OMEROWEB, get_env

logger = logging.getLogger(__name__)

TABLE_NAME = "omp_variable_sets"
TABLE_NAME_AI_CREDENTIALS = "omp_ai_credentials"
TABLE_NAME_USER_SETTINGS = "omp_user_settings"
TABLE_PREFIX = "omp_"
ENV_USER = "OMP_DATA_USER"
ENV_PASS = "OMP_DATA_PASS"
ENV_HOST = "OMP_DATA_HOST"
ENV_DB = "OMP_DATA_DB"
ENV_PORT = "OMP_DATA_PORT"


class VariableStoreError(Exception):
    """Raised when variable set persistence fails."""


class AiCredentialStoreError(Exception):
    """Raised when AI credential persistence fails."""


class UserSettingsStoreError(Exception):
    """Raised when user settings persistence fails."""


class UserDataStoreError(Exception):
    """Raised when user data deletion fails."""


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
        raise VariableStoreError(errors.psycopg2_missing())

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
        raise VariableStoreError(errors.psycopg2_missing())

    _psycopg2_sql = sql
    return _psycopg2_sql


def _db_params():
    user = get_env(ENV_USER, env_file=ENV_FILE_OMEROWEB)
    password = get_env(ENV_PASS, env_file=ENV_FILE_OMEROWEB)
    host = get_env(ENV_HOST, env_file=ENV_FILE_OMEROWEB)
    dbname = get_env(ENV_DB, env_file=ENV_FILE_OMEROWEB)

    if not user or not password:
        raise VariableStoreError(errors.missing_db_credentials())

    candidate = get_env(ENV_PORT, env_file=ENV_FILE_OMEROWEB)
    candidate_str = str(candidate).strip()
    try:
        port = int(candidate_str)
    except ValueError:
        raise VariableStoreError(f"Invalid database port value: {candidate_str}")

    port_candidates = [port]

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
        except VariableStoreError:
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
        raise VariableStoreError(errors.db_connection_failed())

    try:
        yield conn
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _ensure_schema(conn):
    sql = _load_psycopg2_sql()
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL,
                    set_name TEXT NOT NULL,
                    var_names JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(username, set_name)
                );
                """
            ).format(sql.Identifier(TABLE_NAME))
        )
        cur.execute(
            sql.SQL(
                """
                CREATE INDEX IF NOT EXISTS {} ON {} (username);
                """
            ).format(
                sql.Identifier(f"{TABLE_NAME}_username_idx"),
                sql.Identifier(TABLE_NAME),
            )
        )
    conn.commit()


def _ensure_ai_schema(conn):
    sql = _load_psycopg2_sql()
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(username, provider)
                );
                """
            ).format(sql.Identifier(TABLE_NAME_AI_CREDENTIALS))
        )
        cur.execute(
            sql.SQL(
                """
                CREATE INDEX IF NOT EXISTS {} ON {} (username);
                """
            ).format(
                sql.Identifier(f"{TABLE_NAME_AI_CREDENTIALS}_username_idx"),
                sql.Identifier(TABLE_NAME_AI_CREDENTIALS),
            )
        )
    conn.commit()


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


def list_variable_sets(username):
    try:
        sql = _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT set_name
                        FROM {}
                        WHERE username = %s
                        ORDER BY updated_at DESC, set_name ASC
                        """
                    ).format(sql.Identifier(TABLE_NAME)),
                    (username,),
                )
                rows = cur.fetchall()
                return [r[0] for r in rows if r and r[0] is not None]
    except VariableStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to list variable sets for %s: %s", username, e)
        raise VariableStoreError(errors.variable_sets_fetch_failed())


def save_variable_set(username, set_name, var_names):
    try:
        _, extras = _load_psycopg2()
        sql = _load_psycopg2_sql()
        json_payload = extras.Json(var_names)
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {} (username, set_name, var_names, updated_at)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (username, set_name)
                        DO UPDATE SET var_names = EXCLUDED.var_names, updated_at = NOW()
                        """
                    ).format(sql.Identifier(TABLE_NAME)),
                    (username, set_name, json_payload),
                )
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT var_names
                        FROM {}
                        WHERE username = %s AND set_name = %s
                        """
                    ).format(sql.Identifier(TABLE_NAME)),
                    (username, set_name),
                )
                row = cur.fetchone()
                if row is None:
                    raise VariableStoreError(errors.variable_set_not_persisted())
    except VariableStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to save variable set '%s' for %s: %s", set_name, username, e)
        raise VariableStoreError(errors.variable_set_save_failed())


def load_variable_set(username, set_name):
    try:
        sql = _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT var_names
                        FROM {}
                        WHERE username = %s AND set_name = %s
                        """
                    ).format(sql.Identifier(TABLE_NAME)),
                    (username, set_name),
                )
                row = cur.fetchone()
                return row[0] if row else None
    except VariableStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to load variable set '%s' for %s: %s", set_name, username, e)
        raise VariableStoreError(errors.variable_set_load_failed())


def delete_variable_set(username, set_name):
    """
    Delete a saved variable set for a user.
    """
    try:
        sql = _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        DELETE FROM {}
                        WHERE username = %s AND set_name = %s
                        """
                    ).format(sql.Identifier(TABLE_NAME)),
                    (username, set_name),
                )

                if cur.rowcount == 0:
                    raise VariableStoreError(errors.variable_set_missing(set_name))

            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT 1
                        FROM {}
                        WHERE username = %s AND set_name = %s
                        """
                    ).format(sql.Identifier(TABLE_NAME)),
                    (username, set_name),
                )
                if cur.fetchone():
                    raise VariableStoreError(errors.variable_set_delete_unconfirmed())

    except VariableStoreError:
        raise
    except Exception as e:
        logger.exception(
            "Failed to delete variable set '%s' for %s: %s",
            set_name,
            username,
            e,
        )
        raise VariableStoreError(errors.variable_set_delete_failed())


def list_ai_credentials(username):
    try:
        sql = _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_ai_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT provider
                        FROM {}
                        WHERE username = %s
                        ORDER BY provider ASC
                        """
                    ).format(sql.Identifier(TABLE_NAME_AI_CREDENTIALS)),
                    (username,),
                )
                rows = cur.fetchall()
                return [r[0] for r in rows if r and r[0] is not None]
    except AiCredentialStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to list AI credentials for %s: %s", username, e)
        raise AiCredentialStoreError(errors.ai_credentials_fetch_failed())


def get_ai_credential(username, provider):
    try:
        sql = _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_ai_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT api_key
                        FROM {}
                        WHERE username = %s AND provider = %s
                        """
                    ).format(sql.Identifier(TABLE_NAME_AI_CREDENTIALS)),
                    (username, provider),
                )
                row = cur.fetchone()
                return row[0] if row and row[0] is not None else None
    except AiCredentialStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to fetch AI credentials for %s/%s: %s", username, provider, e)
        raise AiCredentialStoreError(errors.ai_credentials_fetch_failed())


def save_ai_credentials(username, provider, api_key):
    try:
        sql = _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_ai_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {} (username, provider, api_key, updated_at)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (username, provider)
                        DO UPDATE SET api_key = EXCLUDED.api_key, updated_at = NOW()
                        """
                    ).format(sql.Identifier(TABLE_NAME_AI_CREDENTIALS)),
                    (username, provider, api_key),
                )
            conn.commit()
    except AiCredentialStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to save AI credentials for %s/%s: %s", username, provider, e)
        raise AiCredentialStoreError(errors.ai_credentials_save_failed())


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


def delete_all_user_settings(username):
    try:
        sql = _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_user_settings_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        DELETE FROM {}
                        WHERE username = %s
                        """
                    ).format(sql.Identifier(TABLE_NAME_USER_SETTINGS)),
                    (username,),
                )
                deleted = cur.rowcount
            conn.commit()
            return deleted
    except UserSettingsStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to delete user settings for %s: %s", username, e)
        raise UserSettingsStoreError(errors.user_settings_delete_failed())


def delete_all_variable_sets(username):
    try:
        sql = _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        DELETE FROM {}
                        WHERE username = %s
                        """
                    ).format(sql.Identifier(TABLE_NAME)),
                    (username,),
                )
                deleted = cur.rowcount
            conn.commit()
            return deleted
    except VariableStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to delete variable sets for %s: %s", username, e)
        raise VariableStoreError(errors.variable_sets_delete_failed())


def delete_all_ai_credentials(username):
    try:
        sql = _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_ai_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        DELETE FROM {}
                        WHERE username = %s
                        """
                    ).format(sql.Identifier(TABLE_NAME_AI_CREDENTIALS)),
                    (username,),
                )
                deleted = cur.rowcount
            conn.commit()
            return deleted
    except AiCredentialStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to delete AI credentials for %s: %s", username, e)
        raise AiCredentialStoreError(errors.ai_credentials_delete_failed())


def delete_all_user_data(username):
    try:
        with _connect() as conn:
            sql = _load_psycopg2_sql()
            tables = _list_user_scoped_tables(conn)
            deleted_counts = {}
            with conn.cursor() as cur:
                for table in tables:
                    cur.execute(
                        sql.SQL(
                            """
                            DELETE FROM {}
                            WHERE username = %s
                            """
                        ).format(sql.Identifier(table)),
                        (username,),
                    )
                    deleted_counts[table] = cur.rowcount
            conn.commit()
            return deleted_counts
    except (VariableStoreError, AiCredentialStoreError, UserSettingsStoreError):
        raise UserDataStoreError(errors.user_data_delete_failed())
    except Exception as e:
        logger.exception("Failed to delete user data for %s: %s", username, e)
        raise UserDataStoreError(errors.user_data_delete_failed())


def _list_user_scoped_tables(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT table_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND column_name = 'username'
              AND table_name LIKE %s
            """,
            (f"{TABLE_PREFIX}%",),
        )
        rows = cur.fetchall()

    tables = []
    for (table_name,) in rows:
        if re.match(r"^omp_[A-Za-z0-9_]+$", table_name):
            tables.append(table_name)
    return sorted(tables)
