"""Keep the approved source exception narrower than a package-version ignore."""

from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

import pytest
import yaml

from tools import source_advisory_guard as guard


REVIEW_DATE = date(2026, 10, 8)


@pytest.fixture
def source(tmp_path):
    """Inputs: private temporary root. Output: complete, isolated reviewed inputs."""
    scope = tmp_path / guard.SCOPE
    shutil.copytree(guard.ROOT / guard.SCOPE, scope)
    for name in guard.LOCK_FILES:
        shutil.copyfile(guard.ROOT / guard.SCOPE.parent / name, scope.parent / name)
    return tmp_path


def change_text(path, old, new):
    """Inputs: fixture and expected text. Output: one explicit malformed-input mutation."""
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def raw_report(root):
    """Inputs: fixture root. Output: OSV-shaped unfiltered advisory evidence."""
    return {
        "results": [
            {
                "source": {
                    "path": str(root / guard.SCOPE / "nltk.cdx.xml"),
                    "type": "sbom",
                },
                "packages": [
                    {
                        "package": dict(guard.PACKAGE),
                        "vulnerabilities": [{"id": guard.ADVISORY}],
                        "groups": [
                            {
                                "ids": [guard.ADVISORY],
                                "aliases": [
                                    guard.ADVISORY,
                                    "CVE-2026-81726",
                                    "PYSEC-2026-3740",
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def test_current_review_is_complete_and_time_bounded(source):
    """Inputs: reviewed files. Output: exact-source acceptance, never release-wide approval."""
    review = guard.check(source, today=REVIEW_DATE)
    assert review["advisory"] == guard.ADVISORY
    guard.validate_report(raw_report(source), source, review)
    for day in (date(2026, 10, 7), date(2026, 11, 7), date(2027, 1, 1)):
        with pytest.raises(ValueError, match="review window"):
            guard.check(source, today=day)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("schema_version = 1", "schema_version = 2"),
        (guard.ADVISORY, "GHSA-unreviewed"),
        ('version = "3.10.3"', 'version = "3.10.4"'),
        (
            guard.crawl4ai_research.NLTK_SOURCE_URL,
            "https://example.org/different.tar.gz",
        ),
        (guard.crawl4ai_research.NLTK_SOURCE_SHA256, "0" * 64),
        ('source_revision = "', 'source_revision = "invalid-'),
        ("[lock_sha256]", "[unreviewed_locks]"),
        ("2026-10-08", "2026-09-01"),
    ],
)
def test_review_changes_fail_closed(source, old, new):
    """Inputs: altered source/review identities. Output: each unqualified change blocks."""
    change_text(source / guard.SCOPE / "review.toml", old, new)
    with pytest.raises((ValueError, KeyError)):
        guard.check(source, today=REVIEW_DATE)


@pytest.mark.parametrize("name", sorted(guard.LOCK_FILES))
def test_any_dependency_lock_change_invalidates_review(source, name):
    """Inputs: changed runtime or build lock bytes. Output: old approval cannot carry over."""
    path = source / guard.SCOPE.parent / name
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="locks changed"):
        guard.check(source, today=REVIEW_DATE)


@pytest.mark.parametrize("kind", ["extra", "directory", "symlink", "scope-symlink"])
def test_directory_scope_cannot_cover_other_dependencies(source, kind):
    """Inputs: additional or redirected inventory. Output: native directory ignore stays singular."""
    scope = source / guard.SCOPE
    if kind == "extra":
        (scope / "requirements.txt").write_text("nltk==3.10.3\n")
    elif kind == "directory":
        (scope / "review.toml").unlink()
        (scope / "review.toml").mkdir()
    elif kind == "symlink":
        review = scope / "review.toml"
        target = source / "review.toml"
        review.rename(target)
        review.symlink_to(target)
    else:
        moved = source / "moved"
        scope.rename(moved)
        scope.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError):
        guard.check(source, today=REVIEW_DATE)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("/schema/bom/1.6", "/schema/bom/1.5"),
        ('version="1">', 'version="2">'),
        ("</bom>", "<vulnerabilities/></bom>"),
        (
            "</components>",
            '<component type="library"><name>other</name></component></components>',
        ),
        ("<name>nltk</name>", "<name>other</name>"),
        ("<version>3.10.3</version>", "<version>3.10.4</version>"),
        ('type="library"', 'type="application"'),
        ("pkg:pypi/nltk@3.10.3", "pkg:pypi/nltk@3.10.4"),
        (guard.crawl4ai_research.NLTK_SOURCE_URL, "https://example.org/other.tar.gz"),
        (guard.crawl4ai_research.NLTK_SOURCE_SHA256, "0" * 64),
        ("</bom>", ""),
        ("<components>", '<!DOCTYPE bom [<!ENTITY test "value">]><components>'),
    ],
)
def test_inventory_identity_and_scope_are_enforced(source, old, new):
    """Inputs: mismatched or broadened SBOM. Output: exception cannot mask other packages."""
    change_text(source / guard.SCOPE / "nltk.cdx.xml", old, new)
    with pytest.raises(ValueError):
        guard.check(source, today=REVIEW_DATE)


@pytest.mark.parametrize(
    "extra",
    [
        "\n[[IgnoredVulns]]\nid = 'unreviewed'\n",
        "\n[[PackageOverrides]]\nignore = true\n",
    ],
)
def test_native_config_cannot_broaden_the_exception(source, extra):
    """Inputs: a second ignore or whole-package override. Output: reject before native scan."""
    path = source / guard.SCOPE / "osv-scanner.toml"
    path.write_text(path.read_text() + extra)
    with pytest.raises(ValueError, match="broadened"):
        guard.check(source, today=REVIEW_DATE)


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data.update(results=[]),
        lambda data: data["results"][0]["source"].update(type="lockfile"),
        lambda data: data["results"][0]["source"].update(path="wrong.cdx.json"),
        lambda data: data["results"][0].update(packages=[]),
        lambda data: data["results"][0]["packages"][0]["package"].update(version="0"),
        lambda data: data["results"][0]["packages"][0].update(vulnerabilities=[]),
        lambda data: data["results"][0]["packages"][0]["vulnerabilities"].append(
            {"id": "GHSA-new"}
        ),
        lambda data: data["results"][0]["packages"][0]["vulnerabilities"][0].update(
            withdrawn="2026-10-08"
        ),
        lambda data: data["results"][0]["packages"][0].update(groups=[]),
        lambda data: data["results"][0]["packages"][0]["groups"][0].update(
            ids=["other"]
        ),
        lambda data: data["results"][0]["packages"][0]["groups"][0].update(
            ignored=True
        ),
        lambda data: data["results"][0]["packages"][0]["groups"][0].update(aliases=[]),
    ],
)
def test_raw_reports_cannot_be_replaced_by_partial_or_clean_results(source, change):
    """Inputs: missing, filtered or additional findings. Output: fail without rewriting evidence."""
    report = raw_report(source)
    change(report)
    before = deepcopy(report)
    with pytest.raises(ValueError):
        guard.validate_report(report, source, guard.check(source, today=REVIEW_DATE))
    assert report == before


@pytest.fixture
def scanner(source, monkeypatch):
    """Inputs: deterministic executable bytes and real source policy. Output: isolated scan harness."""
    path = source / "scanner"
    path.write_bytes(b"fixture executable")
    monkeypatch.setattr(
        guard, "SCANNER_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()
    )
    original = guard.check
    monkeypatch.setattr(
        guard, "check", lambda root=source: original(root, today=REVIEW_DATE)
    )
    return path


def test_audit_retains_native_bytes_and_forces_unfiltered_configuration(
    source, scanner, monkeypatch
):
    """Inputs: native-shaped process output. Output: raw bytes, status and identity remain intact."""
    payload = json.dumps(raw_report(source), indent=3).encode() + b"\n"
    output = source / "evidence"

    def run(command, **kwargs):
        """Inputs: scanner invocation. Output: native fixture files and expected advisory exit."""
        assert command[0] == str(scanner.resolve())
        assert f"--config={(output / 'unfiltered.toml').resolve()}" in command
        assert (output / "unfiltered.toml").read_bytes() == b""
        assert kwargs["timeout"] == 180
        assert kwargs["cwd"] == source
        assert not kwargs["check"]
        (output / "raw.json").write_bytes(payload)
        kwargs["stdout"].write(b"native stdout")
        kwargs["stderr"].write(b"native stderr")
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(guard.subprocess, "run", run)
    guard.audit(scanner, output, source)
    assert (output / "raw.json").read_bytes() == payload
    assert (output / "stdout.log").read_bytes() == b"native stdout"
    assert (output / "stderr.log").read_bytes() == b"native stderr"
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["returncode"] == 1
    assert receipt["raw_sha256"] == hashlib.sha256(payload).hexdigest()
    with pytest.raises(FileExistsError):
        guard.audit(scanner, output, source)


@pytest.mark.parametrize("returncode", [0, 2, -9])
def test_scanner_errors_or_no_longer_needed_exception_do_not_pass(
    source, scanner, monkeypatch, returncode
):
    """Inputs: clean, failed or killed scanner. Output: record status and require review."""
    monkeypatch.setattr(
        guard.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, returncode),
    )
    output = source / "evidence"
    with pytest.raises(ValueError, match="failed or"):
        guard.audit(scanner, output, source)
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["returncode"] == returncode
    assert receipt["raw_sha256"] is None


def test_wrong_scanner_and_mid_scan_policy_changes_are_rejected(
    source, scanner, monkeypatch
):
    """Inputs: unpinned engine or concurrent policy edit. Output: neither can authorize a scan."""
    output = source / "evidence"
    original_hash = guard.SCANNER_SHA256
    monkeypatch.setattr(guard, "SCANNER_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="executable"):
        guard.audit(scanner, output, source)
    assert not output.exists()
    monkeypatch.setattr(guard, "SCANNER_SHA256", original_hash)

    def run(command, **kwargs):
        """Inputs: process boundary. Output: valid result plus a concurrent review mutation."""
        (output / "raw.json").write_text(json.dumps(raw_report(source)))
        change_text(
            source / guard.SCOPE / "review.toml",
            "Reviewed upstream",
            "Changed upstream",
        )
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(guard.subprocess, "run", run)
    with pytest.raises(ValueError, match="during its audit"):
        guard.audit(scanner, output, source)
    assert (output / "raw.json").is_file()


def test_cli_success_failure_and_timeout_keep_truthful_exit_status(
    monkeypatch, capsys, tmp_path
):
    """Inputs: command outcomes. Output: successful checks only exit zero; all failures remain errors."""
    monkeypatch.setattr(guard, "check", lambda: {})
    assert guard.main(["check"]) == 0
    calls = []
    monkeypatch.setattr(guard, "audit", lambda *args: calls.append(args))
    assert (
        guard.main(
            [
                "audit",
                "--scanner",
                str(tmp_path / "scanner"),
                "--output",
                str(tmp_path / "new"),
            ]
        )
        == 0
    )
    assert len(calls) == 1
    with pytest.raises(SystemExit) as error:
        guard.main(["audit"])
    assert error.value.code == 2

    def failed():
        """Inputs: none. Output: representative bounded scanner timeout."""
        raise subprocess.TimeoutExpired("scanner", 180)

    monkeypatch.setattr(guard, "check", failed)
    assert guard.main(["check"]) == 1
    assert "failed" in capsys.readouterr().err


def test_module_entrypoint_rejects_unknown_commands(monkeypatch):
    """Inputs: an unsupported CLI command. Output: real module entrypoint fails before scanning."""
    monkeypatch.setattr(sys, "argv", ["source_advisory_guard", "invalid-command"])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(Path(guard.__file__)), run_name="__main__")
    assert error.value.code == 2


def test_workflow_preserves_raw_evidence_before_directory_exception():
    """Inputs: actual workflow. Output: native scan depends on the strict, artifact-producing audit."""
    workflow = yaml.safe_load(
        (guard.ROOT / ".github/workflows/security-code-scanning.yml").read_text()
    )
    jobs = workflow["jobs"]
    assert jobs["osv-scanner"]["needs"] == "osv-scanner-audit"
    steps = jobs["osv-scanner-audit"]["steps"]
    step = next(s for s in steps if "source_advisory_guard audit" in s.get("run", ""))
    assert guard.SCANNER_SHA256 in step["run"]
    assert "sha256sum --check --strict" in step["run"]
    assert "source_advisory_guard check" in step["run"]
    artifact = next(
        s for s in steps if s.get("with", {}).get("name") == "source-advisory-evidence"
    )
    assert artifact["if"] == "always()"
    assert artifact["with"]["if-no-files-found"] == "error"
    args = jobs["osv-scanner"]["with"]["scan-args"]
    assert "--config" not in args
    assert f"--lockfile={guard.SCOPE.as_posix()}/nltk.cdx.xml" in args
