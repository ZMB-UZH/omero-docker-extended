from __future__ import annotations

import builtins
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from omeroweb_omp_plugin.services import data_store

TEST_DB_AUTH_VALUE = "plugin-db-auth-value"


class _FakeSqlTemplate:
    """Test double for fake SQL template."""

    def __init__(self, query):
        """Create `_FakeSqlTemplate` with `query`.

        Inputs: `query`. Output: None.
        """
        self.query = str(query)

    def format(self, *args, **kwargs):
        """Return formatted representation.

        Inputs: `*args`, `**kwargs`. Output: `self.query`.
        """
        return self.query


class _FakeSqlModule:
    """Test double for fake SQL module."""

    @staticmethod
    def SQL(query):
        """Return the SQL for `_FakeSqlModule`.

        Inputs: `query`. Output: `_FakeSqlTemplate` result.
        """
        return _FakeSqlTemplate(query)

    @staticmethod
    def Identifier(name):
        """Return the identifier for `_FakeSqlModule`.

        Inputs: `name` name. Output: `name`.
        """
        return name


class _FakeExtras:
    """Test double for fake extras."""

    @staticmethod
    def Json(payload):
        """Return the JSON for `_FakeExtras`.

        Inputs: `payload` payload. Output: `dict`.
        """
        return {"json": payload}


class _FakeCursor:
    """Test double for fake cursor."""

    def __init__(self, *, fetchone=None, fetchall=None, rowcount=0, rowcounts=None):
        """Create `_FakeCursor` with its default state.

        Inputs: `fetchone`, `fetchall`, `rowcount`, `rowcounts`. Output: None.
        """
        self.fetchone_value = fetchone
        self.fetchall_value = fetchall or []
        self.rowcount = rowcount
        self.rowcounts = list(rowcounts or [])
        self.executed = []

    def execute(self, query, params=None):
        """Execute `_FakeCursor`'s captured query or command.

        Inputs: `query`, `params`. Output: None.
        """
        self.executed.append((str(query), params))
        if self.rowcounts:
            self.rowcount = self.rowcounts.pop(0)

    def fetchone(self):
        """Return one result row from `_FakeCursor`.

        Inputs: none. Output: `self.fetchone_value`.
        """
        return self.fetchone_value

    def fetchall(self):
        """Return all result rows.

        Inputs: none. Output: `list` result.
        """
        return list(self.fetchall_value)

    def __enter__(self):
        """Enter `_FakeCursor`'s context-managed fake resource.

        Inputs: none. Output: `self`.
        """
        return self

    def __exit__(self, exc_type, exc, tb):
        """Exit `_FakeCursor`'s context-managed fake resource.

        Inputs: `exc_type`, `exc`, `tb`. Output: bool.
        """
        return False


class _FakeConnection:
    """Test double for fake connection."""

    def __init__(self, cursors):
        """Create `_FakeConnection` with `cursors`.

        Inputs: `cursors`. Output: None.
        """
        self._cursors = list(cursors)
        self.commits = 0
        self.closed = False

    def cursor(self):
        """Return a database cursor.

        Inputs: none. Output: `self._cursors.pop` result.
        """
        if not self._cursors:
            self._cursors.append(_FakeCursor())
        return self._cursors.pop(0)

    def commit(self):
        """Commit `_FakeConnection`'s fake transaction.

        Inputs: caller provides no extra arguments. Output: records the fake side effect.
        """
        self.commits += 1

    def close(self):
        """Close `_FakeConnection`'s fake resource handle.

        Inputs: caller provides no extra arguments. Output: records the fake side effect.
        """
        self.closed = True


class _RaisingContext:
    """Test double for raising context behavior in this module."""

    def __init__(self, error):
        """Create `_RaisingContext` with `error`.

        Inputs: `error`. Output: None.
        """
        self.error = error

    def __enter__(self):
        """Enter `_RaisingContext`'s context-managed fake resource.

        Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
        fail.
        """
        raise self.error

    def __exit__(self, exc_type, exc, tb):
        """Exit `_RaisingContext`'s context-managed fake resource.

        Inputs: `exc_type`, `exc`, `tb`. Output: bool.
        """
        return False


def _patch_connection_queue(monkeypatch, connections):
    """Patch the connection queue.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `connections`. Output: iterator of
    yielded items.
    """
    queue = list(connections)

    @contextmanager
    def fake_connect():
        """Simulate connect so the surrounding test controls that dependency.

        Inputs: none. Output: iterator of yielded items.
        """
        yield queue.pop(0)

    monkeypatch.setattr(data_store, "_connect", fake_connect)


def test_connection_and_schema_helpers_cover_env_validation_and_cleanup(monkeypatch):
    """Check connection and schema helpers cover env validation and cleanup cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in connection and schema helpers cover env validation and cleanup.
    """
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
    """Check crud helpers cover variable sets credentials and user cleanup cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in crud helpers cover variable sets credentials and user cleanup.
    """
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
    """Confirm delete validation and table listing reject unconfirmed removals is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when delete validation and table listing reject unconfirmed removals stops reporting the expected error.
    """
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
    """Confirm import and connection helpers raise store errors on backend failures exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in import and connection helpers raise store errors on backend failures.
    Raises: ImportError when validation or the called operation fails.
    """
    original_import = builtins.__import__

    def failing_import(name, global_vars=None, local_vars=None, fromlist=(), level=0):
        """Return the failing import.

        Inputs: `name` name, `global_vars`, `local_vars`, `fromlist`, `level`. Output:
        `original_import` result. Raises: ImportError for the exercised failure path.
        """
        if name == "psycopg2" or name.startswith("psycopg2"):
            raise ImportError("psycopg2 missing")
        return original_import(name, global_vars, local_vars, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    data_store._PSYCOPG2_MODULES.module = None
    data_store._PSYCOPG2_MODULES.extras = None
    data_store._PSYCOPG2_MODULES.sql = None

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

    with pytest.raises(data_store.VariableStoreError), data_store._connect():
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
    """Verify crud operations wrap unexpected backend failures.

    Inputs: pytest provides `monkeypatch`, `operation`, `args`, `error_type`. Output: fails on regressions in crud operations wrap unexpected backend failures.
    """
    monkeypatch.setattr(data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    monkeypatch.setattr(
        data_store,
        "_load_psycopg2",
        lambda: (SimpleNamespace(), _FakeExtras),
    )

    monkeypatch.setattr(
        data_store,
        "_connect",
        lambda: _RaisingContext(RuntimeError("backend failure")),
    )

    with pytest.raises(error_type):
        operation(*args)


def test_cached_import_helpers_and_connection_cleanup_cover_remaining_branches(
    monkeypatch,
):
    """Check cached import helpers and connection cleanup cover remaining branches cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in cached import helpers and connection cleanup cover remaining branches.
    when validation or the called operation fails.
    """
    sentinel_mod = object()
    sentinel_extras = object()
    sentinel_sql = object()
    data_store._PSYCOPG2_MODULES.module = sentinel_mod
    data_store._PSYCOPG2_MODULES.extras = sentinel_extras
    data_store._PSYCOPG2_MODULES.sql = sentinel_sql

    assert data_store._load_psycopg2() == (sentinel_mod, sentinel_extras)
    assert data_store._load_psycopg2_sql() is sentinel_sql

    data_store._PSYCOPG2_MODULES.module = None
    data_store._PSYCOPG2_MODULES.extras = None
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
            SimpleNamespace(
                connect=lambda **kwargs: (_ for _ in ()).throw(AssertionError)
            ),
            _FakeExtras,
        ),
    )
    monkeypatch.setattr(data_store, "_db_params", lambda: [])
    with pytest.raises(data_store.VariableStoreError), data_store._connect():
        pass

    class _ClosingConnection(_FakeConnection):
        """Test double for closing connection behavior in this module."""

        def close(self):
            """Close `_ClosingConnection`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
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
    """Confirm specific store error paths and confirmation failures are propagated exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when specific store error paths and confirmation failures are propagated stops reporting the expected error.
    """
    monkeypatch.setattr(data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    monkeypatch.setattr(
        data_store,
        "_load_psycopg2",
        lambda: (SimpleNamespace(), _FakeExtras),
    )

    monkeypatch.setattr(
        data_store,
        "_connect",
        lambda: _RaisingContext(data_store.VariableStoreError("typed")),
    )
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

    monkeypatch.setattr(
        data_store,
        "_connect",
        lambda: _RaisingContext(data_store.AiCredentialStoreError("typed-ai")),
    )
    with pytest.raises(data_store.AiCredentialStoreError, match="typed-ai"):
        data_store.list_ai_credentials("alice")
    with pytest.raises(data_store.AiCredentialStoreError, match="typed-ai"):
        data_store.get_ai_credential("alice", "openai")
    with pytest.raises(data_store.AiCredentialStoreError, match="typed-ai"):
        data_store.save_ai_credentials("alice", "openai", "secret")
    with pytest.raises(data_store.AiCredentialStoreError, match="typed-ai"):
        data_store.delete_all_ai_credentials("alice")

    monkeypatch.setattr(
        data_store,
        "_connect",
        lambda: _RaisingContext(data_store.UserSettingsStoreError("typed-settings")),
    )
    with pytest.raises(data_store.UserSettingsStoreError, match="typed-settings"):
        data_store.delete_all_user_settings("alice")

    settings_missing_conn = _FakeConnection([_FakeCursor(), _FakeCursor(fetchone=None)])
    _patch_connection_queue(monkeypatch, [settings_missing_conn])
    monkeypatch.setattr(data_store, "_ensure_user_settings_schema", lambda conn: None)
    with pytest.raises(data_store.UserSettingsStoreError, match="persisted"):
        data_store.save_user_settings("alice", {"theme": "dark"})

    monkeypatch.setattr(
        data_store,
        "_connect",
        lambda: _RaisingContext(data_store.VariableStoreError("typed-user-data")),
    )
    with pytest.raises(data_store.UserDataStoreError, match="user data"):
        data_store.delete_all_user_data("alice")


def test_real_psycopg2_loader_paths_cover_success_imports(monkeypatch):
    """Verify real psycopg2 loader paths cover success imports.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in real psycopg2 loader paths cover success imports.
    """
    data_store._PSYCOPG2_MODULES.module = None
    data_store._PSYCOPG2_MODULES.extras = None
    data_store._PSYCOPG2_MODULES.sql = None

    psycopg2_mod, extras_mod = data_store._load_psycopg2()
    sql_mod = data_store._load_psycopg2_sql()

    assert psycopg2_mod.__name__ == "psycopg2"
    assert extras_mod.__name__.endswith(".extras")
    assert sql_mod.__name__.endswith(".sql")


def test_connect_re_raises_variable_store_errors_from_backend(monkeypatch):
    """Confirm connect re raises variable store errors from backend exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when connect re raises variable store errors from backend stops reporting the expected error.
    """
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

    with (
        pytest.raises(data_store.VariableStoreError, match="typed connect failure"),
        data_store._connect(),
    ):
        pass
