from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from omeroweb_import.services import data_store as import_data_store


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

    def __init__(self, *, fetchone=None):
        """Create `_FakeCursor` with its default state.

        Inputs: `fetchone`. Output: None.
        """
        self.fetchone_value = fetchone
        self.executed = []

    def execute(self, query, params=None):
        """Execute `_FakeCursor`'s captured query or command.

        Inputs: `query`, `params`. Output: None.
        """
        self.executed.append((str(query), params))

    def fetchone(self):
        """Return one result row from `_FakeCursor`.

        Inputs: none. Output: `self.fetchone_value`.
        """
        return self.fetchone_value

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


def test_import_data_store_connection_schema_and_crud(monkeypatch):
    """Verify import data store connection schema and crud.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in import data store connection schema and crud.
    Raises: OSError when validation or the called operation fails.
    """
    monkeypatch.setenv(import_data_store.ENV_USER, "import-user")
    monkeypatch.setenv(import_data_store.ENV_AUTH, "import-pass")
    monkeypatch.setenv(import_data_store.ENV_HOST, "database-plugin")
    monkeypatch.setenv(import_data_store.ENV_DB, "import-db")
    monkeypatch.setenv(import_data_store.ENV_PORT, "5434")
    monkeypatch.setenv("PGPORT", "5433")

    params = import_data_store._db_params()
    assert [entry["port"] for entry in params] == [5434, 5433, 5432]

    connection = _FakeConnection([_FakeCursor()])

    def fake_connect(**kwargs):
        """Simulate connect so the surrounding test controls that dependency.

        Inputs: `**kwargs` keyword arguments. Output: `connection`. Raises: OSError when validation or the called operation fails.
        """
        if kwargs["port"] == 5434:
            raise OSError("port closed")
        return connection

    monkeypatch.setattr(
        import_data_store,
        "_load_psycopg2",
        lambda: (SimpleNamespace(connect=fake_connect), _FakeExtras),
    )

    with import_data_store._connect() as opened:
        assert opened is connection
    assert connection.closed is True

    monkeypatch.setattr(import_data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    schema_conn = _FakeConnection([_FakeCursor()])
    import_data_store._ensure_user_settings_schema(schema_conn)
    assert schema_conn.commits == 1

    special_schema_conn = _FakeConnection([_FakeCursor()])
    import_data_store._ensure_special_method_settings_schema(special_schema_conn)
    assert special_schema_conn.commits == 1

    monkeypatch.setattr(
        import_data_store, "_ensure_user_settings_schema", lambda conn: None
    )
    monkeypatch.setattr(
        import_data_store, "_ensure_special_method_settings_schema", lambda conn: None
    )
    monkeypatch.setattr(
        import_data_store,
        "_load_psycopg2",
        lambda: (SimpleNamespace(), _FakeExtras),
    )

    queue = [
        _FakeConnection([_FakeCursor(), _FakeCursor(fetchone=({"layout": "grid"},))]),
        _FakeConnection([_FakeCursor(), _FakeCursor(fetchone=({"enabled": True},))]),
        _FakeConnection([_FakeCursor(fetchone=({"enabled": True},))]),
    ]

    @contextmanager
    def fake_queue_connect():
        """Simulate queue connect so the surrounding test controls that dependency.

        Inputs: none. Output: iterator of yielded items.
        """
        yield queue.pop(0)

    monkeypatch.setattr(import_data_store, "_connect", fake_queue_connect)

    import_data_store.save_user_settings("alice", {"layout": "grid"})
    import_data_store.save_special_method_settings(
        "alice", "grouped", {"enabled": True}
    )
    assert import_data_store.load_special_method_settings("alice", "grouped") == {
        "enabled": True
    }


def test_import_data_store_validates_credentials_ports_and_connection_failures(
    monkeypatch,
):
    """Verify import data store validates credentials ports and connection failures.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in import data store validates credentials ports and connection failures.
    AssertionError when validation or the called operation fails.
    """
    monkeypatch.delenv(import_data_store.ENV_USER, raising=False)
    monkeypatch.delenv(import_data_store.ENV_AUTH, raising=False)
    monkeypatch.delenv(import_data_store.ENV_HOST, raising=False)
    monkeypatch.delenv(import_data_store.ENV_DB, raising=False)

    try:
        import_data_store._db_params()
    except import_data_store.UserSettingsStoreError as exc:
        assert str(exc) == import_data_store.errors.missing_db_credentials()
    else:
        raise AssertionError("Expected missing credentials error")

    monkeypatch.setenv(import_data_store.ENV_USER, "import-user")
    monkeypatch.setenv(import_data_store.ENV_AUTH, "import-pass")
    monkeypatch.setenv(import_data_store.ENV_HOST, "database-plugin")
    monkeypatch.setenv(import_data_store.ENV_DB, "import-db")
    monkeypatch.setenv(import_data_store.ENV_PORT, "bad")
    monkeypatch.setenv("PGPORT", "5435")

    assert [entry["port"] for entry in import_data_store._db_params()] == [
        5435,
        5433,
        5432,
    ]

    monkeypatch.setattr(
        import_data_store,
        "_load_psycopg2",
        lambda: (
            SimpleNamespace(
                connect=lambda **kwargs: (_ for _ in ()).throw(OSError("offline"))
            ),
            _FakeExtras,
        ),
    )

    try:
        with import_data_store._connect():
            pass
    except import_data_store.UserSettingsStoreError as exc:
        assert str(exc) == import_data_store.errors.db_connection_failed()
    else:
        raise AssertionError("Expected connection failure")


def test_import_data_store_persistence_and_load_failures_are_sanitized(monkeypatch):
    """Verify import data store persistence and load failures are sanitized.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in import data store persistence and load failures are sanitized.
    Raises: AssertionError when validation or the called operation fails.
    """
    monkeypatch.setattr(import_data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    monkeypatch.setattr(
        import_data_store,
        "_load_psycopg2",
        lambda: (SimpleNamespace(), _FakeExtras),
    )
    monkeypatch.setattr(
        import_data_store, "_ensure_user_settings_schema", lambda conn: None
    )
    monkeypatch.setattr(
        import_data_store, "_ensure_special_method_settings_schema", lambda conn: None
    )

    @contextmanager
    def _missing_user_row():
        """Return the missing user row.

        Inputs: none. Output: iterator of yielded items.
        """
        yield _FakeConnection([_FakeCursor(), _FakeCursor(fetchone=None)])

    monkeypatch.setattr(import_data_store, "_connect", _missing_user_row)
    try:
        import_data_store.save_user_settings("alice", {"layout": "grid"})
    except import_data_store.UserSettingsStoreError as exc:
        assert str(exc) == import_data_store.errors.user_settings_not_persisted()
    else:
        raise AssertionError("Expected user settings persistence failure")

    @contextmanager
    def _missing_special_row():
        """Return the missing special row.

        Inputs: none. Output: iterator of yielded items.
        """
        yield _FakeConnection([_FakeCursor(), _FakeCursor(fetchone=None)])

    monkeypatch.setattr(import_data_store, "_connect", _missing_special_row)
    try:
        import_data_store.save_special_method_settings(
            "alice",
            "grouped",
            {"enabled": True},
        )
    except import_data_store.UserSettingsStoreError as exc:
        assert (
            str(exc) == import_data_store.errors.special_method_settings_not_persisted()
        )
    else:
        raise AssertionError("Expected special method persistence failure")

    monkeypatch.setattr(
        import_data_store,
        "_connect",
        lambda: _RaisingContext(RuntimeError("database unavailable")),
    )
    try:
        import_data_store.load_special_method_settings("alice", "grouped")
    except import_data_store.UserSettingsStoreError as exc:
        assert str(exc) == import_data_store.errors.db_connection_failed()
    else:
        raise AssertionError("Expected wrapped load failure")


def test_import_data_store_loaders_and_connect_cover_cache_and_empty_option_edges(
    monkeypatch,
):
    """Verify import data store loaders and connect cover cache and empty option edges.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in import data store loaders and connect cover cache and empty option edges.
    """
    sentinel_mod = object()
    sentinel_extras = object()
    sentinel_sql = object()
    monkeypatch.setattr(import_data_store, "_psycopg2_mod", sentinel_mod)
    monkeypatch.setattr(import_data_store, "_psycopg2_extras", sentinel_extras)
    monkeypatch.setattr(import_data_store, "_psycopg2_sql", sentinel_sql)

    assert import_data_store._load_psycopg2() == (sentinel_mod, sentinel_extras)
    assert import_data_store._load_psycopg2_sql() is sentinel_sql

    monkeypatch.setenv(import_data_store.ENV_USER, "import-user")
    monkeypatch.setenv(import_data_store.ENV_AUTH, "import-pass")
    monkeypatch.setenv(import_data_store.ENV_HOST, "database-plugin")
    monkeypatch.setenv(import_data_store.ENV_DB, "import-db")
    monkeypatch.setenv(import_data_store.ENV_PORT, " ")
    monkeypatch.setenv("PGPORT", "5436")
    assert [entry["port"] for entry in import_data_store._db_params()] == [
        5436,
        5433,
        5432,
    ]

    monkeypatch.setattr(import_data_store, "_db_params", lambda: [])
    monkeypatch.setattr(
        import_data_store,
        "_load_psycopg2",
        lambda: (SimpleNamespace(connect=lambda **kwargs: None), _FakeExtras),
    )
    with (
        pytest.raises(
            import_data_store.UserSettingsStoreError,
            match=import_data_store.errors.db_connection_failed(),
        ),
        import_data_store._connect(),
    ):
        pass

    monkeypatch.setattr(
        import_data_store,
        "_db_params",
        lambda: [{"host": "database-plugin", "port": 5432}],
    )
    monkeypatch.setattr(
        import_data_store,
        "_load_psycopg2",
        lambda: (
            SimpleNamespace(
                connect=lambda **kwargs: (_ for _ in ()).throw(
                    import_data_store.UserSettingsStoreError("boom")
                )
            ),
            _FakeExtras,
        ),
    )
    with (
        pytest.raises(import_data_store.UserSettingsStoreError, match="boom"),
        import_data_store._connect(),
    ):
        pass

    monkeypatch.setattr(import_data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    monkeypatch.setattr(
        import_data_store, "_ensure_special_method_settings_schema", lambda conn: None
    )

    @contextmanager
    def _missing_special_row():
        """Return the missing special row.

        Inputs: none. Output: iterator of yielded items.
        """
        yield _FakeConnection([_FakeCursor(fetchone=None)])

    monkeypatch.setattr(import_data_store, "_connect", _missing_special_row)
    assert import_data_store.load_special_method_settings("alice", "grouped") is None

    monkeypatch.setattr(
        import_data_store,
        "_connect",
        lambda: _RaisingContext(import_data_store.UserSettingsStoreError("wrapped")),
    )
    with pytest.raises(import_data_store.UserSettingsStoreError, match="wrapped"):
        import_data_store.load_special_method_settings("alice", "grouped")


def test_import_data_store_real_loader_success_paths_cache_imports(monkeypatch):
    """Verify import data store real loader success paths cache imports.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in import data store real loader success paths cache imports.
    """
    monkeypatch.setattr(import_data_store, "_psycopg2_mod", None)
    monkeypatch.setattr(import_data_store, "_psycopg2_extras", None)
    monkeypatch.setattr(import_data_store, "_psycopg2_sql", None)

    psycopg2_mod, extras_mod = import_data_store._load_psycopg2()
    sql_mod = import_data_store._load_psycopg2_sql()

    assert psycopg2_mod.__name__ == "psycopg2"
    assert extras_mod.__name__.endswith(".extras")
    assert sql_mod.__name__.endswith(".sql")
