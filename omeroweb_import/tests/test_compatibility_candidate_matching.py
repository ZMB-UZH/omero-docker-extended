"""Regression tests for compatibility candidate parsing."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from omeroweb_import.views.core_functions import _classify_compatibility_output


def test_classify_marks_incompatible_when_output_contains_unrelated_candidate(
    tmp_path: Path,
):
    expected_file = tmp_path / "sample.unsupported"
    stdout = f"{tmp_path / 'other-file.tiff'}\n"

    status, _details = _classify_compatibility_output(
        0,
        stdout,
        "",
        expected_file_path=expected_file,
    )

    assert status == "incompatible"


def test_classify_marks_compatible_when_expected_file_is_candidate(tmp_path: Path):
    expected_file = tmp_path / "image.ome.tif"
    stdout = f"{expected_file}\n"

    status, _details = _classify_compatibility_output(
        0,
        stdout,
        "",
        expected_file_path=expected_file,
    )

    assert status == "compatible"


def test_classify_marks_incompatible_when_stdout_has_non_path_line(tmp_path: Path):
    expected_file = tmp_path / "sample.unsupported"
    stdout = f"Using OMERODIR={tmp_path / 'compat-check-1234'}\n"

    status, _details = _classify_compatibility_output(
        0,
        stdout,
        "",
        expected_file_path=expected_file,
    )

    assert status == "incompatible"


def test_classify_marks_compatible_for_quoted_expected_candidate(tmp_path: Path):
    expected_file = tmp_path / "image.ome.tif"
    stdout = f'"{expected_file}"\n'

    status, _details = _classify_compatibility_output(
        0,
        stdout,
        "",
        expected_file_path=expected_file,
    )

    assert status == "compatible"
