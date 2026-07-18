import base64
import hashlib
import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from omero_plugin_common.logging_utils import sanitize_log_value, sanitized_exc_info

from ..strings import errors
from omero_plugin_common.env_utils import ENV_FILE_OMEROWEB, get_env

logger = logging.getLogger(__name__)

TABLE_NAME = "omp_variable_sets"
TABLE_NAME_AI_CREDENTIALS = "omp_ai_credentials"
TABLE_NAME_USER_SETTINGS = "omp_user_settings"
TABLE_PREFIX = "omp_"
ENV_USER = "OMP_DATA_USER"
ENV_AUTH = "OMP_DATA_PASS"
ENV_HOST = "OMP_DATA_HOST"
ENV_DB = "OMP_DATA_DB"
ENV_PORT = "OMP_DATA_PORT"
ENV_AI_CREDENTIAL_ENCRYPTION_KEY = "OMP_AI_CREDENTIAL_ENCRYPTION_KEY"
AI_CREDENTIAL_ENCRYPTION_PREFIX = "fernet:v1:"


class VariableStoreError(Exception):
    """Raised when variable set persistence fails."""


class AiCredentialStoreError(Exception):
    """Raised when AI credential persistence fails."""


class UserSettingsStoreError(Exception):
    """Raised when user settings persistence fails."""


class UserDataStoreError(Exception):
    """Raised when user data deletion fails."""


@dataclass
class _Psycopg2ModuleCache:
    """Helper type for psycopg2 module cache behavior."""

    module: Any | None = None
    extras: Any | None = None
    sql: Any | None = None


_PSYCOPG2_MODULES = _Psycopg2ModuleCache()


def _load_psycopg2():
    """Load the psycopg2.

    Inputs: none. Output: `tuple`. Raises: VariableStoreError when validation or
    external operations fail.
    """
    if _PSYCOPG2_MODULES.module is not None and _PSYCOPG2_MODULES.extras is not None:
        return _PSYCOPG2_MODULES.module, _PSYCOPG2_MODULES.extras

    try:
        import psycopg2
        from psycopg2 import extras
    except ImportError as exc:
        raise VariableStoreError(errors.psycopg2_missing()) from exc

    _PSYCOPG2_MODULES.module = psycopg2
    _PSYCOPG2_MODULES.extras = extras
    return _PSYCOPG2_MODULES.module, _PSYCOPG2_MODULES.extras


def _load_psycopg2_sql():
    """Load the psycopg2 SQL.

    Inputs: none. Output: load psycopg2 SQL result. Raises: VariableStoreError when validation
    or the called operation fails.
    """
    if _PSYCOPG2_MODULES.sql is not None:
        return _PSYCOPG2_MODULES.sql

    try:
        from psycopg2 import sql
    except ImportError as exc:
        raise VariableStoreError(errors.psycopg2_missing()) from exc

    _PSYCOPG2_MODULES.sql = sql
    return _PSYCOPG2_MODULES.sql


def _safe_query(template, *identifiers):
    """Compose a parameterized SQL query with safe psycopg2.sql identifiers.

    Inputs: `template`, `*identifiers`. Output: `format` result.
    """
    sql_mod = _load_psycopg2_sql()
    return sql_mod.SQL(template).format(*[sql_mod.Identifier(i) for i in identifiers])


def _load_fernet():
    """Load Fernet primitives for AI credential encryption.

    Inputs: none. Output: Fernet class and InvalidToken exception type.
    """
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as exc:  # pragma: no cover - dependency present in CI image
        raise AiCredentialStoreError(errors.ai_credentials_save_failed()) from exc
    return Fernet, InvalidToken


def _ai_credential_key_material():
    """Return secret material used to derive the AI credential encryption key.

    Inputs: deployment environment and Django settings. Output: secret string.
    """
    try:
        explicit = get_env(
            ENV_AI_CREDENTIAL_ENCRYPTION_KEY,
            env_file=ENV_FILE_OMEROWEB,
        )
    except RuntimeError:
        explicit = None
    if explicit:
        return str(explicit)
    secret_key = getattr(settings, "SECRET_KEY", "")
    if not secret_key:
        raise AiCredentialStoreError(errors.ai_credentials_save_failed())
    return str(secret_key)


def _ai_credential_fernet():
    """Return a Fernet instance derived from deployment-local secret material.

    Inputs: configured key material. Output: Fernet instance.
    """
    Fernet, _invalid_token = _load_fernet()
    material = _ai_credential_key_material().encode("utf-8", errors="surrogatepass")
    digest = hashlib.sha256(b"omp-ai-credential-v1\0" + material).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_ai_credential(api_key):
    """Encrypt an AI provider credential before database persistence.

    Inputs: `api_key` plaintext or encrypted value. Output: stored credential value.
    """
    if api_key is None:
        return None
    value = str(api_key)
    if value.startswith(AI_CREDENTIAL_ENCRYPTION_PREFIX):
        return value
    token = _ai_credential_fernet().encrypt(
        value.encode("utf-8", errors="surrogatepass")
    )
    return f"{AI_CREDENTIAL_ENCRYPTION_PREFIX}{token.decode('ascii')}"


def _decrypt_ai_credential(stored_value):
    """Decrypt an AI provider credential, preserving legacy plaintext rows.

    Inputs: `stored_value` from the database. Output: plaintext credential.
    """
    if stored_value is None:
        return None
    value = str(stored_value)
    if not value.startswith(AI_CREDENTIAL_ENCRYPTION_PREFIX):
        return value
    _fernet, InvalidToken = _load_fernet()
    token = value[len(AI_CREDENTIAL_ENCRYPTION_PREFIX) :].encode("ascii")
    try:
        plaintext = _ai_credential_fernet().decrypt(token)
    except InvalidToken as exc:
        raise AiCredentialStoreError(errors.ai_credentials_fetch_failed()) from exc
    return plaintext.decode("utf-8", errors="surrogatepass")


def _migrate_legacy_ai_credentials(conn):
    """Encrypt pre-existing plaintext AI credentials in place.

    Inputs: database `conn`. Output: updates legacy credential rows.
    """
    _load_psycopg2_sql()
    with conn.cursor() as cur:
        select_stmt = _safe_query(
            """
                SELECT id, api_key
                FROM {}
                WHERE api_key NOT LIKE %s
                """,
            TABLE_NAME_AI_CREDENTIALS,
        )
        cur.execute(select_stmt, (f"{AI_CREDENTIAL_ENCRYPTION_PREFIX}%",))
        rows = cur.fetchall()
    if not rows:
        return
    with conn.cursor() as cur:
        update_stmt = _safe_query(
            """
                UPDATE {}
                SET api_key = %s, updated_at = NOW()
                WHERE id = %s
                """,
            TABLE_NAME_AI_CREDENTIALS,
        )
        for row in rows:
            if not row or row[0] is None or row[1] is None:
                continue
            cur.execute(update_stmt, (_encrypt_ai_credential(row[1]), row[0]))


def _db_params():
    """Return the db params.

    Inputs: none. Output: db params result. Raises: VariableStoreError when validation or the
    called operation fails.
    """
    user = get_env(ENV_USER, env_file=ENV_FILE_OMEROWEB)
    password = get_env(ENV_AUTH, env_file=ENV_FILE_OMEROWEB)
    host = get_env(ENV_HOST, env_file=ENV_FILE_OMEROWEB)
    dbname = get_env(ENV_DB, env_file=ENV_FILE_OMEROWEB)

    if not user or not password:
        raise VariableStoreError(errors.missing_db_credentials())

    candidate = get_env(ENV_PORT, env_file=ENV_FILE_OMEROWEB)
    candidate_str = str(candidate).strip()
    try:
        port = int(candidate_str)
    except ValueError as exc:
        raise VariableStoreError(
            f"Invalid database port value: {candidate_str}"
        ) from exc

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
    """Open the connection for `omeroweb_omp_plugin.services.data_store`.

    Inputs: none. Output: iterator of yielded items. Raises: VariableStoreError when validation
    or the called operation fails.
    """
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
        raise VariableStoreError(errors.db_connection_failed())

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


def _ensure_schema(conn):
    """Ensure the schema.

    Inputs: `conn` OMERO gateway connection. Output: None.
    """
    _load_psycopg2_sql()
    with conn.cursor() as cur:
        stmt = _safe_query(
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
                """,
            TABLE_NAME,
        )
        cur.execute(stmt)
        stmt = _safe_query(
            """
                CREATE INDEX IF NOT EXISTS {} ON {} (username);
                """,
            f"{TABLE_NAME}_username_idx",
            TABLE_NAME,
        )
        cur.execute(stmt)
    _migrate_legacy_ai_credentials(conn)
    conn.commit()


def _ensure_ai_schema(conn):
    """Ensure AI schema.

    Inputs: `conn`. Output: None.
    """
    _load_psycopg2_sql()
    with conn.cursor() as cur:
        stmt = _safe_query(
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
                """,
            TABLE_NAME_AI_CREDENTIALS,
        )
        cur.execute(stmt)
        stmt = _safe_query(
            """
                CREATE INDEX IF NOT EXISTS {} ON {} (username);
                """,
            f"{TABLE_NAME_AI_CREDENTIALS}_username_idx",
            TABLE_NAME_AI_CREDENTIALS,
        )
        cur.execute(stmt)
    conn.commit()


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


def list_variable_sets(username):
    """Return list variable sets.

    Inputs: `username` username. Output: `list`. Raises: VariableStoreError when validation or
    the called operation fails.
    """
    try:
        _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        SELECT set_name
                        FROM {}
                        WHERE username = %s
                        ORDER BY updated_at DESC, set_name ASC
                        """,
                    TABLE_NAME,
                )
                cur.execute(stmt, (username,))
                rows = cur.fetchall()
                return [r[0] for r in rows if r and r[0] is not None]
    except VariableStoreError:
        raise
    except Exception as e:
        logger.error(
            "Failed to list variable sets for %s: %s",
            sanitize_log_value(username),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise VariableStoreError(errors.variable_sets_fetch_failed()) from None


def save_variable_set(username, set_name, var_names):
    """Save the variable set.

    Inputs: `username` username, `set_name`, `var_names`. Output: None. Raises:
    VariableStoreError when validation or the called operation fails.
    """
    try:
        _, extras = _load_psycopg2()
        _load_psycopg2_sql()
        json_payload = extras.Json(var_names)
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        INSERT INTO {} (username, set_name, var_names, updated_at)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (username, set_name)
                        DO UPDATE SET var_names = EXCLUDED.var_names, updated_at = NOW()
                        """,
                    TABLE_NAME,
                )
                cur.execute(stmt, (username, set_name, json_payload))
            conn.commit()

            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        SELECT var_names
                        FROM {}
                        WHERE username = %s AND set_name = %s
                        """,
                    TABLE_NAME,
                )
                cur.execute(stmt, (username, set_name))
                row = cur.fetchone()
                if row is None:
                    raise VariableStoreError(errors.variable_set_not_persisted())
    except VariableStoreError:
        raise
    except Exception as e:
        logger.error(
            "Failed to save variable set '%s' for %s: %s",
            sanitize_log_value(set_name),
            sanitize_log_value(username),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise VariableStoreError(errors.variable_set_save_failed()) from None


def load_variable_set(username, set_name):
    """Return load variable set.

    Inputs: `username` username, `set_name`. Output: load variable set result. Raises:
    VariableStoreError when validation or the called operation fails.
    """
    try:
        _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        SELECT var_names
                        FROM {}
                        WHERE username = %s AND set_name = %s
                        """,
                    TABLE_NAME,
                )
                cur.execute(stmt, (username, set_name))
                row = cur.fetchone()
                return row[0] if row else None
    except VariableStoreError:
        raise
    except Exception as e:
        logger.error(
            "Failed to load variable set '%s' for %s: %s",
            sanitize_log_value(set_name),
            sanitize_log_value(username),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise VariableStoreError(errors.variable_set_load_failed()) from None


def delete_variable_set(username, set_name):
    """Delete the variable set.

    Inputs: `username` username, `set_name`. Output: None. Raises: VariableStoreError
    when validation or the called operation fails.
    """
    try:
        _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        DELETE FROM {}
                        WHERE username = %s AND set_name = %s
                        """,
                    TABLE_NAME,
                )
                cur.execute(stmt, (username, set_name))

                if cur.rowcount == 0:
                    raise VariableStoreError(errors.variable_set_missing(set_name))

            conn.commit()

            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        SELECT 1
                        FROM {}
                        WHERE username = %s AND set_name = %s
                        """,
                    TABLE_NAME,
                )
                cur.execute(stmt, (username, set_name))
                if cur.fetchone():
                    raise VariableStoreError(errors.variable_set_delete_unconfirmed())

    except VariableStoreError:
        raise
    except Exception as e:
        logger.error(
            "Failed to delete variable set '%s' for %s: %s",
            sanitize_log_value(set_name),
            sanitize_log_value(username),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise VariableStoreError(errors.variable_set_delete_failed()) from None


def list_ai_credentials(username):
    """Return list ai credentials.

    Inputs: `username` username. Output: `list`. Raises: AiCredentialStoreError when validation
    or the called operation fails.
    """
    try:
        _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_ai_schema(conn)
            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        SELECT provider
                        FROM {}
                        WHERE username = %s
                        ORDER BY provider ASC
                        """,
                    TABLE_NAME_AI_CREDENTIALS,
                )
                cur.execute(stmt, (username,))
                rows = cur.fetchall()
                return [r[0] for r in rows if r and r[0] is not None]
    except AiCredentialStoreError:
        raise
    except Exception as e:
        logger.error(
            "Failed to list AI providers for %s: %s",
            sanitize_log_value(username),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise AiCredentialStoreError(errors.ai_credentials_fetch_failed()) from None


def get_ai_credential(username, provider):
    """Return the ai credential value exposed by this OMERO-compatible object.

    Inputs: `username` username, `provider`. Output: get ai credential result. Raises:
    AiCredentialStoreError when validation or the called operation fails.
    """
    try:
        _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_ai_schema(conn)
            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        SELECT api_key
                        FROM {}
                        WHERE username = %s AND provider = %s
                        """,
                    TABLE_NAME_AI_CREDENTIALS,
                )
                cur.execute(stmt, (username, provider))
                row = cur.fetchone()
                return (
                    _decrypt_ai_credential(row[0])
                    if row and row[0] is not None
                    else None
                )
    except AiCredentialStoreError:
        raise
    except Exception as e:
        logger.error(
            "Failed to fetch AI provider config for %s/%s: %s",
            sanitize_log_value(username),
            sanitize_log_value(provider),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise AiCredentialStoreError(errors.ai_credentials_fetch_failed()) from None


def save_ai_credentials(username, provider, api_key):
    """Save the ai credentials.

    Inputs: `username` username, `provider`, `api_key`. Output: None. Raises:
    AiCredentialStoreError when validation or the called operation fails.
    """
    try:
        _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_ai_schema(conn)
            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        INSERT INTO {} (username, provider, api_key, updated_at)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (username, provider)
                        DO UPDATE SET api_key = EXCLUDED.api_key, updated_at = NOW()
                        """,
                    TABLE_NAME_AI_CREDENTIALS,
                )
                cur.execute(stmt, (username, provider, _encrypt_ai_credential(api_key)))
            conn.commit()
    except AiCredentialStoreError:
        raise
    except Exception as e:
        logger.error(
            "Failed to save AI provider config for %s/%s: %s",
            sanitize_log_value(username),
            sanitize_log_value(provider),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise AiCredentialStoreError(errors.ai_credentials_save_failed()) from None


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


def delete_all_user_settings(username):
    """Delete the all user settings.

    Inputs: `username` username. Output: `deleted`. Raises: UserSettingsStoreError when
    validation or the called operation fails.
    """
    try:
        _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_user_settings_schema(conn)
            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        DELETE FROM {}
                        WHERE username = %s
                        """,
                    TABLE_NAME_USER_SETTINGS,
                )
                cur.execute(stmt, (username,))
                deleted = cur.rowcount
            conn.commit()
            return deleted
    except UserSettingsStoreError:
        raise
    except Exception as e:
        logger.error(
            "Failed to delete user settings for %s: %s",
            sanitize_log_value(username),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise UserSettingsStoreError(errors.user_settings_delete_failed()) from None


def delete_all_variable_sets(username):
    """Delete the all variable sets.

    Inputs: `username` username. Output: `deleted`. Raises: VariableStoreError when validation
    or the called operation fails.
    """
    try:
        _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        DELETE FROM {}
                        WHERE username = %s
                        """,
                    TABLE_NAME,
                )
                cur.execute(stmt, (username,))
                deleted = cur.rowcount
            conn.commit()
            return deleted
    except VariableStoreError:
        raise
    except Exception as e:
        logger.error(
            "Failed to delete variable sets for %s: %s",
            sanitize_log_value(username),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise VariableStoreError(errors.variable_sets_delete_failed()) from None


def delete_all_ai_credentials(username):
    """Delete all AI credentials.

    Inputs: `username` username. Output: `deleted`. Raises: AiCredentialStoreError when
    validation or the called operation fails.
    """
    try:
        _load_psycopg2_sql()
        with _connect() as conn:
            _ensure_ai_schema(conn)
            with conn.cursor() as cur:
                stmt = _safe_query(
                    """
                        DELETE FROM {}
                        WHERE username = %s
                        """,
                    TABLE_NAME_AI_CREDENTIALS,
                )
                cur.execute(stmt, (username,))
                deleted = cur.rowcount
            conn.commit()
            return deleted
    except AiCredentialStoreError:
        raise
    except Exception as e:
        logger.error(
            "Failed to delete AI provider config for %s: %s",
            sanitize_log_value(username),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise AiCredentialStoreError(errors.ai_credentials_delete_failed()) from None


def delete_all_user_data(username):
    """Delete the all user data.

    Inputs: `username` username. Output: `deleted_counts`. Raises: UserDataStoreError
    when validation or the called operation fails.
    """
    try:
        with _connect() as conn:
            _load_psycopg2_sql()
            tables = _list_user_scoped_tables(conn)
            deleted_counts = {}
            with conn.cursor() as cur:
                for table in tables:
                    stmt = _safe_query(
                        """
                            DELETE FROM {}
                            WHERE username = %s
                            """,
                        table,
                    )
                    cur.execute(stmt, (username,))
                    deleted_counts[table] = cur.rowcount
            conn.commit()
            return deleted_counts
    except (VariableStoreError, AiCredentialStoreError, UserSettingsStoreError):
        raise UserDataStoreError(errors.user_data_delete_failed()) from None
    except Exception as e:
        logger.error(
            "Failed to delete user data for %s: %s",
            sanitize_log_value(username),
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        raise UserDataStoreError(errors.user_data_delete_failed()) from None


def _list_user_scoped_tables(conn):
    """Return the user scoped tables.

    Inputs: `conn` OMERO gateway connection. Output: `list`.
    """
    with conn.cursor() as cur:
        cur.execute(  # nosemgrep
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
