"""Run composite smoke checks for agent-surface contract tests."""

from __future__ import annotations

import argparse
import py_compile
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_command(command: list[str]) -> int:
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    return completed.returncode


def _plugin_suite_fallback() -> int:
    smoke_commands = [
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--noconftest",
            "-p",
            "no:cacheprovider",
            "-W",
            "error",
            "tests/test_admin_tools_security_regressions.py",
            "omeroweb_admin_tools/tests/test_log_query.py",
            "omeroweb_imaris_connector/tests/test_security_regressions.py",
        ]
    ]
    for command in smoke_commands:
        if _run_command(command) != 0:
            return 1

    for relative_path in (
        "omeroweb_import/tests/test_cli_runtime_env.py",
        "omeroweb_import/tests/test_security_hardening.py",
        "omeroweb_omp_plugin/tests/test_log_sanitization.py",
    ):
        py_compile.compile(
            str(REPO_ROOT / relative_path),
            doraise=True,
        )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a named composite smoke profile for agent-surface tests."
    )
    parser.add_argument("profile", help="Smoke profile to run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    profile = args.profile
    if profile == "plugin-suite-fallback":
        return _plugin_suite_fallback()

    print(f"Unknown smoke profile: {profile}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
