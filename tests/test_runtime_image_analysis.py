"""Regression coverage for runtime-package analysis, independent of the carrier."""

import json
from pathlib import Path

import pytest

from tools import scan_prebuilt_runtime_images as scanner


def _sbom():
    """Inputs: none. Output: a minimal SPDX software-package fixture."""
    return {
        "spdxVersion": "SPDX-2.3",
        "packages": [
            {
                "SPDXID": "SPDXRef-package",
                "externalRefs": [
                    {
                        "referenceType": "purl",
                        "referenceLocator": "pkg:pypi/example@1.0",
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "document",
    [
        None,
        {},
        {"spdxVersion": "SPDX-2.3", "packages": []},
        {"spdxVersion": "SPDX-2.3", "packages": [None]},
        {"spdxVersion": "SPDX-2.3", "packages": [{"SPDXID": "file"}]},
    ],
)
def test_empty_or_nonsoftware_inventory_fails(document):
    """Inputs: invalid SPDX documents. Output: asserts rejection, not clean coverage."""
    with pytest.raises(ValueError):
        scanner.package_count(document)


@pytest.mark.parametrize(
    "document",
    [
        None,
        {},
        {"version": "2.1.0", "runs": []},
        {"version": "2.1.0", "runs": [{}]},
        {"version": "2.1.0", "runs": [{"results": [None]}]},
        {
            "version": "2.1.0",
            "runs": [{"results": [], "invocations": [{"executionSuccessful": False}]}],
        },
    ],
)
def test_incomplete_analysis_is_not_a_clean_report(document):
    """Inputs: incomplete SARIF documents. Output: asserts coverage validation fails."""
    with pytest.raises(ValueError):
        scanner.vulnerability_count(document)


def test_every_required_image_is_accounted_for_and_identical_images_scan_once(
    monkeypatch, tmp_path
):
    """The immutable image ID, not the carrier or an arbitrary tag, is analyzed.

    Inputs: three references to two image fixtures. Output: asserts complete coverage.
    """
    first = "sha256:" + "a" * 64
    second = "sha256:" + "b" * 64
    ids = {"example/web:1": first, "example/worker:1": first, "example/db:2": second}
    calls = []

    def run(_docker, arguments, *, env, log):
        """Inputs: Docker command. Output: fixture identity or generated analysis file."""
        calls.append(arguments)
        if arguments[:2] == ["image", "inspect"]:
            return ids[arguments[-1]]
        assert env["DOCKER_SCOUT_CACHE_FORMAT"] == "tar"
        output = Path(arguments[arguments.index("--output") + 1])
        if arguments[1] == "sbom":
            assert arguments[-1] in {f"local://{first}", f"local://{second}"}
            document = _sbom()
        else:
            assert arguments[-1].startswith("sbom://")
            document = {
                "version": "2.1.0",
                "runs": [{"results": [{"ruleId": "TEST-FINDING"}]}],
            }
        output.write_text(json.dumps(document))
        return ""

    monkeypatch.setattr(scanner.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(scanner, "_run", run)
    summary = scanner.scan_images(list(ids), tmp_path)
    assert summary["inventory"] == ids
    assert len(summary["images"]) == 2
    assert sum(call[:2] == ["scout", "sbom"] for call in calls) == 2
    assert all(
        row["packages"] == 1 and row["vulnerabilities"] == 1
        for row in summary["images"].values()
    )
    assert json.loads((tmp_path / "coverage.json").read_text()) == summary


def test_invalid_inventory_and_missing_docker_fail(monkeypatch, tmp_path):
    """Inputs: invalid image lists and absent CLI. Output: asserts explicit failure."""
    for images in ([], [""], ["-option"], ["two images"]):
        with pytest.raises(ValueError):
            scanner.scan_images(images, tmp_path)
    monkeypatch.setattr(scanner.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError):
        scanner.scan_images(["example/web:1"], tmp_path)
