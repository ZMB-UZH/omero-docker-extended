from __future__ import annotations

import builtins
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from omeroweb_tools.services import enhanced_search_store as store


class _RecordingCursor:
    def __init__(self, *, fetchone_rows=None, fetchall_rows=None):
        self.executed = []
        self._fetchone_rows = list(fetchone_rows or [])
        self._fetchall_rows = list(fetchall_rows or [])
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append({"raw_sql": sql, "sql_text": str(sql), "params": params})

    def fetchone(self):
        return self._fetchone_rows.pop(0) if self._fetchone_rows else None

    def fetchall(self):
        return self._fetchall_rows.pop(0) if self._fetchall_rows else []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _RecordingConn:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.commits = 0
        self.closed = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed += 1


def test_psycopg_loaders_cover_success_cache_and_missing_driver(monkeypatch):
    class _FakeSQLTemplate:
        def __init__(self, template):
            self.template = template

        def format(self, *identifiers):
            return self.template.format(*identifiers)

    fake_extras = types.SimpleNamespace(Json=lambda payload: payload)
    fake_sql = types.SimpleNamespace(
        SQL=lambda template: _FakeSQLTemplate(template),
        Identifier=lambda value: f"<{value}>",
    )
    fake_psycopg2 = types.ModuleType("psycopg2")
    fake_psycopg2.extras = fake_extras
    fake_psycopg2.sql = fake_sql
    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)
    monkeypatch.setattr(store, "_psycopg2_mod", None)
    monkeypatch.setattr(store, "_psycopg2_extras", None)
    monkeypatch.setattr(store, "_psycopg2_sql", None)

    loaded_psycopg2, loaded_extras = store._load_psycopg2()
    loaded_sql = store._load_psycopg2_sql()
    cached_psycopg2, cached_extras = store._load_psycopg2()

    assert loaded_psycopg2 is fake_psycopg2
    assert loaded_extras is fake_extras
    assert loaded_sql is fake_sql
    assert cached_psycopg2 is fake_psycopg2
    assert cached_extras is fake_extras
    assert store._safe_query("SELECT {} FROM {}", "column", "table") == (
        "SELECT <column> FROM <table>"
    )

    monkeypatch.delitem(sys.modules, "psycopg2", raising=False)
    monkeypatch.setattr(store, "_psycopg2_mod", None)
    monkeypatch.setattr(store, "_psycopg2_extras", None)
    monkeypatch.setattr(store, "_psycopg2_sql", None)
    original_import = builtins.__import__

    def _missing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "psycopg2":
            raise ImportError("missing driver")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _missing_import)

    with pytest.raises(store.EnhancedSearchStoreError, match="psycopg2 is required"):
        store._load_psycopg2()

    with pytest.raises(store.EnhancedSearchStoreError, match="psycopg2 is required"):
        store._load_psycopg2_sql()


def test_db_params_and_connect_cover_wrapped_failures_and_close_suppression(
    monkeypatch,
):
    db_auth_value = "plugin-auth-value"

    def _env_value(name, env_file=None):
        del env_file
        return {
            store.ENV_USER: "plugin-user",
            store.ENV_AUTH: db_auth_value,
            store.ENV_HOST: "database_plugin",
            store.ENV_DB: "plugin-db",
            store.ENV_PORT: "5433",
        }[name]

    monkeypatch.setattr(
        store,
        "get_env",
        _env_value,
    )
    assert store._db_params() == {
        "user": "plugin-user",
        "password": db_auth_value,
        "host": "database_plugin",
        "dbname": "plugin-db",
        "port": 5433,
    }

    class _FailingPsycopg:
        @staticmethod
        def connect(**kwargs):
            raise RuntimeError("db boom")

    monkeypatch.setattr(store, "_load_psycopg2", lambda: (_FailingPsycopg(), None))
    monkeypatch.setattr(store, "_db_params", lambda: {"dbname": "plugin-db"})

    with pytest.raises(
        store.EnhancedSearchStoreError,
        match="Enhanced-search database operation failed.",
    ):
        with store.connect():
            pass

    monkeypatch.setattr(
        store,
        "_load_psycopg2",
        lambda: (SimpleNamespace(connect=lambda **kwargs: object()), None),
    )
    monkeypatch.setattr(
        store,
        "_db_params",
        lambda: (_ for _ in ()).throw(store.EnhancedSearchStoreError("driver missing")),
    )
    with pytest.raises(store.EnhancedSearchStoreError, match="driver missing"):
        with store.connect():
            pass

    class _BadCloseConn:
        def close(self):
            raise RuntimeError("close boom")

    class _OkPsycopg:
        @staticmethod
        def connect(**kwargs):
            return _BadCloseConn()

    monkeypatch.setattr(store, "_db_params", lambda: {"dbname": "plugin-db"})
    monkeypatch.setattr(store, "_load_psycopg2", lambda: (_OkPsycopg(), None))
    with store.connect() as conn:
        assert isinstance(conn, _BadCloseConn)


def test_ensure_schema_bootstraps_tables_indexes_and_commit(monkeypatch):
    cursor = _RecordingCursor()
    conn = _RecordingConn(cursor)

    def _load_sql_module():
        return object()

    monkeypatch.setattr(
        store, "_safe_query", lambda template, *ids: template.format(*ids)
    )
    monkeypatch.setattr(store, "_load_psycopg2_sql", _load_sql_module)

    store.ensure_schema(conn)

    combined_sql = "\n".join(call["sql_text"] for call in cursor.executed)
    assert "CREATE TABLE IF NOT EXISTS acquisition_search_image" in combined_sql
    assert "CREATE TABLE IF NOT EXISTS acquisition_search_channel" in combined_sql
    assert "CREATE TABLE IF NOT EXISTS acquisition_search_attribute" in combined_sql
    assert "CREATE TABLE IF NOT EXISTS acquisition_search_scope_item" in combined_sql
    assert "CREATE TABLE IF NOT EXISTS acquisition_search_sync_state" in combined_sql
    assert "CREATE TABLE IF NOT EXISTS acquisition_search_saved_query" in combined_sql
    assert "CREATE TABLE IF NOT EXISTS acquisition_search_user_settings" in combined_sql
    assert "USING GIN (to_tsvector('simple', search_document))" in combined_sql
    assert conn.commits == 1


def test_list_sync_states_and_saved_queries_map_store_rows(monkeypatch):
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    run_marker = "sync-run-id"
    cursor = _RecordingCursor(
        fetchall_rows=[
            [
                (
                    "user",
                    7,
                    "Your acquisition metadata",
                    3,
                    "running",
                    "alice",
                    run_marker,
                    99,
                    5,
                    "Indexing scope...",
                    "",
                    datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc),
                    None,
                    None,
                    datetime(2026, 4, 12, 10, 5, tzinfo=timezone.utc),
                )
            ],
            [
                (
                    3,
                    "My query",
                    {"query_text": "lsm"},
                    datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc),
                    datetime(2026, 4, 12, 9, 5, tzinfo=timezone.utc),
                )
            ],
        ]
    )
    conn = _RecordingConn(cursor)

    states = store.list_sync_states(conn)
    saved_queries = store.list_saved_queries(conn, "alice")

    assert states == [
        {
            "scope_type": "user",
            "scope_id": 7,
            "scope_label": "Your acquisition metadata",
            "schema_version": 3,
            "status": "running",
            "requested_by": "alice",
            "run_token": run_marker,
            "last_cursor_image_id": 99,
            "indexed_image_count": 5,
            "current_message": "Indexing scope...",
            "last_error": "",
            "last_started_at": datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc),
            "last_finished_at": None,
            "last_successful_at": None,
            "updated_at": datetime(2026, 4, 12, 10, 5, tzinfo=timezone.utc),
        }
    ]
    assert saved_queries == [
        {
            "id": 3,
            "query_name": "My query",
            "query_payload": {"query_text": "lsm"},
            "created_at": datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 4, 12, 9, 5, tzinfo=timezone.utc),
        }
    ]


def test_prune_helpers_search_rows_without_filters_and_non_dict_settings_row(
    monkeypatch,
):
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    cursor = _RecordingCursor(
        fetchone_rows=[(2,), ("not-a-dict",)], fetchall_rows=[[()]]
    )
    conn = _RecordingConn(cursor)

    def _execute(sql, params=None):
        cursor.executed.append({"raw_sql": sql, "sql_text": str(sql), "params": params})
        if "DELETE FROM" in str(sql):
            cursor.rowcount = 3
        else:
            cursor.rowcount = 0

    cursor.execute = _execute
    prune_run_marker = "sync-run-a"

    pruned_scope = store.prune_scope_membership(conn, "user", 7, prune_run_marker)
    pruned_docs = store.prune_orphan_documents(conn)
    rows, total = store.search_index_rows(
        conn,
        visible_group_ids=None,
        current_user_id=None,
        query_text="",
        filters={},
        limit=None,
        offset=0,
    )
    payload = store.load_user_settings(conn, "alice", defaults={"default": True})

    assert pruned_scope == 3
    assert pruned_docs == 3
    assert rows == [{}]
    assert total == 2
    assert payload == {"default": True}


def test_sync_markers_and_document_upsert_cover_write_paths(monkeypatch):
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    cursor = _RecordingCursor()
    conn = _RecordingConn(cursor)
    run_marker = "sync-run-a"

    store.update_sync_progress(
        conn,
        "user",
        7,
        run_token=run_marker,
        indexed_image_count=4,
        current_message="Indexed 4 image(s)...",
        last_cursor_image_id=99,
    )
    store.mark_sync_complete(
        conn,
        "user",
        7,
        run_token=run_marker,
        indexed_image_count=4,
        current_message="Finished indexing.",
    )
    store.mark_sync_error(
        conn,
        "user",
        7,
        run_token=run_marker,
        error_text="Worker dispatch failed.",
        indexed_image_count=2,
    )
    store.upsert_search_document(
        conn,
        image_row={
            "image_id": 17,
            "group_id": 5,
            "group_name": "Research",
            "group_can_read": True,
            "owner_id": 9,
            "owner_name": "alice",
            "image_name": "img-17",
            "dataset_id": 101,
            "dataset_name": "Dataset A",
            "project_id": 201,
            "project_name": "Project A",
            "schema_version": 3,
            "acquisition_date": datetime(2026, 4, 12, 8, 0, tzinfo=timezone.utc),
            "instrument_manufacturer": "Zeiss",
            "instrument_model": "LSM 980",
            "objective_model": "Plan-Apochromat",
            "objective_magnification": 63.0,
            "objective_na": 1.4,
            "detector_model": "Airyscan 2",
            "detector_binning": "2x2",
            "detector_gain": 1.5,
            "pixel_size_x_um": 0.108,
            "pixel_size_y_um": 0.108,
            "z_step_um": 0.4,
            "channel_summary": "GFP",
            "search_document": "Zeiss LSM 980 GFP",
        },
        channels=[
            {
                "channel_index": 0,
                "label": "GFP",
                "excitation_nm": 488.0,
                "emission_nm": 525.0,
            }
        ],
        attributes=[
            {
                "attribute_key": "laser_line_nm",
                "attribute_text": "488 nm",
                "attribute_numeric": 488.0,
            }
        ],
        scope_type="user",
        scope_id=7,
        run_token=run_marker,
    )

    executed_sql = [call["sql_text"] for call in cursor.executed]
    assert "indexed_image_count = %s" in executed_sql[0]
    assert "status = 'idle'" in executed_sql[1]
    assert "status = 'error'" in executed_sql[2]
    assert "INSERT INTO " in executed_sql[3]
    assert "acquisition_search_image" in executed_sql[3]
    assert "DELETE FROM " in executed_sql[4]
    assert "acquisition_search_channel" in executed_sql[4]
    assert "INSERT INTO " in executed_sql[5]
    assert "acquisition_search_channel" in executed_sql[5]
    assert "DELETE FROM " in executed_sql[6]
    assert "acquisition_search_attribute" in executed_sql[6]
    assert "INSERT INTO " in executed_sql[7]
    assert "acquisition_search_attribute" in executed_sql[7]
    assert "INSERT INTO " in executed_sql[8]
    assert "acquisition_search_scope_item" in executed_sql[8]
    assert conn.commits == 4


def test_user_settings_and_saved_query_writes_use_json_payloads(monkeypatch):
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    wrapped = []

    class _Extras:
        @staticmethod
        def Json(payload):
            wrapped.append(payload)
            return {"wrapped": payload}

    monkeypatch.setattr(store, "_load_psycopg2", lambda: (object(), _Extras()))
    monkeypatch.setattr(
        store,
        "load_user_settings",
        lambda conn, username, defaults=None: {**(defaults or {}), "loaded": True},
    )
    cursor = _RecordingCursor(fetchall_rows=[[()]])
    conn = _RecordingConn(cursor)

    saved_settings = store.save_user_settings(
        conn,
        "alice",
        {"acquisition_metadata_enabled": True},
    )
    store.save_saved_query(conn, "alice", "My query", {"query_text": "lsm"})

    def _delete_execute(sql, params=None):
        cursor.executed.append({"raw_sql": sql, "sql_text": str(sql), "params": params})
        cursor.rowcount = 1

    cursor.execute = _delete_execute
    deleted = store.delete_saved_query(conn, "alice", 3)

    assert wrapped == [
        {"acquisition_metadata_enabled": True},
        {"query_text": "lsm"},
    ]
    assert saved_settings == {
        "acquisition_metadata_enabled": True,
        "loaded": True,
    }
    assert deleted is True
