from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from tools.env_safety_guard import ENV_TEMPLATE_PAIRS
from tools.prepare_ci_compose_environment import (
    CiComposeEnvironmentError,
    prepare_ci_compose_environment,
)


def _write_contracts(root: Path) -> None:
    """Create a complete synthetic environment-template surface.

    Inputs: temporary repository `root`. Output: tracked-style example files.
    """
    contracts = ((".env_example", ".env"), *ENV_TEMPLATE_PAIRS)
    for index, (source, _target) in enumerate(contracts):
        source_path = root / source
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(f"CONTRACT_{index}=value-{index}\n", encoding="utf-8")
    (root / ".env_example").write_text(
        "ROOT=/ignored\n"
        "OMERO_INSTALLATION_PATH=${ROOT}/old\n"
        "NESTED=${OMERO_INSTALLATION_PATH}/nested\n",
        encoding="utf-8",
    )
    (root / "installation_paths_example.env").write_text(
        "OMERO_DATA_PATH=${OMERO_INSTALLATION_PATH}/data\n",
        encoding="utf-8",
    )


def _profile_runner(stdout: str = "sysctl-init\ncrowdsec\n"):
    """Create a deterministic Compose profile command double.

    Inputs: command `stdout`. Output: validating subprocess-compatible runner.
    """

    def run(command, **kwargs):
        """Validate a Compose profile command and return configured output.

        Inputs: command sequence and subprocess keyword arguments. Output:
        successful completed process.
        """
        assert command == [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "config",
            "--profiles",
        ]
        assert kwargs["check"] is True
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return run


def test_prepare_ci_environment_creates_private_resolved_contracts(
    tmp_path: Path,
) -> None:
    """Verify complete preparation, reference resolution, and private modes.

    Inputs: pytest `tmp_path`. Output: fails on synthetic environment drift.
    """
    _write_contracts(tmp_path)
    github_environment = tmp_path / "github" / "environment"

    values = prepare_ci_compose_environment(
        tmp_path,
        github_environment,
        run_command=_profile_runner("sysctl-init\ncrowdsec\nsysctl-init\n"),
    )

    assert values["OMERO_INSTALLATION_PATH"] == str(tmp_path.resolve())
    assert values["OMERO_DATA_PATH"] == f"{tmp_path.resolve()}/data"
    assert values["NESTED"] == f"{tmp_path.resolve()}/nested"
    assert values["COMPOSE_PROFILES"] == "crowdsec,sysctl-init"
    for _source, target in ((".env_example", ".env"), *ENV_TEMPLATE_PAIRS):
        target_path = tmp_path / target
        assert target_path.is_file()
        assert stat.S_IMODE(target_path.stat().st_mode) == 0o600

    github_text = github_environment.read_text(encoding="utf-8")
    assert stat.S_IMODE(github_environment.stat().st_mode) == 0o600
    assert "COMPOSE_PROFILES<<OMERO_ENV_COMPOSE_PROFILES_" in github_text
    assert "crowdsec,sysctl-init" in github_text


def test_prepare_ci_environment_refuses_existing_operator_file(tmp_path: Path) -> None:
    """Verify an existing operator file prevents all preparation.

    Inputs: pytest `tmp_path`. Output: preserves operator state and reports refusal.
    """
    _write_contracts(tmp_path)
    existing = tmp_path / "installation_paths.env"
    existing.write_text("operator-owned\n", encoding="utf-8")

    with pytest.raises(CiComposeEnvironmentError, match="Refusing to overwrite"):
        prepare_ci_compose_environment(
            tmp_path,
            tmp_path / "github-env",
            run_command=_profile_runner(),
        )

    assert existing.read_text(encoding="utf-8") == "operator-owned\n"
    assert not (tmp_path / ".env").exists()


def test_prepare_ci_environment_reports_all_missing_contracts(tmp_path: Path) -> None:
    """Verify missing contracts are reported before runtime files are created.

    Inputs: pytest `tmp_path`. Output: fails on partial preparation.
    """
    with pytest.raises(CiComposeEnvironmentError, match="Missing environment contract"):
        prepare_ci_compose_environment(
            tmp_path,
            tmp_path / "github-env",
            run_command=_profile_runner(),
        )

    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "installation_paths.env").exists()


def test_prepare_ci_environment_cleans_partial_files_after_unsafe_value(
    tmp_path: Path,
) -> None:
    """Verify unsafe reference failure removes every generated file.

    Inputs: pytest `tmp_path`. Output: fails on residual runtime files.
    """
    _write_contracts(tmp_path)
    (tmp_path / ".env_example").write_text("BAD=$(id)\n", encoding="utf-8")

    with pytest.raises(CiComposeEnvironmentError, match="Unsafe synthetic"):
        prepare_ci_compose_environment(
            tmp_path,
            tmp_path / "github-env",
            run_command=_profile_runner(),
        )

    for _source, target in ((".env_example", ".env"), *ENV_TEMPLATE_PAIRS):
        assert not (tmp_path / target).exists()


def test_prepare_ci_environment_requires_at_least_one_profile(tmp_path: Path) -> None:
    """Verify a Compose graph must expose at least one profile.

    Inputs: pytest `tmp_path`. Output: rejects an empty profile set.
    """
    _write_contracts(tmp_path)

    with pytest.raises(CiComposeEnvironmentError, match="No Compose profiles"):
        prepare_ci_compose_environment(
            tmp_path,
            tmp_path / "github-env",
            run_command=_profile_runner("\n"),
        )

    assert not (tmp_path / ".env").exists()


def test_prepare_ci_environment_rejects_malformed_assignment(tmp_path: Path) -> None:
    """Verify malformed environment keys fail closed.

    Inputs: pytest `tmp_path`. Output: rejects a malformed key.
    """
    _write_contracts(tmp_path)
    (tmp_path / ".env_example").write_text("INVALID-KEY=value\n", encoding="utf-8")

    with pytest.raises(CiComposeEnvironmentError, match="Invalid environment key"):
        prepare_ci_compose_environment(
            tmp_path,
            tmp_path / "github-env",
            run_command=_profile_runner(),
        )

    assert not (tmp_path / ".env").exists()


def test_prepare_ci_environment_cleans_files_after_compose_failure(
    tmp_path: Path,
) -> None:
    """Verify Compose discovery failure removes synthetic files.

    Inputs: pytest `tmp_path`. Output: fails on residual deployment files.
    """
    _write_contracts(tmp_path)

    def failed_runner(command, **kwargs):
        """Raise a deterministic Compose command failure.

        Inputs: command sequence and subprocess keyword arguments. Output: none;
        raises `CalledProcessError`.
        """
        raise subprocess.CalledProcessError(17, command, stderr="compose failed")

    with pytest.raises(CiComposeEnvironmentError, match="discover Compose profiles"):
        prepare_ci_compose_environment(
            tmp_path,
            tmp_path / "github-env",
            run_command=failed_runner,
        )

    for _source, target in ((".env_example", ".env"), *ENV_TEMPLATE_PAIRS):
        assert not (tmp_path / target).exists()


def test_prepare_ci_environment_refuses_symlinked_github_environment(
    tmp_path: Path,
) -> None:
    """Verify GitHub environment symlinks cannot redirect exported values.

    Inputs: pytest `tmp_path`. Output: preserves the symlink target and reports refusal.
    """
    _write_contracts(tmp_path)
    victim = tmp_path / "victim"
    victim.write_text("operator-owned\n", encoding="utf-8")
    github_environment = tmp_path / "github-env"
    os.symlink(victim, github_environment)

    with pytest.raises(CiComposeEnvironmentError, match="safely open"):
        prepare_ci_compose_environment(
            tmp_path,
            github_environment,
            run_command=_profile_runner(),
        )

    assert victim.read_text(encoding="utf-8") == "operator-owned\n"
    assert not (tmp_path / ".env").exists()
