from __future__ import annotations

import builtins
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from omeroweb_import.services import data_store as import_data_store


class _FakeSqlTemplate:
    """Test double for fake SQL template."""

    def __init__(self, query):
        """Initialize the instance.

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
        """SQL.

        Inputs: `query`. Output: `_FakeSqlTemplate` result.
        """
        return _FakeSqlTemplate(query)

    @staticmethod
    def Identifier(name):
        """Identifier.

        Inputs: `name`. Output: `name`.
        """
        return name


class _FakeExtras:
    """Test double for fake extras."""

    @staticmethod
    def Json(payload):
        """JSON.

        Inputs: `payload`. Output: dict.
        """
        return {"json": payload}


def test_data_store_loaders_raise_repo_errors_when_psycopg2_is_missing(monkeypatch):
    """Verify data store loaders raise repo errors when psycopg2 is missing.

    Inputs: `monkeypatch`. Output: `original_import` result. Raises on invalid or
    unavailable state.

    unavailable state.
    """
    original_import = builtins.__import__
    monkeypatch.setattr(import_data_store, "_psycopg2_mod", None)
    monkeypatch.setattr(import_data_store, "_psycopg2_extras", None)
    monkeypatch.setattr(import_data_store, "_psycopg2_sql", None)

    def _missing_import(name, *args, **kwargs):
        """Missing import.

        Inputs: `name`, `*args`, `**kwargs`. Output: `original_import` result. Raises on
        invalid or unavailable state.

        invalid or unavailable state.
        """
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
    """Verify data store connect closes connections and wraps save failures.

    Inputs: `monkeypatch`. Output: yielded values. Raises on invalid or unavailable
    state.

    state.
    """
    monkeypatch.setenv(import_data_store.ENV_USER, "import-user")
    monkeypatch.setenv(import_data_store.ENV_AUTH, "import-pass")
    monkeypatch.setenv(import_data_store.ENV_HOST, "database-plugin")
    monkeypatch.setenv(import_data_store.ENV_DB, "import-db")
    monkeypatch.setenv(import_data_store.ENV_PORT, "5433")

    class _ClosingConnection:
        """Represent closing connection."""

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
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
        """Represent exploding cursor."""

        @staticmethod
        def execute(query, params=None):
            """Execute the query or command.

            Inputs: `query`, `params`. Output: None. Raises on invalid or unavailable
            state.
            """
            raise RuntimeError("write exploded")

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    class _ExplodingConnection:
        """Represent exploding connection."""

        @staticmethod
        def cursor():
            """Return a database cursor.

            Inputs: none. Output: `_ExplodingCursor` result.
            """
            return _ExplodingCursor()

        @staticmethod
        def commit():
            """Commit the transaction.

            Inputs: none. Output: None.
            """
            return None

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None.
            """
            return None

    @contextmanager
    def _failing_connect():
        """Failing connect.

        Inputs: none. Output: yielded values.
        """
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
