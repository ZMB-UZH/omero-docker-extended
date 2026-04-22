from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "maintenance" / "postgres" / "pg-maintenance-entrypoint.sh"
CRON = REPO_ROOT / "maintenance" / "postgres" / "pg-maintenance-cron"
RUNNER = REPO_ROOT / "maintenance" / "postgres" / "pg-maintenance-cron-runner"
MAINTENANCE = REPO_ROOT / "maintenance" / "postgres" / "pg-maintenance.sh"


def _maintenance_env(**overrides: str) -> dict[str, str]:
    env = {
        "PATH": os.environ["PATH"],
        "OMERO_DB_HOST": "database",
        "OMERO_DB_PORT": "5432",
        "OMERO_DB_NAME": "omero",
        "OMERO_DB_USER": "omero",
        "OMERO_DB_PASS": "omero-password",
        "PLUGIN_DB_HOST": "database-plugin",
        "PLUGIN_DB_PORT": "5433",
        "PLUGIN_DB_NAME": "omero-plugin",
        "PLUGIN_DB_USER": "omero-plugin",
        "PLUGIN_DB_PASS": "plugin-password",
    }
    env.update(overrides)
    return env


def _run_bash(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        check=False,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def test_entrypoint_writes_private_shell_quoted_cron_env(tmp_path: Path) -> None:
    env_file = tmp_path / "pg-maintenance-env"
    marker = tmp_path / "command-substitution-ran"
    omero_pass = f"space value $(touch {marker}) 'quote' \"double\""
    plugin_pass = "line-one\nline-two; still literal"
    env = _maintenance_env(
        PG_MAINTENANCE_ENV_FILE=str(env_file),
        OMERO_DB_PASS=omero_pass,
        PLUGIN_DB_PASS=plugin_pass,
        EXPECTED_OMERO_DB_PASS=omero_pass,
        EXPECTED_PLUGIN_DB_PASS=plugin_pass,
    )

    result = _run_bash(
        f"""
        set -euo pipefail
        source {ENTRYPOINT}
        write_cron_env
        source {env_file}
        [[ "$OMERO_DB_PASS" == "$EXPECTED_OMERO_DB_PASS" ]]
        [[ "$PLUGIN_DB_PASS" == "$EXPECTED_PLUGIN_DB_PASS" ]]
        """,
        env,
    )

    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    env_text = env_file.read_text(encoding="utf-8")
    assert "export OMERO_DB_PASS=" in env_text
    assert "export PLUGIN_DB_PASS=" in env_text
    assert "$(" not in env_text
    assert "\\$\\(touch\\" in env_text


def test_entrypoint_fails_before_cron_when_required_env_is_missing(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "pg-maintenance-env"
    env = _maintenance_env(PG_MAINTENANCE_ENV_FILE=str(env_file))
    del env["PLUGIN_DB_PASS"]

    result = _run_bash(
        f"""
        set -euo pipefail
        source {ENTRYPOINT}
        write_cron_env
        """,
        env,
    )

    assert result.returncode != 0
    assert "PLUGIN_DB_PASS" in result.stderr
    assert not env_file.exists()


def test_cron_schedule_uses_runner_without_self_rewriting_or_guard_leak() -> None:
    cron_text = CRON.read_text(encoding="utf-8")

    assert "/usr/local/bin/pg-maintenance-cron-runner vacuum_analyze" in cron_text
    assert (
        '[ "$(date +\\%d)" -le 7 ] && /usr/local/bin/pg-maintenance-cron-runner reindex'
    ) in cron_text
    assert ". /etc/pg-maintenance-env" not in cron_text
    assert "/usr/local/bin/pg-maintenance.sh" not in cron_text
    assert "; /usr/local/bin/pg-maintenance-cron-runner reindex" not in cron_text


def test_cron_runner_sources_private_env_before_exec(tmp_path: Path) -> None:
    env_file = tmp_path / "pg-maintenance-env"
    output_file = tmp_path / "runner-output"
    fake_script = tmp_path / "fake-maintenance.sh"
    expected_pass = "literal $(echo unsafe)"
    env = _maintenance_env(
        PG_MAINTENANCE_ENV_FILE=str(env_file),
        OMERO_DB_PASS=expected_pass,
    )
    write_result = _run_bash(
        f"""
        set -euo pipefail
        source {ENTRYPOINT}
        write_cron_env
        """,
        env,
    )
    assert write_result.returncode == 0, write_result.stderr
    fake_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                'printf "action=%s\\n" "$1" > "$OUTPUT_FILE"',
                'printf "pass=%s\\n" "$OMERO_DB_PASS" >> "$OUTPUT_FILE"',
            ]
        ),
        encoding="utf-8",
    )
    fake_script.chmod(0o755)

    result = subprocess.run(
        ["bash", str(RUNNER), "vacuum_analyze"],
        check=False,
        cwd=REPO_ROOT,
        env={
            "PATH": os.environ["PATH"],
            "PG_MAINTENANCE_ENV_FILE": str(env_file),
            "PG_MAINTENANCE_SCRIPT": str(fake_script),
            "OUTPUT_FILE": str(output_file),
        },
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert output_file.read_text(encoding="utf-8") == (
        f"action=vacuum_analyze\npass={expected_pass}\n"
    )


def test_pg_maintenance_fails_when_database_command_fails(tmp_path: Path) -> None:
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    capture_file = tmp_path / "pgoptions"
    (stub_bin / "pg_isready").write_text(
        "#!/usr/bin/env bash\nexit 0\n",
        encoding="utf-8",
    )
    (stub_bin / "vacuumdb").write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                'printf "%s\\n" "$PGOPTIONS" > "$CAPTURE_FILE"',
                'printf "synthetic vacuum failure\\n" >&2',
                "exit 17",
            ]
        ),
        encoding="utf-8",
    )
    (stub_bin / "reindexdb").write_text(
        "#!/usr/bin/env bash\nexit 0\n",
        encoding="utf-8",
    )
    for helper in stub_bin.iterdir():
        helper.chmod(0o755)

    env = _maintenance_env(
        PATH=f"{stub_bin}:{os.environ['PATH']}",
        CAPTURE_FILE=str(capture_file),
    )
    result = subprocess.run(
        ["bash", str(MAINTENANCE), "vacuum_analyze"],
        check=False,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    combined_output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "synthetic vacuum failure" in combined_output
    assert "VACUUM ANALYZE failed on omero (exit 17)." in combined_output
    assert "lock_timeout=2s" in capture_file.read_text(encoding="utf-8")
