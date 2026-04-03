from __future__ import annotations

import builtins
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from omeroweb_omp_plugin.services import data_store

TEST_DB_AUTH_VALUE = "plugin-db-auth-value"


class _FakeSqlTemplate:
    def __init__(self, query):
        self.query = str(query)

    def format(self, *args, **kwargs):
        return self.query


class _FakeSqlModule:
    @staticmethod
    def SQL(query):
        return _FakeSqlTemplate(query)

    @staticmethod
    def Identifier(name):
        return name


class _FakeExtras:
    @staticmethod
    def Json(payload):
        return {"json": payload}


class _FakeCursor:
    def __init__(self, *, fetchone=None, fetchall=None, rowcount=0, rowcounts=None):
        self.fetchone_value = fetchone
        self.fetchall_value = fetchall or []
        self.rowcount = rowcount
        self.rowcounts = list(rowcounts or [])
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((str(query), params))
        if self.rowcounts:
            self.rowcount = self.rowcounts.pop(0)

    def fetchone(self):
        return self.fetchone_value

    def fetchall(self):
        return list(self.fetchall_value)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, cursors):
        self._cursors = list(cursors)
        self.commits = 0
        self.closed = False

    def cursor(self):
        if not self._cursors:
            self._cursors.append(_FakeCursor())
        return self._cursors.pop(0)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def _patch_connection_queue(monkeypatch, connections):
    queue = list(connections)

    @contextmanager
    def fake_connect():
        yield queue.pop(0)

    monkeypatch.setattr(data_store, "_connect", fake_connect)


def test_connection_and_schema_helpers_cover_env_validation_and_cleanup(monkeypatch):
    env_values = {
        data_store.ENV_USER: "plugin-user",
        data_store.ENV_AUTH: TEST_DB_AUTH_VALUE,
        data_store.ENV_HOST: "database-plugin",
        data_store.ENV_DB: "plugin-db",
        data_store.ENV_PORT: "5433",
    }
    monkeypatch.setattr(
        data_store,
        "get_env",
        lambda key, env_file=None: env_values.get(key, ""),
    )

    assert data_store._db_params() == [
        {
            "user": "plugin-user",
            "password": TEST_DB_AUTH_VALUE,
            "host": "database-plugin",
            "dbname": "plugin-db",
            "port": 5433,
        }
    ]

    env_values[data_store.ENV_PORT] = "not-a-port"
    with pytest.raises(data_store.VariableStoreError, match="Invalid database port"):
        data_store._db_params()

    env_values[data_store.ENV_PORT] = "5433"
    conn = _FakeConnection([_FakeCursor()])
    fake_psycopg2 = SimpleNamespace(connect=lambda **kwargs: conn)
    monkeypatch.setattr(
        data_store, "_load_psycopg2", lambda: (fake_psycopg2, _FakeExtras)
    )

    with data_store._connect() as opened:
        assert opened is conn

    assert conn.closed is True

    monkeypatch.setattr(data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    schema_conn = _FakeConnection([_FakeCursor()])
    data_store._ensure_schema(schema_conn)
    assert schema_conn.commits == 1

    ai_schema_conn = _FakeConnection([_FakeCursor()])
    data_store._ensure_ai_schema(ai_schema_conn)
    assert ai_schema_conn.commits == 1

    user_schema_conn = _FakeConnection([_FakeCursor()])
    data_store._ensure_user_settings_schema(user_schema_conn)
    assert user_schema_conn.commits == 1


def test_crud_helpers_cover_variable_sets_credentials_and_user_cleanup(monkeypatch):
    monkeypatch.setattr(data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    monkeypatch.setattr(
        data_store,
        "_load_psycopg2",
        lambda: (SimpleNamespace(), _FakeExtras),
    )
    monkeypatch.setattr(data_store, "_ensure_schema", lambda conn: None)
    monkeypatch.setattr(data_store, "_ensure_ai_schema", lambda conn: None)
    monkeypatch.setattr(data_store, "_ensure_user_settings_schema", lambda conn: None)

    connections = [
        _FakeConnection([_FakeCursor(fetchall=[("set-b",), (None,), ("set-a",)])]),
        _FakeConnection([_FakeCursor(), _FakeCursor(fetchone=(["alpha"],))]),
        _FakeConnection([_FakeCursor(fetchone=(["alpha", "beta"],))]),
        _FakeConnection([_FakeCursor(rowcount=1), _FakeCursor(fetchone=None)]),
        _FakeConnection([_FakeCursor(fetchall=[("anthropic",), ("openai",)])]),
        _FakeConnection([_FakeCursor(fetchone=("api-key",))]),
        _FakeConnection([_FakeCursor()]),
        _FakeConnection([_FakeCursor(), _FakeCursor(fetchone=({"theme": "dark"},))]),
        _FakeConnection([_FakeCursor(rowcount=2)]),
        _FakeConnection([_FakeCursor(rowcount=3)]),
        _FakeConnection([_FakeCursor(rowcount=1)]),
        _FakeConnection([_FakeCursor(rowcounts=[4, 5])]),
    ]
    _patch_connection_queue(monkeypatch, connections)
    monkeypatch.setattr(
        data_store,
        "_list_user_scoped_tables",
        lambda conn: ["omp_ai_credentials", "omp_variable_sets"],
    )

    assert data_store.list_variable_sets("alice") == ["set-b", "set-a"]
    data_store.save_variable_set("alice", "set-a", ["alpha"])
    assert data_store.load_variable_set("alice", "set-a") == ["alpha", "beta"]
    data_store.delete_variable_set("alice", "set-a")
    assert data_store.list_ai_credentials("alice") == ["anthropic", "openai"]
    assert data_store.get_ai_credential("alice", "openai") == "api-key"
    data_store.save_ai_credentials("alice", "openai", "api-key")
    data_store.save_user_settings("alice", {"theme": "dark"})
    assert data_store.delete_all_user_settings("alice") == 2
    assert data_store.delete_all_variable_sets("alice") == 3
    assert data_store.delete_all_ai_credentials("alice") == 1
    assert data_store.delete_all_user_data("alice") == {
        "omp_ai_credentials": 4,
        "omp_variable_sets": 5,
    }


def test_delete_validation_and_table_listing_reject_unconfirmed_removals(monkeypatch):
    monkeypatch.setattr(data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    monkeypatch.setattr(data_store, "_ensure_schema", lambda conn: None)

    failing_delete_conn = _FakeConnection([_FakeCursor(rowcount=0)])
    _patch_connection_queue(monkeypatch, [failing_delete_conn])

    with pytest.raises(data_store.VariableStoreError):
        data_store.delete_variable_set("alice", "missing")

    listing_conn = _FakeConnection(
        [
            _FakeCursor(
                fetchall=[
                    ("omp_variable_sets",),
                    ("omp_ai_credentials",),
                    ("omp-bad",),
                    ("other",),
                ]
            )
        ]
    )
    assert data_store._list_user_scoped_tables(listing_conn) == [
        "omp_ai_credentials",
        "omp_variable_sets",
    ]


def test_import_and_connection_helpers_raise_store_errors_on_backend_failures(
    monkeypatch,
):
    original_import = builtins.__import__

    def failing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "psycopg2" or name.startswith("psycopg2"):
            raise ImportError("psycopg2 missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    monkeypatch.setattr(data_store, "_psycopg2_mod", None)
    monkeypatch.setattr(data_store, "_psycopg2_extras", None)
    monkeypatch.setattr(data_store, "_psycopg2_sql", None)

    with pytest.raises(data_store.VariableStoreError):
        data_store._load_psycopg2()
    with pytest.raises(data_store.VariableStoreError):
        data_store._load_psycopg2_sql()

    monkeypatch.setattr(builtins, "__import__", original_import)
    monkeypatch.setattr(
        data_store,
        "_load_psycopg2",
        lambda: (
            SimpleNamespace(
                connect=lambda **kwargs: (_ for _ in ()).throw(
                    RuntimeError("database down")
                )
            ),
            _FakeExtras,
        ),
    )
    monkeypatch.setattr(
        data_store,
        "_db_params",
        lambda: [
            {
                "user": "plugin-user",
                "password": TEST_DB_AUTH_VALUE,
                "host": "database-plugin",
                "dbname": "plugin-db",
                "port": 5433,
            }
        ],
    )

    with pytest.raises(data_store.VariableStoreError):
        with data_store._connect():
            pass


@pytest.mark.parametrize(
    ("operation", "args", "error_type"),
    [
        (data_store.list_variable_sets, ("alice",), data_store.VariableStoreError),
        (
            data_store.save_variable_set,
            ("alice", "set-a", ["alpha"]),
            data_store.VariableStoreError,
        ),
        (
            data_store.load_variable_set,
            ("alice", "set-a"),
            data_store.VariableStoreError,
        ),
        (
            data_store.delete_variable_set,
            ("alice", "set-a"),
            data_store.VariableStoreError,
        ),
        (data_store.list_ai_credentials, ("alice",), data_store.AiCredentialStoreError),
        (
            data_store.get_ai_credential,
            ("alice", "openai"),
            data_store.AiCredentialStoreError,
        ),
        (
            data_store.save_ai_credentials,
            ("alice", "openai", "api-key"),
            data_store.AiCredentialStoreError,
        ),
        (
            data_store.save_user_settings,
            ("alice", {"theme": "dark"}),
            data_store.UserSettingsStoreError,
        ),
        (
            data_store.delete_all_user_settings,
            ("alice",),
            data_store.UserSettingsStoreError,
        ),
        (
            data_store.delete_all_variable_sets,
            ("alice",),
            data_store.VariableStoreError,
        ),
        (
            data_store.delete_all_ai_credentials,
            ("alice",),
            data_store.AiCredentialStoreError,
        ),
        (
            data_store.delete_all_user_data,
            ("alice",),
            data_store.UserDataStoreError,
        ),
    ],
)
def test_crud_operations_wrap_unexpected_backend_failures(
    monkeypatch, operation, args, error_type
):
    monkeypatch.setattr(data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    monkeypatch.setattr(
        data_store,
        "_load_psycopg2",
        lambda: (SimpleNamespace(), _FakeExtras),
    )

    @contextmanager
    def failing_connect():
        raise RuntimeError("backend failure")
        yield

    monkeypatch.setattr(data_store, "_connect", failing_connect)

    with pytest.raises(error_type):
        operation(*args)


def test_cached_import_helpers_and_connection_cleanup_cover_remaining_branches(
    monkeypatch,
):
    sentinel_mod = object()
    sentinel_extras = object()
    sentinel_sql = object()
    monkeypatch.setattr(data_store, "_psycopg2_mod", sentinel_mod)
    monkeypatch.setattr(data_store, "_psycopg2_extras", sentinel_extras)
    monkeypatch.setattr(data_store, "_psycopg2_sql", sentinel_sql)

    assert data_store._load_psycopg2() == (sentinel_mod, sentinel_extras)
    assert data_store._load_psycopg2_sql() is sentinel_sql

    monkeypatch.setattr(data_store, "_psycopg2_mod", None)
    monkeypatch.setattr(data_store, "_psycopg2_extras", None)
    monkeypatch.setattr(
        data_store,
        "get_env",
        lambda key, env_file=None: {
            data_store.ENV_USER: "",
            data_store.ENV_AUTH: "",
            data_store.ENV_HOST: "db",
            data_store.ENV_DB: "omp",
            data_store.ENV_PORT: "5432",
        }.get(key, ""),
    )
    with pytest.raises(data_store.VariableStoreError):
        data_store._db_params()

    monkeypatch.setattr(
        data_store,
        "_load_psycopg2",
        lambda: (
            SimpleNamespace(connect=lambda **kwargs: (_ for _ in ()).throw(AssertionError)),
            _FakeExtras,
        ),
    )
    monkeypatch.setattr(data_store, "_db_params", lambda: [])
    with pytest.raises(data_store.VariableStoreError):
        with data_store._connect():
            pass

    class _ClosingConnection(_FakeConnection):
        def close(self):
            raise RuntimeError("close exploded")

    closing_conn = _ClosingConnection([_FakeCursor()])
    monkeypatch.setattr(
        data_store,
        "_load_psycopg2",
        lambda: (SimpleNamespace(connect=lambda **kwargs: closing_conn), _FakeExtras),
    )
    monkeypatch.setattr(
        data_store,
        "_db_params",
        lambda: [
            {
                "user": "plugin-user",
                "password": TEST_DB_AUTH_VALUE,
                "host": "database-plugin",
                "dbname": "plugin-db",
                "port": 5433,
            }
        ],
    )
    with data_store._connect() as opened:
        assert opened is closing_conn


def test_specific_store_error_paths_and_confirmation_failures_are_propagated(
    monkeypatch,
):
    monkeypatch.setattr(data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    monkeypatch.setattr(
        data_store,
        "_load_psycopg2",
        lambda: (SimpleNamespace(), _FakeExtras),
    )

    @contextmanager
    def variable_error_connect():
        raise data_store.VariableStoreError("typed")
        yield

    monkeypatch.setattr(data_store, "_connect", variable_error_connect)
    with pytest.raises(data_store.VariableStoreError, match="typed"):
        data_store.list_variable_sets("alice")
    with pytest.raises(data_store.VariableStoreError, match="typed"):
        data_store.load_variable_set("alice", "set-a")
    with pytest.raises(data_store.VariableStoreError, match="typed"):
        data_store.delete_all_variable_sets("alice")

    save_missing_conn = _FakeConnection([_FakeCursor(), _FakeCursor(fetchone=None)])
    _patch_connection_queue(monkeypatch, [save_missing_conn])
    monkeypatch.setattr(data_store, "_ensure_schema", lambda conn: None)
    with pytest.raises(data_store.VariableStoreError, match="persisted"):
        data_store.save_variable_set("alice", "set-a", ["alpha"])

    delete_unconfirmed_conn = _FakeConnection(
        [_FakeCursor(rowcount=1), _FakeCursor(fetchone=(1,))]
    )
    _patch_connection_queue(monkeypatch, [delete_unconfirmed_conn])
    monkeypatch.setattr(data_store, "_ensure_schema", lambda conn: None)
    with pytest.raises(data_store.VariableStoreError, match="confirmed"):
        data_store.delete_variable_set("alice", "set-a")

    @contextmanager
    def ai_error_connect():
        raise data_store.AiCredentialStoreError("typed-ai")
        yield

    monkeypatch.setattr(data_store, "_connect", ai_error_connect)
    with pytest.raises(data_store.AiCredentialStoreError, match="typed-ai"):
        data_store.list_ai_credentials("alice")
    with pytest.raises(data_store.AiCredentialStoreError, match="typed-ai"):
        data_store.get_ai_credential("alice", "openai")
    with pytest.raises(data_store.AiCredentialStoreError, match="typed-ai"):
        data_store.save_ai_credentials("alice", "openai", "secret")
    with pytest.raises(data_store.AiCredentialStoreError, match="typed-ai"):
        data_store.delete_all_ai_credentials("alice")

    @contextmanager
    def settings_error_connect():
        raise data_store.UserSettingsStoreError("typed-settings")
        yield

    monkeypatch.setattr(data_store, "_connect", settings_error_connect)
    with pytest.raises(data_store.UserSettingsStoreError, match="typed-settings"):
        data_store.delete_all_user_settings("alice")

    settings_missing_conn = _FakeConnection([_FakeCursor(), _FakeCursor(fetchone=None)])
    _patch_connection_queue(monkeypatch, [settings_missing_conn])
    monkeypatch.setattr(data_store, "_ensure_user_settings_schema", lambda conn: None)
    with pytest.raises(data_store.UserSettingsStoreError, match="persisted"):
        data_store.save_user_settings("alice", {"theme": "dark"})

    @contextmanager
    def user_data_error_connect():
        raise data_store.VariableStoreError("typed-user-data")
        yield

    monkeypatch.setattr(data_store, "_connect", user_data_error_connect)
    with pytest.raises(data_store.UserDataStoreError, match="user data"):
        data_store.delete_all_user_data("alice")


def test_real_psycopg2_loader_paths_cover_success_imports(monkeypatch):
    monkeypatch.setattr(data_store, "_psycopg2_mod", None)
    monkeypatch.setattr(data_store, "_psycopg2_extras", None)
    monkeypatch.setattr(data_store, "_psycopg2_sql", None)

    psycopg2_mod, extras_mod = data_store._load_psycopg2()
    sql_mod = data_store._load_psycopg2_sql()

    assert psycopg2_mod.__name__ == "psycopg2"
    assert extras_mod.__name__.endswith(".extras")
    assert sql_mod.__name__.endswith(".sql")


def test_connect_re_raises_variable_store_errors_from_backend(monkeypatch):
    monkeypatch.setattr(
        data_store,
        "_load_psycopg2",
        lambda: (
            SimpleNamespace(
                connect=lambda **kwargs: (_ for _ in ()).throw(
                    data_store.VariableStoreError("typed connect failure")
                )
            ),
            _FakeExtras,
        ),
    )
    monkeypatch.setattr(
        data_store,
        "_db_params",
        lambda: [
            {
                "user": "plugin-user",
                "password": TEST_DB_AUTH_VALUE,
                "host": "database-plugin",
                "dbname": "plugin-db",
                "port": 5433,
            }
        ],
    )

    with pytest.raises(data_store.VariableStoreError, match="typed connect failure"):
        with data_store._connect():
            pass
