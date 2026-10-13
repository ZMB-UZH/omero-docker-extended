"""Execute the Redis readiness script against controlled native CLI responses."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "docker/redis-healthcheck.sh"
INFO = (
    "loading:0\naof_enabled:1\naof_last_write_status:ok\naof_last_bgrewrite_status:ok\n"
)


@pytest.mark.parametrize(
    ("policy", "info", "exit_code", "healthy"),
    [
        ("maxmemory-policy\nnoeviction", INFO, "0", True),
        ("maxmemory-policy\r\nnoeviction\r", INFO.replace("\n", "\r\n"), "0", True),
        ("maxmemory-policy\nallkeys-lru", INFO, "0", False),
        ("NOAUTH", INFO, "0", False),
        ("maxmemory-policy\nnoeviction", "", "0", False),
        ("maxmemory-policy\nnoeviction", INFO, "1", False),
        *[
            ("maxmemory-policy\nnoeviction", INFO.replace(old, new), "0", False)
            for old, new in (
                ("loading:0", "loading:1"),
                ("aof_enabled:1", "aof_enabled:0"),
                ("aof_last_write_status:ok", "aof_last_write_status:err"),
                ("aof_last_bgrewrite_status:ok", "aof_last_bgrewrite_status:err"),
            )
        ],
    ],
)
def test_health_requires_persistence_and_non_eviction(
    tmp_path, policy, info, exit_code, healthy
):
    """Inputs: readiness and failure responses. Output: only complete, safe state succeeds."""
    cli = tmp_path / "redis-cli"
    cli.write_text(
        '#!/bin/sh\n[ "$EXIT_CODE" = 0 ] || exit "$EXIT_CODE"\ncase "$2" in\nCONFIG) printf "%s\\n" "$POLICY";;\nINFO) printf "%s" "$INFO";;\n*) exit 3;;\nesac\n'
    )
    cli.chmod(0o700)
    env = dict(
        os.environ,
        PATH=f"{tmp_path}:{os.defpath}",
        POLICY=policy,
        INFO=info,
        EXIT_CODE=exit_code,
    )
    shell = shutil.which("sh")
    assert shell, "Redis health checks require a POSIX shell."
    result = subprocess.run(
        [shell, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert (result.returncode == 0) is healthy
    assert not result.stdout
