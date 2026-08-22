"""Tests for the pre-upload SARIF result guard."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tools import sarif_result_guard


def write_sarif(path: Path, runs: list[dict[str, object]]) -> None:
    """Write a minimal SARIF fixture.

    Inputs: destination `path` and SARIF `runs`. Output: fixture file on disk.
    """

    path.write_text(json.dumps({"version": "2.1.0", "runs": runs}), encoding="utf-8")


def test_load_sarif_results_accepts_empty_multi_run_report(tmp_path: Path) -> None:
    """Verify explicit empty result arrays are accepted across runs.

    Inputs: temporary directory fixture. Output: asserts an empty result list.
    """

    report = tmp_path / "empty.sarif"
    write_sarif(report, [{"results": []}, {}])

    assert sarif_result_guard.load_sarif_results(report) == []


def test_load_sarif_results_returns_every_finding(tmp_path: Path) -> None:
    """Verify findings from all runs are returned without filtering.

    Inputs: temporary directory fixture. Output: asserts complete result ordering.
    """

    report = tmp_path / "findings.sarif"
    expected = [{"ruleId": "RULE-1"}, {"ruleId": "RULE-2"}]
    write_sarif(report, [{"results": expected[:1]}, {"results": expected[1:]}])

    assert sarif_result_guard.load_sarif_results(report) == expected


def test_load_sarif_results_rejects_missing_runs(tmp_path: Path) -> None:
    """Verify an incomplete SARIF object cannot pass as an empty scan.

    Inputs: temporary directory fixture. Output: asserts validation failure.
    """

    report = tmp_path / "invalid.sarif"
    report.write_text("{}", encoding="utf-8")

    try:
        sarif_result_guard.load_sarif_results(report)
    except sarif_result_guard.SarifValidationError as exc:
        assert "at least one SARIF run" in str(exc)
    else:
        raise AssertionError("missing SARIF runs were accepted")


def test_result_summary_includes_rule_and_location() -> None:
    """Verify failure output identifies the rule and source location.

    Inputs: representative SARIF result. Output: exact rule-location summary equality.
    """

    result = {
        "ruleId": "RULE-1",
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": "docker/example.Dockerfile"},
                    "region": {"startLine": 17},
                }
            }
        ],
    }

    assert (
        sarif_result_guard.result_summary(result)
        == "RULE-1 at docker/example.Dockerfile:17"
    )


def test_main_blocks_non_empty_report(tmp_path: Path, monkeypatch, capsys) -> None:
    """Verify the CLI blocks a report containing findings.

    Inputs: temporary report and pytest process fixtures. Output: asserts exit status and diagnostic.
    """

    report = tmp_path / "finding.sarif"
    write_sarif(report, [{"results": [{"ruleId": "RULE-1"}]}])
    monkeypatch.setattr(sys, "argv", ["sarif_result_guard.py", str(report)])

    assert sarif_result_guard.main() == 1
    assert "upload is blocked" in capsys.readouterr().err


def test_main_fails_closed_on_invalid_report(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Verify malformed scanner output is treated as infrastructure failure.

    Inputs: malformed report and pytest process fixtures. Output: asserts fail-closed status and diagnostic.
    """

    report = tmp_path / "invalid.sarif"
    report.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["sarif_result_guard.py", str(report)])

    assert sarif_result_guard.main() == 2
    assert "cannot read valid JSON" in capsys.readouterr().err
