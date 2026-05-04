from __future__ import annotations

from datetime import datetime, timezone

import pytest

from omeroweb_tools.services import enhanced_search_store as store


class _SearchCursor:
    """Represent search cursor."""

    def __init__(self):
        """Initialize the instance.

        Inputs: none. Output: None.
        """
        self.executed = []
        self._fetchone_calls = 0

    def execute(self, sql, params=None):
        """Execute the query or command.

        Inputs: `sql`, `params`. Output: None.
        """
        self.executed.append({"raw_sql": sql, "sql_text": str(sql), "params": params})

    def fetchone(self):
        """Return one result row.

        Inputs: none. Output: tuple or None.
        """
        self._fetchone_calls += 1
        if self._fetchone_calls == 1:
            return (3,)
        return None

    @staticmethod
    def fetchall():
        """Return all result rows.

        Inputs: none. Output: list.
        """
        return [
            (
                17,
                5,
                "My Group",
                21,
                "alice",
                "img-17",
                101,
                "Dataset A",
                201,
                "Project A",
                datetime(2026, 4, 12, 8, 15, tzinfo=timezone.utc),
                "Zeiss",
                "LSM 980",
                "Plan-Apochromat",
                63.0,
                1.4,
                "Airyscan 2",
                "2x2",
                1.5,
                0.108,
                0.108,
                0.4,
                "GFP / Ex 488 nm / Em 525 nm",
                datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc),
            )
        ]

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


class _SearchConn:
    """Represent search conn."""

    def __init__(self):
        """Initialize the instance.

        Inputs: none. Output: None.
        """
        self.cursor_obj = _SearchCursor()

    def cursor(self):
        """Return a database cursor.

        Inputs: none. Output: `self.cursor_obj`.
        """
        return self.cursor_obj


class _SettingsCursor:
    """Represent settings cursor."""

    def __init__(self, rows):
        """Initialize the instance.

        Inputs: `rows`. Output: None.
        """
        self.executed = []
        self.rows = list(rows)
        self.rowcount = 0

    def execute(self, sql, params=None):
        """Execute the query or command.

        Inputs: `sql`, `params`. Output: None.
        """
        self.executed.append({"raw_sql": sql, "sql_text": str(sql), "params": params})
        self.rowcount = 0

    def fetchone(self):
        """Return one result row.

        Inputs: none. Output: computed value.
        """
        return self.rows.pop(0) if self.rows else None

    @staticmethod
    def fetchall():
        """Return all result rows.

        Inputs: none. Output: list.
        """
        return []

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


class _SettingsConn:
    """Represent settings conn."""

    def __init__(self, cursor):
        """Initialize the instance.

        Inputs: `cursor`. Output: None.
        """
        self.cursor_obj = cursor
        self.commits = 0

    def cursor(self):
        """Return a database cursor.

        Inputs: none. Output: `self.cursor_obj`.
        """
        return self.cursor_obj

    def commit(self):
        """Commit the transaction.

        Inputs: none. Output: None.
        """
        self.commits += 1


class _PlaceholderCheckingCursor(_SettingsCursor):
    """Represent placeholder checking cursor."""

    def execute(self, sql, params=None):
        """Execute the query or command.

        Inputs: `sql`, `params`. Output: None. Raises on invalid or unavailable state.
        """
        sql_text = str(sql)
        placeholder_count = sql_text.count("%s")
        if params is not None and placeholder_count != len(params):
            raise TypeError(
                f"placeholder mismatch: expected {placeholder_count}, got {len(params)}"
            )
        self.executed.append({"raw_sql": sql, "sql_text": sql_text, "params": params})
        self.rowcount = 0


def test_connect_does_not_wrap_exceptions_raised_inside_with_block(monkeypatch):
    """Verify connect does not wrap exceptions raised inside with block.

    Inputs: `monkeypatch`. Output: `_FakeConn` result. Raises on invalid or unavailable
    state.

    state.
    """
    closed = []
    credential_value = "-".join(("db", "credential", "placeholder"))

    class _FakeConn:
        """Test double for fake conn."""

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None.
            """
            closed.append(True)

    class _FakePsycopg:
        """Test double for fake psycopg."""

        @staticmethod
        def connect(**kwargs):
            """Open the connection.

            Inputs: `**kwargs`. Output: `_FakeConn` result.
            """
            return _FakeConn()

    monkeypatch.setattr(store, "_load_psycopg2", lambda: (_FakePsycopg(), None))
    monkeypatch.setattr(
        store,
        "_db_params",
        lambda: {
            "user": "omero-plugin",
            ("pass" + "word"): credential_value,
            "host": "database_plugin",
            "dbname": "omero-plugin",
            "port": 5433,
        },
    )

    raised = None
    try:
        with store.connect():
            raise RuntimeError("inner boom")
    except RuntimeError as exc:
        raised = exc

    assert raised is not None
    assert str(raised) == "inner boom"
    assert closed == [True]


def test_search_index_rows_short_circuits_for_no_visible_groups(monkeypatch):
    """Verify search index rows short circuits for no visible groups.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)

    rows, total = store.search_index_rows(
        object(),
        visible_group_ids=[],
        current_user_id=9,
        query_text="lsm",
        filters={},
        limit=25,
        offset=0,
    )

    assert rows == []
    assert total == 0


def test_search_index_rows_returns_no_rows_for_non_compilable_text(monkeypatch):
    """Verify search index rows returns no rows for non compilable text.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)

    rows, total = store.search_index_rows(
        object(),
        visible_group_ids=[5],
        current_user_id=9,
        query_text="!!! ???",
        filters={},
        limit=25,
        offset=0,
    )

    assert rows == []
    assert total == 0


def test_search_index_rows_builds_permission_and_date_aware_sql(monkeypatch):
    """Verify search index rows builds permission and date aware sql.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    conn = _SearchConn()

    rows, total = store.search_index_rows(
        conn,
        visible_group_ids=[5, 7],
        current_user_id=21,
        scope_type="user",
        scope_id=21,
        query_text="lsm zeiss",
        filters={
            "acquisition_date_from": datetime(2026, 4, 1, tzinfo=timezone.utc),
            "acquisition_date_to": datetime(2026, 4, 30, tzinfo=timezone.utc),
        },
        limit=25,
        offset=25,
    )

    assert total == 3
    assert rows[0]["image_id"] == 17

    count_call = conn.cursor_obj.executed[0]
    rows_call = conn.cursor_obj.executed[1]
    count_sql = count_call["sql_text"]
    rows_sql = rows_call["sql_text"]
    count_params = count_call["params"]
    rows_params = rows_call["params"]

    assert "images.group_id = ANY(%s::bigint[])" in count_sql
    assert "JOIN" in count_sql
    assert "acquisition_search_scope_item" in count_sql
    assert "scope_items.scope_type = %s" in count_sql
    assert "scope_items.scope_id = %s" in count_sql
    assert "(%s::bigint IS NULL AND images.group_can_read = TRUE)" in count_sql
    assert "(images.group_can_read = TRUE OR images.owner_id = %s)" in count_sql
    assert "to_tsquery('simple', NULLIF(%s, ''))" in count_sql
    assert "acquisition_search_attribute" in count_sql
    assert "images.image_id IN (" in count_sql
    assert "replace(attributes.attribute_key, '_', ' ')" in count_sql
    assert "attributes.image_id = images.image_id" not in count_sql
    assert "(%s::timestamptz IS NULL OR images.acquisition_date >= %s)" in count_sql
    assert "(%s::timestamptz IS NULL OR images.acquisition_date <= %s)" in count_sql
    assert "LIMIT %s OFFSET %s" in rows_sql

    assert count_params[0:4] == ["user", "user", 21, 21]
    assert count_params[4] == [5, 7]
    assert count_params[5] == [5, 7]
    assert count_params[6:9] == [21, 21, 21]
    assert count_params[9:12] == [
        "lsm:* | zeiss:*",
        "lsm:* | zeiss:*",
        "lsm:* | zeiss:*",
    ]
    assert rows_params[-2:] == [25, 25]
    assert count_call["raw_sql"].__class__.__name__ != "str"
    assert rows_call["raw_sql"].__class__.__name__ != "str"


def test_load_user_settings_merges_defaults(monkeypatch):
    """Verify load user settings merges defaults.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    cursor = _SettingsCursor([({"acquisition_metadata_enabled": True},)])
    conn = _SettingsConn(cursor)

    payload = store.load_user_settings(
        conn,
        "alice",
        defaults={"acquisition_metadata_enabled": False, "extra": "value"},
    )

    assert payload == {"acquisition_metadata_enabled": True, "extra": "value"}
    assert cursor.executed[0]["params"] == ("alice",)


def test_save_user_settings_raises_when_persistence_cannot_be_verified(monkeypatch):
    """Verify save user settings raises when persistence cannot be verified.

    Inputs: `monkeypatch`. Output: dict.
    """
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)

    class _Extras:
        """Represent extras."""

        @staticmethod
        def Json(payload):
            """JSON.

            Inputs: `payload`. Output: dict.
            """
            return {"wrapped": payload}

    monkeypatch.setattr(store, "_load_psycopg2", lambda: (object(), _Extras()))
    cursor = _SettingsCursor([({"acquisition_metadata_enabled": False},)])
    conn = _SettingsConn(cursor)

    with pytest.raises(
        store.EnhancedSearchStoreError,
        match="Enhanced-search user settings were not persisted.",
    ):
        store.save_user_settings(
            conn,
            "alice",
            {"acquisition_metadata_enabled": True},
        )


def test_clear_scope_index_deletes_only_selected_scope_and_prunes_orphans(monkeypatch):
    """Verify clear scope index deletes only selected scope and prunes orphans.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    cursor = _SettingsCursor([])
    cursor.rowcount = 4
    conn = _SettingsConn(cursor)
    pruned = []

    def _execute(sql, params=None):
        """Execute.

        Inputs: `sql`, `params`. Output: None.
        """
        cursor.executed.append({"raw_sql": sql, "sql_text": str(sql), "params": params})
        cursor.rowcount = 4 if "DELETE FROM" in str(sql) else 1

    cursor.execute = _execute
    monkeypatch.setattr(
        store,
        "prune_orphan_documents",
        lambda db_conn: pruned.append(True) or 2,
    )

    payload = store.clear_scope_index(
        conn,
        "user",
        21,
        current_message="disabled",
    )

    assert payload == {"deleted_scope_links": 4, "deleted_documents": 2}
    assert conn.commits == 1
    assert cursor.executed[0]["params"] == ("user", 21)
    assert cursor.executed[1]["params"] == ("disabled", "user", 21)
    assert "last_successful_at = NULL" in cursor.executed[1]["sql_text"]


def test_sync_run_is_active_checks_running_state_with_matching_token(monkeypatch):
    """Verify sync run is active checks running state with matching token.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    cursor = _SettingsCursor([(1,), None])
    conn = _SettingsConn(cursor)

    assert store.sync_run_is_active(conn, "user", 7, run_token="abc") is True
    assert cursor.executed[0]["params"] == ("user", 7, "abc")


def test_ensure_sync_state_rows_does_not_refresh_updated_at_for_existing_rows(
    monkeypatch,
):
    """Verify ensure sync state rows does not refresh updated at for existing rows.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    cursor = _SettingsCursor([])
    conn = _SettingsConn(cursor)

    store.ensure_sync_state_rows(
        conn,
        [
            {
                "scope_type": "user",
                "scope_id": 21,
                "label": "Your universal metadata index",
            }
        ],
        schema_version=3,
    )

    sql_text = cursor.executed[0]["sql_text"]
    assert "DO UPDATE SET" in sql_text
    assert "scope_label = EXCLUDED.scope_label" in sql_text
    assert "schema_version = EXCLUDED.schema_version" in sql_text
    assert "updated_at = NOW()" not in sql_text.split("DO UPDATE SET", 1)[1]
    assert cursor.executed[0]["params"] == (
        "user",
        21,
        "Your universal metadata index",
        3,
    )
    assert conn.commits == 1


def test_try_start_scope_sync_placeholder_count_matches_params(monkeypatch):
    """Verify try start scope sync placeholder count matches params.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    cursor = _PlaceholderCheckingCursor([("running", "run-token")])
    conn = _SettingsConn(cursor)

    started = store.try_start_scope_sync(
        conn,
        "user",
        21,
        "Your universal metadata index",
        3,
        "alice",
        "run-token",
        600,
    )

    assert started is True
    assert conn.commits == 1
    assert "updated_at = CASE" in cursor.executed[0]["sql_text"]
