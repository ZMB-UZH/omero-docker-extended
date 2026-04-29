from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TMP_INSTALLER = REPO_ROOT / "scripts" / "install-tmp-cleaner.sh"
QUOTA_INSTALLER = REPO_ROOT / "scripts" / "install-quota-enforcer.sh"
BASH_BIN = "/bin/bash"
TMP_CLEANER_UNITS = (
    "omero-tmp-cleaner.timer",
    "omero-tmp-cleaner.service",
)
QUOTA_ENFORCER_UNITS = (
    "omero-quota-enforcer.timer",
    "omero-quota-enforcer.path",
    "omero-quota-enforcer.service",
)


def _fake_systemctl(tmp_path: Path) -> tuple[Path, Path]:
    """Handle fake systemctl."""
    log_file = tmp_path / "systemctl.log"
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                'printf "%s\\n" "$*" >> "$SYSTEMCTL_LOG"',
            ]
        ),
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    return systemctl, log_file


def _fake_root_bin(tmp_path: Path) -> Path:
    """Handle fake root bin."""
    bin_dir = tmp_path / "fake-bin"
    id_bin = bin_dir / "id"
    dpkg_query = bin_dir / "dpkg-query"
    bin_dir.mkdir(exist_ok=True)
    id_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                'if [[ "${1:-}" = "-u" ]]; then echo 0; exit 0; fi',
                'exec /usr/bin/id "$@"',
            ]
        ),
        encoding="utf-8",
    )
    dpkg_query.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                'if [[ "${1:-}" = "-W" ]]; then printf "install ok installed"; exit 0; fi',
                "exit 1",
            ]
        ),
        encoding="utf-8",
    )
    id_bin.chmod(0o755)
    dpkg_query.chmod(0o755)
    return bin_dir


def _run_bash(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Handle run bash."""
    return subprocess.run(
        [BASH_BIN, "-c", script],
        check=False,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def _sh(path: Path) -> str:
    """Handle sh."""
    return shlex.quote(str(path))


def _systemd_escape(value: Path) -> str:
    """Handle systemd escape."""
    safe = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/._:@+-")
    return "".join(
        char if char in safe else f"\\x{ord(char):02x}" for char in str(value)
    )


def _write_stale_systemd_artifacts(
    systemd_dir: Path, unit_names: tuple[str, ...]
) -> None:
    """Handle write stale systemd artifacts."""
    for dependency_dir in (
        systemd_dir / "multi-user.target.wants",
        systemd_dir / "timers.target.wants",
        systemd_dir / "local-fs.target.requires",
    ):
        dependency_dir.mkdir(parents=True, exist_ok=True)

    for unit_name in unit_names:
        (systemd_dir / unit_name).write_text("stale unit\n", encoding="utf-8")
        dropin_dir = systemd_dir / f"{unit_name}.d"
        dropin_dir.mkdir(parents=True, exist_ok=True)
        (dropin_dir / "override.conf").write_text("stale override\n", encoding="utf-8")
        (systemd_dir / "multi-user.target.wants" / unit_name).symlink_to(
            systemd_dir / unit_name
        )
        (systemd_dir / "timers.target.wants" / unit_name).write_text(
            "stale dependency file\n",
            encoding="utf-8",
        )
        corrupt_dependency = systemd_dir / "local-fs.target.requires" / unit_name
        corrupt_dependency.mkdir()
        (corrupt_dependency / "corrupt").write_text("stale\n", encoding="utf-8")


def _assert_stale_systemd_artifacts_removed(
    systemd_dir: Path,
    unit_names: tuple[str, ...],
) -> None:
    """Handle assert stale systemd artifacts removed."""
    for unit_name in unit_names:
        assert not (systemd_dir / f"{unit_name}.d").exists()
        for dependency_dir in systemd_dir.glob("*.wants"):
            assert not (dependency_dir / unit_name).exists()
        for dependency_dir in systemd_dir.glob("*.requires"):
            assert not (dependency_dir / unit_name).exists()


def test_tmp_cleaner_installer_replaces_managed_units_without_host_paths(
    tmp_path: Path,
) -> None:
    """Verify test tmp cleaner installer replaces managed u behavior."""
    systemctl, systemctl_log = _fake_systemctl(tmp_path)
    systemd_dir = tmp_path / "systemd system"
    tmp_dir = tmp_path / "omero tmp"
    bin_dir = tmp_path / "local sbin"
    service_file = systemd_dir / "omero-tmp-cleaner.service"
    timer_file = systemd_dir / "omero-tmp-cleaner.timer"
    tmp_dir.mkdir()
    systemd_dir.mkdir()
    _write_stale_systemd_artifacts(systemd_dir, TMP_CLEANER_UNITS)

    result = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(TMP_INSTALLER)}
        SYSTEMD_SYSTEM_DIR={_sh(systemd_dir)}
        SYSTEMCTL_BIN={_sh(systemctl)}
        TMP_CLEANER_BIN={_sh(bin_dir / "omero-tmp-cleaner")}
        OMERO_TMP_DIR={_sh(tmp_dir)}
        replace_managed_units
        render_unit "$SCRIPT_DIR/omero-tmp-cleaner.service" \
            "$SYSTEMD_SYSTEM_DIR/omero-tmp-cleaner.service"
        install -D -m 0644 "$SCRIPT_DIR/omero-tmp-cleaner.timer" \
            "$SYSTEMD_SYSTEM_DIR/omero-tmp-cleaner.timer"
        "$SYSTEMCTL_BIN" daemon-reload
        """,
        {
            "PATH": os.environ["PATH"],
            "SYSTEMCTL_LOG": str(systemctl_log),
        },
    )

    assert result.returncode == 0, result.stderr
    _assert_stale_systemd_artifacts_removed(systemd_dir, TMP_CLEANER_UNITS)
    service_text = service_file.read_text(encoding="utf-8")
    timer_text = timer_file.read_text(encoding="utf-8")
    assert "stale" not in service_text
    assert "stale" not in timer_text
    assert "__OMERO_TMP_PATH__" not in service_text
    assert "__TMP_CLEANER_BIN__" not in service_text
    assert _systemd_escape(tmp_dir) in service_text
    assert _systemd_escape(bin_dir / "omero-tmp-cleaner") in service_text
    assert "/usr/local/sbin/omero-tmp-cleaner" not in service_text
    systemctl_text = systemctl_log.read_text(encoding="utf-8")
    assert "disable --now omero-tmp-cleaner.timer omero-tmp-cleaner.service" in (
        systemctl_text
    )
    assert "reset-failed omero-tmp-cleaner.timer omero-tmp-cleaner.service" in (
        systemctl_text
    )


def test_tmp_cleaner_full_installer_is_idempotent_and_purges_stale_artifacts(
    tmp_path: Path,
) -> None:
    """Verify test tmp cleaner full installer is idempotent behavior."""
    systemctl, systemctl_log = _fake_systemctl(tmp_path)
    fake_bin = _fake_root_bin(tmp_path)
    systemd_dir = tmp_path / "systemd system"
    tmp_dir = tmp_path / "omero tmp"
    bin_dir = tmp_path / "local sbin"
    tmp_dir.mkdir()
    systemd_dir.mkdir()

    env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SYSTEMCTL_LOG": str(systemctl_log),
        "SYSTEMD_SYSTEM_DIR": str(systemd_dir),
        "LOCAL_SBIN_DIR": str(bin_dir),
        "SYSTEMCTL_BIN": str(systemctl),
    }
    first = subprocess.run(
        [BASH_BIN, str(TMP_INSTALLER), str(tmp_dir)],
        check=False,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    _write_stale_systemd_artifacts(systemd_dir, TMP_CLEANER_UNITS)
    second = subprocess.run(
        [BASH_BIN, str(TMP_INSTALLER), str(tmp_dir)],
        check=False,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    _assert_stale_systemd_artifacts_removed(systemd_dir, TMP_CLEANER_UNITS)
    assert (systemd_dir / "omero-tmp-cleaner.service").is_file()
    assert (systemd_dir / "omero-tmp-cleaner.timer").is_file()
    installed_cleaner = bin_dir / "omero-tmp-cleaner"
    assert installed_cleaner.read_text(encoding="utf-8") == (
        REPO_ROOT / "scripts" / "omero-tmp-cleaner.sh"
    ).read_text(encoding="utf-8")
    assert installed_cleaner.stat().st_mode & 0o777 == 0o755
    systemctl_text = systemctl_log.read_text(encoding="utf-8")
    assert systemctl_text.count("enable omero-tmp-cleaner.timer") == 2
    assert systemctl_text.count("start omero-tmp-cleaner.timer") == 2


def test_quota_installer_renders_actual_paths_and_replaces_stale_units(
    tmp_path: Path,
) -> None:
    """Verify test quota installer renders actual paths and behavior."""
    systemctl, systemctl_log = _fake_systemctl(tmp_path)
    systemd_dir = tmp_path / "systemd system"
    install_root = tmp_path / "install root"
    data_dir = tmp_path / "omero data"
    defaults_file = tmp_path / "etc default" / "omero-quota-enforcer"
    enforcer_path = install_root / "scripts" / "omero-quota-enforcer.sh"
    state_file = data_dir / ".admin-tools" / "group-quotas.json"
    service_file = systemd_dir / "omero-quota-enforcer.service"
    timer_file = systemd_dir / "omero-quota-enforcer.timer"
    path_file = systemd_dir / "omero-quota-enforcer.path"
    systemd_dir.mkdir()
    _write_stale_systemd_artifacts(systemd_dir, QUOTA_ENFORCER_UNITS)

    result = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(QUOTA_INSTALLER)}
        SYSTEMD_SYSTEM_DIR={_sh(systemd_dir)}
        SYSTEMCTL_BIN={_sh(systemctl)}
        defaults_file={_sh(defaults_file)}
        enforcer_dst={_sh(enforcer_path)}
        OMERO_DATA_DIR={_sh(data_dir)}
        state_file={_sh(state_file)}
        replace_managed_units
        render_unit "$SCRIPT_DIR/omero-quota-enforcer.service" \
            "$SYSTEMD_SYSTEM_DIR/omero-quota-enforcer.service"
        install -D -m 0644 "$SCRIPT_DIR/omero-quota-enforcer.timer" \
            "$SYSTEMD_SYSTEM_DIR/omero-quota-enforcer.timer"
        render_unit "$SCRIPT_DIR/omero-quota-enforcer.path" \
            "$SYSTEMD_SYSTEM_DIR/omero-quota-enforcer.path"
        "$SYSTEMCTL_BIN" daemon-reload
        """,
        {
            "PATH": os.environ["PATH"],
            "SYSTEMCTL_LOG": str(systemctl_log),
        },
    )

    assert result.returncode == 0, result.stderr
    _assert_stale_systemd_artifacts_removed(systemd_dir, QUOTA_ENFORCER_UNITS)
    service_text = service_file.read_text(encoding="utf-8")
    path_text = path_file.read_text(encoding="utf-8")
    assert "stale" not in service_text
    assert "stale" not in timer_file.read_text(encoding="utf-8")
    assert "stale" not in path_text
    assert "__DEFAULTS_FILE__" not in service_text
    assert "__ENFORCER_PATH__" not in service_text
    assert "__OMERO_DATA_DIR__" not in service_text
    assert "__QUOTA_STATE_FILE__" not in path_text
    assert _systemd_escape(defaults_file) in service_text
    assert _systemd_escape(enforcer_path) in service_text
    assert _systemd_escape(data_dir) in service_text
    assert _systemd_escape(state_file) in path_text
    assert "/opt/omero/scripts/omero-quota-enforcer.sh" not in service_text
    assert "/etc/default/omero-quota-enforcer" not in service_text
    systemctl_text = systemctl_log.read_text(encoding="utf-8")
    assert "disable --now omero-quota-enforcer.timer " in systemctl_text
    assert (
        "reset-failed omero-quota-enforcer.timer "
        "omero-quota-enforcer.path omero-quota-enforcer.service" in systemctl_text
    )


def test_quota_full_installer_is_idempotent_and_purges_stale_artifacts(
    tmp_path: Path,
) -> None:
    """Verify test quota full installer is idempotent and p behavior."""
    systemctl, systemctl_log = _fake_systemctl(tmp_path)
    fake_bin = _fake_root_bin(tmp_path)
    systemd_dir = tmp_path / "systemd system"
    install_root = tmp_path / "install root"
    data_dir = tmp_path / "omero data"
    defaults_file = tmp_path / "etc default" / "omero-quota-enforcer"
    data_dir.mkdir()
    systemd_dir.mkdir()

    env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SYSTEMCTL_LOG": str(systemctl_log),
        "SYSTEMD_SYSTEM_DIR": str(systemd_dir),
        "SYSTEMCTL_BIN": str(systemctl),
        "OMERO_INSTALLATION_PATH": str(install_root),
        "OMERO_QUOTA_DEFAULTS_FILE": str(defaults_file),
    }
    first = subprocess.run(
        [BASH_BIN, str(QUOTA_INSTALLER), str(data_dir)],
        check=False,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    _write_stale_systemd_artifacts(systemd_dir, QUOTA_ENFORCER_UNITS)
    second = subprocess.run(
        [BASH_BIN, str(QUOTA_INSTALLER), str(data_dir)],
        check=False,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    _assert_stale_systemd_artifacts_removed(systemd_dir, QUOTA_ENFORCER_UNITS)
    assert (systemd_dir / "omero-quota-enforcer.service").is_file()
    assert (systemd_dir / "omero-quota-enforcer.timer").is_file()
    assert (systemd_dir / "omero-quota-enforcer.path").is_file()
    installed_enforcer = install_root / "scripts" / "omero-quota-enforcer.sh"
    assert installed_enforcer.read_text(encoding="utf-8") == (
        REPO_ROOT / "scripts" / "omero-quota-enforcer.sh"
    ).read_text(encoding="utf-8")
    assert installed_enforcer.stat().st_mode & 0o777 == 0o755
    assert (data_dir / ".admin-tools" / "quota-enforcer-installed").is_file()
    assert (
        data_dir / ".admin-tools" / "group-quotas.json"
    ).stat().st_mode & 0o777 == 0o666
    systemctl_text = systemctl_log.read_text(encoding="utf-8")
    assert systemctl_text.count("enable omero-quota-enforcer.timer") == 2
    assert systemctl_text.count("start omero-quota-enforcer.timer") == 2
    assert systemctl_text.count("enable omero-quota-enforcer.path") == 2
    assert systemctl_text.count("start omero-quota-enforcer.path") == 2


def test_quota_defaults_file_quotes_installation_specific_paths(
    tmp_path: Path,
) -> None:
    """Verify test quota defaults file quotes installation behavior."""
    data_dir = tmp_path / 'omero data "quoted" $HOME `tick` back\\slash'
    defaults_file = tmp_path / "etc default" / "omero-quota-enforcer"
    data_dir.mkdir()

    result = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(QUOTA_INSTALLER)}
        OMERO_DATA_DIR={_sh(data_dir)}
        DEFAULTS_FILE={_sh(defaults_file)}
        write_defaults_file
        source {_sh(defaults_file)}
        [[ "$OMERO_DATA_DIR" == {_sh(str(data_dir))} ]]
        [[ "$QUOTA_STATE_FILE" == "$OMERO_DATA_DIR/.admin-tools/group-quotas.json" ]]
        [[ "$MANAGED_REPO_ROOT" == "$OMERO_DATA_DIR/ManagedRepository" ]]
        [[ "$PROJECTS_FILE" == "$OMERO_DATA_DIR/.admin-tools/quota/projects" ]]
        [[ "$PROJID_FILE" == "$OMERO_DATA_DIR/.admin-tools/quota/projid" ]]
        """,
        {"PATH": os.environ["PATH"]},
    )

    assert result.returncode == 0, result.stderr
    defaults_text = defaults_file.read_text(encoding="utf-8")
    assert '\\"quoted\\"' in defaults_text
    assert "\\$HOME" in defaults_text
    assert "\\`tick\\`" in defaults_text
