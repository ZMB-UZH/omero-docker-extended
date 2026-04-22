from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TMP_INSTALLER = REPO_ROOT / "scripts" / "install-tmp-cleaner.sh"
QUOTA_INSTALLER = REPO_ROOT / "scripts" / "install-quota-enforcer.sh"


def _fake_systemctl(tmp_path: Path) -> tuple[Path, Path]:
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


def _run_bash(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        check=False,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def _sh(path: Path) -> str:
    return shlex.quote(str(path))


def test_tmp_cleaner_installer_replaces_managed_units_without_host_paths(
    tmp_path: Path,
) -> None:
    systemctl, systemctl_log = _fake_systemctl(tmp_path)
    systemd_dir = tmp_path / "systemd system"
    tmp_dir = tmp_path / "omero tmp"
    bin_dir = tmp_path / "local sbin"
    service_file = systemd_dir / "omero-tmp-cleaner.service"
    timer_file = systemd_dir / "omero-tmp-cleaner.timer"
    tmp_dir.mkdir()
    systemd_dir.mkdir()
    service_file.write_text("stale service\n", encoding="utf-8")
    timer_file.write_text("stale timer\n", encoding="utf-8")

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
    service_text = service_file.read_text(encoding="utf-8")
    timer_text = timer_file.read_text(encoding="utf-8")
    assert "stale" not in service_text
    assert "stale" not in timer_text
    assert "__OMERO_TMP_PATH__" not in service_text
    assert "__TMP_CLEANER_BIN__" not in service_text
    assert str(tmp_dir) in service_text
    assert str(bin_dir / "omero-tmp-cleaner") in service_text
    assert "/usr/local/sbin/omero-tmp-cleaner" not in service_text
    assert "disable --now omero-tmp-cleaner.timer omero-tmp-cleaner.service" in (
        systemctl_log.read_text(encoding="utf-8")
    )


def test_quota_installer_renders_actual_paths_and_replaces_stale_units(
    tmp_path: Path,
) -> None:
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
    for unit_file in (service_file, timer_file, path_file):
        unit_file.write_text("stale unit\n", encoding="utf-8")

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
    service_text = service_file.read_text(encoding="utf-8")
    path_text = path_file.read_text(encoding="utf-8")
    assert "stale" not in service_text
    assert "stale" not in timer_file.read_text(encoding="utf-8")
    assert "stale" not in path_text
    assert "__DEFAULTS_FILE__" not in service_text
    assert "__ENFORCER_PATH__" not in service_text
    assert "__OMERO_DATA_DIR__" not in service_text
    assert "__QUOTA_STATE_FILE__" not in path_text
    assert str(defaults_file) in service_text
    assert str(enforcer_path) in service_text
    assert str(data_dir) in service_text
    assert str(state_file) in path_text
    assert "/opt/omero/scripts/omero-quota-enforcer.sh" not in service_text
    assert "/etc/default/omero-quota-enforcer" not in service_text
    assert "disable --now omero-quota-enforcer.timer " in (
        systemctl_log.read_text(encoding="utf-8")
    )
