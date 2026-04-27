from __future__ import annotations

import requests

import pytest

from omeroweb_admin_tools import config as admin_config
from omeroweb_admin_tools.services import system_diagnostics
from omeroweb_admin_tools.services.system_diagnostics import (
    DatabaseRuntimeProfile,
    DiagnosticCheckResult,
)


def test_build_log_config_validates_environment_values(monkeypatch):
    monkeypatch.setattr(
        admin_config,
        "require_env",
        lambda name, env_file=None, hint=None: "https://loki:3100/",
    )
    monkeypatch.setattr(
        admin_config,
        "get_int_env",
        lambda name, env_file=None: {
            "ADMIN_TOOLS_LOG_LOOKBACK_SECONDS": 900,
            "ADMIN_TOOLS_LOG_MAX_ENTRIES": 250,
            "ADMIN_TOOLS_LOG_CACHE_MAX_MB": 128,
            "ADMIN_TOOLS_LOG_INTERNAL_FILE_BATCH_SIZE": 12,
            "ADMIN_TOOLS_LOG_MAX_PARALLEL_QUERIES": 4,
        }[name],
    )
    monkeypatch.setattr(
        admin_config,
        "get_float_env",
        lambda name, env_file=None: 4.5,
    )
    config = admin_config.build_log_config()

    assert config == admin_config.LogConfig(
        loki_url="https://loki:3100",
        lookback_seconds=900,
        max_entries=250,
        timeout_seconds=4.5,
        cache_max_bytes=128 * 1024 * 1024,
        internal_file_batch_size=12,
        max_parallel_queries=4,
    )

    monkeypatch.setattr(
        admin_config,
        "get_int_env",
        lambda name, env_file=None: (
            0
            if name == "ADMIN_TOOLS_LOG_INTERNAL_FILE_BATCH_SIZE"
            else {
                "ADMIN_TOOLS_LOG_LOOKBACK_SECONDS": 900,
                "ADMIN_TOOLS_LOG_MAX_ENTRIES": 250,
                "ADMIN_TOOLS_LOG_CACHE_MAX_MB": 128,
                "ADMIN_TOOLS_LOG_MAX_PARALLEL_QUERIES": 4,
            }[name]
        ),
    )
    assert admin_config.optional_log_config() is None

    monkeypatch.setattr(
        admin_config,
        "get_int_env",
        lambda name, env_file=None: (_ for _ in ()).throw(RuntimeError("missing env")),
    )
    assert admin_config.optional_log_config() is None


def _result(check_id: str, status: str) -> DiagnosticCheckResult:
    return DiagnosticCheckResult(
        check_id=check_id,
        label=check_id,
        status=status,
        duration_ms=1,
        summary=check_id,
        details="details",
    )


def test_system_diagnostics_edge_branches_cover_runtime_failures(monkeypatch):
    monkeypatch.delenv("EMPTY_PRIMARY", raising=False)
    monkeypatch.setenv("EMPTY_PRIMARY", " ")
    assert (
        system_diagnostics._first_present_env(("EMPTY_PRIMARY",), "fallback")
        == "fallback"
    )

    previous_psycopg2_mod = system_diagnostics._get_cached_psycopg2_module()
    try:
        system_diagnostics._set_cached_psycopg2_module(None)
        with pytest.raises(RuntimeError, match="psycopg2-binary"):
            system_diagnostics._load_psycopg2()
    finally:
        system_diagnostics._set_cached_psycopg2_module(previous_psycopg2_mod)

    calls = []

    def docker_api(path, timeout_seconds=4.0):
        calls.append(path)
        if path.startswith("/containers/json"):
            return True, [{}], ""
        return (
            True,
            {"State": {"Status": "running", "Health": {"Status": "healthy"}}},
            "",
        )

    monkeypatch.setattr(system_diagnostics, "_docker_api_json", docker_api)
    runtime, error = system_diagnostics._inspect_docker_service_runtime("omeroserver")
    assert runtime is None
    assert "container ID" in error

    monkeypatch.setattr(
        system_diagnostics,
        "_docker_api_json",
        lambda path, timeout_seconds=4.0: (
            (True, [], "") if path.startswith("/containers/json") else (True, {}, "")
        ),
    )
    runtime, error = system_diagnostics._inspect_docker_service_runtime("omeroserver")
    assert runtime is None
    assert "No container found" in error

    monkeypatch.setattr(
        system_diagnostics,
        "_docker_api_json",
        lambda path, timeout_seconds=4.0: (
            (True, ["bad-record"], "")
            if path.startswith("/containers/json")
            else (True, {}, "")
        ),
    )
    runtime, error = system_diagnostics._inspect_docker_service_runtime("omeroserver")
    assert runtime is None
    assert "no container records" in error

    monkeypatch.setattr(
        system_diagnostics,
        "_docker_api_json",
        lambda path, timeout_seconds=4.0: (
            (True, [{"Id": "abc", "Created": "bad", "Names": []}], "")
            if path.startswith("/containers/json")
            else (True, "not-a-dict", "")
        ),
    )
    runtime, error = system_diagnostics._inspect_docker_service_runtime("omeroserver")
    assert runtime is None
    assert "inspect payload was invalid" in error

    class _Connection:
        @staticmethod
        def cursor():
            class _Cursor:
                @staticmethod
                def execute(query):
                    return None

                @staticmethod
                def fetchone():
                    return None

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            return _Cursor()

        @staticmethod
        def close():
            raise RuntimeError("close failed")

    def _psycopg2_connection():
        return type(
            "Psycopg2",
            (),
            {"connect": staticmethod(lambda **kwargs: _Connection())},
        )()

    monkeypatch.setattr(
        system_diagnostics,
        "_load_psycopg2",
        _psycopg2_connection,
    )
    value, error = system_diagnostics._execute_sql_sanity_query(
        DatabaseRuntimeProfile("database", 5432, "omero", "secret", "omero")
    )
    assert value is None
    assert error == "SQL query returned no rows."

    monkeypatch.setattr(
        system_diagnostics.requests,
        "get",
        lambda url, timeout=1.0, allow_redirects=True: (_ for _ in ()).throw(
            requests.RequestException("offline")
        ),
    )
    http_result = system_diagnostics._http_probe(
        "http",
        "Probe HTTP",
        "https://omeroserver",
        1.0,
    )
    assert http_result.status == "fail"
    assert http_result.summary == "HTTP probe failed"

    monkeypatch.setattr(
        system_diagnostics,
        "_execute_sql_sanity_query",
        lambda profile: (None, "SQL query returned no rows."),
    )
    sql_result = system_diagnostics._direct_pg_test(
        "sql",
        "Run SQL",
        lambda: DatabaseRuntimeProfile("database", 5432, "omero", "secret", "omero"),
    )
    assert sql_result.status == "fail"
    assert sql_result.details == "SQL query returned no rows."

    monkeypatch.setattr(
        system_diagnostics,
        "_run_omero_server_core",
        lambda: [_result("omero", "pass"), _result("http", "warn")],
    )
    warn_payload = system_diagnostics.run_diagnostic_script("omero_server_core")
    assert warn_payload["status"] == "warn"
    assert warn_payload["summary"]["warn"] == 1

    monkeypatch.setattr(
        system_diagnostics,
        "_run_omero_server_core",
        lambda: [_result("omero", "pass"), _result("db", "fail")],
    )
    fail_payload = system_diagnostics.run_diagnostic_script("omero_server_core")
    assert fail_payload["status"] == "fail"
    assert fail_payload["summary"]["fail"] == 1
