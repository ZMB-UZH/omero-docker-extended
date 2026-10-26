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
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    )
    assert checkout["with"]["persist-credentials"] is False
    assert setup_python["uses"] == (
        "actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0"
    )
    assert setup_python["with"]["python-version"] == "3.14.8"
    assert prepare["run"] == "python3 -m tools.prepare_ci_compose_environment"

    script = validate["run"]
    services = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())[
        "services"
    ]
    profiles = {
        profile
        for service in services.values()
        for profile in service.get("profiles", [])
    }
    images = {service["image"] for service in services.values()}
    builds = {name for name, service in services.items() if "build" in service}
    assert '"${compose[@]}" config --quiet' in script
    assert '"${compose[@]}" config --services' in script
    assert f'[ "${{#services[@]}}" -eq {len(services)} ]' in script
    assert '"${compose[@]}" config --profiles' in script
    assert f'[ "${{#profiles[@]}}" -eq {len(profiles)} ]' in script
    assert '"${compose[@]}" config --images' in script
    assert f'[ "${{#images[@]}}" -eq {len(images)} ]' in script
    assert "*:latest" in script
    assert '"${compose[@]}" build --print' in script
    assert f"len(targets) != {len(builds)}" in script
    assert "docker buildx bake" in script
    assert '--file "${bake_plan}"' in script
    assert "--check" in script
    assert "--set '*.output=type=cacheonly'" in script
    assert "docker compose build" not in script
    assert "python3 -m unittest -v tests.container_tls_image" in script
