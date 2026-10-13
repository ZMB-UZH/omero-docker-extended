"""Execute the hosted deployment contract against an isolated candidate copy."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess

import yaml

from tools.prepare_ci_compose_environment import prepare_ci_compose_environment
from tools.run_local_workflow_gates import tracked_source_paths


ROOT = Path(__file__).resolve().parents[1]


def test_hosted_deployment_contracts_on_candidate(tmp_path: Path) -> None:
    """Inputs: Git-selected source and Docker. Output: complete Compose/Bake parity without live env files."""
    bash = shutil.which("bash")
    assert bash and shutil.which("docker"), "Deployment checks require Bash and Docker."
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    paths = tracked_source_paths(ROOT)
    assert paths, "Deployment checks require a non-empty Git candidate."
    for name in paths:
        relative = PurePosixPath(name)
        source = ROOT / relative
        assert not relative.is_absolute() and ".." not in relative.parts
        assert not source.is_symlink() and source.resolve().is_relative_to(ROOT)
        if not source.exists():
            continue  # A tracked deletion must remain absent in the candidate.
        assert source.is_file()
        target = candidate / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    values = prepare_ci_compose_environment(candidate, tmp_path / "github-env")
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("COMPOSE_")
    }
    environment.update(values, RUNNER_TEMP=str(tmp_path))
    workflow = yaml.safe_load(
        (candidate / ".github/workflows/deployment-contracts.yml").read_text()
    )
    steps = workflow["jobs"]["deployment-contracts"]["steps"]
    scripts = [
        step["run"]
        for step in steps
        if step["name"] == "Validate Compose and build contracts"
    ]
    assert len(scripts) == 1 and "${{" not in scripts[0]
    result = subprocess.run(
        [bash, "-e", "-o", "pipefail", "-c", scripts[0]],
        cwd=candidate,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
