"""Protect complete runtime cohorts without changing operator deployment inputs."""

from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def requirements(path):
    """Inputs: reviewed requirement file. Output: parsed, unique named requirements."""
    rows = [
        Requirement(line)
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    result = {canonicalize_name(row.name): row for row in rows}
    assert len(result) == len(rows)
    assert all(row.url is None and row.marker is None for row in rows)
    return result


@pytest.mark.parametrize("role", ["server", "web"])
def test_runtime_update_roots_are_in_the_complete_exact_cohort(role):
    """Inputs: direct inputs and resolved cohort. Output: no missing, floating, or conflicting pin."""
    roots = requirements(ROOT / f"docker/requirements-runtime-{role}.in")
    cohort = requirements(ROOT / f"docker/requirements-runtime-{role}.txt")
    assert roots.keys() < cohort.keys()
    for name, requirement in cohort.items():
        specifiers = list(requirement.specifier)
        assert len(specifiers) == 1
        assert specifiers[0].operator == "==" and "*" not in specifiers[0].version
        if name in roots:
            assert requirement.specifier == roots[name].specifier
    assert not {"tifffile", "bioformats2raw", "omero-figure"} & cohort.keys()


def test_runtime_transitive_network_and_web_constraints_remain_aligned():
    """Inputs: runtime cohorts. Output: complete HTTP/2 and supported OMERO web dependencies."""
    server = requirements(ROOT / "docker/requirements-runtime-server.txt")
    web = requirements(ROOT / "docker/requirements-runtime-web.txt")
    assert {"httpx", "httpcore", "h11", "h2", "hpack", "hyperframe"} < server.keys()
    for name in {"certifi", "charset-normalizer", "idna"}:
        assert server[name].specifier == web[name].specifier
    assert str(web["django"].specifier) == "==5.2.18"
    assert str(web["django-cors-headers"].specifier) == "==3.7.0"
    assert str(web["omero-web"].specifier) == "==5.33.2"
    assert str(web["omero-py"].specifier) == "==5.23.0"


def test_dependabot_monitors_runtime_python_inputs_and_locks():
    """Inputs: actual Dependabot policy. Output: runtime cohorts cannot fall outside update discovery."""
    policy = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    matches = [
        item
        for item in policy["updates"]
        if item["package-ecosystem"] == "pip" and item["directory"] == "/docker"
    ]
    assert len(matches) == 1
    assert matches[0]["schedule"]["interval"] == "weekly"
    assert matches[0]["open-pull-requests-limit"] > 0
