#!/usr/bin/env python3
"""Fail CI when a workflow run introduces new GitHub code scanning alerts."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


AlertFetcher = Callable[..., list[dict[str, Any]]]
SleepFn = Callable[[float], None]
ClockFn = Callable[[], float]
DefaultBranchResolver = Callable[[str], str | None]


@dataclass(frozen=True)
class EvaluationResult:
    status: str
    message: str
    alerts: tuple[dict[str, Any], ...] = ()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Block workflow runs that add new GitHub code scanning alerts."
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
    if not timestamp:
        return None
    normalized = timestamp.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized).astimezone(UTC)


def _first_non_empty(*values: Any) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def payload_repository_full_name(event_payload: dict[str, Any]) -> str:
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


def normalize_severity(alert: dict[str, Any]) -> str:
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
    instance = alert.get("most_recent_instance") or {}
    location = instance.get("location") or {}
    return str(location.get("path") or "").strip() or "<unknown>"


def alert_rule(alert: dict[str, Any]) -> str:
    rule = alert.get("rule") or {}
    return str(rule.get("id") or rule.get("name") or "<unknown>").strip()


def alert_tool(alert: dict[str, Any]) -> str:
    tool = alert.get("tool") or {}
    return str(tool.get("name") or "<unknown>").strip()


def format_alert(alert: dict[str, Any]) -> str:
    return (
        f"#{alert.get('number', '?')} "
        f"[{normalize_severity(alert)}] "
        f"{alert_tool(alert)}/{alert_rule(alert)} "
        f"{alert_path(alert)}"
    )


def render_failure_message(prefix: str, alerts: list[dict[str, Any]]) -> str:
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
    if workflow_started_at is None:
        return []
    delta_alerts = []
    for alert in alerts:
        created_at = parse_iso8601(alert.get("created_at"))
        if created_at is not None and created_at >= workflow_started_at:
            delta_alerts.append(alert)
    return delta_alerts


def evaluate_pull_request_alerts(
    pr_number: int,
    fetch_alerts: AlertFetcher,
    *,
    settle_timeout_seconds: int,
    poll_interval_seconds: int,
    monotonic: ClockFn = time.monotonic,
    sleep: SleepFn = time.sleep,
) -> EvaluationResult:
    alerts = wait_for_stable_snapshot(
        lambda: fetch_alerts(pr=pr_number),
        settle_timeout_seconds=settle_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        monotonic=monotonic,
        sleep=sleep,
    )
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
            message=render_failure_message(
                f"Push scan created new default-branch alerts on {ref}",
                delta_alerts,
            ),
            alerts=tuple(delta_alerts),
        )
    return EvaluationResult(
        status="pass",
        message=(
            f"No new default-branch alerts were created on {ref} "
            f"({len(alerts)} open total on the branch snapshot)."
        ),
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
        return evaluate_pull_request_alerts(
            pr_number,
            fetch_alerts,
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
                    "security-code-scanning push payload is missing default or head branch information."
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


def list_code_scanning_alerts(
    repository: str,
    token: str,
    *,
    ref: str | None = None,
    pr: int | None = None,
) -> list[dict[str, Any]]:
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
        url = (
            f"https://api.github.com/repos/{repository}/code-scanning/alerts?"
            f"{urlencode(page_query)}"
        )
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "security-delta-guard",
            },
        )
        with urlopen(request, timeout=30) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise RuntimeError(f"Unexpected GitHub API payload type: {type(batch)!r}")
        alerts.extend(batch)
        if len(batch) < 100:
            return alerts
        page += 1


def get_default_branch(repository: str, token: str) -> str | None:
    request = Request(
        f"https://api.github.com/repos/{repository}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "security-delta-guard",
        },
    )
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected GitHub API payload type: {type(payload)!r}")
    return _first_non_empty(payload.get("default_branch")) or None


def load_event_payload(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub event payload must be a JSON object.")
    return payload


def main() -> int:
    args = parse_args()
    if not args.event_path:
        print("ERROR: --event-path is required.", file=sys.stderr)
        return 2
    if not args.repository:
        print("ERROR: --repository is required.", file=sys.stderr)
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
        result = evaluate_workflow_run(
            event_payload,
            lambda **kwargs: list_code_scanning_alerts(
                args.repository,
                token,
                **kwargs,
            ),
            settle_timeout_seconds=args.settle_timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            resolve_default_branch=lambda repository: get_default_branch(
                repository, token
            ),
        )
    except HTTPError as exc:
        print(
            f"ERROR: GitHub API request failed with HTTP {exc.code}.", file=sys.stderr
        )
        return 2
    except URLError as exc:
        print(f"ERROR: GitHub API request failed: {exc.reason}.", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: security delta guard failed: {exc}", file=sys.stderr)
        return 2

    stream = sys.stderr if result.status == "fail" else sys.stdout
    print(result.message, file=stream)
    return 1 if result.status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
