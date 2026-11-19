"""Protect complete runtime cohorts without changing operator deployment inputs."""

from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "docker/runtime"


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
    roots = requirements(RUNTIME / role / "requirements.in")
    cohort = requirements(RUNTIME / role / "requirements.txt")
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
    server = requirements(RUNTIME / "server/requirements.txt")
    web = requirements(RUNTIME / "web/requirements.txt")
    assert {"httpx", "httpcore", "h11", "h2", "hpack", "hyperframe"} < server.keys()
    for name in {"certifi", "charset-normalizer", "idna"}:
        assert server[name].specifier == web[name].specifier
    assert str(web["django"].specifier) == "==5.2.19"
    assert str(web["django-cors-headers"].specifier) == "==3.7.0"
    assert str(web["omero-web"].specifier) == "==5.33.4"
    assert str(web["omero-py"].specifier) == "==5.23.0"


@pytest.mark.parametrize(("role", "minor"), [("server", 11), ("web", 12)])
def test_runtime_dependency_consumers_use_the_correct_python_cohort(role, minor):
    """Inputs: runtime files and consumers. Output: split resolver and scan coverage."""
    policy = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    role_path = RUNTIME / role
    directory = role_path.relative_to(ROOT).as_posix()
    matches = [
        item
        for item in policy["updates"]
        if item["package-ecosystem"] == "pip" and item["directory"] == f"/{directory}"
    ]
    assert len(matches) == 1
    assert matches[0]["schedule"]["interval"] == "weekly"
    assert matches[0]["open-pull-requests-limit"] > 0
    assert not any(
        item["package-ecosystem"] == "pip" and item["directory"] == "/docker"
        for item in policy["updates"]
    )
    resolver = Version((role_path / ".python-version").read_text().strip())
    assert len(resolver.release) == 3 and resolver.release[:2] == (3, minor)

    lockfile = f"{directory}/requirements.txt"
    assert (
        f"COPY {lockfile} /tmp/requirements-runtime-{role}.txt"
        in (ROOT / f"docker/omero-{role}.Dockerfile").read_text()
    )
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/security-code-scanning.yml").read_text()
    )
    assert f"--lockfile=requirements.txt:{lockfile}" in (
        workflow["jobs"]["osv-scanner"]["with"]["scan-args"].splitlines()
    )
