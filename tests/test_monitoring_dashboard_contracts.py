from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = REPO_ROOT / "monitoring" / "grafana" / "dashboards"


def _dashboard(name: str) -> dict[str, Any]:
    """Handle dashboard."""
    return json.loads((DASHBOARD_DIR / name).read_text(encoding="utf-8"))


def _expressions(value: Any) -> list[str]:
    """Handle expressions."""
    if isinstance(value, dict):
        expressions = []
        if isinstance(value.get("expr"), str):
            expressions.append(value["expr"])
        for child in value.values():
            expressions.extend(_expressions(child))
        return expressions
    if isinstance(value, list):
        expressions = []
        for child in value:
            expressions.extend(_expressions(child))
        return expressions
    return []


def test_grafana_dashboards_are_valid_json() -> None:
    """Verify test grafana dashboards are valid JSON."""
    for dashboard_path in sorted(DASHBOARD_DIR.glob("*.json")):
        json.loads(dashboard_path.read_text(encoding="utf-8"))


def test_database_cache_hit_ratio_queries_guard_zero_denominators() -> None:
    """Verify test database cache hit ratio queries guard z behavior."""
    expressions = _expressions(_dashboard("database-metrics.json"))

    assert (
        'sum(pg_stat_database_blks_hit{datname="omero"}) / '
        'clamp_min(sum(pg_stat_database_blks_hit{datname="omero"}) + '
        'sum(pg_stat_database_blks_read{datname="omero"}), 1)'
    ) in expressions
    assert (
        'pg_stat_database_blks_hit{datname="omero"} / '
        'clamp_min(pg_stat_database_blks_hit{datname="omero"} + '
        'pg_stat_database_blks_read{datname="omero"}, 1)'
    ) in expressions


def test_plugin_database_cache_hit_ratio_queries_guard_zero_denominators() -> None:
    """Verify test plugin database cache hit ratio queries behavior."""
    expressions = _expressions(_dashboard("plugin-database-metrics.json"))

    assert (
        'sum(pg_stat_database_blks_hit{datname="omero-plugin"}) / '
        'clamp_min(sum(pg_stat_database_blks_hit{datname="omero-plugin"}) + '
        'sum(pg_stat_database_blks_read{datname="omero-plugin"}), 1)'
    ) in expressions
    assert (
        'pg_stat_database_blks_hit{datname="omero-plugin"} / '
        'clamp_min(pg_stat_database_blks_hit{datname="omero-plugin"} + '
        'pg_stat_database_blks_read{datname="omero-plugin"}, 1)'
    ) in expressions


def test_redis_dashboard_queries_do_not_emit_infinite_ratios() -> None:
    """Verify test redis dashboard queries do not emit infi behavior."""
    expressions = _expressions(_dashboard("redis-metrics.json"))

    assert (
        "(redis_memory_used_bytes / redis_memory_max_bytes) "
        "and on(instance) (redis_memory_max_bytes > 0)"
    ) in expressions
    assert (
        "rate(redis_keyspace_hits_total[5m]) / "
        "clamp_min(rate(redis_keyspace_hits_total[5m]) + "
        "rate(redis_keyspace_misses_total[5m]), 1)"
    ) in expressions
