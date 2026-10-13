"""Prove Python verification inventories include the entire pending source tree."""

from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest
import yaml

from tools import mypy_check, vulture_check


@pytest.mark.parametrize(
    "inventory", [mypy_check.list_mypy_targets, vulture_check.list_vulture_targets]
)
def test_scan_inventory_covers_new_source_and_preserves_git_filenames(
    tmp_path, inventory
):
    """Inputs: real Git index plus unstaged files. Output: complete source scope, no private cache."""
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("private/\n")
    tracked = "package/tracked.py"
    new_paths = [
        "package/new.py",
        "package/space name.py",
        "package/line\nbreak.py",
        "package/\u00e9.py",
    ]
    excluded = [
        "tests/test_new.py",
        "package/tests/test_private.py",
        "private/runtime.py",
    ]
    for name in [tracked, *new_paths, *excluded]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value = 1\n")
    subprocess.run([git, "add", "--", tracked, ".gitignore"], cwd=tmp_path, check=True)
    before = subprocess.run(
        [git, "status", "--porcelain=v1", "-z"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    ).stdout
    assert set(inventory(tmp_path)) == {tracked, *new_paths}
    after = subprocess.run(
        [git, "status", "--porcelain=v1", "-z"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    ).stdout
    assert before == after
    subprocess.run([git, "add", "-N", "--", new_paths[0]], cwd=tmp_path, check=True)
    selected = inventory(tmp_path)
    assert set(selected) == {tracked, *new_paths}
    assert len(selected) == len(set(selected))
    assert all(not Path(name).is_absolute() for name in selected)


def test_mypy_checks_namespace_modules_once_and_detects_type_errors(tmp_path):
    """Inputs: real namespace package and checker. Output: unique modules and genuine type checking."""
    root = Path(__file__).resolve().parents[1]
    package = tmp_path / "namespace" / "service"
    package.mkdir(parents=True)
    (package / "values.py").write_text("value: int = 1\n")
    consumer = package / "consumer.py"
    consumer.write_text(
        "from namespace.service.values import value\nresult: int = value\n"
    )
    command = [
        sys.executable,
        "-m",
        "mypy",
        "--config-file",
        str(root / "mypy.ini"),
        "--no-incremental",
        "namespace/service/values.py",
        "namespace/service/consumer.py",
    ]
    success = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert success.returncode == 0, success.stdout + success.stderr
    assert "no issues found in 2 source files" in success.stdout
    consumer.write_text(
        "from namespace.service.values import value\nresult: str = value\n"
    )
    failure = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert failure.returncode == 1, failure.stdout + failure.stderr
    assert 'variable has type "str"' in failure.stdout
    assert "[assignment]" in failure.stdout
    assert "Found 1 error in 1 file (checked 2 source files)" in failure.stdout


def test_gui_test_prerequisites_and_isolation_remain_documented():
    """Inputs: verification policy and parsed CI setup. Output: explicit native dependencies installed before tests."""
    root = Path(__file__).resolve().parents[1]
    skill = (root / ".agents/skills/verification-loop/SKILL.md").read_text()
    for prerequisite in (
        "`ripgrep`",
        "`xvfb`",
        "`xauth`",
        "Tk-enabled Python",
        "fail, never skip",
    ):
        assert prerequisite in skill
    assert "isolated, authenticated Xvfb display with TCP disabled" in skill
    workflow = yaml.safe_load((root / ".github/workflows/tests.yml").read_text())
    steps = workflow["jobs"]["test-with-coverage"]["steps"]
    install = next(step for step in steps if step.get("name") == "Install dependencies")
    packages = set()
    for line in install["run"].replace("\\\n", " ").splitlines():
        arguments = shlex.split(line)
        if arguments[:3] == ["sudo", "apt-get", "install"]:
            assert {"--no-install-recommends", "--yes"} <= set(arguments)
            packages.update(
                argument for argument in arguments[3:] if not argument.startswith("-")
            )
    assert {"ripgrep", "xvfb", "xauth", "libtk8.6"} <= packages
    test_step = next(step for step in steps if step.get("id") == "tests")
    assert steps.index(install) < steps.index(test_step)
