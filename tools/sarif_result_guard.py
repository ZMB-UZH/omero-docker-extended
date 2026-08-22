#!/usr/bin/env python3
"""Reject SARIF reports that contain findings before they are uploaded."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class SarifValidationError(ValueError):
    """Raised when a scanner report is missing or structurally invalid."""


def parse_args() -> argparse.Namespace:
    """Parse paths to SARIF reports that must be empty.

    Inputs: process command-line arguments. Output: validated argument namespace.
    """

    parser = argparse.ArgumentParser(
        description="Fail when a SARIF report is invalid or contains results."
    )
    parser.add_argument(
        "sarif_files",
        nargs="+",
        type=Path,
        help="One or more SARIF reports that must contain zero results.",
    )
    return parser.parse_args()


def load_sarif_results(path: Path) -> list[dict[str, Any]]:
    """Load validated result objects from one SARIF report.

    Inputs: SARIF `path`. Output: every result mapping from every report run.
    """

    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SarifValidationError(f"cannot read valid JSON from {path}") from exc

    if not isinstance(payload, dict):
        raise SarifValidationError(f"{path} must contain a JSON object")
    runs = payload.get("runs")
    if not isinstance(runs, list) or not runs:
        raise SarifValidationError(f"{path} must contain at least one SARIF run")

    results: list[dict[str, Any]] = []
    for run_index, run in enumerate(runs):
        if not isinstance(run, dict):
            raise SarifValidationError(f"{path} run {run_index} must be an object")
        run_results = run.get("results", [])
        if not isinstance(run_results, list):
            raise SarifValidationError(
                f"{path} run {run_index} results must be an array"
            )
        if any(not isinstance(result, dict) for result in run_results):
            raise SarifValidationError(
                f"{path} run {run_index} contains a non-object result"
            )
        results.extend(run_results)
    return results


def result_summary(result: dict[str, Any]) -> str:
    """Build a compact rule and source-location diagnostic.

    Inputs: one SARIF `result`. Output: human-readable finding summary.
    """

    rule_id = str(result.get("ruleId") or "<unknown-rule>")
    locations = result.get("locations") or []
    path = "<unknown-path>"
    line = "?"
    if locations and isinstance(locations[0], dict):
        physical = locations[0].get("physicalLocation") or {}
        artifact = physical.get("artifactLocation") or {}
        region = physical.get("region") or {}
        path = str(artifact.get("uri") or path)
        line = str(region.get("startLine") or line)
    return f"{rule_id} at {path}:{line}"


def main() -> int:
    """Validate every report and block uploads containing results.

    Inputs: process command-line arguments. Output: CLI exit status.
    """

    args = parse_args()
    findings: list[tuple[Path, dict[str, Any]]] = []
    try:
        for path in args.sarif_files:
            findings.extend((path, result) for result in load_sarif_results(path))
    except SarifValidationError as exc:
        print(f"ERROR: SARIF result guard: {exc}", file=sys.stderr)
        return 2

    if findings:
        print(
            f"ERROR: SARIF result guard found {len(findings)} result(s); "
            "upload is blocked.",
            file=sys.stderr,
        )
        for path, result in findings[:20]:
            print(f"- {path}: {result_summary(result)}", file=sys.stderr)
        if len(findings) > 20:
            print(f"- ... and {len(findings) - 20} more", file=sys.stderr)
        return 1

    print(f"SARIF result guard passed: {len(args.sarif_files)} report(s), 0 results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
