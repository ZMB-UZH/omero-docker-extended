"""Verify direct-URL dependency provenance and retain unfiltered OSV evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET  # nosec B405 - reviewed local inventory; DTDs rejected before parsing

from tools import crawl4ai_research


ROOT = Path(__file__).resolve().parents[1]
SCOPE = Path(".github/requirements/crawl4ai-source")
SCOPE_FILES = {"nltk.cdx.xml", "review.toml", "osv-scanner.toml"}
LOCK_FILES = {"crawl4ai.in", "crawl4ai.txt", "crawl4ai-build.in", "crawl4ai-build.txt"}
PACKAGE = {
    "name": "nltk",
    "version": crawl4ai_research.NLTK_VERSION,
    "ecosystem": "PyPI",
}
SCANNER_VERSION = "2.7.0"
SCANNER_SHA256 = "160c6253e2922e9e0a6a9771c5c4c40a4b3c6090b34a3cdd5e80c96cc2e4218b"  # DevSkim: ignore DS173237 -- public OSV release binary SHA-256


def digest(path: Path) -> str:
    """Inputs: artifact path. Output: SHA-256 of its exact bytes."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def check(root: Path = ROOT) -> dict:
    """Inputs: source root. Output: exact artifact identity, locks and exception-free policy."""
    scope = root / SCOPE
    if scope.is_symlink() or {p.name for p in scope.iterdir()} != SCOPE_FILES:
        raise ValueError("Source inventory directory scope changed")
    if any(not p.is_file() or p.is_symlink() for p in scope.iterdir()):
        raise ValueError("Source inventory inputs must be regular files")
    review = tomllib.loads((scope / "review.toml").read_text(encoding="utf-8"))
    if (
        set(review)
        != {
            "schema_version",
            "package",
            "archive_url",
            "archive_sha256",
            "reason",
            "lock_sha256",
        }
        or review["schema_version"] != 2
    ):
        raise ValueError("Source provenance schema changed")
    if review["package"] != PACKAGE:
        raise ValueError("Source inventory package changed")
    if (
        review["archive_url"] != crawl4ai_research.NLTK_SOURCE_URL
        or review["archive_sha256"] != crawl4ai_research.NLTK_SOURCE_SHA256
    ):
        raise ValueError("Source inventory archive changed")
    locks = review["lock_sha256"]
    if set(locks) != LOCK_FILES or any(
        digest(scope.parent / name) != expected for name, expected in locks.items()
    ):
        raise ValueError("Source inventory dependency locks changed")
    check_inventory(scope / "nltk.cdx.xml", review)
    config = tomllib.loads((scope / "osv-scanner.toml").read_text(encoding="utf-8"))
    if config:
        raise ValueError(
            "Native OSV configuration must not contain exceptions or overrides"
        )
    return review


def check_inventory(path: Path, review: dict) -> None:
    """Inputs: native CycloneDX XML and review. Output: exact single-component provenance."""
    text = path.read_text(encoding="utf-8")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.IGNORECASE):
        raise ValueError("Source inventory must not declare a DTD or entities")
    namespace = "http://cyclonedx.org/schema/bom/1.6"  # DevSkim: ignore DS137138 -- XML namespace identifier, never a connection
    expected = f"""<bom xmlns="{namespace}" version="1">
      <components><component type="library">
        <name>nltk</name><version>{PACKAGE["version"]}</version><purl>pkg:pypi/nltk@{PACKAGE["version"]}</purl>
        <externalReferences>
          <reference type="vcs"><url>https://github.com/nltk/nltk/tree/v{PACKAGE["version"]}</url></reference>
          <reference type="distribution"><url>{review["archive_url"]}</url>
            <hashes><hash alg="SHA-256">{review["archive_sha256"]}</hash></hashes>
          </reference>
        </externalReferences>
      </component></components>
    </bom>"""
    try:
        actual = ET.canonicalize(text, strip_text=True)
    except ET.ParseError as error:
        raise ValueError("Malformed source inventory XML") from error
    if actual != ET.canonicalize(expected, strip_text=True):
        raise ValueError("Source inventory scope or provenance changed")


def validate_report(report: dict, root: Path) -> None:
    """Inputs: unfiltered native OSV JSON. Output: require the complete inventory and no findings."""
    results = report["results"]
    if len(results) != 1:
        raise ValueError("Raw source audit must contain exactly one inventory")
    source = results[0]["source"]
    if (
        source["type"] != "sbom"
        or Path(source["path"]).resolve() != (root / SCOPE / "nltk.cdx.xml").resolve()
    ):
        raise ValueError("Raw source audit inventory identity changed")
    packages = results[0]["packages"]
    if len(packages) != 1 or packages[0]["package"] != {
        **PACKAGE,
        "purl": f"pkg:pypi/nltk@{PACKAGE['version']}",
    }:
        raise ValueError("Raw source audit package scope changed")
    if (
        packages[0].get("vulnerabilities", []) != []
        or packages[0].get("groups", []) != []
    ):
        raise ValueError(
            "Raw source audit contains advisory findings or filtered groups"
        )


def audit(scanner: Path, output: Path, root: Path = ROOT) -> None:
    """Inputs: pinned scanner and fresh evidence directory. Output: unmodified scan artifacts."""
    review = check(root)
    scanner = scanner.resolve(strict=True)
    if digest(scanner) != SCANNER_SHA256:
        raise ValueError(
            f"OSV executable does not match the verified Linux {SCANNER_VERSION} asset"
        )
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    raw = output / "raw.json"
    empty_config = output / "unfiltered.toml"
    empty_config.write_text("", encoding="utf-8")
    command = [
        str(scanner),
        "scan",
        "source",
        f"--config={empty_config.resolve()}",
        f"--lockfile={root / SCOPE / 'nltk.cdx.xml'}",
        "--all-packages",
        "--format=json",
        f"--output-file={raw.resolve()}",
    ]
    (output / "review.json").write_text(
        json.dumps(review, indent=2) + "\n", encoding="utf-8"
    )
    (output / "command.json").write_text(
        json.dumps(command, indent=2) + "\n", encoding="utf-8"
    )
    with (
        (output / "stdout.log").open("wb") as stdout,
        (output / "stderr.log").open("wb") as stderr,
    ):
        result = subprocess.run(
            command, cwd=root, stdout=stdout, stderr=stderr, check=False, timeout=180
        )
    receipt = {
        "scanner_version": SCANNER_VERSION,
        "scanner_sha256": digest(scanner),
        "returncode": result.returncode,
        "raw_sha256": digest(raw) if raw.is_file() else None,
    }
    (output / "receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    if result.returncode != 0:
        raise ValueError("Raw source audit failed or found advisories")
    validate_report(json.loads(raw.read_text(encoding="utf-8")), root)
    if check(root) != review:
        raise ValueError("Source provenance changed during its audit")


def main(argv: list[str] | None = None) -> int:
    """Inputs: CLI arguments. Output: zero only after complete source-policy verification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "audit"))
    parser.add_argument("--scanner", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            check()
        else:
            if args.scanner is None or args.output is None:
                parser.error("audit requires --scanner and --output")
            audit(args.scanner, args.output)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(f"Source advisory verification failed: {exc}", file=sys.stderr)
        return 1
    print("Source advisory verification passed; raw findings are not modified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
