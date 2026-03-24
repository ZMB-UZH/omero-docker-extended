"""Render a compact markdown summary from coverage.py JSON output."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


PACKAGE_PREFIXES = [
    ("omero_plugin_common", "omero_plugin_common/"),
    ("omeroweb_admin_tools", "omeroweb_admin_tools/"),
    ("omeroweb_imaris_connector", "omeroweb_imaris_connector/"),
    ("omeroweb_import", "omeroweb_import/"),
    ("omeroweb_omp_plugin", "omeroweb_omp_plugin/"),
]


def _is_tracked_source(path: str) -> bool:
    if "/tests/" in path or path.endswith("conftest.py"):
        return False
    return any(path.startswith(prefix) for _name, prefix in PACKAGE_PREFIXES)


def _package_rows(report: dict) -> list[tuple[str, float, int, int]]:
    rows = []
    for package_name, prefix in PACKAGE_PREFIXES:
        covered = 0
        statements = 0
        missing = 0
        for path, payload in report.get("files", {}).items():
            if not path.startswith(prefix) or "/tests/" in path:
                continue
            summary = payload.get("summary", {})
            covered += int(summary.get("covered_lines", 0))
            statements += int(summary.get("num_statements", 0))
            missing += int(summary.get("missing_lines", 0))
        percent = (100.0 * covered / statements) if statements else 0.0
        rows.append((package_name, percent, covered, missing, statements))
    return rows


def _compress_line_ranges(lines: list[int], *, limit: int = 4) -> str:
    if not lines:
        return "-"

    ranges = []
    start = end = lines[0]
    for line in lines[1:]:
        if line == end + 1:
            end = line
            continue
        ranges.append((start, end))
        start = end = line
    ranges.append((start, end))

    rendered = []
    for range_start, range_end in ranges[:limit]:
        if range_start == range_end:
            rendered.append(str(range_start))
        else:
            rendered.append(f"{range_start}-{range_end}")
    if len(ranges) > limit:
        rendered.append("...")
    return ", ".join(rendered)


def _low_coverage_rows(report: dict, top_files: int) -> list[tuple[str, float, int, int, str]]:
    rows = []
    for path, payload in report.get("files", {}).items():
        if not _is_tracked_source(path):
            continue
        summary = payload.get("summary", {})
        missing_lines = [int(line) for line in payload.get("missing_lines", [])]
        rows.append(
            (
                path,
                float(summary.get("percent_covered", 0.0)),
                int(summary.get("missing_lines", 0)),
                int(summary.get("num_statements", 0)),
                _compress_line_ranges(missing_lines),
            )
        )
    rows.sort(key=lambda row: (row[1], -row[2], row[0]))
    return rows[:top_files]


def render_markdown(report: dict, *, top_files: int = 20) -> str:
    totals = report.get("totals", {})
    overall_percent = float(totals.get("percent_covered", 0.0))
    covered = int(totals.get("covered_lines", 0))
    statements = int(totals.get("num_statements", 0))
    missing = int(totals.get("missing_lines", 0))

    lines = [
        "## Coverage Summary",
        "",
        f"Overall tracked coverage: **{overall_percent:.2f}%** ({covered}/{statements} lines, {missing} missing)",
        "",
        "### Package Coverage",
        "",
        "| Package | Coverage | Covered | Missing | Statements |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for package_name, percent, package_covered, package_missing, package_statements in _package_rows(report):
        lines.append(
            f"| `{package_name}` | {percent:.2f}% | {package_covered} | {package_missing} | {package_statements} |"
        )

    lines.extend(
        [
            "",
            f"### Lowest-Covered Files (Top {top_files})",
            "",
            "| File | Coverage | Missing | Missing line ranges | Statements |",
            "| --- | ---: | ---: | --- | ---: |",
        ]
    )
    for path, percent, missing_lines, statements_count, missing_ranges in _low_coverage_rows(report, top_files):
        lines.append(
            f"| `{path}` | {percent:.2f}% | {missing_lines} | `{missing_ranges}` | {statements_count} |"
        )

    lines.extend(
        [
            "",
            "Download the uploaded coverage artifact for the full HTML line-by-line report.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-json", required=True, help="Path to coverage.py JSON report")
    parser.add_argument("--output-md", required=True, help="Output markdown path")
    parser.add_argument("--top-files", type=int, default=20, help="How many low-coverage files to include")
    args = parser.parse_args()

    report = json.loads(Path(args.coverage_json).read_text(encoding="utf-8"))
    markdown = render_markdown(report, top_files=args.top_files)
    Path(args.output_md).write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
