"""Exercise scanner CLI boundaries with native Git output and real source files."""

import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

import pytest

from tools import regression_guard as guard


@pytest.fixture
def staged_repo(tmp_path):
    """Inputs: private directory. Output: Git index without creating any commits."""
    git = shutil.which("git")
    assert git is not None, "Git is required for the scanner's native CLI tests"
    subprocess.run([git, "init", "--quiet", str(tmp_path)], check=True)
    return tmp_path, git


@pytest.mark.parametrize(
    "filename",
    [
        "plain.py",
        "nested/space in name.py",
        "nested/caf\u00e9.py",
        'nested/"quoted".py',
        "nested/new\nline.py",
        "nested/tab\tname.py",
    ],
)
def test_diff_scan_preserves_native_git_filenames(
    staged_repo, monkeypatch, capsys, filename
):
    """Inputs: staged filenames Git may quote. Output: every changed file is scanned."""
    root, git = staged_repo
    path = root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def verify(value):\n    assert value\n", encoding="utf-8")
    (root / "control.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run([git, "-C", str(root), "add", "--all"], check=True)
    native_output = subprocess.check_output
    calls = []

    def staged_diff(command, **kwargs):
        """Inputs: Git diff argv. Output: native index output without fixture commits."""
        calls.append(command)
        assert command.count("review-base..HEAD") == 1
        actual = [part for part in command if part != "review-base..HEAD"]
        actual.insert(actual.index("diff") + 1, "--cached")
        return native_output(actual, **kwargs)

    monkeypatch.setattr(guard.subprocess, "check_output", staged_diff)
    assert (
        guard.main(
            [
                "--repo-root",
                str(root),
                "scan",
                "--diff",
                "review-base",
                "--format",
                "json",
            ]
        )
        == 1
    )
    results = json.loads(capsys.readouterr().out)
    assert [(item["rule"], item["path"], item["line"]) for item in results] == [
        ("RG001", filename, 2)
    ]
    assert len(calls) == 1


def test_diff_scan_round_trips_non_utf8_linux_filename(staged_repo, monkeypatch):
    """Inputs: Linux filename bytes. Output: lossless filesystem decoding."""
    root, git = staged_repo
    filename = os.fsdecode(b"source-\xff.py")
    path = root / filename
    path.write_text("value = 1\n", encoding="utf-8")
    subprocess.run([git, "-C", str(root), "add", "--all"], check=True)
    native_output = subprocess.check_output

    def staged_diff(command, **kwargs):
        """Inputs: Git diff argv. Output: the native byte-framed index diff."""
        actual = [part for part in command if part != "review-base..HEAD"]
        actual.insert(actual.index("diff") + 1, "--cached")
        return native_output(actual, **kwargs)

    monkeypatch.setattr(guard.subprocess, "check_output", staged_diff)
    assert guard._git_changed_files(root, "review-base") == [path]


def test_empty_diff_does_not_scan_unchanged_files(staged_repo, monkeypatch, capsys):
    """Inputs: empty Git diff and unchanged finding. Output: no unrelated findings."""
    root, _ = staged_repo
    (root / "unchanged.py").write_text("assert True\n", encoding="utf-8")
    native_output = subprocess.check_output

    def staged_diff(command, **kwargs):
        """Inputs: Git diff argv. Output: an empty native index diff."""
        actual = [part for part in command if part != "review-base..HEAD"]
        actual.insert(actual.index("diff") + 1, "--cached")
        return native_output(actual, **kwargs)

    monkeypatch.setattr(guard.subprocess, "check_output", staged_diff)
    assert (
        guard.main(
            [
                "--repo-root",
                str(root),
                "scan",
                "--diff",
                "review-base",
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == []
    assert guard.scan_paths(root, []) == []
    assert [finding.rule_id for finding in guard.scan_paths(root, None)] == ["RG001"]


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("Git unavailable"),
        subprocess.CalledProcessError(128, "git"),
        subprocess.TimeoutExpired("git", 60),
    ],
)
def test_diff_scan_fails_closed_on_git_error(tmp_path, monkeypatch, failure):
    """Inputs: Git process failure. Output: explicit error rather than a clean result."""

    def fail(*_args, **_kwargs):
        """Inputs: subprocess invocation. Output: the selected operating-system failure."""
        raise failure

    monkeypatch.setattr(guard.subprocess, "check_output", fail)
    with pytest.raises(SystemExit, match="git diff failed"):
        guard.main(["--repo-root", str(tmp_path), "scan", "--diff", "base"])


def test_diff_scan_requires_git(tmp_path, monkeypatch):
    """Inputs: missing Git executable. Output: fail before spawning any command."""
    monkeypatch.setattr(guard.shutil, "which", lambda _name: None)
    with pytest.raises(SystemExit, match="Git is required"):
        guard._git_changed_files(tmp_path, "base")


def test_diff_base_cannot_become_a_git_option(staged_repo):
    """Inputs: option-shaped base ref. Output: rejection without writing an output file."""
    root, _ = staged_repo
    output = root / "unexpected-output"
    with pytest.raises(SystemExit, match="git diff failed"):
        guard._git_changed_files(root, f"--output={output}")
    assert not output.exists()
    assert not output.with_name(output.name + "..HEAD").exists()


@pytest.mark.parametrize("output_format", ["text", "json", "markdown"])
def test_catalog_cli_matches_actual_rules(output_format, capsys):
    """Inputs: supported catalog formats. Output: every real rule is represented."""
    assert guard.main(["catalog", "--format", output_format]) == 0
    output = capsys.readouterr().out
    for rule in guard.CATALOG:
        assert rule.id in output
    if output_format == "json":
        assert len(json.loads(output)) == len(guard.CATALOG)


def test_text_scan_reports_findings_below_failure_threshold(tmp_path, capsys):
    """Inputs: a high-severity finding and critical threshold. Output: visible, not gated."""
    (tmp_path / "module.py").write_text("assert True\n", encoding="utf-8")
    assert (
        guard.main(["--repo-root", str(tmp_path), "scan", "--fail-on", "critical"]) == 0
    )
    output = capsys.readouterr().out
    assert "RG001" in output and "module.py:1" in output
    assert "1 finding(s); 0 at or above 'critical'" in output


def test_empty_scan_reports_zero(tmp_path, capsys):
    """Inputs: empty source directory. Output: explicit zero findings."""
    assert guard.main(["--repo-root", str(tmp_path), "scan"]) == 0
    assert "no findings" in capsys.readouterr().out


def test_unknown_severity_is_never_silently_filtered():
    """Inputs: a future severity label. Output: conservative gating."""
    finding = guard.Finding("test", "future", "source.py", 1, 0, "message", "excerpt")
    assert guard._filter_severity([finding], "critical") == [finding]


def test_direct_script_entrypoint(monkeypatch, capsys):
    """Inputs: actual script entrypoint. Output: catalog JSON and successful exit."""
    monkeypatch.setattr(
        sys, "argv", ["regression_guard", "catalog", "--format", "json"]
    )
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(Path(guard.__file__)), run_name="__main__")
    assert result.value.code == 0
    assert len(json.loads(capsys.readouterr().out)) == len(guard.CATALOG)
