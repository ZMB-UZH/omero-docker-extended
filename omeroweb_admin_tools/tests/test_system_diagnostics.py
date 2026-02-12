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
