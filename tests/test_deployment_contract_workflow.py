from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deployment-contracts.yml"


def test_deployment_contract_workflow_is_default_branch_only_and_least_privilege() -> (
    None
):
    """Verify the deployment workflow trigger and permission boundary.

    Inputs: repository workflow fixture. Output: fails on trigger or permission drift.
    """
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    triggers = workflow[True]

    assert "workflow_dispatch" in triggers
    assert triggers["push"] is None
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["deployment-contracts"]
    assert job["if"] == "github.ref_name == github.event.repository.default_branch"
    assert job["permissions"] == {"contents": "read"}
    assert "environment" not in job


def test_deployment_contract_workflow_validates_full_compose_build_graph() -> None:
    """Verify the complete non-mutating Compose and Buildx validation graph.

    Inputs: repository workflow fixture. Output: fails on deployment-check drift.
    """
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["deployment-contracts"]["steps"]
    checkout = next(step for step in steps if step["name"] == "Checkout")
    setup_python = next(step for step in steps if step["name"] == "Setup Python")
    prepare = next(
        step
        for step in steps
        if step["name"] == "Prepare synthetic CI environment files"
    )
    validate = next(
        step for step in steps if step["name"] == "Validate Compose and build contracts"
    )

    assert checkout["uses"] == (
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
    )
    assert checkout["with"]["persist-credentials"] is False
    assert setup_python["uses"] == (
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
    )
    assert setup_python["with"]["python-version"] == "3.14.4"
    assert prepare["run"] == "python3 tools/prepare_ci_compose_environment.py"

    script = validate["run"]
    assert '"${compose[@]}" config --quiet' in script
    assert '"${compose[@]}" config --services' in script
    assert '[ "${#services[@]}" -eq 21 ]' in script
    assert '"${compose[@]}" config --profiles' in script
    assert '[ "${#profiles[@]}" -eq 2 ]' in script
    assert '"${compose[@]}" config --images' in script
    assert '[ "${#images[@]}" -eq 19 ]' in script
    assert "*:latest" in script
    assert '"${compose[@]}" build --print' in script
    assert "len(targets) != 6" in script
    assert "docker buildx bake" in script
    assert '--file "${bake_plan}"' in script
    assert "--check" in script
    assert "--set '*.output=type=cacheonly'" in script
    assert "docker compose build" not in script
