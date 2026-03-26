from __future__ import annotations

from omeroweb_admin_tools.services import system_diagnostics
from omeroweb_admin_tools.services.system_diagnostics import DiagnosticCheckResult
from omeroweb_admin_tools.services.system_diagnostics import DatabaseRuntimeProfile
from omeroweb_admin_tools.services.system_diagnostics import run_diagnostic_script
from omeroweb_admin_tools.services.system_diagnostics import serialize_scripts


def _result(check_id: str, label: str, status: str) -> DiagnosticCheckResult:
    return DiagnosticCheckResult(
        check_id=check_id,
        label=label,
        status=status,
        duration_ms=1,
        summary=f"{label} {status}",
        details="details",
    )


def test_serialize_scripts_exposes_operator_metadata() -> None:
    payload = serialize_scripts()

    assert any(item["script_id"] == "omero_database" for item in payload)
    assert all(item["label"] for item in payload)
    assert all(item["category"] for item in payload)


def test_run_diagnostic_script_unknown_id() -> None:
    payload = run_diagnostic_script("not_a_script")

    assert payload["status"] == "fail"
    assert payload["checks"] == []
    assert "Unknown script_id" in payload["error"]


def test_run_diagnostic_script_end_to_end_contains_checks(monkeypatch) -> None:
    monkeypatch.setattr(
        system_diagnostics,
        "_run_omero_server_core",
        lambda: [_result("omero", "OMERO", "pass")],
    )
    monkeypatch.setattr(
        system_diagnostics,
        "_run_database_checks",
        lambda *args, **kwargs: [_result(args[0], args[1], "pass")],
    )

    payload = run_diagnostic_script("platform_end_to_end")

    assert payload["script_id"] == "platform_end_to_end"
    assert payload["label"] == "Platform end-to-end bundle"
    assert payload["summary"]["total"] == 3
    assert isinstance(payload["checks"], list)


def test_compose_check_reports_docker_runtime_error(monkeypatch) -> None:
    monkeypatch.setattr(
        system_diagnostics,
        "_inspect_docker_service_runtime",
        lambda service: (
            None,
            "Permission denied accessing Docker socket at /var/run/docker.sock.",
        ),
    )

    result = system_diagnostics._compose_ps_health(
        "compose", "Inspect OMERO.server compose state", "omeroserver"
    )

    assert result.status == "fail"
    assert result.summary == "Docker runtime inspection failed"
    assert "Permission denied accessing Docker socket" in result.details


def test_compose_check_passes_with_running_healthy_container(monkeypatch) -> None:
    monkeypatch.setattr(
        system_diagnostics,
        "_inspect_docker_service_runtime",
        lambda service: (
            {
                "container_id": "abcdef123456",
                "container_name": "omeroserver",
                "state": "running",
                "health": "healthy",
            },
            "",
        ),
    )

    result = system_diagnostics._compose_ps_health(
        "compose", "Inspect OMERO.server compose state", "omeroserver"
    )

    assert result.status == "pass"
    assert result.summary == "Docker state: running, health: healthy"
    assert "container omeroserver" in result.details


def test_direct_pg_test_passes_with_select_one(monkeypatch) -> None:
    profile = DatabaseRuntimeProfile(
        host="database",
        port=5432,
        user="omero",
        password="secret",
        dbname="omero",
    )
    monkeypatch.setattr(
        system_diagnostics,
        "_execute_sql_sanity_query",
        lambda resolved: (1, ""),
    )

    result = system_diagnostics._direct_pg_test(
        "sql", "Run direct SQL sanity test (OMERO database)", lambda: profile
    )

    assert result.status == "pass"
    assert result.summary == "Direct SQL check completed"
    assert "SELECT 1 returned 1" in result.details


def test_direct_pg_test_fails_when_password_missing() -> None:
    profile = DatabaseRuntimeProfile(
        host="database",
        port=5432,
        user="omero",
        password="",
        dbname="omero",
    )

    result = system_diagnostics._direct_pg_test(
        "sql", "Run direct SQL sanity test (OMERO database)", lambda: profile
    )

    assert result.status == "fail"
    assert result.summary == "Direct SQL sanity test failed"
    assert "Missing PostgreSQL password" in result.details


def test_run_diagnostic_script_includes_script_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        system_diagnostics,
        "_run_omero_server_core",
        lambda: [_result("omero_host_dns", "Resolve OMERO.server hostname", "pass")],
    )

    payload = run_diagnostic_script("omero_server_core")

    assert payload["status"] == "pass"
    assert payload["label"] == "OMERO.server core connectivity"
    assert payload["category"] == "OMERO.server"
    assert payload["checks"][0]["label"] == "Resolve OMERO.server hostname"


def test_run_diagnostic_script_hides_internal_exception_text(monkeypatch) -> None:
    monkeypatch.setattr(
        system_diagnostics,
        "_run_omero_server_core",
        lambda: (_ for _ in ()).throw(RuntimeError("sensitive backend details")),
    )

    payload = run_diagnostic_script("omero_server_core")

    assert payload["status"] == "fail"
    assert payload["checks"] == []
    assert (
        payload["error"] == "Failed to execute check due to an internal server error."
    )
