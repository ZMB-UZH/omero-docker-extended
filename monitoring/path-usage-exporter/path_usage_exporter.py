#!/usr/bin/env python3
"""Path usage exporter for OMERO host paths.

Reads OMERO-related host paths from installation_paths.env and resolves usage
via host `df` output for each configured path. Results are written as
Prometheus textfile-collector metrics consumed by node-exporter.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import time

DEFAULT_OUTPUT = "/textfile/omero_paths.prom"
DEFAULT_INTERVAL_SECONDS = 30
DEFAULT_PATHS_ENV_FILE = "/config/installation_paths.env"
DEFAULT_HOST_ROOT = "/host"
DEFAULT_DF_TIMEOUT_SECONDS = 10
# node-exporter reads this file from a separate container UID. The textfile
# metrics are non-sensitive and must remain readable outside the writer UID.
TEXTFILE_METRIC_MODE = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH


def env_int(name: str, default: int, minimum: int = 1) -> int:
    """Return a bounded integer from the environment."""
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return max(value, minimum)


OUT = os.environ.get("PATH_USAGE_EXPORTER_OUTPUT", DEFAULT_OUTPUT)
INTERVAL_SECONDS = env_int(
    "PATH_USAGE_EXPORTER_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS
)
PATHS_ENV_FILE = os.environ.get("PATH_USAGE_EXPORTER_ENV_FILE", DEFAULT_PATHS_ENV_FILE)
HOST_ROOT = os.environ.get("PATH_USAGE_EXPORTER_HOST_ROOT", DEFAULT_HOST_ROOT)
DF_TIMEOUT_SECONDS = env_int(
    "PATH_USAGE_EXPORTER_DF_TIMEOUT_SECONDS", DEFAULT_DF_TIMEOUT_SECONDS
)

TARGETS: list[tuple[str, str]] = [
    ("omero_data", "OMERO_DATA_PATH"),
    ("database_main", "OMERO_DATABASE_PATH"),
    ("database_plugin", "OMERO_PLUGIN_DATABASE_PATH"),
]


def parse_env_file(env_file_path: str) -> dict[str, str]:
    """Parse a simple KEY=VALUE env file into a dictionary."""
    result: dict[str, str] = {}
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


def host_path_for_df(path_value: str, host_root: str = HOST_ROOT) -> str:
    """Translate a host path to the same location under the host-root mount."""
    stripped_path = path_value.strip()
    if not stripped_path.startswith("/"):
        raise ValueError(f"Path must be absolute: {path_value}")
    normalized_host_path = os.path.normpath(stripped_path)
    return os.path.normpath(os.path.join(host_root, normalized_host_path.lstrip("/")))


def df_usage(
    path_for_df: str, timeout_seconds: int = DF_TIMEOUT_SECONDS
) -> tuple[str, int, int, float] | None:
    """Return mountpoint and byte usage from portable `df -kP` output."""
    command = ["df", "-kP", path_for_df]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None

    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return None

    fields = lines[1].split(maxsplit=5)
    if len(fields) < 6:
        return None

    try:
        total = int(fields[1]) * 1024
        used = int(fields[2]) * 1024
    except ValueError:
        return None
    mountpoint = fields[5]
    ratio = (used / total) if total > 0 else 0.0
    return mountpoint, total, used, ratio


def escape_label_value(value: str) -> str:
    """Escape Prometheus text-format label values."""
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def render_labels(labels: dict[str, str]) -> str:
    """Render Prometheus labels in insertion order."""
    return ",".join(
        f'{name}="{escape_label_value(value)}"' for name, value in labels.items()
    )


def render_metrics(env_values: dict[str, str]) -> str:
    """Render Prometheus metrics text for configured targets."""
    lines: list[str] = [
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
        labels = render_labels(
            {
                "kind": kind,
                "env_key": env_key,
                "path": host_path_value,
                "mountpoint": mountpoint,
            }
        )
        lines.append(f"omero_path_used_ratio{{{labels}}} {ratio}")
        lines.append(f"omero_path_bytes_total{{{labels}}} {float(total)}")
        lines.append(f"omero_path_bytes_used{{{labels}}} {float(used)}")

    return "\n".join(lines) + "\n"


def write_metrics(content: str) -> None:
    """Write metrics atomically to textfile collector output."""
    output_dir = os.path.dirname(OUT) or "."
    os.makedirs(output_dir, exist_ok=True)

    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output_dir,
            prefix=f".{os.path.basename(OUT)}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, TEXTFILE_METRIC_MODE)
        os.replace(tmp_name, OUT)
    except Exception:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
        raise


def main() -> None:
    """Collect and export OMERO host path usage metrics forever."""
    while True:
        try:
            env_values = parse_env_file(PATHS_ENV_FILE)
            metrics = render_metrics(env_values)
            write_metrics(metrics)
        except Exception as exc:
            print(f"Error collecting metrics: {type(exc).__name__}: {exc}", flush=True)

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
