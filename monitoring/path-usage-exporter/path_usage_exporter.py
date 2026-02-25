#!/usr/bin/env python3
"""Path usage exporter for OMERO Docker volumes.

Periodically queries Docker container mount metadata and measures filesystem
usage for OMERO-related bind mounts.  Results are written as Prometheus
textfile-collector metrics consumed by node-exporter.
"""

import os
import time

import docker

OUT = "/textfile/omero_paths.prom"
TMP = OUT + ".tmp"
INTERVAL = 30

TARGETS = [
    ("omero_data",      "omeroserver",     "/OMERO"),
    ("database_main",   "database",        "/var/lib/postgresql/data"),
    ("database_plugin", "database-plugin", "/var/lib/postgresql/data"),
]


def stat_path(host_path: str):
    st = os.statvfs(host_path)
    total = st.f_frsize * st.f_blocks
    avail = st.f_frsize * st.f_bavail
    used = total - avail
    ratio = (used / total) if total > 0 else 0.0
    return total, used, ratio


def find_mount_source(container, dst):
    for m in container.attrs.get("Mounts", []):
        if m.get("Destination") == dst:
            return m.get("Source"), m.get("Type")
    return None, None


def main():
    client = docker.DockerClient(base_url="unix:///var/run/docker.sock")

    while True:
        lines = []
        lines.append("# HELP omero_path_used_ratio Filesystem used ratio for OMERO-related Docker mounts")
        lines.append("# TYPE omero_path_used_ratio gauge")
        lines.append("# HELP omero_path_bytes_total Total bytes for OMERO-related Docker mounts")
        lines.append("# TYPE omero_path_bytes_total gauge")
        lines.append("# HELP omero_path_bytes_used Used bytes for OMERO-related Docker mounts")
        lines.append("# TYPE omero_path_bytes_used gauge")

        containers = client.containers.list(all=True)
        by_service = {}
        for c in containers:
            svc = c.labels.get("com.docker.compose.service")
            if svc:
                by_service[svc] = c

        for kind, service, dst in TARGETS:
            c = by_service.get(service)
            if not c:
                continue
            src, mtype = find_mount_source(c, dst)
            if not src:
                continue

            host_src = os.path.join("/host", src.lstrip("/"))
            host_src_real = os.path.realpath(host_src)

            if not os.path.exists(host_src_real):
                continue

            total, used, ratio = stat_path(host_src_real)
            labels = f'kind="{kind}",service="{service}",dst="{dst}",src="{src}",type="{mtype or ""}"'
            lines.append(f"omero_path_used_ratio{{{labels}}} {ratio}")
            lines.append(f"omero_path_bytes_total{{{labels}}} {float(total)}")
            lines.append(f"omero_path_bytes_used{{{labels}}} {float(used)}")

        data = "\n".join(lines) + "\n"
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(TMP, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(TMP, OUT)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
