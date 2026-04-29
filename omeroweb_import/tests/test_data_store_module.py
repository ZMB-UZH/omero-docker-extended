from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from omeroweb_import.services import data_store as import_data_store


class _FakeSqlTemplate:
    """Test double for fake SQL template."""

    def __init__(self, query):
        self.query = str(query)

    def format(self, *args, **kwargs):
        """Build format."""
        return self.query


class _FakeSqlModule:
    """Test double for fake SQL module."""

    @staticmethod
    def SQL(query):
        """Handle SQL."""
        return _FakeSqlTemplate(query)

    @staticmethod
    def Identifier(name):
        """Handle identifier."""
        return name


class _FakeExtras:
    """Test double for fake extras."""

    @staticmethod
    def Json(payload):
        """Handle JSON."""
        return {"json": payload}


class _FakeCursor:
    """Test double for fake cursor."""

    def __init__(self, *, fetchone=None):
        self.fetchone_value = fetchone
        self.executed = []

    def execute(self, query, params=None):
        """Run execute."""
        self.executed.append((str(query), params))

    def fetchone(self):
        """Handle fetchone."""
        return self.fetchone_value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    """Test double for fake connection."""

    def __init__(self, cursors):
        self._cursors = list(cursors)
        self.commits = 0
        self.closed = False

    def cursor(self):
        """Handle cursor."""
        return self._cursors.pop(0)

    def commit(self):
        """Handle commit."""
        self.commits += 1

    def close(self):
        """Handle close."""
        self.closed = True


class _RaisingContext:
    """Represent raising context."""

    def __init__(self, error):
        self.error = error

    def __enter__(self):
        raise self.error

    def __exit__(self, exc_type, exc, tb):
        return False


def test_import_data_store_connection_schema_and_crud(monkeypatch):
    """Verify test import data store connection schema and behavior."""
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
        """Handle fake connect."""
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
        """Handle fake queue connect."""
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
    """Verify test import data store validates credentials behavior."""
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
    """Verify test import data store persistence and load f behavior."""
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
        """Handle missing user row."""
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
        """Handle missing special row."""
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
    """Verify test import data store loaders and connect co behavior."""
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
        """Handle missing special row."""
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
    """Verify test import data store real loader success pa behavior."""
    monkeypatch.setattr(import_data_store, "_psycopg2_mod", None)
    monkeypatch.setattr(import_data_store, "_psycopg2_extras", None)
    monkeypatch.setattr(import_data_store, "_psycopg2_sql", None)

    psycopg2_mod, extras_mod = import_data_store._load_psycopg2()
    sql_mod = import_data_store._load_psycopg2_sql()

    assert psycopg2_mod.__name__ == "psycopg2"
    assert extras_mod.__name__.endswith(".extras")
    assert sql_mod.__name__.endswith(".sql")
