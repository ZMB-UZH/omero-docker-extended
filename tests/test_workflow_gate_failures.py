"""Verify the verifier: failures, tool selection and raw scanner evidence."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from tools import run_local_workflow_gates as gates


@pytest.fixture
def gate_context(tmp_path):
    """Inputs: private checkout. Output: gate settings that cannot touch installed applications."""
    root = tmp_path / "source"
    root.mkdir()
    return gates.GateContext(
        root, tmp_path / "reports", tmp_path / "venv", sys.executable, False
    )


@pytest.mark.parametrize("status", [0, 7])
def test_devskim_driver_propagates_child_status_and_artifact_location(
    gate_context, status
):
    """Inputs: a real scanner-driver child. Output: exact artifact path and native failure, never a false pass."""
    tool = gate_context.repo_root / "tools" / "devskim_gate.py"
    tool.parent.mkdir()
    tool.write_text(
        "import argparse, pathlib, sys\n"
        "p=argparse.ArgumentParser(); p.add_argument('--artifact-dir', required=True)\n"
        "root=pathlib.Path(p.parse_args().artifact_dir); root.mkdir(parents=True)\n"
        "(root/'invoked').write_text(str(root))\n"
        f"sys.exit({status})\n"
    )
    if status:
        with pytest.raises(gates.GateError, match="exit code 7"):
            gates.run_devskim(gate_context)
    else:
        assert gates.run_devskim(gate_context) is None
    expected = gate_context.artifact_dir / "devskim"
    assert (expected / "invoked").read_text() == str(expected)


@pytest.mark.parametrize("keep_going", [False, True])
def test_command_sequence_preserves_real_exit_status(gate_context, keep_going):
    """Inputs: successful, failing and later native processes. Output: exact stop/continue semantics."""
    context = replace(gate_context, keep_going=keep_going)
    commands = tuple(
        (
            f"step-{index}",
            (
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; "
                f"Path('step-{index}').write_text('executed'); sys.exit({status})",
            ),
        )
        for index, status in enumerate((0, 7, 9))
    )
    with pytest.raises(gates.GateError, match="exit code 7") as error:
        gates._run_many(context, commands)
    assert (context.repo_root / "step-0").read_text() == "executed"
    assert (context.repo_root / "step-1").read_text() == "executed"
    assert (context.repo_root / "step-2").exists() == keep_going
    assert ("exit code 9" in str(error.value)) == keep_going


@pytest.mark.parametrize("source", ["venv", "path", "missing"])
def test_executable_selection_prefers_pinned_runtime(gate_context, monkeypatch, source):
    """Inputs: available executable locations. Output: pinned tool preferred and absence fatal."""
    local = gate_context.tool_venv / "bin" / "fixture-tool"
    if source == "venv":
        local.parent.mkdir(parents=True)
        local.write_text("fixture")
    external = str(gate_context.repo_root / "fixture-tool")
    lookup = Mock(return_value=external if source != "missing" else None)
    monkeypatch.setattr(gates.shutil, "which", lookup)
    if source == "missing":
        with pytest.raises(gates.GateError, match="Missing required executable"):
            gates._require_executable("fixture-tool", gate_context)
    else:
        assert gates._require_executable("fixture-tool", gate_context) == (
            str(local) if source == "venv" else external
        )
    if source == "venv":
        lookup.assert_not_called()


@pytest.mark.parametrize("output", [None, "invalid\n", "upstream/topic/nested\n"])
def test_symbolic_head_preserves_branch_segments(gate_context, monkeypatch, output):
    """Inputs: absent, malformed or nested remote HEAD. Output: no invented branch name."""
    monkeypatch.setattr(gates, "_git_stdout", lambda *_args: output)
    assert gates._symbolic_remote_head_branch(gate_context.repo_root, "upstream") == (
        "topic/nested" if output and "/" in output else ""
    )


@pytest.mark.parametrize("output", [None, "* remote fixture\n", "HEAD branch:   \n"])
def test_remote_head_without_branch_stays_unknown(gate_context, monkeypatch, output):
    """Inputs: incomplete remote metadata. Output: no fallback name manufactured."""
    monkeypatch.setattr(gates, "_git_stdout", lambda *_args: output)
    assert gates._remote_head_branch(gate_context.repo_root, "fixture") == ""


@pytest.mark.parametrize("symbolic", ["release/next", ""])
def test_branch_resolution_uses_symbolic_metadata_only_after_remote_checks(
    gate_context, monkeypatch, symbolic
):
    """Inputs: unavailable remote HEAD. Output: checked symbolic fallback or explicit failure."""
    monkeypatch.delenv("DEFAULT_BRANCH", raising=False)
    monkeypatch.setattr(gates, "_preferred_remotes", lambda _root: ("first", "second"))
    calls = []

    def remote(_root, name):
        """Inputs: remote name. Output: record failed authoritative lookup."""
        calls.append(("remote", name))
        return ""

    def local(_root, name):
        """Inputs: remote name. Output: optional local HEAD after every remote lookup."""
        calls.append(("symbolic", name))
        return symbolic if name == "second" else ""

    monkeypatch.setattr(gates, "_remote_head_branch", remote)
    monkeypatch.setattr(gates, "_symbolic_remote_head_branch", local)
    if symbolic:
        assert gates._default_branch(gate_context.repo_root) == symbolic
    else:
        with pytest.raises(gates.GateError, match="Cannot detect the default branch"):
            gates._default_branch(gate_context.repo_root)
    assert calls == [
        ("remote", "first"),
        ("remote", "second"),
        ("symbolic", "first"),
        ("symbolic", "second"),
    ]


@pytest.mark.parametrize("exists", [False, True])
def test_setup_keeps_hash_locked_requirements_and_exact_linter_pin(
    gate_context, monkeypatch, exists
):
    """Inputs: fresh or existing tool env. Output: every lockfile installed with hash enforcement."""
    context = gate_context
    (context.repo_root / ".ruff.toml").write_text('required-version = "==0.16.10"\n')
    python = context.tool_venv / "bin" / "python"
    if exists:
        python.parent.mkdir(parents=True)
        python.write_text("existing interpreter")
    runner = Mock()
    monkeypatch.setattr(gates, "_run", runner)
    gates._install_python_workflow_dependencies(context)
    commands = [call.args[0] for call in runner.call_args_list]
    if not exists:
        creation = commands.pop(0)
        assert creation == (sys.executable, "-m", "venv", str(context.tool_venv))
    assert len(commands) == 5
    assert {command[-1] for command in commands[:-1]} == {
        ".github/requirements/tests-ci.txt",
        ".github/requirements/mypy-ci.txt",
        ".github/requirements/vulture-ci.txt",
        ".github/requirements/security-code-scanning.txt",
    }
    for command in commands[:-1]:
        assert command[:6] == (
            str(python),
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "--requirement",
        )
    assert commands[-1] == (str(python), "-m", "pip", "install", "ruff==0.16.10")
    assert all(
        call.kwargs["cwd"] == context.repo_root for call in runner.call_args_list
    )


def test_docs_lint_and_prevention_gates_execute_all_required_steps(
    gate_context, monkeypatch
):
    """Inputs: gate runners. Output: canonical commands preserve source scope and exception checks."""
    runner = Mock()
    monkeypatch.setattr(gates, "_run", runner)
    monkeypatch.setattr(gates, "_require_executable", lambda *_args: "fixture-ruff")
    gates.run_docs(gate_context)
    gates.run_ruff(gate_context)
    gates.run_mypy(gate_context)
    gates.run_vulture(gate_context)
    gates.run_regression_guard(gate_context)
    assert [call.args[0] for call in runner.call_args_list] == [
        (sys.executable, "tools/lint_docs_structure.py"),
        (sys.executable, "-m", "unittest", "-v", "tests/test_lint_docs_structure.py"),
        ("fixture-ruff", "check", "."),
        ("fixture-ruff", "format", "--check", "."),
        (sys.executable, "tools/mypy_check.py"),
        (sys.executable, "tools/vulture_check.py"),
        (sys.executable, "tools/regression_guard.py", "scan", "--fail-on", "info"),
        (sys.executable, "tools/regression_guard.py", "selfcheck"),
        (sys.executable, "-m", "tools.source_advisory_guard", "check"),
    ]


@pytest.mark.parametrize("keep_going", [False, True])
def test_split_suite_failure_cannot_be_hidden_by_later_coverage_steps(
    gate_context, monkeypatch, keep_going
):
    """Inputs: first suite and coverage-report failures. Output: retained failure with isolated artifacts."""
    context = replace(gate_context, keep_going=keep_going)
    calls = []

    def runner(command, **kwargs):
        """Inputs: test or reporting command. Output: controlled failure with real gate orchestration."""
        calls.append((command, kwargs))
        if kwargs["label"] in {"pytest with coverage: tests/", "coverage xml"}:
            raise gates.GateError(kwargs["label"] + " fixture failure")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(gates, "_run", runner)
    with pytest.raises(gates.GateError, match="tests/.*fixture failure") as error:
        gates.run_tests(context)
    assert len(calls) == (11 if keep_going else 1)
    assert ("coverage xml fixture failure" in str(error.value)) == keep_going
    if keep_going:
        suite_files = [kwargs["env"]["COVERAGE_FILE"] for _, kwargs in calls[:8]]
        assert len(set(suite_files)) == 8
        assert len({Path(value).parent for value in suite_files}) == 1
        assert all(
            Path(value).is_relative_to(context.artifact_dir) for value in suite_files
        )
        assert calls[-1][1]["label"] == "coverage report"


@pytest.mark.parametrize(
    ("code", "stdout", "stderr", "message"),
    [
        (8, "", "native failure", "exit code 8: native failure"),
        (8, "", "", "exit code 8: no scanner diagnostic"),
        (0, "not json", "", "invalid SARIF"),
        (0, "[]", "", "no valid SARIF runs"),
        (
            0,
            '{"runs":[{"results":[{"ruleId":"DL3007"}]}]}',
            "",
            "Hadolint findings",
        ),
    ],
)
def test_hadolint_engine_or_payload_failure_never_passes(
    gate_context, monkeypatch, code, stdout, stderr, message
):
    """Inputs: failed scanner or malformed raw output. Output: failed gate and preserved available evidence."""
    context = gate_context
    relative = "Dockerfile"
    (context.repo_root / relative).write_text("FROM scratch\n")
    monkeypatch.setattr(gates, "_require_executable", lambda *_args: "fixture-docker")
    monkeypatch.setattr(gates, "discover_dockerfiles", lambda _root: (relative,))
    monkeypatch.setattr(
        gates.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], code, stdout, stderr),
    )
    with pytest.raises(gates.GateError, match=message):
        gates.run_hadolint(context)
    report = context.artifact_dir / "hadolint" / "Dockerfile.sarif"
    assert report.exists() == (code == 0)
    if report.exists():
        assert report.read_text() == stdout


def test_hadolint_requires_discovered_dockerfiles(gate_context, monkeypatch):
    """Inputs: empty source inventory. Output: explicit refusal, never a vacuous clean scan."""
    monkeypatch.setattr(gates, "_require_executable", lambda *_args: "fixture-docker")
    monkeypatch.setattr(gates, "discover_dockerfiles", lambda _root: ())
    with pytest.raises(gates.GateError, match="No Dockerfiles"):
        gates.run_hadolint(gate_context)


@pytest.mark.parametrize("setup_only", [False, True])
def test_successful_setup_selects_new_interpreter(
    gate_context, monkeypatch, capsys, setup_only
):
    """Inputs: successful setup. Output: setup-only stops; normal invocation uses the new interpreter."""
    context = gate_context
    monkeypatch.setattr(gates, "REPO_ROOT", context.repo_root)
    setup = Mock()
    runner = Mock()
    monkeypatch.setattr(gates, "_install_python_workflow_dependencies", setup)
    monkeypatch.setitem(gates.PROFILES, "ci", (runner,))
    arguments = [
        "--artifact-dir",
        str(context.artifact_dir),
        "--tool-venv",
        str(context.tool_venv),
        "--setup-only" if setup_only else "--setup",
    ]
    assert gates.main(arguments) == 0
    setup.assert_called_once()
    if setup_only:
        runner.assert_not_called()
        assert "Python tools are installed" in capsys.readouterr().out
    else:
        assert runner.call_args.args[0].python == str(
            context.tool_venv / "bin" / "python"
        )


def test_dockerfile_inventory_cli_is_machine_readable():
    """Inputs: actual Linux CLI. Output: deterministic JSON inventory with no setup side effects."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "tools/run_local_workflow_gates.py", "--list-dockerfiles"],
        cwd=root,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    inventory = json.loads(result.stdout)
    assert inventory == list(gates.discover_dockerfiles(root))
    assert inventory and result.stderr == ""


def test_non_repository_git_failure_has_no_invented_metadata(gate_context):
    """Inputs: native Git in a non-repository. Output: failed lookup stays unknown."""
    assert (
        gates._git_stdout(gate_context.repo_root, "rev-parse", "--show-toplevel")
        is None
    )
    assert gates._upstream_remote(gate_context.repo_root) == ""
    assert gates._configured_remotes(gate_context.repo_root) == ()


def test_remote_preference_preserves_upstream_and_deduplicates(
    gate_context, monkeypatch
):
    """Inputs: upstream plus duplicate remote entries. Output: stable unique lookup order."""
    monkeypatch.setattr(gates, "_upstream_remote", lambda _root: "upstream")
    monkeypatch.setattr(
        gates, "_configured_remotes", lambda _root: ("origin", "upstream", "mirror")
    )
    assert gates._preferred_remotes(gate_context.repo_root) == (
        "upstream",
        "origin",
        "mirror",
    )
    monkeypatch.setenv("DEFAULT_BRANCH", "release/current")
    assert gates._default_branch(gate_context.repo_root) == "release/current"


@pytest.mark.parametrize("content", ["", 'required-version = ">=0.16.0"\n'])
def test_ruff_installation_refuses_absent_or_floating_pin(gate_context, content):
    """Inputs: unusable linter policy. Output: explicit setup failure, never an unpinned install."""
    (gate_context.repo_root / ".ruff.toml").write_text(content)
    with pytest.raises(gates.GateError, match="required-version"):
        gates._read_required_ruff_version(gate_context.repo_root)


@pytest.mark.parametrize("count", [0, 2])
def test_super_linter_image_requires_one_unambiguous_source(gate_context, count):
    """Inputs: absent or conflicting scanner references. Output: no arbitrary image selection."""
    path = gate_context.repo_root / ".github" / "workflows" / "super-linter.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "".join(
            f"ghcr.io/super-linter/super-linter:v{index}\n" for index in range(count)
        )
    )
    with pytest.raises(gates.GateError, match="exactly one"):
        gates._read_super_linter_image(gate_context.repo_root)


@pytest.mark.parametrize("linked", [False, True])
def test_bandit_scope_rejects_aliases_and_tracks_only_existing_files(
    gate_context, monkeypatch, linked
):
    """Inputs: missing source or an external alias. Output: absent files omitted, aliases fail closed."""
    external = gate_context.repo_root.parent / "outside.py"
    external.write_text("private_fixture = 1\n")
    if linked:
        (gate_context.repo_root / "linked.py").symlink_to(external)
    (gate_context.repo_root / "regular.py").write_text("public_fixture = 1\n")
    monkeypatch.setattr(
        gates, "tracked_source_paths", lambda _root: ("linked.py", "regular.py")
    )
    if linked:
        with pytest.raises(gates.GateError, match="regular in-repository file"):
            gates.discover_bandit_targets(gate_context.repo_root)
    else:
        targets = gates.discover_bandit_targets(gate_context.repo_root)
        assert targets.production_files == ("./regular.py",)
        assert targets.test_files == ()
    assert external.read_text() == "private_fixture = 1\n"


@pytest.mark.parametrize(
    "production,tests",
    [((), ()), (("./source.py",), ()), ((), ("./tests/test_source.py",))],
)
def test_bandit_refuses_incomplete_scope_before_scanner_execution(
    gate_context, monkeypatch, production, tests
):
    """Inputs: missing production or test inventory. Output: a failed gate before any scanner runs."""
    monkeypatch.setattr(gates, "_require_executable", lambda *_args: "fixture-bandit")
    monkeypatch.setattr(
        gates,
        "discover_bandit_targets",
        lambda _root: gates.BanditTargets(production, tests),
    )
    run = Mock()
    monkeypatch.setattr(gates, "_run", run)
    with pytest.raises(gates.GateError, match="non-empty production and test"):
        gates.run_bandit(gate_context)
    run.assert_not_called()
