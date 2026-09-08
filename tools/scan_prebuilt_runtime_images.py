#!/usr/bin/env python3
"""Verify complete Scout analysis of runtime images before creating a carrier."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def package_count(document: dict) -> int:
    """Reject empty/file-only inventories rather than treating them as clean.

    Inputs: SPDX document. Output: package count; raises ValueError for invalid input.
    """
    if not isinstance(document, dict) or document.get("spdxVersion") != "SPDX-2.3":
        raise ValueError("Runtime analysis did not produce an SPDX 2.3 document.")
    packages = document.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("Runtime analysis found no packages.")
    if not all(
        isinstance(package, dict) and package.get("SPDXID") for package in packages
    ):
        raise ValueError("Runtime package inventory is malformed.")
    if not any(
        isinstance(reference, dict)
        and reference.get("referenceType") == "purl"
        and str(reference.get("referenceLocator", "")).startswith("pkg:")
        for package in packages
        for reference in package.get("externalRefs", [])
    ):
        raise ValueError(
            "Runtime inventory contains no identifiable software packages."
        )
    return len(packages)


def vulnerability_count(document: dict) -> int:
    """Validate a completed Scout SARIF report, retaining every result.

    Inputs: SARIF document. Output: result count; raises ValueError for incomplete runs.
    """
    if not isinstance(document, dict) or document.get("version") != "2.1.0":
        raise ValueError("Runtime vulnerability report is not SARIF 2.1.0.")
    runs = document.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("Runtime vulnerability report has no analysis runs.")
    count = 0
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("results"), list):
            raise ValueError("Runtime vulnerability analysis has no results array.")
        for invocation in run.get("invocations", []):
            if invocation.get("executionSuccessful") is False:
                raise ValueError("Runtime vulnerability analysis was unsuccessful.")
        if not all(
            isinstance(result, dict) and result.get("ruleId")
            for result in run["results"]
        ):
            raise ValueError("Runtime vulnerability results are malformed.")
        count += len(run["results"])
    return count


def _run(docker: str, arguments: list[str], *, env: dict, log: Path) -> str:
    """Bound execution and keep detailed scanner output out of public release logs.

    Inputs: Docker argv, environment and private log. Output: decoded command stdout.
    """
    try:
        with log.open("ab") as errors:
            result = subprocess.run(
                [docker, *arguments],
                env=env,
                stdout=subprocess.PIPE,
                stderr=errors,
                timeout=1800,
                check=True,
            )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            "Runtime image analysis failed; inspect the private scan log."
        ) from exc
    return result.stdout.decode("utf-8")


def scan_images(images: list[str], output_dir: Path) -> dict:
    """Analyze each immutable local image once and bind coverage to every tag.

    Inputs: runtime references and private output directory. Output: coverage manifest.
    """
    if not images or any(
        not image or image.startswith("-") or any(c.isspace() for c in image)
        for image in images
    ):
        raise ValueError("A nonempty runtime image inventory is required.")
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker is required for runtime analysis.")
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_dir = output_dir.resolve(strict=True)
    log = output_dir / "scan.log"
    records = {}
    inventory = {}
    for image in sorted(set(images)):
        image_id = _run(
            docker,
            ["image", "inspect", "--format", "{{.Id}}", image],
            env=dict(os.environ),
            log=log,
        ).strip()
        if re.fullmatch(r"sha256:[a-f0-9]{64}", image_id) is None:
            raise ValueError("Runtime image identity is invalid.")
        inventory[image] = image_id
        if image_id in records:
            continue
        name = image_id.split(":", 1)[1]
        sbom = output_dir / f"{name}.spdx.json"
        report = output_dir / f"{name}.sarif.json"
        # Scout temporary layers can be large. Reclaim only this invocation's
        # scratch space after each image, without pruning Docker or shared caches.
        with tempfile.TemporaryDirectory(prefix="omero-runtime-scout-") as scratch:
            env = dict(
                os.environ,
                DOCKER_SCOUT_CACHE_FORMAT="tar",
                DOCKER_SCOUT_CACHE_DIR=scratch,
                TMPDIR=scratch,
            )
            _run(
                docker,
                [
                    "scout",
                    "sbom",
                    "--format",
                    "spdx",
                    "--output",
                    str(sbom),
                    f"local://{image_id}",
                ],
                env=env,
                log=log,
            )
            packages = package_count(json.loads(sbom.read_text(encoding="utf-8")))
            _run(
                docker,
                [
                    "scout",
                    "cves",
                    "--format",
                    "sarif",
                    "--output",
                    str(report),
                    f"sbom://{sbom}",
                ],
                env=env,
                log=log,
            )
            vulnerabilities = vulnerability_count(
                json.loads(report.read_text(encoding="utf-8"))
            )
        records[image_id] = {
            "packages": packages,
            "vulnerabilities": vulnerabilities,
            "sbom_sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
            "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
        }
        print(
            f"Runtime image {image_id}: {packages} packages; {vulnerabilities} vulnerability results.",
            flush=True,
        )
    for image, expected_id in inventory.items():
        actual_id = _run(
            docker,
            ["image", "inspect", "--format", "{{.Id}}", image],
            env=dict(os.environ),
            log=log,
        ).strip()
        if actual_id != expected_id:
            raise RuntimeError(
                "A runtime image changed during analysis; rebuild the inventory."
            )
    summary = {"schema_version": 1, "inventory": inventory, "images": records}
    (output_dir / "coverage.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main(argv=None) -> int:
    """Run coverage validation without confusing coverage with CVE acceptance.

    Inputs: CLI arguments. Output: zero after complete analysis; errors propagate.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--required-images-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    scan_images(
        args.required_images_file.read_text(encoding="utf-8").splitlines(),
        args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
