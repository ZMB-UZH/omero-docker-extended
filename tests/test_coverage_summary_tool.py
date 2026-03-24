"""Regression tests for the coverage summary reporting tool."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_coverage_summary_tool_writes_markdown_report(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    coverage_json = tmp_path / "coverage.json"
    output_md = tmp_path / "coverage-summary.md"
    coverage_json.write_text(
        json.dumps(
            {
                "totals": {
                    "covered_lines": 75,
                    "num_statements": 100,
                    "missing_lines": 25,
                    "percent_covered": 75.0,
                },
                "files": {
                    "omero_plugin_common/request_utils.py": {
                        "summary": {
                            "covered_lines": 30,
                            "num_statements": 30,
                            "missing_lines": 0,
                            "percent_covered": 100.0,
                        },
                        "missing_lines": [],
                    },
                    "omeroweb_import/views/core_functions.py": {
                        "summary": {
                            "covered_lines": 20,
                            "num_statements": 50,
                            "missing_lines": 30,
                            "percent_covered": 40.0,
                        },
                        "missing_lines": [
                            11,
                            12,
                            13,
                            14,
                            25,
                            26,
                            40,
                            41,
                            42,
                            75,
                        ],
                    },
                    "omeroweb_omp_plugin/views/index_view.py": {
                        "summary": {
                            "covered_lines": 25,
                            "num_statements": 50,
                            "missing_lines": 5,
                            "percent_covered": 50.0,
                        },
                        "missing_lines": [91, 92, 93, 120, 121],
                    },
                    "omeroweb_import/tests/test_something.py": {
                        "summary": {
                            "covered_lines": 10,
                            "num_statements": 10,
                            "missing_lines": 0,
                            "percent_covered": 100.0,
                        },
                        "missing_lines": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools" / "coverage_summary.py"),
            "--coverage-json",
            str(coverage_json),
            "--output-md",
            str(output_md),
            "--top-files",
            "2",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = output_md.read_text(encoding="utf-8")
    assert "Overall tracked coverage: **75.00%** (75/100 lines, 25 missing)" in summary
    assert "| `omero_plugin_common` | 100.00% | 30 | 0 | 30 |" in summary
    assert "| `omeroweb_import` | 40.00% | 20 | 30 | 50 |" in summary
    assert "| `omeroweb_import/views/core_functions.py` | 40.00% | 30 | `11-14, 25-26, 40-42, 75` | 50 |" in summary
    assert "Download the uploaded coverage artifact for the full HTML line-by-line report." in summary
    assert "omeroweb_import/tests/test_something.py" not in summary
