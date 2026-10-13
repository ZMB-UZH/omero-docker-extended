from __future__ import annotations

import os
import errno
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.env_safety_guard import ENV_TEMPLATE_PAIRS
from tools import prepare_ci_compose_environment as environment
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


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink"])
def test_contract_copy_rejects_nonregular_sources(tmp_path, kind):
    """Inputs: unsafe contract sources. Output: no target creation or external modification."""
    source = tmp_path / "example"
    outside = tmp_path / "outside"
    outside.write_bytes(b"preserved")
    if kind == "directory":
        source.mkdir()
    elif kind == "symlink":
        source.symlink_to(outside)
    target = tmp_path / "runtime"
    with pytest.raises(CiComposeEnvironmentError, match="contract"):
        environment._copy_contract_exclusively(source, target)
    assert not target.exists()
    assert outside.read_bytes() == b"preserved"


@pytest.mark.parametrize("mode", ["rb", "wb"])
def test_contract_copy_closes_descriptors_after_stream_open_failure(
    tmp_path, monkeypatch, mode
):
    """Inputs: stream creation failure. Output: closed descriptors and no partial target."""
    source = tmp_path / "example"
    source.write_bytes(b"synthetic=value\n")
    target = tmp_path / "runtime"
    descriptors = []
    original = os.fdopen

    def fdopen(descriptor, actual_mode, *args, **kwargs):
        """Inputs: native descriptor. Output: injected failure before ownership transfers."""
        if actual_mode == mode:
            descriptors.append(descriptor)
            raise OSError(errno.EMFILE, "fixture stream allocation failure")
        return original(descriptor, actual_mode, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", fdopen)
    with pytest.raises((OSError, CiComposeEnvironmentError)):
        environment._copy_contract_exclusively(source, target)
    try:
        for descriptor in descriptors:
            with pytest.raises(OSError) as error:
                os.fstat(descriptor)
            assert error.value.errno == errno.EBADF
    finally:
        # Close only a leaked descriptor owned by this fixture, even on a failed assertion.
        for descriptor in descriptors:
            try:
                os.fstat(descriptor)
            except OSError:
                continue
            os.close(descriptor)
    assert not target.exists()
    assert source.read_bytes() == b"synthetic=value\n"


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_exclusive_copy_preserves_target_created_after_preflight(tmp_path, kind):
    """Inputs: target appearing after inventory. Output: exclusive open refuses replacement."""
    source = tmp_path / "example"
    source.write_bytes(b"new synthetic value")
    target = tmp_path / "runtime"
    outside = tmp_path / "outside"
    outside.write_bytes(b"preserved")
    if kind == "symlink":
        target.symlink_to(outside)
    else:
        target.write_bytes(b"preserved")
    with pytest.raises(CiComposeEnvironmentError, match="Refusing to overwrite"):
        environment._copy_contract_exclusively(source, target)
    assert target.read_bytes() == outside.read_bytes() == b"preserved"
    assert target.is_symlink() == (kind == "symlink")


def test_copy_fsync_failure_removes_only_its_partial_target(tmp_path, monkeypatch):
    """Inputs: durability failure. Output: no successful or partial runtime contract."""
    source = tmp_path / "example"
    source.write_bytes(b"synthetic=value\n")
    target = tmp_path / "runtime"

    def fail_sync(_descriptor):
        """Inputs: pending descriptor. Output: injected storage failure."""
        raise OSError(errno.EIO, "fixture synchronization failure")

    monkeypatch.setattr(os, "fsync", fail_sync)
    with pytest.raises(OSError, match="synchronization failure"):
        environment._copy_contract_exclusively(source, target)
    assert not target.exists()
    assert source.read_bytes() == b"synthetic=value\n"


@pytest.mark.parametrize(
    "payload", [None, b"invalid=\xff", b"REPEATED=a\nREPEATED=b\n"]
)
def test_load_rejects_unreadable_or_ambiguous_contract(tmp_path, payload):
    """Inputs: missing, undecodable or duplicate contract. Output: fail closed with no values printed."""
    path = tmp_path / "runtime"
    if payload is not None:
        path.write_bytes(payload)
    with pytest.raises(CiComposeEnvironmentError, match="Invalid synthetic"):
        environment._load_environment_values([(tmp_path / "example", path)])


def test_load_ignores_comments_and_accepts_export_syntax(tmp_path):
    """Inputs: harmless shell-style formatting. Output: literal assignment parser semantics."""
    path = tmp_path / "runtime"
    path.write_text(
        "\n# comment\nnot-an-assignment\nexport FIRST=one\nSECOND='two words'\n"
    )
    assert environment._load_environment_values([(path, path)]) == {
        "FIRST": "one",
        "SECOND": "two words",
    }


def test_resolution_rejects_unterminated_reference(tmp_path):
    """Inputs: unfinished expansion. Output: no malformed environment reaches Compose."""
    with pytest.raises(
        CiComposeEnvironmentError,
        match="Unsafe synthetic.*unsupported parameter expansion",
    ):
        environment._resolve_environment_values(tmp_path, {"BROKEN": "${UNFINISHED"})


def test_environment_channel_rejects_delimiter_collision(tmp_path, monkeypatch):
    """Inputs: value containing its generated delimiter. Output: no channel mutation."""
    path = tmp_path / "github-env"
    path.write_text("EXISTING=value\n")
    monkeypatch.setattr(
        environment.uuid, "uuid4", lambda: SimpleNamespace(hex="fixture")
    )
    with pytest.raises(CiComposeEnvironmentError, match="Could not encode"):
        environment._append_github_environment(
            path, {"VALUE": "OMERO_ENV_VALUE_fixture"}
        )
    assert path.read_text() == "EXISTING=value\n"


def test_environment_channel_rejects_fifo_without_blocking(tmp_path):
    """Inputs: open FIFO in place of a regular channel. Output: immediate refusal."""
    path = tmp_path / "channel"
    os.mkfifo(path, mode=0o600)
    reader = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    try:
        with pytest.raises(CiComposeEnvironmentError, match="not a regular file"):
            environment._append_github_environment(path, {"VALUE": "synthetic"})
        assert stat.S_ISFIFO(path.stat().st_mode)
    finally:
        os.close(reader)


def test_environment_channel_permission_failure_closes_descriptor(
    tmp_path, monkeypatch
):
    """Inputs: rejected permission change. Output: original channel preserved and descriptor closed."""
    path = tmp_path / "channel"
    path.write_text("EXISTING=value\n")
    descriptors = []

    def fail_mode(descriptor, _mode):
        """Inputs: opened channel. Output: injected filesystem permission failure."""
        descriptors.append(descriptor)
        raise PermissionError(errno.EPERM, "fixture permission failure")

    monkeypatch.setattr(os, "fchmod", fail_mode)
    with pytest.raises(CiComposeEnvironmentError, match="Could not write"):
        environment._append_github_environment(path, {"NEW": "synthetic"})
    for descriptor in descriptors:
        with pytest.raises(OSError) as error:
            os.fstat(descriptor)
        assert error.value.errno == errno.EBADF
    assert path.read_text() == "EXISTING=value\n"


@pytest.mark.parametrize("explicit_channel", [False, True])
def test_prepare_cli_resolves_contracts_without_logging_values(
    tmp_path, explicit_channel
):
    """Inputs: real CLI and a deterministic Compose executable. Output: private resolved files."""
    _write_contracts(tmp_path)
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "if sys.argv[1:] != ['compose', '-f', 'docker-compose.yml', 'config', '--profiles']:\n"
        "    raise SystemExit(9)\n"
        "print('ci-fixture')\n"
    )
    docker.chmod(0o700)
    channel = tmp_path / "channel"
    child_env = dict(
        os.environ, PATH=str(binary) + os.pathsep + os.environ.get("PATH", "")
    )
    child_env.pop("GITHUB_ENV", None)
    arguments = [
        sys.executable,
        "-m",
        "tools.prepare_ci_compose_environment",
        "--root",
        str(tmp_path),
    ]
    if explicit_channel:
        arguments.extend(["--github-env", str(channel)])
    else:
        child_env["GITHUB_ENV"] = str(channel)
    result = subprocess.run(
        arguments,
        cwd=Path(__file__).resolve().parents[1],
        env=child_env,
        check=False,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "Prepared" in result.stdout and "resolved values" in result.stdout
    assert "value-" not in result.stdout and str(tmp_path) not in result.stdout
    assert "ci-fixture" in channel.read_text()
    assert stat.S_IMODE(channel.stat().st_mode) == 0o600


def test_prepare_cli_requires_channel_before_creating_files(tmp_path, monkeypatch):
    """Inputs: absent channel argument. Output: refusal before any contract side effect."""
    _write_contracts(tmp_path)
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    with pytest.raises(CiComposeEnvironmentError, match="GITHUB_ENV or --github-env"):
        environment.main(["--root", str(tmp_path)])
    assert not (tmp_path / ".env").exists()
