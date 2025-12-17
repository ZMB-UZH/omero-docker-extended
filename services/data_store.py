import logging
import os
from contextlib import contextmanager


logger = logging.getLogger(__name__)


class VariableStoreError(Exception):
    """Raised when variable set persistence fails."""


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
        raise VariableStoreError(
            "psycopg2 is not installed. Please install psycopg2-binary in the OMERO.web environment."
        )

    _psycopg2_mod = psycopg2
    _psycopg2_extras = extras
    return _psycopg2_mod, _psycopg2_extras


def _db_params():
    user = os.environ.get("FMP_DATA_USER")
    password = os.environ.get("FMP_DATA_PASS")
    host = os.environ.get("FMP_DATA_HOST", "database_plugin")
    port = int(os.environ.get("FMP_DATA_PORT", "5433"))
    dbname = os.environ.get("FMP_DATA_DB", "filename-metadata")

    if not user or not password:
        raise VariableStoreError("Database credentials are missing (FMP_DATA_USER/FMP_DATA_PASS).")
        
    return {
        "user": user,
        "password": password,
        "host": host,
        "port": port,
        "dbname": dbname,
    }


@contextmanager
def _connect():
    psycopg2, _ = _load_psycopg2()  
    params = _db_params()
    conn = None
    try:
        conn = psycopg2.connect(**params)
        yield conn
    except VariableStoreError:
        raise
    except Exception as e:
        logger.exception("Database connection failed: %s", e)
        raise VariableStoreError("Could not connect to the variable storage database.")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS fmp_variable_sets (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL,
                set_name TEXT NOT NULL,
                var_names JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(username, set_name)
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS fmp_variable_sets_username_idx
                ON fmp_variable_sets (username);
            """
        )
    conn.commit()


def list_variable_sets(username):
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT set_name
                    FROM fmp_variable_sets
                    WHERE username = %s
                    ORDER BY updated_at DESC, set_name ASC
                    """,
                    (username,),
                )
                rows = cur.fetchall()
                return [r[0] for r in rows if r and r[0] is not None]
    except VariableStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to list variable sets for %s: %s", username, e)
        raise VariableStoreError("Unable to fetch saved variable sets.")


def save_variable_set(username, set_name, var_names):
    try:
        _, extras = _load_psycopg2()
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO fmp_variable_sets (username, set_name, var_names, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (username, set_name)
                    DO UPDATE SET var_names = EXCLUDED.var_names, updated_at = NOW()
                    """,
                    (username, set_name, Json(var_names)),
                )
            conn.commit()
    except VariableStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to save variable set '%s' for %s: %s", set_name, username, e)
        raise VariableStoreError("Could not save variable set.")


def load_variable_set(username, set_name):
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT var_names
                    FROM fmp_variable_sets
                    WHERE username = %s AND set_name = %s
                    """,
                    (username, set_name),
                )
                row = cur.fetchone()
                return row[0] if row else None
    except VariableStoreError:
        raise
    except Exception as e:
        logger.exception("Failed to load variable set '%s' for %s: %s", set_name, username, e)
        raise VariableStoreError("Unable to load variable set.")

