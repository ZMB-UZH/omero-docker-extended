"""End-to-end CLI decisions with controlled GitHub API responses, never live mutations."""

import json
from datetime import datetime, UTC
import secrets
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

import pytest

from tools import security_delta_guard as guard


@pytest.mark.parametrize(
    "event,metadata,status,reason",
    [
        ("pull_request", {}, "fail", "pull request number"),
        ("push", {}, "fail", "missing default"),
        ("release", {}, "skip", "unsupported trigger"),
    ],
)
def test_workflow_event_without_scan_identity_cannot_claim_a_clean_result(
    event, metadata, status, reason
):
    """Inputs: incomplete or unrelated workflow metadata. Output: fail or explicit skip without alert access."""

    def unexpected(*_args, **_kwargs):
        """Inputs: forbidden alert request. Output: proof that no scope was guessed."""
        raise AssertionError("alert scope is unknown")

    result = guard.evaluate_workflow_run(
        {"workflow_run": {"conclusion": "success", "event": event, **metadata}},
        unexpected,
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
    )
    assert result.status == status
    assert reason in result.message


@pytest.mark.parametrize(
    "event,status,reason",
    [
        ("push", "fail", "missing default-branch"),
        ("release", "skip", "unsupported event"),
    ],
)
def test_direct_event_without_branch_scope_is_not_success(event, status, reason):
    """Inputs: incomplete or unrelated direct event. Output: no success and no guessed branch."""

    def unexpected(*_args, **_kwargs):
        """Inputs: forbidden alert request. Output: fail if an unknown scope reaches the API."""
        raise AssertionError("branch scope is unknown")

    result = guard.evaluate_direct_event(
        event,
        {},
        repository="example/project",
        ref="",
        run_id="7",
        fetch_alerts=unexpected,
        settle_timeout_seconds=0,
        poll_interval_seconds=0,
    )
    assert result.status == status
    assert reason in result.message


@pytest.mark.parametrize("value", [None, "", " \t "])
def test_absent_timestamp_is_never_invented(value):
    """Inputs: absent API time. Output: unknown rather than host time or epoch."""
    assert guard.parse_iso8601(value) is None


@pytest.mark.parametrize("value", ["2026-01-02T03:04:05Z", "2026-01-02T05:04:05+02:00"])
def test_timestamp_normalizes_explicit_offset(value):
    """Inputs: equivalent offset-aware times. Output: identical UTC cutoff across installations."""
    assert guard.parse_iso8601(value) == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_timestamp_without_offset_cannot_depend_on_host_timezone():
    """Inputs: ambiguous API timestamp. Output: fail closed instead of excluding alerts by host-local time."""
    with pytest.raises(ValueError, match="timezone"):
        guard.parse_iso8601("2026-01-02T03:04:05")


@pytest.mark.parametrize("run_id", ["", " ", "not-an-id"])
def test_workflow_timestamp_requires_numeric_identity_before_network(
    monkeypatch, run_id
):
    """Inputs: missing or malformed run ID. Output: no unconstrained API request."""

    def unexpected(*_args):
        """Inputs: forbidden request. Output: direct proof of pre-network validation."""
        raise AssertionError("invalid run ID reached network")

    monkeypatch.setattr(guard, "github_api_get_json", unexpected)
    with pytest.raises(RuntimeError, match="run ID"):
        guard.get_workflow_run_started_at("example/project", "fixture-auth", run_id)


@pytest.mark.parametrize("operation", ["branch", "timestamp"])
def test_repository_metadata_requires_object_payload(monkeypatch, operation):
    """Inputs: non-object native API reply. Output: operational failure, never an empty success."""
    monkeypatch.setattr(guard, "github_api_get_json", lambda *_args: [])
    with pytest.raises(RuntimeError, match="Unexpected GitHub API payload"):
        if operation == "branch":
            guard.get_default_branch("example/project", "fixture-auth")
        else:
            guard.get_workflow_run_started_at("example/project", "fixture-auth", "7")


def test_unknown_alert_metadata_remains_visible_in_bounded_diagnostics():
    """Inputs: missing repository/severity and many findings. Output: no inferred identity or hidden alert count."""
    assert guard.payload_repository_full_name({}) == ""
    assert guard.normalize_severity({}) == "unknown"
    assert guard.summarize_alerts([]) == "no open alerts"
    assert guard.select_push_delta_alerts([{}], None) == []
    alerts = [{"number": number} for number in range(12)]
    output = guard.render_failure_message("Unaccepted findings", alerts)
    assert (
        "12 alert(s)" in output
        and "unknown=12" in output
        and "... and 2 more" in output
    )


@pytest.mark.parametrize(
    "event,scenario,expected",
    [
        ("push", "baseline", 0),
        ("push", "new", 1),
        ("push", "wrong-baseline", 1),
        ("push", "invalid-baseline", 2),
        ("workflow_run", "baseline", 0),
        ("workflow_run", "new", 1),
        ("push", "api-failure", 2),
    ],
)
def test_cli_uses_complete_api_evidence_before_success(
    tmp_path, monkeypatch, capsys, event, scenario, expected
):
    """Inputs: recorded event/API shapes. Output: failure on new findings, drift or unavailable evidence."""
    payload = {"repository": {"full_name": "example/project"}, "ref": "refs/heads/main"}
    if event == "workflow_run":
        payload["workflow_run"] = {
            "conclusion": "success",
            "event": "push",
            "head_branch": "main",
            "created_at": "2026-10-01T00:00:00Z",
        }
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload))
    credential = secrets.token_urlsafe(24)
    alert = {
        "number": 1,
        "created_at": "2026-10-02T00:00:00Z"
        if scenario == "new"
        else "2026-09-30T00:00:00Z",
        "tool": {"name": "ExampleScanner"},
        "rule": {"id": "existing-rule", "severity": "warning"},
        "most_recent_instance": {"location": {"path": "example.py"}},
    }
    queries = []

    def api(api_path, token):
        """Inputs: scoped request. Output: fixture metadata, findings or an explicit API error."""
        queries.append(api_path)
        assert token == credential
        if scenario == "api-failure":
            raise RuntimeError("Upstream service unavailable")
        if api_path == "/repos/example/project":
            return {"default_branch": "main"}
        if api_path == "/repos/example/project/actions/runs/42":
            return {"run_started_at": "2026-10-01T00:00:00Z"}
        parsed = urlsplit(api_path)
        assert parsed.path == "/repos/example/project/code-scanning/alerts"
        query = parse_qs(parsed.query)
        assert query["ref"] == ["refs/heads/main"]
        assert query["state"] == ["open"]
        return [alert]

    baseline = {
        "wrong-baseline": "ExampleScanner/other-rule",
        "invalid-baseline": "invalid",
    }.get(scenario, "ExampleScanner/existing-rule")
    monkeypatch.setattr(guard, "github_api_get_json", api)
    monkeypatch.setenv("GUARD_TEST_TOKEN", credential)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "security_delta_guard.py",
            "--repository",
            "example/project",
            "--event-name",
            event,
            "--event-path",
            str(path),
            "--ref",
            "refs/heads/main",
            "--run-id",
            "42",
            "--token-env",
            "GUARD_TEST_TOKEN",
            "--settle-timeout-seconds",
            "0",
            "--poll-interval-seconds",
            "0",
            "--baseline-alert",
            baseline,
        ],
    )
    assert guard.main() == expected
    output = capsys.readouterr()
    assert credential not in output.out + output.err
    assert queries
    if expected:
        assert output.err
        assert not output.out
    else:
        assert "baseline matches exactly (1)" in output.out
        assert not output.err
    if scenario == "new":
        assert "#1" in output.err
    if scenario == "wrong-baseline":
        assert "unexpected ExampleScanner/existing-rule" in output.err
        assert "missing ExampleScanner/other-rule" in output.err


@pytest.mark.parametrize(
    "missing", ["event", "repository", "credential", "invalid-repository"]
)
def test_cli_rejects_missing_prerequisites_before_network(monkeypatch, capsys, missing):
    """Inputs: incomplete execution context. Output: controlled failure without API access."""
    for name in ("GITHUB_EVENT_PATH", "GITHUB_REPOSITORY", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    args = ["guard"]
    if missing != "event":
        args += ["--event-path", "event.json"]
    if missing != "repository":
        args += [
            "--repository",
            "../invalid" if missing == "invalid-repository" else "example/project",
        ]
    monkeypatch.setattr(sys, "argv", args)

    def deny(*args, **kwargs):
        """Inputs: any unexpected API access. Output: fail the test immediately."""
        pytest.fail("Invalid CLI input must fail before any API request")

    monkeypatch.setattr(guard, "github_api_get_json", deny)
    assert guard.main() == 2
    assert "ERROR:" in capsys.readouterr().err


@pytest.mark.parametrize("use_pr", [False, True])
def test_alert_inventory_reads_every_page_and_preserves_filter(monkeypatch, use_pr):
    """Inputs: more than one API page. Output: complete ordered inventory with encoded scope."""
    queries = []

    def api(path, token):
        """Inputs: paginated query. Output: a full first page and final partial page."""
        query = parse_qs(urlsplit(path).query)
        queries.append(query)
        return (
            [{"number": n} for n in range(100)]
            if query["page"] == ["1"]
            else [{"number": 100}]
        )

    monkeypatch.setattr(guard, "github_api_get_json", api)
    scope = {"pr": 7} if use_pr else {"ref": "refs/heads/release/stable"}
    alerts = guard.list_code_scanning_alerts(
        "example/project", "isolated-test-credential", **scope
    )
    assert [item["number"] for item in alerts] == list(range(101))
    assert len(queries) == 2
    assert all(
        query["pr" if use_pr else "ref"]
        == ["7" if use_pr else "refs/heads/release/stable"]
        for query in queries
    )


@pytest.mark.parametrize(
    "mode", ["absent-curl", "timeout", "os-error", "bad-json", "nonzero"]
)
def test_transport_failure_never_becomes_empty_success(monkeypatch, mode):
    """Inputs: unavailable or broken native transport. Output: explicit RuntimeError, never no findings."""
    monkeypatch.setattr(
        guard.shutil,
        "which",
        lambda _name: None if mode == "absent-curl" else "/usr/bin/curl",
    )

    def run(command, **kwargs):
        """Inputs: native command. Output: the selected failure at its actual transport boundary."""
        if mode == "timeout":
            raise subprocess.TimeoutExpired(command, 30)
        if mode == "os-error":
            raise OSError("transport unavailable")
        return subprocess.CompletedProcess(
            command, 22 if mode == "nonzero" else 0, stdout="upstream error", stderr=""
        )

    monkeypatch.setattr(guard.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="GitHub API request"):
        guard._github_api_get_json(
            "/repos/example/project", "isolated-test-credential", api_version=None
        )


@pytest.mark.parametrize("payload", [{}, [], [None]])
def test_invalid_api_version_inventory_fails_closed(monkeypatch, payload):
    """Inputs: absent or invalid API versions. Output: explicit failure rather than a guessed version."""
    monkeypatch.setattr(guard._GITHUB_API_VERSION_CACHE, "value", None)
    monkeypatch.setattr(guard, "_github_api_get_json", lambda *args, **kwargs: payload)
    with pytest.raises(RuntimeError, match="GitHub API versions"):
        guard.latest_github_api_version("isolated-test-credential")


def test_alert_inventory_rejects_non_list_api_response(monkeypatch):
    """Inputs: an API error object. Output: refusal instead of an empty successful inventory."""
    monkeypatch.setattr(
        guard, "github_api_get_json", lambda *args: {"message": "Unavailable"}
    )
    with pytest.raises(RuntimeError, match="Unexpected GitHub API payload"):
        guard.list_code_scanning_alerts("example/project", "isolated-test-credential")
