#!/usr/bin/env python3
"""Query external scanner inventories without putting tokens in argv."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from collections import Counter
from typing import Any


USER_AGENT = "omero-docker-extended-scanner-inventory"
REPOSITORY_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120


def curl_config_quote(value: str) -> str:
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


def parse_args() -> argparse.Namespace:
    """Parse args.

    Inputs: none. Output: `argparse.Namespace`.
    """
    parser = argparse.ArgumentParser(
        description="Summarize GitHub code-scanning or DeepSource findings."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    github = subparsers.add_parser(
        "github-code-scanning",
        help="Summarize GitHub code-scanning alerts.",
    )
    github.add_argument(
        "--repository",
        required=True,
        help="Repository in OWNER/REPO format.",
    )
    github.add_argument(
        "--branch",
        required=True,
        help="Branch name to query.",
    )
    github.add_argument(
        "--state",
        default="open",
        choices=("open", "dismissed", "fixed"),
        help="Alert state to query.",
    )
    github.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="Environment variable containing the GitHub token.",
    )
    add_request_timeout_argument(github)

    deepsource = subparsers.add_parser(
        "deepsource",
        help="Summarize DeepSource grouped issues and occurrences.",
    )
    deepsource.add_argument(
        "--repository",
        required=True,
        help="Repository in gh/OWNER/REPO format.",
    )
    deepsource.add_argument(
        "--token-env",
        default="DEEPSOURCE_TOKEN",
        help="Environment variable containing the DeepSource token.",
    )
    add_request_timeout_argument(deepsource)
    deepsource_issues = subparsers.add_parser(
        "deepsource-issues",
        help="List DeepSource grouped issues with sample occurrences.",
    )
    deepsource_issues.add_argument(
        "--repository",
        required=True,
        help="Repository in gh/OWNER/REPO format.",
    )
    deepsource_issues.add_argument(
        "--issue-limit",
        type=positive_int,
        default=100,
        help="Maximum grouped issues to request.",
    )
    deepsource_issues.add_argument(
        "--occurrence-limit",
        type=positive_int,
        default=5,
        help="Maximum sample occurrences to request per grouped issue.",
    )
    deepsource_issues.add_argument(
        "--token-env",
        default="DEEPSOURCE_TOKEN",
        help="Environment variable containing the DeepSource token.",
    )
    add_request_timeout_argument(deepsource_issues)
    return parser.parse_args()


def positive_int(value: str) -> int:
    """Positive int.

    Inputs: `value`. Output: `int`. Raises on invalid or unavailable state.
    """
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def add_request_timeout_argument(parser: argparse.ArgumentParser) -> None:
    """Add request timeout argument.

    Inputs: `parser`. Output: None.
    """
    parser.add_argument(
        "--request-timeout",
        type=positive_int,
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        help=(
            "Per-request timeout in seconds for scanner API calls "
            f"(default: {DEFAULT_REQUEST_TIMEOUT_SECONDS})."
        ),
    )


def read_token(env_name: str, label: str) -> str:
    """Return read token.

    Inputs: `env_name`, `label`. Output: `str`. Raises on invalid or unavailable state.
    """
    token = os.environ.get(env_name, "").strip()
    if token:
        return token
    if not sys.stdin.isatty():
        raise SystemExit(f"{env_name} is required")
    token = getpass.getpass(f"{label} token: ").strip()
    if not token:
        raise SystemExit(f"{env_name} is required")
    return token


def validate_repository_component(value: str) -> bool:
    """Return True when a repository path component is safe for API paths.

    Inputs: `value`. Output: `bool`.
    """
    return (
        bool(value)
        and value not in {".", ".."}
        and REPOSITORY_COMPONENT_RE.fullmatch(value) is not None
    )


def parse_github_repository(repository: str) -> tuple[str, str]:
    """Return a validated GitHub OWNER/REPO tuple.

    Inputs: `repository`. Output: `tuple[str, str]`. Raises on invalid or unavailable
    state.
    """
    parts = repository.split("/")
    if (
        len(parts) != 2
        or not validate_repository_component(parts[0])
        or not validate_repository_component(parts[1])
    ):
        raise SystemExit(
            "GitHub repository must use OWNER/REPO format with safe path components"
        )
    return parts[0], parts[1]


def fetch_json(
    url: str,
    *,
    headers: dict[str, str],
    data: bytes | None = None,
    method: str | None = None,
    service: str,
    timeout_seconds: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> Any:
    """Fetch JSON.

    Inputs: `url`, `headers`, `data`, `method`, `service`, `timeout_seconds`. Output:
    `Any`. Raises on invalid or unavailable state.
    """
    parsed_url = urllib.parse.urlsplit(url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise SystemExit(f"{service} request requires an HTTPS URL")
    curl_bin = shutil.which("curl")
    if curl_bin is None:
        raise SystemExit(f"{service} request failed: curl is required")
    config_lines = [f"url = {curl_config_quote(url)}"]
    if method is not None:
        config_lines.append(f"request = {curl_config_quote(method)}")
    for name, value in headers.items():
        config_lines.append(f"header = {curl_config_quote(f'{name}: {value}')}")
    if data is not None:
        config_lines.append(f"data-binary = {curl_config_quote(data.decode('utf-8'))}")
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
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"{service} request failed: {exc}") from None
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SystemExit(f"{service} request failed: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise SystemExit(f"{service} request returned invalid JSON") from None


def latest_github_api_version(
    timeout_seconds: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> str:
    """Latest github API version.

    Inputs: `timeout_seconds`. Output: `str`. Raises on invalid or unavailable state.
    """
    versions = fetch_json(
        "https://api.github.com/versions",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
        service="GitHub versions",
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(versions, list) or not versions:
        raise SystemExit("GitHub versions request returned no supported versions")
    if not all(isinstance(version, str) for version in versions):
        raise SystemExit("GitHub versions request returned an invalid response")
    return max(versions)


def summarize_github_code_scanning(args: argparse.Namespace) -> dict[str, Any]:
    """Summarize github code scanning.

    Inputs: `args`. Output: `dict[str, Any]`. Raises on invalid or unavailable state.
    """
    owner, repo = parse_github_repository(args.repository)
    repository = f"{owner}/{repo}"
    token = read_token(args.token_env, "GitHub")
    timeout_seconds = getattr(args, "request_timeout", DEFAULT_REQUEST_TIMEOUT_SECONDS)
    api_version = latest_github_api_version(timeout_seconds=timeout_seconds)
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": api_version,
    }
    alerts: list[dict[str, Any]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {
                "state": args.state,
                "branch": args.branch,
                "per_page": "100",
                "page": str(page),
            }
        )
        batch = fetch_json(
            f"https://api.github.com/repos/{repository}/code-scanning/alerts?{query}",
            headers=headers,
            service="GitHub code-scanning",
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(batch, list):
            raise SystemExit(
                "GitHub code-scanning request returned an invalid response"
            )
        alerts.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    by_tool = Counter(
        str((alert.get("tool") or {}).get("name") or "unknown") for alert in alerts
    )
    return {
        "repository": repository,
        "branch": args.branch,
        "state": args.state,
        "api_version": api_version,
        "alerts": len(alerts),
        "by_tool": dict(sorted(by_tool.items())),
    }


def parse_deepsource_repository(repository: str) -> tuple[str, str, str]:
    """Parse deepsource repository.

    Inputs: `repository`. Output: `tuple[str, str, str]`. Raises on invalid or
    unavailable state.
    """
    parts = repository.split("/")
    if (
        len(parts) != 3
        or parts[0] != "gh"
        or not validate_repository_component(parts[1])
        or not validate_repository_component(parts[2])
    ):
        raise SystemExit(
            "DeepSource repository must use gh/OWNER/REPO format with safe path components"
        )
    return "GITHUB", parts[1], parts[2]


def summarize_deepsource(args: argparse.Namespace) -> dict[str, Any]:
    """Summarize deepsource.

    Inputs: `args`. Output: `dict[str, Any]`. Raises on invalid or unavailable state.
    """
    vcs_provider, login, name = parse_deepsource_repository(args.repository)
    token = read_token(args.token_env, "DeepSource")
    timeout_seconds = getattr(args, "request_timeout", DEFAULT_REQUEST_TIMEOUT_SECONDS)
    payload = {
        "query": """
          query($name: String!, $login: String!, $vcsProvider: VCSProvider!) {
            repository(name: $name, login: $login, vcsProvider: $vcsProvider) {
              defaultBranch
              latestCommitOid
              issues(first: 1) { totalCount }
              issueOccurrences(first: 1) { totalCount }
              dependencyVulnerabilityOccurrences(first: 1) { totalCount }
            }
          }
        """,
        "variables": {
            "name": name,
            "login": login,
            "vcsProvider": vcs_provider,
        },
    }
    result = fetch_json(
        "https://api.deepsource.com/graphql/",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
        service="DeepSource API",
        timeout_seconds=timeout_seconds,
    )
    if result.get("errors"):
        raise SystemExit("DeepSource API returned GraphQL errors")
    repository = (result.get("data") or {}).get("repository")
    if not isinstance(repository, dict):
        raise SystemExit("DeepSource repository was not found or returned invalid data")
    return {
        "repository": args.repository,
        "default_branch": repository.get("defaultBranch"),
        "latest_commit_oid": repository.get("latestCommitOid"),
        "grouped_issues": (repository.get("issues") or {}).get("totalCount"),
        "issue_occurrences": (repository.get("issueOccurrences") or {}).get(
            "totalCount"
        ),
        "dependency_vulnerability_occurrences": (
            repository.get("dependencyVulnerabilityOccurrences") or {}
        ).get("totalCount"),
    }


def summarize_deepsource_issues(args: argparse.Namespace) -> dict[str, Any]:
    """Summarize deepsource issues.

    Inputs: `args`. Output: `dict[str, Any]`. Raises on invalid or unavailable state.
    """
    vcs_provider, login, name = parse_deepsource_repository(args.repository)
    token = read_token(args.token_env, "DeepSource")
    timeout_seconds = getattr(args, "request_timeout", DEFAULT_REQUEST_TIMEOUT_SECONDS)
    payload = {
        "query": """
          query(
            $name: String!,
            $login: String!,
            $vcsProvider: VCSProvider!,
            $issueLimit: Int!,
            $occurrenceLimit: Int!
          ) {
            repository(name: $name, login: $login, vcsProvider: $vcsProvider) {
              defaultBranch
              latestCommitOid
              issues(first: $issueLimit) {
                totalCount
                edges {
                  node {
                    id
                    issue {
                      shortcode
                      title
                      category
                      severity
                      shortDescription
                      tags
                      analyzer {
                        shortcode
                        name
                      }
                    }
                    occurrences(first: $occurrenceLimit) {
                      totalCount
                      edges {
                        node {
                          path
                          beginLine
                          beginColumn
                          endLine
                          endColumn
                          title
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        """,
        "variables": {
            "name": name,
            "login": login,
            "vcsProvider": vcs_provider,
            "issueLimit": args.issue_limit,
            "occurrenceLimit": args.occurrence_limit,
        },
    }
    result = fetch_json(
        "https://api.deepsource.com/graphql/",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
        service="DeepSource API",
        timeout_seconds=timeout_seconds,
    )
    if result.get("errors"):
        raise SystemExit("DeepSource API returned GraphQL errors")
    repository = (result.get("data") or {}).get("repository")
    if not isinstance(repository, dict):
        raise SystemExit("DeepSource repository was not found or returned invalid data")
    issues = repository.get("issues")
    if not isinstance(issues, dict):
        raise SystemExit("DeepSource issue list returned invalid data")

    grouped_issues: list[dict[str, Any]] = []
    for edge in issues.get("edges") or []:
        node = edge.get("node") or {}
        issue = node.get("issue") or {}
        analyzer = issue.get("analyzer") or {}
        occurrences = node.get("occurrences") or {}
        sample_occurrences = []
        for occurrence_edge in occurrences.get("edges") or []:
            occurrence = occurrence_edge.get("node") or {}
            sample_occurrences.append(
                {
                    "path": occurrence.get("path"),
                    "begin_line": occurrence.get("beginLine"),
                    "begin_column": occurrence.get("beginColumn"),
                    "end_line": occurrence.get("endLine"),
                    "end_column": occurrence.get("endColumn"),
                    "title": occurrence.get("title"),
                }
            )
        grouped_issues.append(
            {
                "id": node.get("id"),
                "shortcode": issue.get("shortcode"),
                "title": issue.get("title"),
                "category": issue.get("category"),
                "severity": issue.get("severity"),
                "short_description": issue.get("shortDescription"),
                "tags": issue.get("tags") or [],
                "analyzer": {
                    "shortcode": analyzer.get("shortcode"),
                    "name": analyzer.get("name"),
                },
                "occurrences": occurrences.get("totalCount"),
                "sample_occurrences": sample_occurrences,
            }
        )

    return {
        "repository": args.repository,
        "default_branch": repository.get("defaultBranch"),
        "latest_commit_oid": repository.get("latestCommitOid"),
        "grouped_issues": issues.get("totalCount"),
        "returned_grouped_issues": len(grouped_issues),
        "issues": grouped_issues,
    }


def main() -> int:
    """Execute the command entrypoint.

    Inputs: none. Output: `int`. Raises on invalid or unavailable state.
    """
    args = parse_args()
    if args.command == "github-code-scanning":
        summary = summarize_github_code_scanning(args)
    elif args.command == "deepsource":
        summary = summarize_deepsource(args)
    elif args.command == "deepsource-issues":
        summary = summarize_deepsource_issues(args)
    else:  # pragma: no cover - argparse enforces known subcommands.
        raise SystemExit(f"Unsupported command: {args.command}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
