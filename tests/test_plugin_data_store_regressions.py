from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from omeroweb_omp_plugin.services import data_store as omp_data_store

TEST_DB_AUTH = "plugin-db-fixture"


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


def _patch_connection_queue(monkeypatch, module, connections):
    """Patch the connection queue.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `module` module object,
    `connections`. Output: iterator of yielded items.
    """
    queue = list(connections)

    @contextmanager
    def fake_connect():
        """Simulate connect so the surrounding test controls that dependency.

        Inputs: none. Output: iterator of yielded items.
        """
        yield queue.pop(0)

    monkeypatch.setattr(module, "_connect", fake_connect)


def test_omp_data_store_connection_and_schema_helpers(monkeypatch):
    """Verify OMP data store connection and schema helpers.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in OMP data store connection and schema helpers.
    """
    env_values = {
        omp_data_store.ENV_USER: "plugin-user",
        omp_data_store.ENV_AUTH: TEST_DB_AUTH,
        omp_data_store.ENV_HOST: "database-plugin",
        omp_data_store.ENV_DB: "plugin-db",
        omp_data_store.ENV_PORT: "5433",
    }
    monkeypatch.setattr(
        omp_data_store,
        "get_env",
        lambda key, env_file=None: env_values.get(key, ""),
    )

    assert omp_data_store._db_params() == [
        {
            "user": "plugin-user",
            "password": TEST_DB_AUTH,
            "host": "database-plugin",
            "dbname": "plugin-db",
            "port": 5433,
        }
    ]

    env_values[omp_data_store.ENV_PORT] = "not-a-port"
    with pytest.raises(omp_data_store.VariableStoreError):
        omp_data_store._db_params()
    env_values[omp_data_store.ENV_PORT] = "5433"

    conn = _FakeConnection([_FakeCursor()])
    fake_psycopg2 = SimpleNamespace(connect=lambda **kwargs: conn)
    monkeypatch.setattr(
        omp_data_store, "_load_psycopg2", lambda: (fake_psycopg2, _FakeExtras)
    )
    with omp_data_store._connect() as opened:
        assert opened is conn
    assert conn.closed is True

    monkeypatch.setattr(omp_data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    schema_conn = _FakeConnection([_FakeCursor()])
    omp_data_store._ensure_schema(schema_conn)
    assert schema_conn.commits == 1

    ai_schema_conn = _FakeConnection([_FakeCursor()])
    omp_data_store._ensure_ai_schema(ai_schema_conn)
    assert ai_schema_conn.commits == 1

    user_schema_conn = _FakeConnection([_FakeCursor()])
    omp_data_store._ensure_user_settings_schema(user_schema_conn)
    assert user_schema_conn.commits == 1


def test_omp_data_store_variable_sets_credentials_and_user_cleanup(monkeypatch):
    """Check OMP data store variable sets credentials and user cleanup cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in OMP data store variable sets credentials and user cleanup.
    """
    monkeypatch.setattr(omp_data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    monkeypatch.setattr(
        omp_data_store,
        "_load_psycopg2",
        lambda: (SimpleNamespace(), _FakeExtras),
    )
    monkeypatch.setattr(omp_data_store, "_ensure_schema", lambda conn: None)
    monkeypatch.setattr(omp_data_store, "_ensure_ai_schema", lambda conn: None)
    monkeypatch.setattr(
        omp_data_store, "_ensure_user_settings_schema", lambda conn: None
    )

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
    _patch_connection_queue(monkeypatch, omp_data_store, connections)
    monkeypatch.setattr(
        omp_data_store,
        "_list_user_scoped_tables",
        lambda conn: ["omp_ai_credentials", "omp_variable_sets"],
    )

    assert omp_data_store.list_variable_sets("alice") == ["set-b", "set-a"]
    omp_data_store.save_variable_set("alice", "set-a", ["alpha"])
    assert omp_data_store.load_variable_set("alice", "set-a") == ["alpha", "beta"]
    omp_data_store.delete_variable_set("alice", "set-a")
    assert omp_data_store.list_ai_credentials("alice") == ["anthropic", "openai"]
    assert omp_data_store.get_ai_credential("alice", "openai") == "api-key"
    omp_data_store.save_ai_credentials("alice", "openai", "api-key")
    omp_data_store.save_user_settings("alice", {"theme": "dark"})
    assert omp_data_store.delete_all_user_settings("alice") == 2
    assert omp_data_store.delete_all_variable_sets("alice") == 3
    assert omp_data_store.delete_all_ai_credentials("alice") == 1
    assert omp_data_store.delete_all_user_data("alice") == {
        "omp_ai_credentials": 4,
        "omp_variable_sets": 5,
    }


def test_omp_data_store_delete_validation_and_table_listing(monkeypatch):
    """Check OMP data store delete validation and table listing cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in OMP data store delete validation and table listing.
    """
    monkeypatch.setattr(omp_data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    monkeypatch.setattr(omp_data_store, "_ensure_schema", lambda conn: None)

    failing_delete_conn = _FakeConnection([_FakeCursor(rowcount=0)])
    _patch_connection_queue(monkeypatch, omp_data_store, [failing_delete_conn])

    with pytest.raises(omp_data_store.VariableStoreError):
        omp_data_store.delete_variable_set("alice", "missing")

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
    assert omp_data_store._list_user_scoped_tables(listing_conn) == [
        "omp_ai_credentials",
        "omp_variable_sets",
    ]
