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
    """Verify classify marks incompatible when output contains unrelated candidate.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in classify marks incompatible when output contains unrelated candidate.
    """
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
    """Verify classify marks compatible when expected file is candidate.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in classify marks compatible when expected file is candidate.
    """
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
    """Verify the classify marks incompatible when stdout has non path line safety boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when classify marks incompatible when stdout has non path line accepts unsafe input.
    """
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
    """Verify classify marks compatible for quoted expected candidate.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in classify marks compatible for quoted expected candidate.
    """
    expected_file = tmp_path / "image.ome.tif"
    stdout = f'"{expected_file}"\n'

    status, _details = _classify_compatibility_output(
        0,
        stdout,
        "",
        expected_file_path=expected_file,
    )

    assert status == "compatible"


def test_classify_bioformats_unknown_pixel_type_as_incompatible(tmp_path: Path):
    """Verify classify bioformats unknown pixel type as incompatible.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in classify bioformats unknown pixel type as incompatible.
    """
    expected_file = tmp_path / "image.ims"
    stderr = (
        "loci.formats.FormatException: Unknown pixel type: null\n"
        "at loci.formats.in.ImarisHDFReader.initFile(ImarisHDFReader.java:117)"
    )

    status, _details = _classify_compatibility_output(
        1,
        "",
        stderr,
        expected_file_path=expected_file,
    )

    assert status == "incompatible"
