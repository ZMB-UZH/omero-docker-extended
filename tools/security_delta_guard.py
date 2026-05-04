#!/usr/bin/env python3
"""Fail CI when a workflow run introduces new GitHub code scanning alerts."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode


AlertFetcher = Callable[..., list[dict[str, Any]]]
SleepFn = Callable[[float], None]
ClockFn = Callable[[], float]
DefaultBranchResolver = Callable[[str], str | None]
RunStartResolver = Callable[[str, str], datetime | None]
REPOSITORY_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class EvaluationResult:
    """Represent evaluation result."""

    status: str
    message: str
    alerts: tuple[dict[str, Any], ...] = ()


def parse_args() -> argparse.Namespace:
    """Parse args.

    Inputs: none. Output: `argparse.Namespace`.
    """
    parser = argparse.ArgumentParser(
        description="Block workflow runs that add new GitHub code scanning alerts."
    )
    parser.add_argument(
        "--event-name",
        default=os.environ.get("GITHUB_EVENT_NAME", ""),
        help="GitHub Actions event name.",
    )
    parser.add_argument(
        "--event-path",
        default=os.environ.get("GITHUB_EVENT_PATH", ""),
        help="Path to the GitHub Actions event payload JSON.",
    )
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="Repository in OWNER/REPO format.",
    )
    parser.add_argument(
        "--ref",
        default=os.environ.get("GITHUB_REF", ""),
        help="Git ref for the current workflow run.",
    )
    parser.add_argument(
        "--run-id",
        default=os.environ.get("GITHUB_RUN_ID", ""),
        help="GitHub Actions run identifier for the current workflow run.",
    )
    parser.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="Environment variable that stores the GitHub token.",
    )
    parser.add_argument(
        "--settle-timeout-seconds",
        type=int,
        default=180,
        help="Maximum time to wait for alerts to settle after SARIF upload.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=10,
        help="Poll interval while waiting for the alert snapshot to stabilize.",
    )
    return parser.parse_args()


def parse_iso8601(timestamp: str | None) -> datetime | None:
    """Parse iso8601.

    Inputs: `timestamp`. Output: `datetime | None`.
    """
    if not timestamp:
        return None
    normalized = timestamp.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized).astimezone(UTC)


def _first_non_empty(*values: Any) -> str:
    """First non empty.

    Inputs: `*values`. Output: `str`.
    """
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def validate_repository_component(value: str) -> bool:
    """Return True when a repository path component is safe for API paths.

    Inputs: `value`. Output: `bool`.
    """
    return (
        bool(value)
        and value not in {".", ".."}
        and REPOSITORY_COMPONENT_RE.fullmatch(value) is not None
    )


def validate_github_repository(repository: str) -> str:
    """Return a validated GitHub OWNER/REPO identifier.

    Inputs: `repository`. Output: `str`. Raises on invalid or unavailable state.
    """
    parts = repository.split("/")
    if (
        len(parts) != 2
        or not validate_repository_component(parts[0])
        or not validate_repository_component(parts[1])
    ):
        raise ValueError(
            "GitHub repository must use OWNER/REPO format with safe path components"
        )
    return f"{parts[0]}/{parts[1]}"


def payload_repository_full_name(event_payload: dict[str, Any]) -> str:
    """Payload repository full name.

    Inputs: `event_payload`. Output: `str`.
    """
    workflow_run = event_payload.get("workflow_run") or {}
    for candidate in (
        workflow_run.get("head_repository"),
        workflow_run.get("repository"),
        event_payload.get("repository"),
    ):
        if isinstance(candidate, dict):
            full_name = _first_non_empty(candidate.get("full_name"))
            if full_name:
                return full_name
    return ""


def payload_default_branch(event_payload: dict[str, Any]) -> str:
    """Payload default branch.

    Inputs: `event_payload`. Output: `str`.
    """
    workflow_run = event_payload.get("workflow_run") or {}
    for candidate in (
        workflow_run.get("repository"),
        workflow_run.get("head_repository"),
        event_payload.get("repository"),
    ):
        if isinstance(candidate, dict):
            default_branch = _first_non_empty(candidate.get("default_branch"))
            if default_branch:
                return default_branch
    return ""


def payload_pull_request_number(event_payload: dict[str, Any]) -> int | None:
    """Payload pull request number.

    Inputs: `event_payload`. Output: `int | None`.
    """
    pull_request = event_payload.get("pull_request") or {}
    if isinstance(pull_request, dict) and pull_request.get("number") is not None:
        return int(pull_request["number"])
    return None


def payload_ref(event_payload: dict[str, Any]) -> str:
    """Payload ref.

    Inputs: `event_payload`. Output: `str`.
    """
    return _first_non_empty(event_payload.get("ref"))


def normalize_severity(alert: dict[str, Any]) -> str:
    """Normalize severity.

    Inputs: `alert`. Output: `str`.
    """
    rule = alert.get("rule") or {}
    for candidate in (
        alert.get("severity"),
        rule.get("security_severity_level"),
        rule.get("severity"),
    ):
        if candidate:
            return str(candidate).strip().lower()
    return "unknown"


def summarize_alerts(alerts: list[dict[str, Any]]) -> str:
    """Summarize alerts.

    Inputs: `alerts`. Output: `str`.
    """
    counts = Counter(normalize_severity(alert) for alert in alerts)
    if not counts:
        return "no open alerts"
    ordered = [
        severity
        for severity in ("critical", "high", "medium", "warning", "low", "error")
        if severity in counts
    ]
    ordered.extend(
        severity for severity in sorted(counts) if severity not in set(ordered)
    )
    return ", ".join(f"{severity}={counts[severity]}" for severity in ordered)


def alert_path(alert: dict[str, Any]) -> str:
    """Alert path.

    Inputs: `alert`. Output: `str`.
    """
    instance = alert.get("most_recent_instance") or {}
    location = instance.get("location") or {}
    return str(location.get("path") or "").strip() or "<unknown>"


def alert_rule(alert: dict[str, Any]) -> str:
    """Alert rule.

    Inputs: `alert`. Output: `str`.
    """
    rule = alert.get("rule") or {}
    return str(rule.get("id") or rule.get("name") or "<unknown>").strip()


def alert_tool(alert: dict[str, Any]) -> str:
    """Alert tool.

    Inputs: `alert`. Output: `str`.
    """
    tool = alert.get("tool") or {}
    return str(tool.get("name") or "<unknown>").strip()


def format_alert(alert: dict[str, Any]) -> str:
    """Format alert.

    Inputs: `alert`. Output: `str`.
    """
    return (
        f"#{alert.get('number', '?')} "
        f"[{normalize_severity(alert)}] "
        f"{alert_tool(alert)}/{alert_rule(alert)} "
        f"{alert_path(alert)}"
    )


def render_failure_message(prefix: str, alerts: list[dict[str, Any]]) -> str:
    """Render failure message.

    Inputs: `prefix`, `alerts`. Output: `str`.
    """
    details = "\n".join(f"- {format_alert(alert)}" for alert in alerts[:10])
    truncated = ""
    if len(alerts) > 10:
        truncated = f"\n- ... and {len(alerts) - 10} more"
    return (
        f"{prefix}: {len(alerts)} alert(s) ({summarize_alerts(alerts)})\n"
        f"{details}{truncated}"
    )


def wait_for_stable_snapshot(
    fetch_snapshot: Callable[[], list[dict[str, Any]]],
    *,
    settle_timeout_seconds: int,
    poll_interval_seconds: int,
    monotonic: ClockFn = time.monotonic,
    sleep: SleepFn = time.sleep,
) -> list[dict[str, Any]]:
    """Wait for stable snapshot.

    Inputs: `fetch_snapshot`, `settle_timeout_seconds`, `poll_interval_seconds`,
    `monotonic`, `sleep`. Output: `list[dict[str, Any]]`.
    """
    deadline = monotonic() + max(settle_timeout_seconds, 0)
    previous_numbers: tuple[int, ...] | None = None
    while True:
        snapshot = fetch_snapshot()
        numbers = tuple(sorted(int(alert.get("number", 0)) for alert in snapshot))
        if previous_numbers == numbers:
            return snapshot
        if monotonic() >= deadline:
            return snapshot
        previous_numbers = numbers
        sleep(max(poll_interval_seconds, 0))


def select_push_delta_alerts(
    alerts: list[dict[str, Any]], workflow_started_at: datetime | None
) -> list[dict[str, Any]]:
    """Select push delta alerts.

    Inputs: `alerts`, `workflow_started_at`. Output: `list[dict[str, Any]]`.
    """
    if workflow_started_at is None:
        return []
    delta_alerts = []
    for alert in alerts:
        created_at = parse_iso8601(alert.get("created_at"))
        if created_at is not None and created_at >= workflow_started_at:
            delta_alerts.append(alert)
    return delta_alerts


def select_pull_request_delta_alerts(
    pull_request_alerts: list[dict[str, Any]],
    base_branch_alerts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only alerts that are absent from the base branch snapshot.

    Inputs: `pull_request_alerts`, `base_branch_alerts`. Output: `list[dict[str, Any]]`.
    """
    base_numbers = {int(alert.get("number", 0)) for alert in base_branch_alerts}
    return [
        alert
        for alert in pull_request_alerts
        if int(alert.get("number", 0)) not in base_numbers
    ]


def evaluate_default_branch_alerts(
    ref: str,
    workflow_started_at: datetime | None,
    fetch_alerts: AlertFetcher,
    *,
    failure_prefix: str,
    success_prefix: str,
    settle_timeout_seconds: int,
    poll_interval_seconds: int,
    monotonic: ClockFn = time.monotonic,
    sleep: SleepFn = time.sleep,
) -> EvaluationResult:
    """Evaluate default branch alerts.

    Inputs: `ref`, `workflow_started_at`, `fetch_alerts`, `failure_prefix`,
    `success_prefix`, `settle_timeout_seconds`, `poll_interval_seconds`, `monotonic`,
    `sleep`. Output: `EvaluationResult`.
    """
    if workflow_started_at is None:
        return EvaluationResult(
            status="fail",
            message=(
                f"{failure_prefix} could not be evaluated because the workflow "
                f"start timestamp for {ref} was unavailable."
            ),
        )

    alerts = wait_for_stable_snapshot(
        lambda: fetch_alerts(ref=ref),
        settle_timeout_seconds=settle_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        monotonic=monotonic,
        sleep=sleep,
    )
    delta_alerts = select_push_delta_alerts(alerts, workflow_started_at)
    if delta_alerts:
        return EvaluationResult(
            status="fail",
            message=render_failure_message(failure_prefix, delta_alerts),
            alerts=tuple(delta_alerts),
        )
    return EvaluationResult(
        status="pass",
        message=(
            f"{success_prefix} ({len(alerts)} open total on the branch snapshot)."
        ),
    )


def evaluate_pull_request_alerts(
    pr_number: int,
    fetch_alerts: AlertFetcher,
    *,
    base_ref: str | None = None,
    settle_timeout_seconds: int,
    poll_interval_seconds: int,
    monotonic: ClockFn = time.monotonic,
    sleep: SleepFn = time.sleep,
) -> EvaluationResult:
    """Evaluate pull request alerts.

    Inputs: `pr_number`, `fetch_alerts`, `base_ref`, `settle_timeout_seconds`,
    `poll_interval_seconds`, `monotonic`, `sleep`. Output: `EvaluationResult`.
    """
    alerts = wait_for_stable_snapshot(
        lambda: fetch_alerts(pr=pr_number),
        settle_timeout_seconds=settle_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        monotonic=monotonic,
        sleep=sleep,
    )
    if base_ref:
        base_branch_alerts = wait_for_stable_snapshot(
            lambda: fetch_alerts(ref=base_ref),
            settle_timeout_seconds=settle_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            monotonic=monotonic,
            sleep=sleep,
        )
        alerts = select_pull_request_delta_alerts(alerts, base_branch_alerts)
    if alerts:
        return EvaluationResult(
            status="fail",
            message=render_failure_message(
                f"Pull request #{pr_number} introduced code scanning alerts",
                alerts,
            ),
            alerts=tuple(alerts),
        )
    return EvaluationResult(
        status="pass",
        message=f"Pull request #{pr_number} introduced no open code scanning alerts.",
    )


def evaluate_push_alerts(
    ref: str,
    workflow_started_at: datetime | None,
    fetch_alerts: AlertFetcher,
    *,
    settle_timeout_seconds: int,
    poll_interval_seconds: int,
    monotonic: ClockFn = time.monotonic,
    sleep: SleepFn = time.sleep,
) -> EvaluationResult:
    """Evaluate push alerts.

    Inputs: `ref`, `workflow_started_at`, `fetch_alerts`, `settle_timeout_seconds`,
    `poll_interval_seconds`, `monotonic`, `sleep`. Output: `EvaluationResult`.
    """
    return evaluate_default_branch_alerts(
        ref,
        workflow_started_at,
        fetch_alerts,
        failure_prefix=f"Push scan created new default-branch alerts on {ref}",
        success_prefix=f"No new default-branch alerts were created on {ref}",
        settle_timeout_seconds=settle_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        monotonic=monotonic,
        sleep=sleep,
    )


def evaluate_workflow_run(
    event_payload: dict[str, Any],
    fetch_alerts: AlertFetcher,
    *,
    settle_timeout_seconds: int,
    poll_interval_seconds: int,
    resolve_default_branch: DefaultBranchResolver | None = None,
    monotonic: ClockFn = time.monotonic,
    sleep: SleepFn = time.sleep,
) -> EvaluationResult:
    """Evaluate workflow run.

    Inputs: `event_payload`, `fetch_alerts`, `settle_timeout_seconds`,
    `poll_interval_seconds`, `resolve_default_branch`, `monotonic`, `sleep`. Output:
    `EvaluationResult`.
    """
    workflow_run = event_payload.get("workflow_run") or {}
    conclusion = str(workflow_run.get("conclusion") or "").strip().lower()
    if conclusion != "success":
        return EvaluationResult(
            status="fail",
            message=(
                "security-code-scanning did not complete successfully; "
                "the zero-delta alert gate cannot trust the results."
            ),
        )

    trigger_event = str(workflow_run.get("event") or "").strip().lower()
    if trigger_event == "pull_request":
        pull_requests = workflow_run.get("pull_requests") or []
        if not pull_requests:
            return EvaluationResult(
                status="fail",
                message=(
                    "security-code-scanning ran for a pull request, but the "
                    "workflow_run payload did not include a pull request number."
                ),
            )
        pr_number = int(pull_requests[0]["number"])
        base_ref = _first_non_empty(
            pull_requests[0].get("base", {}).get("ref"),
            payload_default_branch(event_payload),
        )
        return evaluate_pull_request_alerts(
            pr_number,
            fetch_alerts,
            base_ref=f"refs/heads/{base_ref}" if base_ref else None,
            settle_timeout_seconds=settle_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            monotonic=monotonic,
            sleep=sleep,
        )

    if trigger_event == "push":
        default_branch = payload_default_branch(event_payload)
        head_branch = _first_non_empty(workflow_run.get("head_branch"))
        if not default_branch and resolve_default_branch is not None:
            repository_full_name = payload_repository_full_name(event_payload)
            if repository_full_name:
                default_branch = _first_non_empty(
                    resolve_default_branch(repository_full_name)
                )
        if not default_branch or not head_branch:
            return EvaluationResult(
                status="fail",
                message=(
                    "security-code-scanning push payload is missing default "
                    "or head branch information."
                ),
            )
        if head_branch != default_branch:
            return EvaluationResult(
                status="skip",
                message=(
                    f"Skipping push delta check for non-default branch {head_branch!r}."
                ),
            )
        workflow_started_at = parse_iso8601(
            str(
                workflow_run.get("created_at")
                or workflow_run.get("run_started_at")
                or ""
            )
        )
        return evaluate_push_alerts(
            f"refs/heads/{head_branch}",
            workflow_started_at,
            fetch_alerts,
            settle_timeout_seconds=settle_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            monotonic=monotonic,
            sleep=sleep,
        )

    return EvaluationResult(
        status="skip",
        message=(
            "Skipping zero-delta code-scanning gate for unsupported trigger "
            f"event {trigger_event!r}."
        ),
    )


def event_scan_label(event_name: str) -> str:
    """Event scan label.

    Inputs: `event_name`. Output: `str`.
    """
    normalized_event = str(event_name or "").strip().lower()
    labels = {
        "push": "Push scan",
        "schedule": "Scheduled scan",
        "workflow_dispatch": "Manual scan",
    }
    return labels.get(normalized_event, "Security scan")


def evaluate_direct_event(
    event_name: str,
    event_payload: dict[str, Any],
    *,
    repository: str,
    ref: str,
    run_id: str,
    fetch_alerts: AlertFetcher,
    settle_timeout_seconds: int,
    poll_interval_seconds: int,
    resolve_default_branch: DefaultBranchResolver | None = None,
    resolve_run_started_at: RunStartResolver | None = None,
    monotonic: ClockFn = time.monotonic,
    sleep: SleepFn = time.sleep,
) -> EvaluationResult:
    """Evaluate direct event.

    Inputs: `event_name`, `event_payload`, `repository`, `ref`, `run_id`,
    `fetch_alerts`, `settle_timeout_seconds`, `poll_interval_seconds`,
    `resolve_default_branch`, `resolve_run_started_at`, `monotonic`, `sleep`. Output:
    `EvaluationResult`.
    """
    normalized_event = _first_non_empty(event_name).lower()
    if normalized_event == "pull_request":
        pr_number = payload_pull_request_number(event_payload)
        if pr_number is None:
            return EvaluationResult(
                status="fail",
                message=(
                    "security-code-scanning pull_request payload did not include "
                    "a pull request number."
                ),
            )
        base_ref = _first_non_empty(
            (event_payload.get("pull_request") or {}).get("base", {}).get("ref"),
            payload_default_branch(event_payload),
        )
        return evaluate_pull_request_alerts(
            pr_number,
            fetch_alerts,
            base_ref=f"refs/heads/{base_ref}" if base_ref else None,
            settle_timeout_seconds=settle_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            monotonic=monotonic,
            sleep=sleep,
        )

    if normalized_event in {"push", "schedule", "workflow_dispatch"}:
        default_branch = payload_default_branch(event_payload)
        if not default_branch and resolve_default_branch is not None:
            default_branch = _first_non_empty(resolve_default_branch(repository))

        current_ref = _first_non_empty(ref, payload_ref(event_payload))
        if not default_branch or not current_ref:
            return EvaluationResult(
                status="fail",
                message=(
                    "security-code-scanning is missing default-branch or ref "
                    "information for the current run."
                ),
            )

        default_ref = f"refs/heads/{default_branch}"
        if current_ref != default_ref:
            return EvaluationResult(
                status="skip",
                message=(
                    "Skipping zero-delta code-scanning gate for non-default "
                    f"branch ref {current_ref!r}."
                ),
            )

        workflow_started_at = None
        if resolve_run_started_at is not None:
            workflow_started_at = resolve_run_started_at(repository, run_id)

        scan_label = event_scan_label(normalized_event)
        return evaluate_default_branch_alerts(
            current_ref,
            workflow_started_at,
            fetch_alerts,
            failure_prefix=(
                f"{scan_label} created new default-branch alerts on {current_ref}"
            ),
            success_prefix=(
                f"{scan_label} created no new default-branch alerts on {current_ref}"
            ),
            settle_timeout_seconds=settle_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            monotonic=monotonic,
            sleep=sleep,
        )

    return EvaluationResult(
        status="skip",
        message=(
            "Skipping zero-delta code-scanning gate for unsupported event "
            f"{normalized_event!r}."
        ),
    )


def list_code_scanning_alerts(
    repository: str,
    token: str,
    *,
    ref: str | None = None,
    pr: int | None = None,
) -> list[dict[str, Any]]:
    """Return list code scanning alerts.

    Inputs: `repository`, `token`, `ref`, `pr`. Output: `list[dict[str, Any]]`. Raises
    on invalid or unavailable state.
    """
    repository = validate_github_repository(repository)
    query = {
        "state": "open",
        "sort": "created",
        "direction": "desc",
        "per_page": 100,
    }
    if ref:
        query["ref"] = ref
    if pr is not None:
        query["pr"] = int(pr)

    alerts: list[dict[str, Any]] = []
    page = 1
    while True:
        page_query = dict(query)
        page_query["page"] = page
        api_path = f"/repos/{repository}/code-scanning/alerts?{urlencode(page_query)}"
        batch = github_api_get_json(api_path, token)
        if not isinstance(batch, list):
            raise RuntimeError(f"Unexpected GitHub API payload type: {type(batch)!r}")
        alerts.extend(batch)
        if len(batch) < 100:
            return alerts
        page += 1


@dataclass
class _GitHubApiVersionCache:
    """Represent git hub API version cache."""

    value: str | None = None


_GITHUB_API_VERSION_CACHE = _GitHubApiVersionCache()


def latest_github_api_version(token: str) -> str:
    """Latest github API version.

    Inputs: `token`. Output: `str`. Raises on invalid or unavailable state.
    """
    if _GITHUB_API_VERSION_CACHE.value is not None:
        return _GITHUB_API_VERSION_CACHE.value

    versions = _github_api_get_json("/versions", token, api_version=None)
    if not isinstance(versions, list) or not versions:
        raise RuntimeError(
            "GitHub API versions request returned no supported versions."
        )
    if not all(isinstance(version, str) for version in versions):
        raise RuntimeError("GitHub API versions request returned an invalid payload.")
    _GITHUB_API_VERSION_CACHE.value = max(versions)
    return _GITHUB_API_VERSION_CACHE.value


def github_api_get_json(api_path: str, token: str) -> Any:
    """Github API get JSON.

    Inputs: `api_path`, `token`. Output: `Any`.
    """
    api_version = latest_github_api_version(token)
    return _github_api_get_json(api_path, token, api_version=api_version)


def _github_api_get_json(api_path: str, token: str, *, api_version: str | None) -> Any:
    """Github API get JSON.

    Inputs: `api_path`, `token`, `api_version`. Output: `Any`. Raises on invalid or
    unavailable state.

    unavailable state.
    """
    if not api_path.startswith("/"):
        raise ValueError(f"GitHub API path must start with '/': {api_path!r}")

    curl_bin = shutil.which("curl")
    if curl_bin is None:
        raise RuntimeError(
            "GitHub API request failed: required executable 'curl' is not available."
        )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "security-delta-guard",
    }
    if api_version is not None:
        headers["X-GitHub-Api-Version"] = api_version
    config_lines = [f"url = {_curl_config_quote(f'https://api.github.com{api_path}')}"]
    for name, value in headers.items():
        config_lines.append(f"header = {_curl_config_quote(f'{name}: {value}')}")
    try:
        result = subprocess.run(
            [
                curl_bin,
                "--silent",
                "--show-error",
                "--location",
                "--fail-with-body",
                "--config",
                "-",
            ],
            check=False,
            capture_output=True,
            input="\n".join(config_lines) + "\n",
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"GitHub API request failed: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"GitHub API request failed: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub API request returned invalid JSON.") from exc


def _curl_config_quote(value: str) -> str:
    """Curl config quote.

    Inputs: `value`. Output: `str`.
    """
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def get_default_branch(repository: str, token: str) -> str | None:
    """Return default branch.

    Inputs: `repository`, `token`. Output: `str | None`. Raises on invalid or
    unavailable state.
    """
    repository = validate_github_repository(repository)
    payload = github_api_get_json(f"/repos/{repository}", token)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected GitHub API payload type: {type(payload)!r}")
    return _first_non_empty(payload.get("default_branch")) or None


def get_workflow_run_started_at(
    repository: str, token: str, run_id: str
) -> datetime | None:
    """Return workflow run started at.

    Inputs: `repository`, `token`, `run_id`. Output: `datetime | None`. Raises on
    invalid or unavailable state.
    """
    repository = validate_github_repository(repository)
    normalized_run_id = _first_non_empty(run_id)
    if not normalized_run_id:
        raise RuntimeError(
            "GitHub Actions run ID is required to evaluate default-branch alert deltas."
        )
    try:
        normalized_run_id = str(int(normalized_run_id))
    except ValueError as exc:
        raise RuntimeError(
            f"GitHub Actions run ID must be numeric, got {run_id!r}."
        ) from exc

    payload = github_api_get_json(
        f"/repos/{repository}/actions/runs/{normalized_run_id}",
        token,
    )
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected GitHub API payload type: {type(payload)!r}")
    return parse_iso8601(
        _first_non_empty(payload.get("run_started_at"), payload.get("created_at"))
    )


def load_event_payload(path: str) -> dict[str, Any]:
    """Return load event payload.

    Inputs: `path`. Output: `dict[str, Any]`. Raises on invalid or unavailable state.
    """
    try:
        payload_path = Path(path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError("GitHub event payload path is not readable.") from exc
    if not payload_path.is_file():
        raise RuntimeError("GitHub event payload path must be a file.")
    with payload_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub event payload must be a JSON object.")
    return payload


def main() -> int:
    """Execute the command entrypoint.

    Inputs: none. Output: `int`.
    """
    args = parse_args()
    if not args.event_path:
        print("ERROR: --event-path is required.", file=sys.stderr)
        return 2
    if not args.repository:
        print("ERROR: --repository is required.", file=sys.stderr)
        return 2
    try:
        repository = validate_github_repository(args.repository)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    token = os.environ.get(args.token_env, "").strip()
    if not token:
        print(
            f"ERROR: environment variable {args.token_env} is required.",
            file=sys.stderr,
        )
        return 2

    try:
        event_payload = load_event_payload(args.event_path)

        def fetch_alerts(**kwargs: Any) -> list[dict[str, Any]]:
            """Fetch alerts.

            Inputs: `**kwargs`. Output: `list[dict[str, Any]]`.
            """
            return list_code_scanning_alerts(
                repository,
                token,
                **kwargs,
            )

        def resolve_default_branch(repository: str) -> str | None:
            """Return resolve default branch.

            Inputs: `repository`. Output: `str | None`.
            """
            return get_default_branch(repository, token)

        def resolve_run_started_at(repository: str, run_id: str) -> datetime | None:
            """Return resolve run started at.

            Inputs: `repository`, `run_id`. Output: `datetime | None`.
            """
            return get_workflow_run_started_at(
                repository,
                token,
                run_id,
            )

        if _first_non_empty(args.event_name).lower() == "workflow_run":
            result = evaluate_workflow_run(
                event_payload,
                fetch_alerts,
                settle_timeout_seconds=args.settle_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                resolve_default_branch=resolve_default_branch,
            )
        else:
            result = evaluate_direct_event(
                args.event_name,
                event_payload,
                repository=repository,
                ref=args.ref,
                run_id=args.run_id,
                fetch_alerts=fetch_alerts,
                settle_timeout_seconds=args.settle_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                resolve_default_branch=resolve_default_branch,
                resolve_run_started_at=resolve_run_started_at,
            )
    except Exception as exc:
        print(f"ERROR: security delta guard failed: {exc}", file=sys.stderr)
        return 2

    stream = sys.stderr if result.status == "fail" else sys.stdout
    print(result.message, file=stream)
    return 1 if result.status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
