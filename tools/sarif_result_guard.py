#!/usr/bin/env python3
"""Block unreviewed SARIF findings while retaining complete scanner evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any


class SarifValidationError(ValueError):
    """Raised when a scanner report is missing or structurally invalid."""


def parse_args() -> argparse.Namespace:
    """Parse reports and an optional source-bound native-suppression manifest.

    Inputs: process command-line arguments. Output: validated argument namespace.
    """

    parser = argparse.ArgumentParser(
        description="Fail when SARIF is invalid or contains unreviewed results."
    )
    parser.add_argument(
        "sarif_files",
        nargs="+",
        type=Path,
        help="One or more SARIF reports that must contain zero results.",
    )
    parser.add_argument(
        "--reviewed-suppressions",
        type=Path,
        help="Verify exact-source approvals for native Semgrep suppressions.",
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


def reviewed_suppressions(
    report: Path, manifest: Path, source_root: Path
) -> set[tuple[str, str, int]]:
    """Validate approved native suppressions against the scanner and live source.

    Inputs: unchanged SARIF, reviewed manifest, checkout root. Output: exact keys.
    Missing, stale, malformed or unbound approvals fail closed, not silently open.
    """
    try:
        policy = json.loads(manifest.read_text(encoding="utf-8"))
        payload = json.loads(report.read_text(encoding="utf-8"))
        root = source_root.resolve(strict=True)
        if (
            not isinstance(policy, dict)
            or set(policy) != {"schema", "tool", "version", "findings"}
            or type(policy["schema"]) is not int
            or policy["schema"] != 1
            or policy["tool"] != "Semgrep OSS"
            or not isinstance(policy["version"], str)
            or not policy["version"]
            or not isinstance(policy["findings"], list)
            or not policy["findings"]
        ):
            raise ValueError("invalid reviewed-suppression manifest")
        runs = payload["runs"]
        if len(runs) != 1:
            raise ValueError("reviewed suppressions require exactly one scanner run")
        run = runs[0]
        driver = run["tool"]["driver"]
        invocations = run["invocations"]
        if (
            driver["name"] != policy["tool"]
            or driver["semanticVersion"] != policy["version"]
            or not isinstance(invocations, list)
            or not invocations
            or any(item.get("executionSuccessful") is not True for item in invocations)
        ):
            raise ValueError("scanner identity or successful execution is unverified")

        approved: set[tuple[str, str, int]] = set()
        for item in policy["findings"]:
            if not isinstance(item, dict) or set(item) != {
                "rule_id",
                "path",
                "line",
                "sha256",
                "reason",
            }:
                raise ValueError("invalid reviewed finding")
            rule, name, line = item["rule_id"], item["path"], item["line"]
            if (
                not all(
                    isinstance(item[field], str) and item[field].strip()
                    for field in ("rule_id", "path", "sha256", "reason")
                )
                or type(line) is not int
                or line < 2
            ):
                raise ValueError("invalid reviewed finding fields")
            relative = PurePosixPath(name)
            if (
                relative.is_absolute()
                or relative.as_posix() != name
                or ".." in relative.parts
                or ":" in name
                or "\\" in name
            ):
                raise ValueError(
                    "reviewed path must be canonical and repository-relative"
                )
            path = root.joinpath(*relative.parts)
            if any(part.is_symlink() for part in (path, *path.parents)):
                raise ValueError("reviewed source must not use symbolic links")
            source = path.read_bytes()
            lines = source.decode("utf-8").splitlines()
            if (
                hashlib.sha256(source).hexdigest() != item["sha256"]
                or line > len(lines)
                or lines[line - 2].strip() != f"# nosemgrep: {rule}"
            ):
                raise ValueError(
                    "reviewed source hash or line-specific annotation changed"
                )
            key = (rule, name, line)
            if key in approved:
                raise ValueError("duplicate reviewed finding")
            approved.add(key)
        return approved
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise SarifValidationError(
            f"cannot verify reviewed suppressions: {exc}"
        ) from exc


def reject_unreviewed_results(
    results: list[dict[str, Any]], approved: set[tuple[str, str, int]]
) -> list[dict[str, Any]]:
    """Match native suppressions exactly once without modifying any SARIF result.

    Inputs: complete results and verified keys. Output: all unapproved results.
    """
    pending = set(approved)
    rejected = []
    for result in results:
        locations = result.get("locations", [])
        key = None
        if isinstance(locations, list) and len(locations) == 1:
            try:
                physical = locations[0]["physicalLocation"]
                key = (
                    result["ruleId"],
                    physical["artifactLocation"]["uri"],
                    physical["region"]["startLine"],
                )
                if (
                    not all(isinstance(value, str) for value in key[:2])
                    or type(key[2]) is not int
                    or physical["region"].get("endLine") != key[2]
                    or physical["artifactLocation"].get("uriBaseId") != "%SRCROOT%"
                ):
                    key = None
            except (KeyError, TypeError):
                key = None
        if key in pending and result.get("suppressions") == [{"kind": "inSource"}]:
            pending.remove(key)
        else:
            rejected.append(result)
    if pending:
        raise SarifValidationError(
            "reviewed findings are missing or no longer natively suppressed"
        )
    return rejected


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
    """Validate every report and block uploads containing unreviewed results.

    Inputs: process command-line arguments. Output: CLI exit status.
    """

    args = parse_args()
    findings: list[tuple[Path, dict[str, Any]]] = []
    approved_count = 0
    try:
        if args.reviewed_suppressions and len(args.sarif_files) != 1:
            raise SarifValidationError(
                "reviewed suppressions require exactly one report"
            )
        for path in args.sarif_files:
            results = load_sarif_results(path)
            if args.reviewed_suppressions:
                approved = reviewed_suppressions(
                    path, args.reviewed_suppressions, Path.cwd()
                )
                results = reject_unreviewed_results(results, approved)
                approved_count = len(approved)
            findings.extend((path, result) for result in results)
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

    print(
        f"SARIF result guard passed: {len(args.sarif_files)} report(s), 0 unreviewed results; "
        f"{approved_count} verified native suppression(s), raw reports unchanged."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
