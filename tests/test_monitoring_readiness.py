"""Exercise the shipped readiness commands against real HTTP responses."""

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import subprocess
import threading

import pytest
import yaml


def _services():
    """Inputs: tracked Compose file. Output: parsed service definitions."""
    return yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text()
    )["services"]


def test_loki_uses_native_readiness_command():
    """Inputs: Compose services. Output: asserts use of Loki's native readiness probe."""
    services = _services()
    assert services["loki"]["healthcheck"]["test"] == [
        "CMD",
        "/usr/bin/loki",
        "-health",
    ]


@pytest.mark.parametrize("status", [200, 302, 403, 503])
def test_alloy_readiness_requires_http_200(status):
    """Inputs: HTTP response status. Output: confirms only 200 passes the real probe."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            """Inputs: test HTTP request. Output: configured readiness response."""
            assert self.path == "/-/ready"
            self.send_response(status)
            self.end_headers()

        def log_message(self, *_args):
            """Inputs: server log arguments. Output: none, keeping fixture traffic quiet."""
            return None

    services = _services()
    listen_arg = next(
        value
        for value in services["alloy"]["command"]
        if value.startswith("--server.http.listen-addr=")
    )
    configured_port = listen_arg.rsplit(":", 1)[1]
    command = services["alloy"]["healthcheck"]["test"][1:]
    assert f"/dev/tcp/127.0.0.1/{configured_port}" in command[-1]
    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            command[-1] = (
                command[-1]
                .replace("$$", "$")
                .replace(
                    f"/127.0.0.1/{configured_port}", f"/127.0.0.1/{server.server_port}"
                )
            )
            result = subprocess.run(
                command, capture_output=True, timeout=10, check=False
            )
            assert (result.returncode == 0) is (status == 200)
        finally:
            server.shutdown()
            thread.join(timeout=5)
