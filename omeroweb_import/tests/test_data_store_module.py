from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from omeroweb_import.services import data_store as import_data_store


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
    def __init__(self, *, fetchone=None):
        self.fetchone_value = fetchone
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((str(query), params))

    def fetchone(self):
        return self.fetchone_value

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
        return self._cursors.pop(0)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def test_import_data_store_connection_schema_and_crud(monkeypatch):
    monkeypatch.setenv(import_data_store.ENV_USER, "import-user")
    monkeypatch.setenv(import_data_store.ENV_PASS, "import-pass")
    monkeypatch.setenv(import_data_store.ENV_HOST, "database-plugin")
    monkeypatch.setenv(import_data_store.ENV_DB, "import-db")
    monkeypatch.setenv(import_data_store.ENV_PORT, "5434")
    monkeypatch.setenv("PGPORT", "5433")

    params = import_data_store._db_params()
    assert [entry["port"] for entry in params] == [5434, 5433, 5432]

    connection = _FakeConnection([_FakeCursor()])

    def fake_connect(**kwargs):
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
        yield queue.pop(0)

    monkeypatch.setattr(import_data_store, "_connect", fake_queue_connect)

    import_data_store.save_user_settings("alice", {"layout": "grid"})
    import_data_store.save_special_method_settings(
        "alice", "grouped", {"enabled": True}
    )
    assert import_data_store.load_special_method_settings("alice", "grouped") == {
        "enabled": True
    }
