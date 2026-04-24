from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "scanner_inventory.py"
SPEC = importlib.util.spec_from_file_location("scanner_inventory", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
scanner_inventory = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scanner_inventory
SPEC.loader.exec_module(scanner_inventory)


def test_parse_deepsource_repository_accepts_only_github_repository_ids() -> None:
    assert scanner_inventory.parse_deepsource_repository(
        "gh/ZMB-UZH/omero-docker-extended"
    ) == ("GITHUB", "ZMB-UZH", "omero-docker-extended")

    with pytest.raises(SystemExit, match="gh/OWNER/REPO"):
        scanner_inventory.parse_deepsource_repository("ZMB-UZH/omero-docker-extended")


def test_summarize_github_code_scanning_paginates_and_counts_tools(
    monkeypatch,
) -> None:
    monkeypatch.setattr(scanner_inventory, "read_token", lambda *_args: "token")
    monkeypatch.setattr(
        scanner_inventory, "latest_github_api_version", lambda: "2026-03-10"
    )
    requested_urls: list[str] = []
    requested_headers: list[dict[str, str]] = []

    def fake_fetch_json(
        url: str,
        *,
        headers: dict[str, str],
        data: bytes | None = None,
        method: str | None = None,
        service: str,
    ) -> Any:
        requested_urls.append(url)
        requested_headers.append(headers)
        assert data is None
        assert method is None
        assert service == "GitHub code-scanning"
        query = parse_qs(urlparse(url).query)
        if query["page"] == ["1"]:
            return [{"tool": {"name": "CodeQL"}} for _ in range(100)]
        return [{"tool": {"name": "Scorecard"}}, {"tool": {}}]

    monkeypatch.setattr(scanner_inventory, "fetch_json", fake_fetch_json)

    summary = scanner_inventory.summarize_github_code_scanning(
        argparse.Namespace(
            repository="ZMB-UZH/omero-docker-extended",
            branch="main",
            state="open",
            token_env="GITHUB_TOKEN",
        )
    )

    assert summary == {
        "repository": "ZMB-UZH/omero-docker-extended",
        "branch": "main",
        "state": "open",
        "api_version": "2026-03-10",
        "alerts": 102,
        "by_tool": {"CodeQL": 100, "Scorecard": 1, "unknown": 1},
    }
    assert "branch=main" in requested_urls[0]
    assert "state=open" in requested_urls[0]
    assert requested_headers[0]["X-GitHub-Api-Version"] == "2026-03-10"
    assert requested_headers[0]["Authorization"] == "Bearer token"


def test_summarize_deepsource_reports_group_and_occurrence_counts(monkeypatch) -> None:
    monkeypatch.setattr(scanner_inventory, "read_token", lambda *_args: "token")
    requested_payloads: list[bytes | None] = []

    def fake_fetch_json(
        url: str,
        *,
        headers: dict[str, str],
        data: bytes | None = None,
        method: str | None = None,
        service: str,
    ) -> Any:
        requested_payloads.append(data)
        assert url == "https://api.deepsource.com/graphql/"
        assert headers["Authorization"] == "Bearer token"
        assert method == "POST"
        assert service == "DeepSource API"
        return {
            "data": {
                "repository": {
                    "defaultBranch": "main",
                    "latestCommitOid": "abc123",
                    "issues": {"totalCount": 36},
                    "issueOccurrences": {"totalCount": 349},
                    "dependencyVulnerabilityOccurrences": {"totalCount": 0},
                }
            }
        }

    monkeypatch.setattr(scanner_inventory, "fetch_json", fake_fetch_json)

    summary = scanner_inventory.summarize_deepsource(
        argparse.Namespace(
            repository="gh/ZMB-UZH/omero-docker-extended",
            token_env="DEEPSOURCE_TOKEN",
        )
    )

    assert summary == {
        "repository": "gh/ZMB-UZH/omero-docker-extended",
        "default_branch": "main",
        "latest_commit_oid": "abc123",
        "grouped_issues": 36,
        "issue_occurrences": 349,
        "dependency_vulnerability_occurrences": 0,
    }
    assert requested_payloads and b"dependencyVulnerabilityOccurrences" in (
        requested_payloads[0] or b""
    )
