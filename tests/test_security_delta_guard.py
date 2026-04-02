from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "security_delta_guard.py"
SPEC = importlib.util.spec_from_file_location("security_delta_guard", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
security_delta_guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = security_delta_guard
SPEC.loader.exec_module(security_delta_guard)


def _alert(number: int, *, created_at: str, severity: str = "high") -> dict:
    return {
        "number": number,
        "created_at": created_at,
        "tool": {"name": "CodeQL"},
        "rule": {"id": "py/log-injection", "security_severity_level": severity},
        "most_recent_instance": {
            "location": {"path": "omeroweb_import/views/core_functions.py"}
        },
    }


def test_wait_for_stable_snapshot_rechecks_until_numbers_repeat() -> None:
    snapshots = iter(
        (
            [_alert(11, created_at="2026-04-02T12:00:00Z")],
            [_alert(11, created_at="2026-04-02T12:00:00Z")],
        )
    )
    calls = {"count": 0}

    def fetch_snapshot():
        calls["count"] += 1
        return next(snapshots)

    result = security_delta_guard.wait_for_stable_snapshot(
        fetch_snapshot,
        settle_timeout_seconds=30,
        poll_interval_seconds=0,
        monotonic=iter((0.0, 0.1)).__next__,
        sleep=lambda _seconds: None,
    )

    assert calls["count"] == 2
    assert [alert["number"] for alert in result] == [11]


def test_github_api_get_json_uses_https_connection(monkeypatch) -> None:
    calls = {}

    class FakeResponse:
        status = 200
        reason = "OK"
        headers = {"content-type": "application/json"}

        def read(self) -> bytes:
            return b'{"default_branch": "main"}'

    class FakeConnection:
        def __init__(self, host: str, *, timeout: int) -> None:
            calls["host"] = host
            calls["timeout"] = timeout

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            calls["method"] = method
            calls["path"] = path
            calls["headers"] = headers

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            calls["closed"] = True

    monkeypatch.setattr(security_delta_guard, "HTTPSConnection", FakeConnection)

    payload = security_delta_guard.github_api_get_json(
        "/repos/ZMB-UZH/omero-docker-extended",
        "example-token",
    )

    assert payload == {"default_branch": "main"}
    assert calls["host"] == "api.github.com"
    assert calls["timeout"] == 30
    assert calls["method"] == "GET"
    assert calls["path"] == "/repos/ZMB-UZH/omero-docker-extended"
    assert calls["headers"]["Authorization"] == "Bearer example-token"
    assert calls["closed"] is True


def test_github_api_get_json_requires_absolute_api_path() -> None:
    with pytest.raises(ValueError, match="must start with '/'"):
        security_delta_guard.github_api_get_json(
            "repos/ZMB-UZH/omero-docker-extended", "token"
        )


def test_select_push_delta_alerts_only_keeps_alerts_created_after_run_start() -> None:
    workflow_started_at = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)
    alerts = [
        _alert(1, created_at="2026-04-02T11:59:59Z"),
        _alert(2, created_at="2026-04-02T12:00:00Z"),
        _alert(3, created_at="2026-04-02T12:05:00Z", severity="medium"),
    ]

    result = security_delta_guard.select_push_delta_alerts(alerts, workflow_started_at)

    assert [alert["number"] for alert in result] == [2, 3]


def test_evaluate_pull_request_alerts_fails_on_any_open_alerts() -> None:
    result = security_delta_guard.evaluate_pull_request_alerts(
        17,
        lambda **kwargs: [_alert(91, created_at="2026-04-02T12:30:00Z")],
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "fail"
    assert "Pull request #17 introduced code scanning alerts" in result.message
    assert "CodeQL/py/log-injection" in result.message


def test_evaluate_push_alerts_passes_when_only_old_backlog_remains() -> None:
    result = security_delta_guard.evaluate_push_alerts(
        "refs/heads/main",
        datetime(2026, 4, 2, 12, 0, tzinfo=UTC),
        lambda **kwargs: [_alert(44, created_at="2026-04-01T09:00:00Z")],
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "pass"
    assert "No new default-branch alerts were created" in result.message


def test_evaluate_workflow_run_skips_non_default_branch_push() -> None:
    called = {"value": False}

    def fetch_alerts(**kwargs):
        called["value"] = True
        return []

    result = security_delta_guard.evaluate_workflow_run(
        {
            "workflow_run": {
                "conclusion": "success",
                "event": "push",
                "head_branch": "feature/security-fix",
                "repository": {"default_branch": "main"},
            }
        },
        fetch_alerts,
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "skip"
    assert called["value"] is False


def test_evaluate_workflow_run_uses_head_repository_default_branch_when_present() -> (
    None
):
    calls = {"count": 0, "kwargs": None}

    def fetch_alerts(**kwargs):
        calls["count"] += 1
        calls["kwargs"] = kwargs
        return []

    result = security_delta_guard.evaluate_workflow_run(
        {
            "workflow_run": {
                "conclusion": "success",
                "event": "push",
                "head_branch": "main",
                "head_repository": {"default_branch": "main"},
                "created_at": "2026-04-02T12:00:00Z",
            }
        },
        fetch_alerts,
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "pass"
    assert calls == {"count": 1, "kwargs": {"ref": "refs/heads/main"}}


def test_evaluate_workflow_run_resolves_default_branch_when_payload_omits_it() -> None:
    calls = {"count": 0, "kwargs": None}
    resolved = {"repository": None}

    def fetch_alerts(**kwargs):
        calls["count"] += 1
        calls["kwargs"] = kwargs
        return []

    def resolve_default_branch(repository: str) -> str:
        resolved["repository"] = repository
        return "main"

    result = security_delta_guard.evaluate_workflow_run(
        {
            "workflow_run": {
                "conclusion": "success",
                "event": "push",
                "head_branch": "main",
                "repository": {"full_name": "ZMB-UZH/omero-docker-extended"},
                "created_at": "2026-04-02T12:00:00Z",
            }
        },
        fetch_alerts,
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        resolve_default_branch=resolve_default_branch,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "pass"
    assert resolved == {"repository": "ZMB-UZH/omero-docker-extended"}
    assert calls == {"count": 1, "kwargs": {"ref": "refs/heads/main"}}


def test_evaluate_workflow_run_fails_when_upstream_security_scan_failed() -> None:
    result = security_delta_guard.evaluate_workflow_run(
        {
            "workflow_run": {
                "conclusion": "failure",
                "event": "pull_request",
                "pull_requests": [{"number": 19}],
            }
        },
        lambda **kwargs: [],
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "fail"
    assert "did not complete successfully" in result.message
