from __future__ import annotations

from omeroweb_admin_tools.services.system_diagnostics import run_diagnostic_script


def test_run_diagnostic_script_unknown_id() -> None:
    payload = run_diagnostic_script("not_a_script")

    assert payload["status"] == "fail"
    assert payload["checks"] == []
    assert "Unknown script_id" in payload["error"]


def test_run_diagnostic_script_end_to_end_contains_checks() -> None:
    payload = run_diagnostic_script("platform_end_to_end")

    assert payload["script_id"] == "platform_end_to_end"
    assert payload["summary"]["total"] >= 3
    assert isinstance(payload["checks"], list)


def test_run_diagnostic_script_optional_compose_skip_is_quiet(monkeypatch) -> None:
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.system_diagnostics._docker_compose_command",
        lambda: None,
    )
    monkeypatch.delenv("ADMIN_TOOLS_REQUIRE_DOCKER_COMPOSE", raising=False)

    payload = run_diagnostic_script("omero_server_core")

    compose_checks = [
        check
        for check in payload["checks"]
        if check["check_id"] == "omero_compose_state"
    ]
    assert len(compose_checks) == 1
    compose_check = compose_checks[0]
    assert compose_check["status"] == "warn"
    assert compose_check["summary"] == "Optional Docker compose check skipped"
    assert "Set ADMIN_TOOLS_REQUIRE_DOCKER_COMPOSE" not in compose_check["details"]


def test_run_diagnostic_script_required_compose_skip_is_actionable(monkeypatch) -> None:
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.system_diagnostics._docker_compose_command",
        lambda: None,
    )
    monkeypatch.setenv("ADMIN_TOOLS_REQUIRE_DOCKER_COMPOSE", "1")

    payload = run_diagnostic_script("omero_database")

    compose_checks = [
        check
        for check in payload["checks"]
        if check["check_id"] == "omero_database_compose_state"
    ]
    assert len(compose_checks) == 1
    compose_check = compose_checks[0]
    assert compose_check["status"] == "warn"
    assert compose_check["summary"] == "Docker compose command unavailable"
    assert "Set ADMIN_TOOLS_REQUIRE_DOCKER_COMPOSE=0" in compose_check["details"]


def test_run_diagnostic_script_optional_pg_skip_is_warning(monkeypatch) -> None:
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.system_diagnostics._docker_compose_command",
        lambda: None,
    )
    monkeypatch.delenv("ADMIN_TOOLS_REQUIRE_DOCKER_COMPOSE", raising=False)

    payload = run_diagnostic_script("omero_database")

    pg_checks = [
        check
        for check in payload["checks"]
        if check["check_id"] == "omero_database_sql"
    ]
    assert len(pg_checks) == 1
    pg_check = pg_checks[0]
    assert pg_check["status"] == "warn"
    assert pg_check["summary"] == "Optional Docker compose check skipped"
    assert "Set ADMIN_TOOLS_REQUIRE_DOCKER_COMPOSE" not in pg_check["details"]
