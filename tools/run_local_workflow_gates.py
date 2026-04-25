#!/usr/bin/env python3
"""Run the locally reproducible GitHub workflow gates.

The GitHub workflow remains the source of truth for hosted-only behavior such
as SARIF upload, CodeQL analysis services, OIDC publishing, and Scorecard
repository checks. This tool mirrors the deterministic commands that can run on
the host before a commit or push.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_DIR = REPO_ROOT / ".cache" / "local-workflow-gates"


@dataclass(frozen=True)
class BanditTargets:
    scan_dirs: tuple[str, ...]
    package_test_dirs: tuple[str, ...]
    test_dirs: tuple[str, ...]
    exclude_csv: str


@dataclass(frozen=True)
class GateContext:
    repo_root: Path
    artifact_dir: Path
    tool_venv: Path
    python: str
    keep_going: bool


class GateError(RuntimeError):
    """A local workflow gate failed or cannot be run faithfully."""


def _require_executable(name: str, context: GateContext | None = None) -> str:
    if context is not None:
        venv_executable = context.tool_venv / "bin" / name
        if venv_executable.is_file():
            return str(venv_executable)

    executable = shutil.which(name)
    if executable is None:
        msg = (
            f"Missing required executable: {name}. Install the same tool used by "
            "the matching GitHub workflow, or rerun with --setup when the tool "
            "is Python-backed."
        )
        raise GateError(msg)
    return executable


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    label: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    print(f"\n==> {label}", flush=True)
    print("+ " + " ".join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
    )
    if check and result.returncode != 0:
        raise GateError(f"{label} failed with exit code {result.returncode}.")
    return result


def _git_stdout(repo_root: Path, *args: str) -> str | None:
    git = _require_executable("git")
    result = subprocess.run(
        (git, *args),
        cwd=repo_root,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _upstream_remote(repo_root: Path) -> str:
    stdout = _git_stdout(
        repo_root,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    )
    if not stdout:
        return ""
    remote_name, separator, _branch = stdout.strip().partition("/")
    return remote_name if separator else ""


def _configured_remotes(repo_root: Path) -> tuple[str, ...]:
    stdout = _git_stdout(repo_root, "remote")
    if not stdout:
        return ()
    return tuple(remote.strip() for remote in stdout.splitlines() if remote.strip())


def _preferred_remotes(repo_root: Path) -> tuple[str, ...]:
    preferred_remotes: list[str] = []
    upstream_remote = _upstream_remote(repo_root)
    if upstream_remote:
        preferred_remotes.append(upstream_remote)
    for remote_name in _configured_remotes(repo_root):
        if remote_name not in preferred_remotes:
            preferred_remotes.append(remote_name)
    return tuple(preferred_remotes)


def _remote_head_branch(repo_root: Path, remote_name: str) -> str:
    stdout = _git_stdout(repo_root, "remote", "show", remote_name)
    if not stdout:
        return ""
    for line in stdout.splitlines():
        key, separator, branch = line.strip().partition(":")
        if separator and key == "HEAD branch" and branch.strip():
            return branch.strip()
    return ""


def _symbolic_remote_head_branch(repo_root: Path, remote_name: str) -> str:
    stdout = _git_stdout(
        repo_root,
        "symbolic-ref",
        "--quiet",
        "--short",
        f"refs/remotes/{remote_name}/HEAD",
    )
    if not stdout:
        return ""
    _remote, separator, branch = stdout.strip().partition("/")
    return branch if separator else ""


def _first_default_branch_candidate(repo_root: Path) -> str:
    preferred_remotes = _preferred_remotes(repo_root)
    for remote_name in preferred_remotes:
        branch = _remote_head_branch(repo_root, remote_name)
        if branch:
            return branch

    for remote_name in preferred_remotes:
        branch = _symbolic_remote_head_branch(repo_root, remote_name)
        if branch:
            return branch

    return ""


def _default_branch(repo_root: Path) -> str:
    configured = os.environ.get("DEFAULT_BRANCH")
    if configured:
        return configured

    branch = _first_default_branch_candidate(repo_root)
    if branch:
        return branch

    raise GateError(
        "Cannot detect the default branch for local Super-Linter. Set "
        "DEFAULT_BRANCH to the repository default branch and rerun the gate."
    )


def _run_many(context: GateContext, steps: Sequence[tuple[str, Sequence[str]]]) -> None:
    failures: list[str] = []
    for label, command in steps:
        try:
            _run(command, cwd=context.repo_root, label=label)
        except GateError as exc:
            if not context.keep_going:
                raise
            failures.append(str(exc))
    if failures:
        joined = "\n".join(f"- {failure}" for failure in failures)
        raise GateError(f"One or more workflow gates failed:\n{joined}")


def _install_python_workflow_dependencies(context: GateContext) -> None:
    if not (context.tool_venv / "bin" / "python").is_file():
        _run(
            (sys.executable, "-m", "venv", str(context.tool_venv)),
            cwd=context.repo_root,
            label="create local workflow tool environment",
        )

    python = str(context.tool_venv / "bin" / "python")
    requirement_files = (
        ".github/requirements/tests-ci.txt",
        ".github/requirements/mypy-ci.txt",
        ".github/requirements/vulture-ci.txt",
        ".github/requirements/security-code-scanning.txt",
    )
    for requirement_file in requirement_files:
        _run(
            (
                python,
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "--requirement",
                requirement_file,
            ),
            cwd=context.repo_root,
            label=f"install {requirement_file}",
        )

    ruff_version = _read_required_ruff_version(context.repo_root)
    _run(
        (python, "-m", "pip", "install", f"ruff=={ruff_version}"),
        cwd=context.repo_root,
        label=f"install Ruff {ruff_version}",
    )


def _read_required_ruff_version(repo_root: Path) -> str:
    for line in (repo_root / ".ruff.toml").read_text(encoding="utf-8").splitlines():
        key, separator, raw_value = line.partition("=")
        if separator and key.strip() == "required-version":
            version = raw_value.strip().strip('"').strip("'")
            if version.startswith("=="):
                return version[2:]
            raise GateError(".ruff.toml required-version must use an exact == pin.")
    raise GateError(".ruff.toml does not define required-version.")


def _read_super_linter_image(repo_root: Path) -> str:
    workflow_text = (
        repo_root / ".github" / "workflows" / "super-linter.yml"
    ).read_text(encoding="utf-8")
    matches = sorted(
        {
            line.strip()
            for line in workflow_text.splitlines()
            if line.strip().startswith("ghcr.io/super-linter/super-linter:")
        }
    )
    if len(matches) != 1:
        raise GateError(
            "Cannot detect exactly one pinned Super-Linter image from "
            ".github/workflows/super-linter.yml."
        )
    return matches[0]


def run_docs(context: GateContext) -> None:
    python = context.python
    _run_many(
        context,
        (
            ("docs structure", (python, "tools/lint_docs_structure.py")),
            (
                "docs lint tests",
                (python, "-m", "unittest", "-v", "tests/test_lint_docs_structure.py"),
            ),
        ),
    )


def run_regression_guard(context: GateContext) -> None:
    _run(
        (context.python, "tools/regression_guard.py", "scan", "--fail-on", "info"),
        cwd=context.repo_root,
        label="regression-guard scan",
    )
    _run(
        (context.python, "tools/regression_guard.py", "selfcheck"),
        cwd=context.repo_root,
        label="regression-guard selfcheck",
    )


def run_ruff(context: GateContext) -> None:
    ruff = _require_executable("ruff", context)
    _run_many(
        context,
        (
            ("ruff check", (ruff, "check", ".")),
            ("ruff format check", (ruff, "format", "--check", ".")),
        ),
    )


def run_mypy(context: GateContext) -> None:
    _run((context.python, "tools/mypy_check.py"), cwd=context.repo_root, label="mypy")


def run_vulture(context: GateContext) -> None:
    _run(
        (context.python, "tools/vulture_check.py"),
        cwd=context.repo_root,
        label="vulture",
    )


def run_tests(context: GateContext) -> None:
    python = context.python
    suites = (
        (".coverage.root", "tests/", "tests/"),
        (
            ".coverage.common",
            "omero_plugin_common/tests/",
            "omero_plugin_common/tests/",
        ),
        (
            ".coverage.imaris",
            "omeroweb_imaris_connector/tests/",
            "omeroweb_imaris_connector/tests/",
        ),
        (
            ".coverage.admin",
            "omeroweb_admin_tools/tests/",
            "omeroweb_admin_tools/tests/",
        ),
        (".coverage.omp", "omeroweb_omp_plugin/tests/", "omeroweb_omp_plugin/tests/"),
        (".coverage.import", "omeroweb_import/tests/", "omeroweb_import/tests/"),
        (".coverage.tools", "omeroweb_tools/tests/", "omeroweb_tools/tests/"),
        (".coverage.zarr", "omero_web_zarr/tests/", "omero_web_zarr/tests/"),
    )
    coverage_files = tuple(coverage_file for coverage_file, _, _ in suites)
    for coverage_file in coverage_files:
        (context.repo_root / coverage_file).unlink(missing_ok=True)
    for combined_artifact in (".coverage", "coverage.xml"):
        (context.repo_root / combined_artifact).unlink(missing_ok=True)

    failures: list[str] = []
    for coverage_file, suite_label, suite_path in suites:
        env = os.environ.copy()
        env["COVERAGE_FILE"] = coverage_file
        try:
            _run(
                (
                    python,
                    "-m",
                    "coverage",
                    "run",
                    "--rcfile=.coveragerc",
                    "-m",
                    "pytest",
                    suite_path,
                    "-v",
                    "-p",
                    "no:cacheprovider",
                    "-W",
                    "error",
                ),
                cwd=context.repo_root,
                env=env,
                label=f"pytest with coverage: {suite_label}",
            )
        except GateError as exc:
            if not context.keep_going:
                raise
            failures.append(str(exc))

    combine_steps = (
        (
            "coverage combine",
            (
                python,
                "-m",
                "coverage",
                "combine",
                "--rcfile=.coveragerc",
                *coverage_files,
            ),
        ),
        ("coverage xml", (python, "-m", "coverage", "xml", "--rcfile=.coveragerc")),
        (
            "coverage report",
            (python, "-m", "coverage", "report", "--rcfile=.coveragerc"),
        ),
    )
    for label, command in combine_steps:
        try:
            _run(command, cwd=context.repo_root, label=label)
        except GateError as exc:
            failures.append(str(exc))

    if failures:
        joined = "\n".join(f"- {failure}" for failure in failures)
        raise GateError(f"One or more test workflow steps failed:\n{joined}")


def discover_bandit_targets(repo_root: Path) -> BanditTargets:
    scan_dirs = tuple(
        sorted(
            path.name
            for path in repo_root.iterdir()
            if path.is_dir()
            and (path.name.startswith("omero_") or path.name.startswith("omeroweb_"))
            and (path / "__init__.py").is_file()
        )
    )

    package_test_dirs: list[str] = []
    for relative_dir in scan_dirs:
        root = repo_root / relative_dir
        for path in root.rglob("*"):
            if path.is_dir() and path.name in {"test", "tests"}:
                package_test_dirs.append(path.relative_to(repo_root).as_posix())

    package_test_dirs_tuple = tuple(sorted(package_test_dirs))
    test_dirs = list(package_test_dirs_tuple)
    if (repo_root / "tests").is_dir():
        test_dirs.append("tests")

    return BanditTargets(
        scan_dirs=scan_dirs,
        package_test_dirs=package_test_dirs_tuple,
        test_dirs=tuple(test_dirs),
        exclude_csv=",".join(package_test_dirs_tuple),
    )


def _sarif_result_count(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return sum(len(run.get("results", [])) for run in data.get("runs", []))


def run_bandit(context: GateContext) -> None:
    bandit = _require_executable("bandit", context)
    context.artifact_dir.mkdir(parents=True, exist_ok=True)
    targets = discover_bandit_targets(context.repo_root)
    print(f"Bandit production directories: {' '.join(targets.scan_dirs) or 'none'}")
    print(f"Bandit test directories: {' '.join(targets.test_dirs) or 'none'}")

    failures: list[str] = []
    if targets.scan_dirs:
        prod_output = context.artifact_dir / "bandit-prod.sarif"
        command: list[str] = [
            bandit,
            "-r",
            *targets.scan_dirs,
        ]
        if targets.exclude_csv:
            command.extend(("--exclude", targets.exclude_csv))
        command.extend(
            (
                "--skip",
                "B603,B404",
                "-f",
                "sarif",
                "-o",
                str(prod_output),
                "--exit-zero",
            )
        )
        _run(command, cwd=context.repo_root, label="bandit production scan")
        prod_count = _sarif_result_count(prod_output)
        if prod_count:
            failures.append(f"Bandit production scan produced {prod_count} result(s).")

    if targets.test_dirs:
        test_output = context.artifact_dir / "bandit-test.sarif"
        _run(
            (
                bandit,
                "-r",
                *targets.test_dirs,
                "--skip",
                "B101,B106,B603,B404",
                "-f",
                "sarif",
                "-o",
                str(test_output),
                "--exit-zero",
            ),
            cwd=context.repo_root,
            label="bandit test scan",
        )
        test_count = _sarif_result_count(test_output)
        if test_count:
            failures.append(f"Bandit test scan produced {test_count} result(s).")

    if failures:
        raise GateError("\n".join(failures))


def run_super_linter(context: GateContext) -> None:
    docker = _require_executable("docker", context)
    default_branch = _default_branch(context.repo_root)
    super_linter_image = _read_super_linter_image(context.repo_root)
    env = os.environ.copy()
    env.update(
        {
            "DEFAULT_BRANCH": default_branch,
            "DEFAULT_WORKSPACE": str(context.repo_root),
            "FILTER_REGEX_EXCLUDE": r"(^|/)third_party/(ecc-v1\.10\.0|caveman-v1\.6\.0)/",
            "LINTER_RULES_PATH": ".",
            "MARKDOWN_CONFIG_FILE": ".markdownlint.yaml",
            "RUN_LOCAL": "true",
            "YAML_CONFIG_FILE": ".yamllint",
            "VALIDATE_ALL_CODEBASE": "true",
            "VALIDATE_GIT_MERGE_CONFLICT_MARKERS": "true",
            "VALIDATE_GITHUB_ACTIONS": "true",
            "VALIDATE_GITHUB_ACTIONS_ZIZMOR": "true",
            "VALIDATE_MARKDOWN": "true",
            "VALIDATE_YAML": "true",
        }
    )
    _run(
        (
            docker,
            "run",
            "--rm",
            "--workdir",
            str(context.repo_root),
            "-e",
            "DEFAULT_BRANCH",
            "-e",
            f"DEFAULT_WORKSPACE={context.repo_root}",
            "-e",
            "FILTER_REGEX_EXCLUDE",
            "-e",
            "LINTER_RULES_PATH",
            "-e",
            "MARKDOWN_CONFIG_FILE",
            "-e",
            "RUN_LOCAL",
            "-e",
            "YAML_CONFIG_FILE",
            "-e",
            "VALIDATE_ALL_CODEBASE",
            "-e",
            "VALIDATE_GIT_MERGE_CONFLICT_MARKERS",
            "-e",
            "VALIDATE_GITHUB_ACTIONS",
            "-e",
            "VALIDATE_GITHUB_ACTIONS_ZIZMOR",
            "-e",
            "VALIDATE_MARKDOWN",
            "-e",
            "VALIDATE_YAML",
            "-v",
            f"{context.repo_root}:{context.repo_root}",
            super_linter_image,
        ),
        cwd=context.repo_root,
        env=env,
        label="super-linter",
    )


GateRunner = Callable[[GateContext], None]

PROFILES: dict[str, tuple[GateRunner, ...]] = {
    "docs": (run_docs,),
    "ruff": (run_ruff,),
    "mypy": (run_mypy,),
    "vulture": (run_vulture,),
    "tests": (run_tests,),
    "bandit": (run_bandit,),
    "regression-guard": (run_regression_guard,),
    "super-linter": (run_super_linter,),
    "python": (run_ruff, run_mypy, run_vulture),
    "ci": (
        run_docs,
        run_regression_guard,
        run_ruff,
        run_mypy,
        run_vulture,
        run_tests,
        run_bandit,
    ),
    "all": (
        run_docs,
        run_regression_guard,
        run_ruff,
        run_mypy,
        run_vulture,
        run_tests,
        run_bandit,
        run_super_linter,
    ),
}


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run locally reproducible gates from the GitHub workflows."
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="ci",
        help=(
            "Gate profile to run. 'ci' mirrors docs, Ruff, Mypy, Vulture, tests, "
            "and Bandit. 'all' also runs the Docker-backed Super-Linter."
        ),
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(
            os.environ.get("LOCAL_WORKFLOW_GATE_ARTIFACT_DIR", DEFAULT_ARTIFACT_DIR)
        ),
        help="Directory for local scanner artifacts.",
    )
    parser.add_argument(
        "--tool-venv",
        type=Path,
        default=None,
        help=(
            "Python tool environment for workflow dependencies. Defaults to "
            "LOCAL_WORKFLOW_GATE_VENV or the artifact directory."
        ),
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Install hash-pinned Python workflow dependencies before running gates.",
    )
    parser.add_argument(
        "--setup-only",
        action="store_true",
        help="Install Python workflow dependencies and exit without running gates.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue independent gates after a failure, then fail at the end.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    artifact_dir = args.artifact_dir.resolve()
    tool_venv = (
        args.tool_venv
        or Path(
            os.environ.get("LOCAL_WORKFLOW_GATE_VENV", artifact_dir / "python-venv")
        )
    ).resolve()
    python = (
        str(tool_venv / "bin" / "python")
        if (tool_venv / "bin" / "python").is_file()
        else sys.executable
    )
    context = GateContext(
        repo_root=REPO_ROOT,
        artifact_dir=artifact_dir,
        tool_venv=tool_venv,
        python=python,
        keep_going=args.keep_going,
    )

    print(f"Repository root: {context.repo_root}")
    print(f"Artifact directory: {context.artifact_dir}")
    print(f"Python tool environment: {context.tool_venv}")
    print(f"Profile: {args.profile}")
    try:
        if args.setup or args.setup_only:
            _install_python_workflow_dependencies(context)
            context = GateContext(
                repo_root=context.repo_root,
                artifact_dir=context.artifact_dir,
                tool_venv=context.tool_venv,
                python=str(context.tool_venv / "bin" / "python"),
                keep_going=context.keep_going,
            )
        if args.setup_only:
            print("\nLocal workflow Python tools are installed.")
            return 0
        for runner in PROFILES[args.profile]:
            runner(context)
    except GateError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1

    print("\nLocal workflow gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
