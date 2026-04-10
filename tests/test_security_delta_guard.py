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

TEST_GITHUB_CREDENTIAL = "-".join(("placeholder", "credential"))


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

    def fake_run(command: list[str], **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return security_delta_guard.subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='{"default_branch": "main"}',
            stderr="",
        )

    monkeypatch.setattr(security_delta_guard.subprocess, "run", fake_run)

    payload = security_delta_guard.github_api_get_json(
        "/repos/ZMB-UZH/omero-docker-extended",
        TEST_GITHUB_CREDENTIAL,
    )

    assert payload == {"default_branch": "main"}
    assert calls["command"] == [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--header",
        "Accept: application/vnd.github+json",
        "--header",
        f"Authorization: Bearer {TEST_GITHUB_CREDENTIAL}",
        "--header",
        "X-GitHub-Api-Version: 2022-11-28",
        "--header",
        "User-Agent: security-delta-guard",
        "https://api.github.com/repos/ZMB-UZH/omero-docker-extended",
    ]
    assert calls["kwargs"] == {
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": 30,
    }


def test_github_api_get_json_requires_absolute_api_path() -> None:
    with pytest.raises(ValueError, match="must start with '/'"):
        security_delta_guard.github_api_get_json(
            "repos/ZMB-UZH/omero-docker-extended", TEST_GITHUB_CREDENTIAL
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


def test_select_pull_request_delta_alerts_subtracts_base_branch_backlog() -> None:
    result = security_delta_guard.select_pull_request_delta_alerts(
        [
            _alert(7, created_at="2026-04-02T12:05:00Z"),
            _alert(8, created_at="2026-04-02T12:06:00Z"),
        ],
        [_alert(7, created_at="2026-04-01T09:00:00Z")],
    )

    assert [alert["number"] for alert in result] == [8]


def test_evaluate_push_alerts_fails_without_workflow_start_timestamp() -> None:
    result = security_delta_guard.evaluate_push_alerts(
        "refs/heads/main",
        None,
        lambda **kwargs: [],
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "fail"
    assert "start timestamp" in result.message


def test_evaluate_pull_request_alerts_fails_only_on_alerts_not_present_on_base_ref() -> (
    None
):
    result = security_delta_guard.evaluate_pull_request_alerts(
        17,
        lambda **kwargs: (
            [_alert(90, created_at="2026-04-01T09:00:00Z")]
            if kwargs.get("ref") == "refs/heads/main"
            else [
                _alert(90, created_at="2026-04-01T09:00:00Z"),
                _alert(91, created_at="2026-04-02T12:30:00Z"),
            ]
        ),
        base_ref="refs/heads/main",
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "fail"
    assert "Pull request #17 introduced code scanning alerts" in result.message
    assert "CodeQL/py/log-injection" in result.message


def test_evaluate_pull_request_alerts_passes_when_only_base_branch_alerts_remain() -> (
    None
):
    result = security_delta_guard.evaluate_pull_request_alerts(
        17,
        lambda **kwargs: [_alert(91, created_at="2026-04-02T12:30:00Z")],
        base_ref="refs/heads/main",
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "pass"
    assert "introduced no open code scanning alerts" in result.message


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


def test_get_workflow_run_started_at_prefers_run_started_at(monkeypatch) -> None:
    def fake_github_api_get_json(api_path: str, credential: str) -> dict:
        assert api_path == "/repos/ZMB-UZH/omero-docker-extended/actions/runs/1234"
        assert credential == TEST_GITHUB_CREDENTIAL
        return {
            "run_started_at": "2026-04-02T12:34:56Z",
            "created_at": "2026-04-02T12:30:00Z",
        }

    monkeypatch.setattr(
        security_delta_guard,
        "github_api_get_json",
        fake_github_api_get_json,
    )

    result = security_delta_guard.get_workflow_run_started_at(
        "ZMB-UZH/omero-docker-extended",
        TEST_GITHUB_CREDENTIAL,
        "1234",
    )

    assert result == datetime(2026, 4, 2, 12, 34, 56, tzinfo=UTC)


def test_evaluate_direct_event_pull_request_uses_payload_pr_number() -> None:
    calls = []

    def fetch_alerts(**kwargs):
        calls.append(kwargs)
        return [_alert(91, created_at="2026-04-02T12:30:00Z")]

    result = security_delta_guard.evaluate_direct_event(
        "pull_request",
        {"pull_request": {"number": 17, "base": {"ref": "main"}}},
        repository="ZMB-UZH/omero-docker-extended",
        ref="refs/pull/17/merge",
        run_id="123",
        fetch_alerts=fetch_alerts,
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "pass"
    assert calls == [{"pr": 17}, {"ref": "refs/heads/main"}]


def test_evaluate_direct_event_push_uses_run_start_resolver() -> None:
    calls = {"alerts": None, "run_started_at": None}

    def fetch_alerts(**kwargs):
        calls["alerts"] = kwargs
        return [_alert(44, created_at="2026-04-01T09:00:00Z")]

    def resolve_run_started_at(repository: str, run_id: str) -> datetime:
        calls["run_started_at"] = (repository, run_id)
        return datetime(2026, 4, 2, 12, 0, tzinfo=UTC)

    result = security_delta_guard.evaluate_direct_event(
        "push",
        {"repository": {"default_branch": "main"}, "ref": "refs/heads/main"},
        repository="ZMB-UZH/omero-docker-extended",
        ref="refs/heads/main",
        run_id="456",
        fetch_alerts=fetch_alerts,
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        resolve_run_started_at=resolve_run_started_at,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "pass"
    assert "Push scan created no new default-branch alerts" in result.message
    assert calls["alerts"] == {"ref": "refs/heads/main"}
    assert calls["run_started_at"] == ("ZMB-UZH/omero-docker-extended", "456")


def test_evaluate_direct_event_skips_non_default_branch_schedule() -> None:
    called = {"value": False}

    def fetch_alerts(**kwargs):
        called["value"] = True
        return []

    result = security_delta_guard.evaluate_direct_event(
        "schedule",
        {"repository": {"default_branch": "main"}},
        repository="ZMB-UZH/omero-docker-extended",
        ref="refs/heads/release-candidate",
        run_id="789",
        fetch_alerts=fetch_alerts,
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "skip"
    assert called["value"] is False


def test_evaluate_direct_event_fails_without_pull_request_number() -> None:
    result = security_delta_guard.evaluate_direct_event(
        "pull_request",
        {"pull_request": {}},
        repository="ZMB-UZH/omero-docker-extended",
        ref="refs/pull/17/merge",
        run_id="123",
        fetch_alerts=lambda **kwargs: [],
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "fail"
    assert "did not include a pull request number" in result.message


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


def test_evaluate_workflow_run_pull_request_subtracts_base_branch_alerts() -> None:
    calls = []

    def fetch_alerts(**kwargs):
        calls.append(kwargs)
        if kwargs.get("ref") == "refs/heads/main":
            return [_alert(44, created_at="2026-04-01T09:00:00Z")]
        return [
            _alert(44, created_at="2026-04-01T09:00:00Z"),
            _alert(45, created_at="2026-04-02T12:00:00Z"),
        ]

    result = security_delta_guard.evaluate_workflow_run(
        {
            "repository": {"default_branch": "main"},
            "workflow_run": {
                "conclusion": "success",
                "event": "pull_request",
                "pull_requests": [{"number": 19, "base": {"ref": "main"}}],
            },
        },
        fetch_alerts,
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result.status == "fail"
    assert calls == [{"pr": 19}, {"ref": "refs/heads/main"}]
    assert "#45" in result.message
