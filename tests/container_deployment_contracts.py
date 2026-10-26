"""Execute the hosted deployment contract against an isolated candidate copy."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess

import pytest
import yaml

from tools.prepare_ci_compose_environment import prepare_ci_compose_environment
from tools.run_local_workflow_gates import tracked_source_paths


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def candidate_environment(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Inputs: Git-selected source. Output: an isolated candidate and synthetic configuration."""
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
    return candidate, environment


def test_hosted_deployment_contracts_on_candidate(
    candidate_environment, tmp_path: Path
) -> None:
    """Inputs: synthetic candidate and Docker. Output: exact hosted Compose/Bake validation."""
    candidate, environment = candidate_environment
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
        [shutil.which("bash"), "-e", "-o", "pipefail", "-c", scripts[0]],
        cwd=candidate,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    plan = json.loads((tmp_path / "compose-bake-plan.json").read_text())
    assert (
        plan["target"]["omeroserver"]["args"]["TIFFFILE_VERSION"]
        == environment["TIFFFILE_VERSION"]
    )
    assert (
        plan["target"]["omeroweb"]["args"]["TIFFFILE_VERSION"]
        == environment["WEB_TIFFFILE_VERSION"]
    )


@pytest.mark.parametrize("web_override", [None, "", "2026.10.15"])
def test_legacy_web_tifffile_fallback_preserves_the_server_pin(
    candidate_environment, web_override
):
    """Inputs: old environment files and optional web override. Output: real Compose interpolation parity."""
    candidate, environment = candidate_environment
    docker = shutil.which("docker")
    assert docker, "Deployment checks require Docker."
    server_env = candidate / "env/omeroserver.env"
    server_env.write_text(
        "\n".join(
            line
            for line in server_env.read_text().splitlines()
            if not line.startswith("WEB_TIFFFILE_VERSION=")
        )
        + "\n"
    )
    environment.pop("WEB_TIFFFILE_VERSION", None)
    if web_override is not None:
        environment["WEB_TIFFFILE_VERSION"] = web_override
    result = subprocess.run(
        [docker, "compose", "-f", "docker-compose.yml", "config", "--format=json"],
        cwd=candidate,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert (
        services["omeroserver"]["build"]["args"]["TIFFFILE_VERSION"]
        == environment["TIFFFILE_VERSION"]
    )
    assert services["omeroweb"]["build"]["args"]["TIFFFILE_VERSION"] == (
        web_override or environment["TIFFFILE_VERSION"]
    )
