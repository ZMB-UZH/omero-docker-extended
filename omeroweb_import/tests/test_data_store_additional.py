from __future__ import annotations

import builtins
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


def test_data_store_loaders_raise_repo_errors_when_psycopg2_is_missing(monkeypatch):
    """Confirm data store loaders raise repo errors when psycopg2 is missing exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in data store loaders raise repo errors when psycopg2 is missing.
    Raises: ImportError when validation or the called operation fails.
    """
    original_import = builtins.__import__
    monkeypatch.setattr(import_data_store, "_psycopg2_mod", None)
    monkeypatch.setattr(import_data_store, "_psycopg2_extras", None)
    monkeypatch.setattr(import_data_store, "_psycopg2_sql", None)

    def _missing_import(name, *args, **kwargs):
        """Return the missing import.

        Inputs: `name` name, `*args` positional arguments, `**kwargs` keyword arguments.
        Output: `original_import` result. Raises: ImportError when validation or
        external operations fail.
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

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in data store connect closes connections and wraps save failures.
    Raises: RuntimeError when validation or the called operation fails.
    """
    monkeypatch.setenv(import_data_store.ENV_USER, "import-user")
    monkeypatch.setenv(import_data_store.ENV_AUTH, "import-pass")
    monkeypatch.setenv(import_data_store.ENV_HOST, "database-plugin")
    monkeypatch.setenv(import_data_store.ENV_DB, "import-db")
    monkeypatch.setenv(import_data_store.ENV_PORT, "5433")

    class _ClosingConnection:
        """Test double for closing connection behavior in this module."""

        @staticmethod
        def close():
            """Close `_ClosingConnection`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
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
        """Test double for exploding cursor behavior in this module."""

        @staticmethod
        def execute(query, params=None):
            """Record the execute call on `_ExplodingCursor` for later assertions.

            Inputs: `query`, `params`. Output: None. Raises: RuntimeError when validation or the called operation fails.
            """
            raise RuntimeError("write exploded")

        def __enter__(self):
            """Enter `_ExplodingCursor`'s context-managed fake resource.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit `_ExplodingCursor`'s context-managed fake resource.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    class _ExplodingConnection:
        """Test double for exploding connection behavior in this module."""

        @staticmethod
        def cursor():
            """Return a database cursor.

            Inputs: none. Output: `_ExplodingCursor` result.
            """
            return _ExplodingCursor()

        @staticmethod
        def commit():
            """Commit `_ExplodingConnection`'s fake transaction.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            return None

        @staticmethod
        def close():
            """Close `_ExplodingConnection`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            return None

    @contextmanager
    def _failing_connect():
        """Return the failing connect.

        Inputs: none. Output: iterator of yielded items.
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
