from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = REPO_ROOT / "monitoring" / "grafana" / "dashboards"


def _dashboard(name: str) -> dict[str, Any]:
    """Return the dashboard.

    Inputs: `name` (str) name. Output: `dict[str, Any]`.
    """
    return json.loads((DASHBOARD_DIR / name).read_text(encoding="utf-8"))


def _expressions(value: Any) -> list[str]:
    """Return the expressions.

    Inputs: `value` (Any) input value. Output: `list[str]`.
    """
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
    """Verify grafana dashboards are valid JSON.

    Inputs: repository fixtures. Output: fails on regressions in grafana dashboards are valid JSON.
    """
    for dashboard_path in sorted(DASHBOARD_DIR.glob("*.json")):
        json.loads(dashboard_path.read_text(encoding="utf-8"))


def test_omeroweb_grafana_proxy_receives_backend_auth_configuration() -> None:
    """Verify OMERO.web receives both Grafana backend auth env files.

    Inputs: repository Compose configuration. Output: fails when a custom
    Grafana admin identity cannot be used by the authenticated proxy.
    """
    compose = yaml.safe_load(
        (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )
    env_files = compose["services"]["omeroweb"]["env_file"]

    assert "./env/grafana.env" in env_files
    assert "./env/omero_secrets.env" in env_files


def test_grafana_live_is_disabled_for_the_http_only_admin_tools_proxy() -> None:
    """Verify Grafana does not start unsupported browser WebSocket sessions.

    Inputs: repository Compose configuration. Output: fails when the HTTP-only
    Admin Tools proxy can emit recurring Grafana Live handshake failures.
    """
    compose = yaml.safe_load(
        (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )

    grafana_environment = compose["services"]["grafana"]["environment"]

    assert grafana_environment["GF_LIVE_MAX_CONNECTIONS"] == "0"


def test_database_cache_hit_ratio_queries_guard_zero_denominators() -> None:
    """Verify database cache hit ratio queries guard zero denominators.

    Inputs: repository fixtures. Output: fails on regressions in database cache hit ratio queries guard zero denominators.
    """
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
    """Verify plugin database cache hit ratio queries guard zero denominators.

    Inputs: repository fixtures. Output: fails on regressions in plugin database cache hit ratio queries guard zero denominators.
    """
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
    """Verify redis dashboard queries do not emit infinite ratios.

    Inputs: repository fixtures. Output: fails on regressions in redis dashboard queries do not emit infinite ratios.
    """
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
