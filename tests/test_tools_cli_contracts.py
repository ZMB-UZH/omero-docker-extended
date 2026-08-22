"""CLI contract tests for repo-local tools."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

CLI_TOOLS = (
    "env_safety_guard.py",
    "cocoindex_agent_search.py",
    "extract_dockerfile_pip_deps.py",
    "frontend_preview_tooling.py",
    "git_push_with_pat.py",
    "lint_docs_structure.py",
    "mypy_check.py",
    "run_agent_skill_smoke.py",
    "run_local_workflow_gates.py",
    "sarif_result_guard.py",
    "scanner_inventory.py",
    "security_delta_guard.py",
    "update_readme_badges.py",
    "verify_agent_skill_provenance.py",
    "vulture_check.py",
    "write_branding_logo_fallback.py",
)


@pytest.mark.parametrize("tool_name", CLI_TOOLS)
def test_cli_tool_supports_help(tool_name: str) -> None:
    """Verify the CLI tool supports help execution contract.

    Inputs: pytest provides `tool_name`. Output: fails on regressions in CLI tool supports help.
    """
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / tool_name), "--help"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    combined_output = f"{result.stdout}\n{result.stderr}".lower()
    assert result.returncode == 0
    assert "usage:" in combined_output
