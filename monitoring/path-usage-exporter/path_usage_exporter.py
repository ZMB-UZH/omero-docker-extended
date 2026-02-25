#!/usr/bin/env python3
"""Path usage exporter for OMERO host paths.

Reads OMERO-related host paths from installation_paths.env and resolves usage
via host `df` output for each configured path. Results are written as
Prometheus textfile-collector metrics consumed by node-exporter.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Dict, List, Optional, Tuple

OUT = "/textfile/omero_paths.prom"
TMP = OUT + ".tmp"
INTERVAL_SECONDS = 30
PATHS_ENV_FILE = "/config/installation_paths.env"
HOST_ROOT = "/host"

TARGETS: List[Tuple[str, str]] = [
    ("omero_data", "OMERO_DATA_PATH"),
    ("database_main", "OMERO_DATABASE_PATH"),
    ("database_plugin", "OMERO_PLUGIN_DATABASE_PATH"),
]


def parse_env_file(env_file_path: str) -> Dict[str, str]:
    """Parse a simple KEY=VALUE env file into a dictionary."""
    result: Dict[str, str] = {}
    if not os.path.exists(env_file_path):
        return result

    with open(env_file_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def host_path_for_df(path_value: str) -> str:
    """Translate host path to the same location under /host mount."""
    normalized = path_value.strip()
    if not normalized.startswith("/"):
        raise ValueError(f"Path must be absolute: {path_value}")
    return os.path.join(HOST_ROOT, normalized.lstrip("/"))


def df_usage(path_for_df: str) -> Optional[Tuple[str, int, int, float]]:
    """Return mountpoint and usage from `df -P -B1` for a path."""
    command = ["df", "-P", "-B1", path_for_df]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None

    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return None

    fields = lines[1].split()
    if len(fields) < 6:
        return None

    total = int(fields[1])
    used = int(fields[2])
    mountpoint = fields[5]
    ratio = (used / total) if total > 0 else 0.0
    return mountpoint, total, used, ratio


def render_metrics(env_values: Dict[str, str]) -> str:
    """Render Prometheus metrics text for configured targets."""
    lines: List[str] = [
        "# HELP omero_path_used_ratio Filesystem used ratio for OMERO-related host paths",
        "# TYPE omero_path_used_ratio gauge",
        "# HELP omero_path_bytes_total Total bytes for OMERO-related host paths",
        "# TYPE omero_path_bytes_total gauge",
        "# HELP omero_path_bytes_used Used bytes for OMERO-related host paths",
        "# TYPE omero_path_bytes_used gauge",
    ]

    for kind, env_key in TARGETS:
        host_path_value = env_values.get(env_key, "")
        if not host_path_value:
            continue

        try:
            path_for_df = host_path_for_df(host_path_value)
        except ValueError:
            continue

        if not os.path.exists(path_for_df):
            continue

        usage = df_usage(path_for_df)
        if usage is None:
            continue

        mountpoint, total, used, ratio = usage
        labels = (
            f'kind="{kind}",env_key="{env_key}",path="{host_path_value}",mountpoint="{mountpoint}"'
        )
        lines.append(f"omero_path_used_ratio{{{labels}}} {ratio}")
        lines.append(f"omero_path_bytes_total{{{labels}}} {float(total)}")
        lines.append(f"omero_path_bytes_used{{{labels}}} {float(used)}")

    return "\n".join(lines) + "\n"


def write_metrics(content: str) -> None:
    """Write metrics atomically to textfile collector output."""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(TMP, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(TMP, OUT)


def main() -> None:
    """Collect and export OMERO host path usage metrics forever."""
    while True:
        try:
            env_values = parse_env_file(PATHS_ENV_FILE)
            metrics = render_metrics(env_values)
            write_metrics(metrics)
        except Exception as exc:
            print(f"Error collecting metrics: {exc}")

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
