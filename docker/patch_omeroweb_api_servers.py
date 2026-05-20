#!/usr/bin/env python3
"""Patch OMERO.web API server discovery to return the request host."""

from __future__ import annotations

import sys
from pathlib import Path


OLD_IMPORT_BLOCK = """import traceback
import json
"""

NEW_IMPORT_BLOCK = """import traceback
import json
import os
"""

OLD_API_SERVERS_BLOCK = '''@json_response()
def api_servers(request, api_version, **kwargs):
    """List the available servers to connect to."""
    servers = []
    for i, obj in enumerate(Server):
        s = {"id": i + 1, "host": obj.host, "port": obj.port}
        if obj.server is not None:
            s["server"] = obj.server
        servers.append(s)
    return {"data": servers}
'''

NEW_API_SERVERS_BLOCK = '''def _api_request_host_without_port(request):
    host = request.get_host()
    if host.startswith("["):
        bracket_end = host.find("]")
        if bracket_end != -1:
            return host[1:bracket_end]
    if host.count(":") == 1:
        return host.rsplit(":", 1)[0]
    return host


def _api_server_host_for_request(request, configured_host):
    if configured_host == os.environ.get("OMEROHOST", ""):
        return _api_request_host_without_port(request)
    return configured_host


@json_response()
def api_servers(request, api_version, **kwargs):
    """List the available servers to connect to."""
    servers = []
    for i, obj in enumerate(Server):
        s = {
            "id": i + 1,
            "host": _api_server_host_for_request(request, obj.host),
            "port": obj.port,
        }
        if obj.server is not None:
            s["server"] = obj.server
        servers.append(s)
    return {"data": servers}
'''


def main() -> int:
    """Run the `docker.patch_omeroweb_api_servers` command entrypoint.

    Inputs: none. Output: `int`. Raises: SystemExit for invalid target layout.
    """
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_omeroweb_api_servers.py <views.py>")

    target_path = Path(sys.argv[1])
    original_text = target_path.read_text(encoding="utf-8")

    if NEW_API_SERVERS_BLOCK in original_text:
        return 0

    if OLD_API_SERVERS_BLOCK not in original_text:
        raise SystemExit(
            f"expected OMERO.web api_servers block not found in {target_path}"
        )

    patched_text = original_text
    if NEW_IMPORT_BLOCK not in patched_text:
        if OLD_IMPORT_BLOCK not in patched_text:
            raise SystemExit(
                f"expected OMERO.web import block not found in {target_path}"
            )
        patched_text = patched_text.replace(OLD_IMPORT_BLOCK, NEW_IMPORT_BLOCK, 1)

    patched_text = patched_text.replace(
        OLD_API_SERVERS_BLOCK,
        NEW_API_SERVERS_BLOCK,
        1,
    )
    target_path.write_text(patched_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
