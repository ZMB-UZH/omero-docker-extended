from __future__ import annotations

import builtins
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

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


def test_data_store_loaders_raise_repo_errors_when_psycopg2_is_missing(monkeypatch):
    original_import = builtins.__import__
    monkeypatch.setattr(import_data_store, "_psycopg2_mod", None)
    monkeypatch.setattr(import_data_store, "_psycopg2_extras", None)
    monkeypatch.setattr(import_data_store, "_psycopg2_sql", None)

    def _missing_import(name, *args, **kwargs):
        if name == "psycopg2":
            raise ImportError("psycopg2 unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _missing_import)

    with pytest.raises(
        import_data_store.UserSettingsStoreError,
        match=import_data_store.errors.psycopg2_missing(),
    ):
        import_data_store._load_psycopg2()

    with pytest.raises(
        import_data_store.UserSettingsStoreError,
        match=import_data_store.errors.psycopg2_missing(),
    ):
        import_data_store._load_psycopg2_sql()


def test_data_store_connect_closes_connections_and_wraps_save_failures(monkeypatch):
    monkeypatch.setenv(import_data_store.ENV_USER, "import-user")
    monkeypatch.setenv(import_data_store.ENV_AUTH, "import-pass")
    monkeypatch.setenv(import_data_store.ENV_HOST, "database-plugin")
    monkeypatch.setenv(import_data_store.ENV_DB, "import-db")
    monkeypatch.setenv(import_data_store.ENV_PORT, "5433")

    class _ClosingConnection:
        def close(self):
            raise RuntimeError("close failed")

    closing_connection = _ClosingConnection()
    monkeypatch.setattr(
        import_data_store,
        "_load_psycopg2",
        lambda: (
            SimpleNamespace(connect=lambda **kwargs: closing_connection),
            _FakeExtras,
        ),
    )

    with import_data_store._connect() as opened:
        assert opened is closing_connection

    class _ExplodingCursor:
        def execute(self, query, params=None):
            raise RuntimeError("write exploded")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _ExplodingConnection:
        def cursor(self):
            return _ExplodingCursor()

        def commit(self):
            return None

        def close(self):
            return None

    @contextmanager
    def _failing_connect():
        yield _ExplodingConnection()

    monkeypatch.setattr(import_data_store, "_load_psycopg2_sql", lambda: _FakeSqlModule)
    monkeypatch.setattr(
        import_data_store, "_load_psycopg2", lambda: (SimpleNamespace(), _FakeExtras)
    )
    monkeypatch.setattr(
        import_data_store, "_ensure_user_settings_schema", lambda conn: None
    )
    monkeypatch.setattr(
        import_data_store, "_ensure_special_method_settings_schema", lambda conn: None
    )
    monkeypatch.setattr(import_data_store, "_connect", _failing_connect)

    with pytest.raises(
        import_data_store.UserSettingsStoreError,
        match=import_data_store.errors.user_settings_save_failed(),
    ):
        import_data_store.save_user_settings("alice", {"layout": "grid"})

    with pytest.raises(
        import_data_store.UserSettingsStoreError,
        match=import_data_store.errors.special_method_settings_save_failed(),
    ):
        import_data_store.save_special_method_settings(
            "alice",
            "grouped",
            {"enabled": True},
        )
