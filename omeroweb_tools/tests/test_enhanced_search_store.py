from __future__ import annotations

from datetime import datetime, timezone

from omeroweb_tools.services import enhanced_search_store as store


class _Cursor:
    def __init__(self):
        self.executed = []
        self._fetchone_calls = 0

    def execute(self, sql, params=None):
        self.executed.append((str(sql), params))

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


class _Conn:
    def __init__(self):
        self.cursor_obj = _Cursor()

    def cursor(self):
        return self.cursor_obj


def test_search_index_rows_short_circuits_for_no_visible_groups(monkeypatch):
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)

    rows, total = store.search_index_rows(
        object(),
        visible_group_ids=[],
        current_user_id=9,
        scope_filter=None,
        query_text="lsm",
        filters={},
        limit=25,
        offset=0,
    )

    assert rows == []
    assert total == 0


def test_search_index_rows_builds_permission_and_filter_aware_sql(monkeypatch):
    monkeypatch.setattr(store, "ensure_schema", lambda conn: None)
    conn = _Conn()

    rows, total = store.search_index_rows(
        conn,
        visible_group_ids=[5, 7],
        current_user_id=21,
        scope_filter=("project", 201),
        query_text="lsm zeiss",
        filters={
            "instrument_model": "980",
            "objective_magnification_min": 40,
            "objective_magnification_max": 100,
            "acquisition_date_from": datetime(2026, 4, 1, tzinfo=timezone.utc),
            "channel_label": "GFP",
            "channel_excitation_nm_min": 480,
        },
        limit=25,
        offset=25,
    )

    assert total == 3
    assert rows[0]["image_id"] == 17

    count_sql, count_params = conn.cursor_obj.executed[0]
    rows_sql, rows_params = conn.cursor_obj.executed[1]

    assert "images.group_id = ANY(%s)" in count_sql
    assert "(images.group_can_read = TRUE OR images.owner_id = %s)" in count_sql
    assert "scope_items.scope_type = %s AND scope_items.scope_id = %s" in count_sql
    assert "plainto_tsquery('simple', %s)" in count_sql
    assert "images.instrument_model ILIKE %s" in count_sql
    assert "channels.label ILIKE %s" in count_sql
    assert "channels.excitation_nm >= %s" in count_sql
    assert "LIMIT %s OFFSET %s" in rows_sql

    assert count_params[0] == [5, 7]
    assert count_params[1] == 21
    assert rows_params[-2:] == [25, 25]
