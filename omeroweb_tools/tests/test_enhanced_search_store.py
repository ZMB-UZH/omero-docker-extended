from __future__ import annotations

from datetime import datetime, timezone

from omeroweb_tools.services import enhanced_search_store as store


class _SearchCursor:
    def __init__(self):
        self.executed = []
        self._fetchone_calls = 0

    def execute(self, sql, params=None):
        self.executed.append({"raw_sql": sql, "sql_text": str(sql), "params": params})

    def fetchone(self):
        self._fetchone_calls += 1
        if self._fetchone_calls == 1:
            return (3,)
        return None

    def fetchall(self):
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
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _SearchConn:
    def __init__(self):
        self.cursor_obj = _SearchCursor()

    def cursor(self):
        return self.cursor_obj


class _SettingsCursor:
    def __init__(self, rows):
        self.executed = []
        self.rows = list(rows)
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append({"raw_sql": sql, "sql_text": str(sql), "params": params})
        self.rowcount = 0

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _SettingsConn:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.commits = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1


class _PlaceholderCheckingCursor(_SettingsCursor):
    def execute(self, sql, params=None):
        sql_text = str(sql)
        placeholder_count = sql_text.count("%s")
        if params is not None and placeholder_count != len(params):
            raise TypeError(
                f"placeholder mismatch: expected {placeholder_count}, got {len(params)}"
            )
        self.executed.append({"raw_sql": sql, "sql_text": sql_text, "params": params})
        self.rowcount = 0


def test_search_index_rows_short_circuits_for_no_visible_groups(monkeypatch):
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
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    conn = _SearchConn()

    rows, total = store.search_index_rows(
        conn,
        visible_group_ids=[5, 7],
        current_user_id=21,
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
    assert "(%s::bigint IS NULL AND images.group_can_read = TRUE)" in count_sql
    assert "(images.group_can_read = TRUE OR images.owner_id = %s)" in count_sql
    assert "to_tsquery('simple', %s)" in count_sql
    assert "(%s::timestamptz IS NULL OR images.acquisition_date >= %s)" in count_sql
    assert "(%s::timestamptz IS NULL OR images.acquisition_date <= %s)" in count_sql
    assert "LIMIT %s OFFSET %s" in rows_sql
    assert "JOIN" not in count_sql

    assert count_params[0] == [5, 7]
    assert count_params[1] == [5, 7]
    assert count_params[2:5] == [21, 21, 21]
    assert count_params[5:7] == ["lsm:* | zeiss:*", "lsm:* | zeiss:*"]
    assert rows_params[-2:] == [25, 25]
    assert count_call["raw_sql"].__class__.__name__ != "str"
    assert rows_call["raw_sql"].__class__.__name__ != "str"


def test_load_user_settings_merges_defaults(monkeypatch):
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


def test_clear_scope_index_deletes_only_selected_scope_and_prunes_orphans(monkeypatch):
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    cursor = _SettingsCursor([])
    cursor.rowcount = 4
    conn = _SettingsConn(cursor)
    pruned = []

    def _execute(sql, params=None):
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
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    cursor = _SettingsCursor([(1,), None])
    conn = _SettingsConn(cursor)

    assert store.sync_run_is_active(conn, "user", 7, run_token="abc") is True
    assert cursor.executed[0]["params"] == ("user", 7, "abc")


def test_try_start_scope_sync_placeholder_count_matches_params(monkeypatch):
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    cursor = _PlaceholderCheckingCursor([("running", "run-token")])
    conn = _SettingsConn(cursor)

    started = store.try_start_scope_sync(
        conn,
        "user",
        21,
        "Your acquisition metadata",
        3,
        "alice",
        "run-token",
        600,
    )

    assert started is True
    assert conn.commits == 1
