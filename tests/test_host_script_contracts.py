from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
BASH_BIN = "/bin/bash"
SCRIPT_DIR = REPO_ROOT / "scripts"


def _run_bash(
    script: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the bash.

    Inputs: `script` (str), `env` (dict[str, str] | None) environment mapping. Output:
    `subprocess.CompletedProcess[str]`.
    """
    run_env = {"PATH": os.environ["PATH"], **(env or {})}
    return subprocess.run(
        [BASH_BIN, "-c", script],
        check=False,
        cwd=REPO_ROOT,
        env=run_env,
        text=True,
        capture_output=True,
    )


def _sh(path: Path | str) -> str:
    """Return the sh.

    Inputs: `path` (Path | str) path. Output: `str`.
    """
    return shlex.quote(str(path))


def test_public_script_and_unit_entrypoints_remain_stable() -> None:
    """Check that public script and unit entrypoints remain stable remains stable.

    Inputs: repository fixtures. Output: fails on regressions in public script and unit entrypoints remain stable integration.
    """
    expected = {
        "enable-storage-quotas.sh",
        "install-quota-enforcer.sh",
        "install-tmp-cleaner.sh",
        "omero-host-service-lib.sh",
        "omero-quota-enforcer.path",
        "omero-quota-enforcer.service",
        "omero-quota-enforcer.sh",
        "omero-quota-enforcer.timer",
        "omero-tmp-cleaner.service",
        "omero-tmp-cleaner.sh",
        "omero-tmp-cleaner.timer",
    }

    assert {path.name for path in SCRIPT_DIR.iterdir()} == expected

    installation_script = (
        REPO_ROOT / "installation" / "installation_script.sh"
    ).read_text(encoding="utf-8")
    assert "scripts/install-quota-enforcer.sh" in installation_script
    assert "scripts/enable-storage-quotas.sh" in installation_script
    assert "scripts/install-tmp-cleaner.sh" in installation_script


def test_storage_quota_enablement_script_is_fail_closed() -> None:
    """Verify storage quota enablement keeps destructive operations guarded.

    Inputs: repository fixtures. Output: fails on regressions in quota enablement safety.
    """
    script = (SCRIPT_DIR / "enable-storage-quotas.sh").read_text(encoding="utf-8")

    assert "--yes-i-have-a-backup" in script
    assert "quota_self_test" in script
    assert '[ "${QUOTA_FSTYPE}" = "ext4" ]' in script
    assert "Root is ext4, but its 'project' feature is not enabled" in script
    assert 'if "prjquota" not in options and "project" not in options:' in script
    assert "matches > 1" in script
    assert "validate_unmount_preconditions" in script
    assert "preflight_compose_if_needed" in script
    assert "mount_has_project_quota" in script
    assert "setpriv --reuid 65534 --regid 65534 --clear-groups" in script
    assert "ext4 project quotas are already enabled" in script
    assert "OMERO_QUOTA_SKIP_COMPOSE" in script


def test_installation_script_reports_failed_storage_quota_enablement(
    tmp_path: Path,
) -> None:
    """Verify failed quota enablement cannot be reported as installed.

    Inputs: pytest provides `tmp_path`. Output: fails when the installer function
    ignores a failing quota enabler because it is called from an `if !` context.
    """
    installation_script = (
        REPO_ROOT / "installation" / "installation_script.sh"
    ).read_text(encoding="utf-8")
    function_match = re.search(
        r"^run_storage_quota_enablement_if_requested\(\) \{\n.*?^}\n",
        installation_script,
        re.MULTILINE | re.DOTALL,
    )
    assert function_match is not None

    install_root = tmp_path / "install root"
    scripts_dir = install_root / "scripts"
    scripts_dir.mkdir(parents=True)
    enabler = scripts_dir / "enable-storage-quotas.sh"
    enabler.write_text("#!/usr/bin/env bash\necho quota-enabler-failed >&2\nexit 23\n")
    enabler.chmod(0o755)

    result = _run_bash(
        f"""
        set -euo pipefail
        {function_match.group(0)}
        OMERO_INSTALLATION_PATH={_sh(install_root)}
        SCRIPT_ENV_FILE={_sh(tmp_path / "installation_paths.env")}
        ENABLE_STORAGE_QUOTAS=1
        STORAGE_QUOTAS_ENABLEMENT_RAN=0
        if run_storage_quota_enablement_if_requested; then
            printf 'status=success ran=%s\\n' "${{STORAGE_QUOTAS_ENABLEMENT_RAN}}"
        else
            printf 'status=failure code=%s ran=%s\\n' "$?" "${{STORAGE_QUOTAS_ENABLEMENT_RAN}}"
        fi
        """
    )

    assert result.returncode == 0, result.stderr
    assert "quota-enabler-failed" in result.stderr
    assert "ext4 project-quota enablement failed" in result.stderr
    assert "status=failure code=1 ran=0" in result.stdout
    assert "status=success" not in result.stdout


def test_host_timers_reschedule_after_reinstall_activation() -> None:
    """Verify host timers reschedule after reinstall activation.

    Inputs: repository fixtures. Output: fails on regressions in host timers reschedule after reinstall activation.
    """
    quota_timer = (SCRIPT_DIR / "omero-quota-enforcer.timer").read_text(
        encoding="utf-8"
    )
    tmp_timer = (SCRIPT_DIR / "omero-tmp-cleaner.timer").read_text(encoding="utf-8")

    assert "OnActiveSec=60s" in quota_timer
    assert "OnUnitActiveSec=60s" in quota_timer
    assert "OnActiveSec=30min" in tmp_timer
    assert "OnUnitActiveSec=30min" in tmp_timer


def test_all_host_shell_scripts_parse_with_bash() -> None:
    """Verify all host shell scripts parse with bash.

    Inputs: repository fixtures. Output: fails on regressions in all host shell scripts parse with bash.
    """
    scripts = sorted(str(path) for path in SCRIPT_DIR.glob("*.sh"))
    result = subprocess.run(
        [BASH_BIN, "-n", *scripts],
        check=False,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_quota_enforcer_rejects_unexpected_cli_arguments(tmp_path: Path) -> None:
    """Confirm quota enforcer rejects unexpected CLI arguments is rejected at the boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in quota enforcer rejects unexpected CLI arguments.
    """
    env = {"OMERO_QUOTA_DEFAULTS_FILE": str(tmp_path / "missing-defaults")}
    script = f"bash {_sh(SCRIPT_DIR / 'omero-quota-enforcer.sh')}"

    help_result = _run_bash(f"{script} --help", env=env)
    assert help_result.returncode == 0, help_result.stderr
    assert "Usage:" in help_result.stderr
    assert "No active group quotas configured" not in help_result.stdout

    unknown_result = _run_bash(f"{script} --unexpected", env=env)
    assert unknown_result.returncode == 2
    assert "Unknown argument: --unexpected" in unknown_result.stderr


def test_systemd_renderer_escapes_spaces_quotes_and_percent(tmp_path: Path) -> None:
    """Verify systemd renderer escapes spaces quotes and percent.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in systemd renderer escapes spaces quotes and percent.
    """
    template = tmp_path / "template.service"
    rendered = tmp_path / "rendered.service"
    template.write_text(
        "ExecStart=__BIN__ --root __ROOT__\nReadWritePaths=__ROOT__\n",
        encoding="utf-8",
    )

    result = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(SCRIPT_DIR / "omero-host-service-lib.sh")}
        omero_render_systemd_unit \
            {_sh(template)} \
            {_sh(rendered)} \
            BIN {_sh('/opt/omero/bin/tool"name')} \
            ROOT {_sh("/srv/OMERO data/100% ready")}
        """
    )

    assert result.returncode == 0, result.stderr
    rendered_text = rendered.read_text(encoding="utf-8")
    assert "__" not in rendered_text
    assert "/opt/omero/bin/tool\\x22name" in rendered_text
    assert "/srv/OMERO\\x20data/100\\x25\\x20ready" in rendered_text


def test_systemd_renderer_replaces_stale_symlink_without_following(
    tmp_path: Path,
) -> None:
    """Verify the systemd renderer replaces stale symlink without following safety boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when systemd renderer replaces stale symlink without following accepts unsafe input.
    """
    template = tmp_path / "template.service"
    rendered = tmp_path / "rendered.service"
    outside_target = tmp_path / "outside-target.service"
    template.write_text("ExecStart=__BIN__\n", encoding="utf-8")
    outside_target.write_text("must not change\n", encoding="utf-8")
    rendered.symlink_to(outside_target)

    result = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(SCRIPT_DIR / "omero-host-service-lib.sh")}
        omero_render_systemd_unit {_sh(template)} {_sh(rendered)} BIN /bin/true
        """
    )

    assert result.returncode == 0, result.stderr
    assert outside_target.read_text(encoding="utf-8") == "must not change\n"
    assert not rendered.is_symlink()
    assert rendered.read_text(encoding="utf-8") == "ExecStart=/bin/true\n"


def test_install_verified_replaces_stale_symlink_without_following(
    tmp_path: Path,
) -> None:
    """Verify the install verified replaces stale symlink without following safety boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when install verified replaces stale symlink without following accepts unsafe input.
    """
    source_file = tmp_path / "source.sh"
    destination = tmp_path / "destination"
    outside_target = tmp_path / "outside-target"
    source_file.write_text("#!/bin/sh\necho source\n", encoding="utf-8")
    outside_target.write_text("must not change\n", encoding="utf-8")
    destination.symlink_to(outside_target)

    result = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(SCRIPT_DIR / "omero-host-service-lib.sh")}
        omero_install_verified {_sh(source_file)} {_sh(destination)} 0755 >/dev/null
        """
    )

    assert result.returncode == 0, result.stderr
    assert outside_target.read_text(encoding="utf-8") == "must not change\n"
    assert not destination.is_symlink()
    assert destination.read_text(encoding="utf-8") == source_file.read_text(
        encoding="utf-8"
    )
    assert destination.stat().st_mode & 0o777 == 0o755


def test_environment_quote_is_safe_for_shell_sourced_defaults(
    tmp_path: Path,
) -> None:
    """Verify environment quote is safe for shell sourced defaults.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in environment quote is safe for shell sourced defaults.
    """
    defaults_file = tmp_path / "defaults"
    value = '/srv/OMERO data/"quoted"/dollar$HOME/back\\slash/`tick`'

    result = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(SCRIPT_DIR / "omero-host-service-lib.sh")}
        VALUE={_sh(value)}
        printf 'OMERO_DATA_DIR=%s\\n' "$(omero_environment_quote "$VALUE")" > {_sh(defaults_file)}
        source {_sh(defaults_file)}
        [[ "$OMERO_DATA_DIR" == "$VALUE" ]]
        """
    )

    assert result.returncode == 0, result.stderr
    defaults_text = defaults_file.read_text(encoding="utf-8")
    assert "dollar\\$HOME" in defaults_text
    assert "`tick`" not in defaults_text
    assert '\\"quoted\\"' in defaults_text


def test_systemd_cleanup_rejects_unsafe_scope(tmp_path: Path) -> None:
    """Confirm systemd cleanup rejects unsafe scope is rejected at the boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in systemd cleanup rejects unsafe scope.
    """
    unsafe_name = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(SCRIPT_DIR / "omero-host-service-lib.sh")}
        omero_remove_systemd_unit_artifacts {_sh(tmp_path)} ../evil.service
        """
    )
    root_dir = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(SCRIPT_DIR / "omero-host-service-lib.sh")}
        omero_remove_systemd_unit_artifacts / omero-tmp-cleaner.service
        """
    )

    assert unsafe_name.returncode != 0
    assert "Unsafe systemd unit name" in unsafe_name.stderr
    assert root_dir.returncode != 0
    assert "Refusing to clean root directory" in root_dir.stderr


def test_tmp_cleaner_unit_rendering_does_not_require_python(tmp_path: Path) -> None:
    """Verify tmp cleaner unit rendering does not require python.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in tmp cleaner unit rendering does not require python.
    """
    template = tmp_path / "template.service"
    rendered = tmp_path / "rendered.service"
    tripwire_bin = tmp_path / "bin"
    tripwire_python = tripwire_bin / "python3"

    template.write_text(
        "ExecStart=__TMP_CLEANER_BIN__ --tmp-dir __OMERO_TMP_PATH__\n",
        encoding="utf-8",
    )
    tripwire_bin.mkdir()
    tripwire_python.write_text("#!/bin/sh\necho python3-called >&2\nexit 97\n")
    tripwire_python.chmod(0o755)

    result = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(SCRIPT_DIR / "install-tmp-cleaner.sh")}
        TMP_CLEANER_BIN={_sh("/usr/local/sbin/omero-tmp-cleaner")}
        OMERO_TMP_DIR={_sh("/srv/OMERO tmp")}
        render_unit {_sh(template)} {_sh(rendered)}
        """,
        env={"PATH": f"{tripwire_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode == 0, result.stderr
    assert "python3-called" not in result.stderr
    assert "/srv/OMERO\\x20tmp" in rendered.read_text(encoding="utf-8")


def test_tmp_cleaner_argument_validation_and_symlink_safety(tmp_path: Path) -> None:
    """Verify the tmp cleaner argument validation and symlink safety safety boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when tmp cleaner argument validation and symlink safety accepts unsafe input.
    """
    tmp_root = tmp_path / "omero tmp root"
    tmp_root.mkdir()
    external_file = tmp_path / "external-payload"
    symlink_path = tmp_root / "old-link"
    external_file.write_text("do not delete\n", encoding="utf-8")
    symlink_path.symlink_to(external_file)
    os.utime(symlink_path, (0, 0), follow_symlinks=False)

    missing_value = subprocess.run(
        [BASH_BIN, str(SCRIPT_DIR / "omero-tmp-cleaner.sh"), "--tmp-dir"],
        check=False,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    invalid_age = subprocess.run(
        [
            BASH_BIN,
            str(SCRIPT_DIR / "omero-tmp-cleaner.sh"),
            "--tmp-dir",
            str(tmp_root),
            "--max-age-seconds",
            "not-a-number",
        ],
        check=False,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    cleanup = subprocess.run(
        [
            BASH_BIN,
            str(SCRIPT_DIR / "omero-tmp-cleaner.sh"),
            "--tmp-dir",
            str(tmp_root),
            "--max-age-seconds",
            "60",
        ],
        check=False,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert missing_value.returncode == 2
    assert "--tmp-dir requires a value" in missing_value.stderr
    assert invalid_age.returncode == 2
    assert "--max-age-seconds must be an integer" in invalid_age.stderr
    assert cleanup.returncode == 0, cleanup.stderr
    assert not symlink_path.exists()
    assert external_file.read_text(encoding="utf-8") == "do not delete\n"


def test_rendered_systemd_units_verify(tmp_path: Path) -> None:
    """Verify rendered systemd units verify.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in rendered systemd units verify.
    """
    systemd_analyze = shutil.which("systemd-analyze")
    if systemd_analyze is None:
        pytest.skip("systemd-analyze is not installed")

    systemd_dir = tmp_path / "systemd"
    bin_dir = tmp_path / "bin"
    tmp_dir = tmp_path / "omero tmp"
    data_dir = tmp_path / "omero data"
    defaults_file = tmp_path / "etc default" / "omero-quota-enforcer"
    state_file = data_dir / ".admin-tools" / "group-quotas.json"
    enforcer_path = bin_dir / "omero-quota-enforcer.sh"
    cleaner_path = bin_dir / "omero-tmp-cleaner"
    for path in (
        systemd_dir,
        bin_dir,
        tmp_dir,
        state_file.parent,
        defaults_file.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)
    defaults_file.touch()
    state_file.touch()
    shutil.copy2("/bin/true", cleaner_path)
    shutil.copy2("/bin/true", enforcer_path)
    cleaner_path.chmod(0o755)
    enforcer_path.chmod(0o755)

    for target in (
        "sysinit.target",
        "local-fs.target",
        "network-online.target",
        "timers.target",
        "multi-user.target",
    ):
        (systemd_dir / target).write_text(
            f"[Unit]\nDescription={target}\n",
            encoding="utf-8",
        )

    render_tmp = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(SCRIPT_DIR / "install-tmp-cleaner.sh")}
        SYSTEMD_SYSTEM_DIR={_sh(systemd_dir)}
        TMP_CLEANER_BIN={_sh(cleaner_path)}
        OMERO_TMP_DIR={_sh(tmp_dir)}
        render_unit "$SCRIPT_DIR/omero-tmp-cleaner.service" \
            "$SYSTEMD_SYSTEM_DIR/omero-tmp-cleaner.service"
        install -D -m 0644 "$SCRIPT_DIR/omero-tmp-cleaner.timer" \
            "$SYSTEMD_SYSTEM_DIR/omero-tmp-cleaner.timer"
        """
    )
    assert render_tmp.returncode == 0, render_tmp.stderr

    render_quota = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(SCRIPT_DIR / "install-quota-enforcer.sh")}
        SYSTEMD_SYSTEM_DIR={_sh(systemd_dir)}
        defaults_file={_sh(defaults_file)}
        enforcer_dst={_sh(enforcer_path)}
        OMERO_DATA_DIR={_sh(data_dir)}
        state_file={_sh(state_file)}
        render_unit "$SCRIPT_DIR/omero-quota-enforcer.service" \
            "$SYSTEMD_SYSTEM_DIR/omero-quota-enforcer.service"
        install -D -m 0644 "$SCRIPT_DIR/omero-quota-enforcer.timer" \
            "$SYSTEMD_SYSTEM_DIR/omero-quota-enforcer.timer"
        render_unit "$SCRIPT_DIR/omero-quota-enforcer.path" \
            "$SYSTEMD_SYSTEM_DIR/omero-quota-enforcer.path"
        """
    )
    assert render_quota.returncode == 0, render_quota.stderr

    unit_files = [
        systemd_dir / "omero-tmp-cleaner.service",
        systemd_dir / "omero-tmp-cleaner.timer",
        systemd_dir / "omero-quota-enforcer.service",
        systemd_dir / "omero-quota-enforcer.timer",
        systemd_dir / "omero-quota-enforcer.path",
    ]
    result = subprocess.run(
        [systemd_analyze, "verify", *(str(path) for path in unit_files)],
        check=False,
        env={**os.environ, "SYSTEMD_UNIT_PATH": str(systemd_dir)},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_quota_state_parser_is_single_pass_and_validates_records(
    tmp_path: Path,
) -> None:
    """Check quota state parser is single pass and validates records parsing against the documented contract.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in quota state parser is single pass and validates records.
    """
    state_file = tmp_path / "group-quotas.json"
    records_file = tmp_path / "records.tsv"
    state_file.write_text(
        """
        {
          "quotas_gb": {
            "group-alpha": 1.5,
            "too/special": 2,
            "too-small": 0.01,
            "infinite": "Infinity",
            "nan": "NaN",
            "bad-number": "not-a-number"
          }
        }
        """,
        encoding="utf-8",
    )

    result = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(SCRIPT_DIR / "omero-quota-enforcer.sh")}
        QUOTA_STATE_FILE={_sh(state_file)}
        MIN_QUOTA_GB=0.10
        load_quota_records {_sh(records_file)}
        cat {_sh(records_file)}
        """
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert "OK\tgroup-alpha\t1.5\t1572864" in lines
    assert "SKIP\t'too/special'\tunsafe group name" in lines
    assert any(line.startswith("ERR\ttoo-small\t") for line in lines)
    assert any(line.startswith("ERR\tinfinite\t") for line in lines)
    assert any(line.startswith("ERR\tnan\t") for line in lines)
    assert any(line.startswith("ERR\tbad-number\t") for line in lines)


def test_quota_path_boundaries_and_mapping_files_are_strict(tmp_path: Path) -> None:
    """Verify the quota path boundaries and mapping files are strict safety boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when quota path boundaries and mapping files are strict accepts unsafe input.
    """
    root = tmp_path / "ManagedRepository"
    child = root / "group"
    sibling = tmp_path / "ManagedRepository-other"
    project_file = tmp_path / "projects"
    error_file = tmp_path / "strict-error"
    symlink_target = tmp_path / "target"
    root.mkdir()
    child.mkdir()
    sibling.mkdir()
    symlink_target.write_text("target\n", encoding="utf-8")
    project_file.symlink_to(symlink_target)

    result = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(SCRIPT_DIR / "omero-quota-enforcer.sh")}
        path_is_strict_child {_sh(child)} {_sh(root)}
        if path_is_strict_child {_sh(root)} {_sh(root)}; then
            exit 10
        fi
        if path_is_strict_child {_sh(sibling)} {_sh(root)}; then
            exit 11
        fi
        if (ensure_regular_or_absent {_sh(project_file)}) 2>{_sh(error_file)}; then
            exit 12
        fi
        cat {_sh(error_file)}
        """
    )

    assert result.returncode == 0, result.stderr
    assert "Refusing to use non-regular file" in result.stdout


def test_quota_mapping_rewrites_are_exact_not_regex_based(tmp_path: Path) -> None:
    """Verify quota mapping rewrites are exact not regex based.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in quota mapping rewrites are exact not regex based.
    """
    projects_file = tmp_path / "projects"
    projid_file = tmp_path / "projid"
    group_path = tmp_path / "ManagedRepository" / "group.alpha"
    other_path = tmp_path / "ManagedRepository" / "groupXalpha"
    group_path.parent.mkdir()
    projects_file.write_text(
        f"200000:{group_path}\n200001:{other_path}\n",
        encoding="utf-8",
    )
    projid_file.write_text(
        "group.alpha:200000\ngroupXalpha:200001\n",
        encoding="utf-8",
    )

    result = _run_bash(
        f"""
        set -euo pipefail
        source {_sh(SCRIPT_DIR / "omero-quota-enforcer.sh")}
        PROJECTS_FILE={_sh(projects_file)}
        PROJID_FILE={_sh(projid_file)}
        write_project_mappings group.alpha 200002 {_sh(group_path)}
        """
    )

    assert result.returncode == 0, result.stderr
    assert projects_file.read_text(encoding="utf-8").splitlines() == [
        f"200001:{other_path}",
        f"200002:{group_path}",
    ]
    assert projid_file.read_text(encoding="utf-8").splitlines() == [
        "groupXalpha:200001",
        "group.alpha:200002",
    ]
