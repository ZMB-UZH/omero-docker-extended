#!/usr/bin/env python3
"""Query external scanner inventories without putting tokens in argv."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Any


USER_AGENT = "omero-docker-extended-scanner-inventory"


def parse_args() -> argparse.Namespace:
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
    return parser.parse_args()


def read_token(env_name: str, label: str) -> str:
    token = os.environ.get(env_name, "").strip()
    if token:
        return token
    if not sys.stdin.isatty():
        raise SystemExit(f"{env_name} is required")
    token = getpass.getpass(f"{label} token: ").strip()
    if not token:
        raise SystemExit(f"{env_name} is required")
    return token


def fetch_json(
    url: str,
    *,
    headers: dict[str, str],
    data: bytes | None = None,
    method: str | None = None,
    service: str,
) -> Any:
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{service} request failed with HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise SystemExit(f"{service} request failed: {exc.reason}") from None


def latest_github_api_version() -> str:
    versions = fetch_json(
        "https://api.github.com/versions",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
        service="GitHub versions",
    )
    if not isinstance(versions, list) or not versions:
        raise SystemExit("GitHub versions request returned no supported versions")
    if not all(isinstance(version, str) for version in versions):
        raise SystemExit("GitHub versions request returned an invalid response")
    return max(versions)


def summarize_github_code_scanning(args: argparse.Namespace) -> dict[str, Any]:
    token = read_token(args.token_env, "GitHub")
    api_version = latest_github_api_version()
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
            f"https://api.github.com/repos/{args.repository}/code-scanning/alerts?{query}",
            headers=headers,
            service="GitHub code-scanning",
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
        "repository": args.repository,
        "branch": args.branch,
        "state": args.state,
        "api_version": api_version,
        "alerts": len(alerts),
        "by_tool": dict(sorted(by_tool.items())),
    }


def parse_deepsource_repository(repository: str) -> tuple[str, str, str]:
    parts = repository.split("/")
    if len(parts) != 3 or parts[0] != "gh" or not parts[1] or not parts[2]:
        raise SystemExit("DeepSource repository must use gh/OWNER/REPO format")
    return "GITHUB", parts[1], parts[2]


def summarize_deepsource(args: argparse.Namespace) -> dict[str, Any]:
    vcs_provider, login, name = parse_deepsource_repository(args.repository)
    token = read_token(args.token_env, "DeepSource")
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


def main() -> int:
    args = parse_args()
    if args.command == "github-code-scanning":
        summary = summarize_github_code_scanning(args)
    elif args.command == "deepsource":
        summary = summarize_deepsource(args)
    else:  # pragma: no cover - argparse enforces known subcommands.
        raise SystemExit(f"Unsupported command: {args.command}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
