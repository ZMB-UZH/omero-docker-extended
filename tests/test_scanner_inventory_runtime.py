"""Real curl/TLS boundary tests and scanner-inventory command error contracts."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from monitoring.tls import certificates
from tools import scanner_inventory as scanner


@pytest.fixture
def inventory_api(tmp_path, monkeypatch):
    """Inputs: private CA and loopback servers. Output: actual curl response fixture."""
    home = tmp_path / "home"
    home.mkdir()
    for name in ("HOME", "CURL_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(home))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    state, trust, servers = (
        tmp_path / name for name in ("private", "trust", "servers")
    )
    for directory in (state, trust, servers, servers / "api"):
        directory.mkdir(mode=0o700)
    identity = certificates.Identity("api", ("127.0.0.1",), os.getuid(), os.getgid())
    certificates.reconcile(state, trust, servers, (identity,))
    monkeypatch.setenv("CURL_CA_BUNDLE", str(trust / "ca.pem"))
    fixture = SimpleNamespace(
        requests=[],
        home=home,
        credential="fixture-private-auth-value",
        transport_errors=[],
        allow_tls_abort=False,
    )

    class Server(ThreadingHTTPServer):
        """Record handler failures and join them before evaluating the fixture."""

        daemon_threads = False

        def handle_error(self, _request, _client_address):
            """Inputs: handler exception. Output: retained evidence checked at teardown."""
            fixture.transport_errors.append((self.server_port, sys.exception()))

    class Handler(BaseHTTPRequestHandler):
        """Inputs: loopback requests. Output: controlled JSON, redirects, and failures."""

        def log_message(self, _format, *_args):
            """Inputs: HTTP log event. Output: retain only structured fixture evidence."""
            return None

        def do_GET(self):
            """Inputs: actual HTTP request. Output: bounded response and request history."""
            fixture.requests.append(
                (self.server.server_port, self.path, dict(self.headers))
            )
            location = None
            status, body = 200, b'{"ok":true}'
            if self.path == "/redirect-plain":
                # This rejected downgrade is intentional; no production traffic uses HTTP.
                location = f"http://127.0.0.1:{plain.server_port}/ok"  # DevSkim: ignore DS137138
                status, body = 302, b""
            elif self.path == "/redirect-secure":
                location = "/ok"
                status, body = 302, b""
            elif self.path == "/bad-json":
                body = b"not JSON"
            elif self.path == "/denied":
                status, body = 403, fixture.credential.encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            if location is not None:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(body)

    plain = Server(("127.0.0.1", 0), Handler)
    secure = Server(("127.0.0.1", 0), Handler)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(servers / "api/cert.pem", servers / "api/key.pem")
    secure.socket = context.wrap_socket(secure.socket, server_side=True)
    threads = [
        threading.Thread(target=server.serve_forever) for server in (plain, secure)
    ]
    for worker in threads:
        worker.start()
    fixture.url = f"https://127.0.0.1:{secure.server_port}"
    fixture.plain_port = plain.server_port
    try:
        yield fixture
    finally:
        for server in (plain, secure):
            server.shutdown()
            server.server_close()
        for worker in threads:
            worker.join(timeout=5)
            assert not worker.is_alive()
        for port, error in fixture.transport_errors:
            assert fixture.allow_tls_abort and not fixture.requests, error
            assert port == secure.server_port, error
            assert isinstance(error, (BrokenPipeError, ConnectionResetError)), error


def fetch(fixture, path):
    """Inputs: controlled local endpoint. Output: real authenticated scanner request."""
    return scanner.fetch_json(
        fixture.url + path,
        headers={"Authorization": "Bearer " + fixture.credential},
        service="Fixture API",
        timeout_seconds=5,
    )


def test_https_redirect_keeps_json_and_authentication(inventory_api):
    """Inputs: verified same-origin redirect. Output: successful authorized JSON response."""
    assert fetch(inventory_api, "/redirect-secure") == {"ok": True}
    assert [request[1] for request in inventory_api.requests] == [
        "/redirect-secure",
        "/ok",
    ]
    assert all(
        row[2]["Authorization"] == "Bearer " + inventory_api.credential
        for row in inventory_api.requests
    )


def test_https_cannot_redirect_to_plaintext(inventory_api):
    """Inputs: HTTPS downgrade redirect. Output: failure before any plaintext request."""
    with pytest.raises(SystemExit, match="request failed"):
        fetch(inventory_api, "/redirect-plain")
    assert all(row[0] != inventory_api.plain_port for row in inventory_api.requests)


def test_user_curl_configuration_cannot_disable_peer_verification(inventory_api):
    """Inputs: unrelated insecure curlrc and mismatched identity. Output: TLS rejection."""
    (inventory_api.home / ".curlrc").write_text("insecure\n")
    inventory_api.url = inventory_api.url.replace("127.0.0.1", "localhost")
    inventory_api.allow_tls_abort = True
    with pytest.raises(SystemExit, match="request failed"):
        fetch(inventory_api, "/ok")
    assert inventory_api.requests == []


def test_invalid_json_and_http_failure_never_disclose_response_body(inventory_api):
    """Inputs: invalid JSON and private denial body. Output: useful, non-secret errors."""
    with pytest.raises(SystemExit, match="invalid JSON"):
        fetch(inventory_api, "/bad-json")
    with pytest.raises(SystemExit, match="request failed") as error:
        fetch(inventory_api, "/denied")
    assert inventory_api.credential not in str(error.value)


@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer"])
def test_positive_limits_reject_invalid_values(value):
    """Inputs: invalid inventory bounds. Output: argument error before an API request."""
    with pytest.raises(argparse.ArgumentTypeError, match="positive integer"):
        scanner.positive_int(value)
    assert scanner.positive_int("2") == 2


@pytest.mark.parametrize("tty", [False, True])
def test_missing_token_never_attempts_noninteractive_prompt(monkeypatch, tty):
    """Inputs: missing token in each terminal mode. Output: explicit absence, no empty auth."""
    monkeypatch.delenv("INVENTORY_FIXTURE_TOKEN", raising=False)
    monkeypatch.setattr(scanner.sys.stdin, "isatty", lambda: tty)
    called = []

    def prompt(_label):
        """Inputs: approved terminal prompt. Output: controlled empty fixture response."""
        called.append(True)
        return " "

    monkeypatch.setattr(scanner.getpass, "getpass", prompt)
    with pytest.raises(SystemExit, match="INVENTORY_FIXTURE_TOKEN is required"):
        scanner.read_token("INVENTORY_FIXTURE_TOKEN", "Fixture")
    assert bool(called) == tty
    if tty:
        monkeypatch.setattr(
            scanner.getpass, "getpass", lambda _label: " fixture-value "
        )
        assert (
            scanner.read_token("INVENTORY_FIXTURE_TOKEN", "Fixture") == "fixture-value"
        )
    monkeypatch.setenv("INVENTORY_FIXTURE_TOKEN", " fixture-value ")
    assert scanner.read_token("INVENTORY_FIXTURE_TOKEN", "Fixture") == "fixture-value"


@pytest.mark.parametrize(
    "failure", [OSError("unavailable"), subprocess.TimeoutExpired(["curl"], 1)]
)
def test_transport_process_failure_is_an_explicit_cli_error(monkeypatch, failure):
    """Inputs: missing process or timeout. Output: controlled non-success result."""
    monkeypatch.setattr(scanner.shutil, "which", lambda _name: "/fixture/curl")

    def failed_run(*_args, **_kwargs):
        """Inputs: process invocation. Output: injected transport exception."""
        raise failure

    monkeypatch.setattr(scanner.subprocess, "run", failed_run)
    with pytest.raises(SystemExit, match="Fixture request failed"):
        scanner.fetch_json("https://example.invalid/", headers={}, service="Fixture")


def test_failed_transport_does_not_print_partial_response_data(monkeypatch):
    """Inputs: interrupted request with partial private data. Output: status-only error."""
    monkeypatch.setattr(scanner.shutil, "which", lambda _name: "/fixture/curl")
    monkeypatch.setattr(
        scanner.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["curl"], -15, stdout="fixture-private-response", stderr=""
        ),
    )
    with pytest.raises(SystemExit, match="curl exited with status -15") as error:
        scanner.fetch_json("https://example.invalid/", headers={}, service="Fixture")
    assert "fixture-private-response" not in str(error.value)


@pytest.mark.parametrize("url", ["file:///fixture", "https:///missing-host"])
def test_invalid_request_url_is_rejected_before_process_launch(url, monkeypatch):
    """Inputs: non-network or missing-host URL. Output: no process or filesystem access."""
    monkeypatch.setattr(
        scanner.shutil, "which", lambda _name: pytest.fail("Unexpected lookup")
    )
    with pytest.raises(SystemExit, match="requires an HTTPS URL"):
        scanner.fetch_json(url, headers={}, service="Fixture")


def test_missing_curl_is_explicit(monkeypatch):
    """Inputs: absent transport executable. Output: dependency failure before API access."""
    monkeypatch.setattr(scanner.shutil, "which", lambda _name: None)
    with pytest.raises(SystemExit, match="curl is required"):
        scanner.fetch_json("https://example.invalid/", headers={}, service="Fixture")


@pytest.mark.parametrize(
    "payload,message",
    [
        ([], "no supported versions"),
        ({"unexpected": True}, "no supported versions"),
        ([None], "invalid response"),
    ],
)
def test_malformed_version_inventory_fails_closed(monkeypatch, payload, message):
    """Inputs: malformed API version inventory. Output: no guessed or downgraded version."""
    monkeypatch.setattr(scanner, "fetch_json", lambda *_args, **_kwargs: payload)
    with pytest.raises(SystemExit, match=message):
        scanner.latest_github_api_version("fixture-value")


def test_malformed_alert_inventory_is_not_reported_as_zero(monkeypatch):
    """Inputs: unexpected alert-response shape. Output: explicit failure, not clean count."""
    monkeypatch.setattr(scanner, "read_token", lambda *_args: "fixture-value")
    monkeypatch.setattr(
        scanner,
        "latest_github_api_version",
        lambda *_args, **_kwargs: "fixture-version",
    )
    monkeypatch.setattr(scanner, "fetch_json", lambda *_args, **_kwargs: {})
    args = argparse.Namespace(
        repository="owner/repository",
        token_env="FIXTURE",
        state="open",
        branch="default",
    )
    with pytest.raises(SystemExit, match="invalid response"):
        scanner.summarize_github_code_scanning(args)


@pytest.mark.parametrize(
    "handler", [scanner.summarize_deepsource, scanner.summarize_deepsource_issues]
)
@pytest.mark.parametrize(
    "payload,message",
    [
        ({"errors": ["fixture-error"]}, "GraphQL errors"),
        ({"data": None}, "repository was not found"),
    ],
)
def test_graphql_errors_are_not_summarized_as_clean(
    monkeypatch, handler, payload, message
):
    """Inputs: GraphQL error or absent repository. Output: explicit unavailable inventory."""
    monkeypatch.setattr(scanner, "read_token", lambda *_args: "fixture-value")
    monkeypatch.setattr(scanner, "fetch_json", lambda *_args, **_kwargs: payload)
    args = argparse.Namespace(
        repository="gh/owner/repository",
        token_env="FIXTURE",
        issue_limit=10,
        occurrence_limit=2,
    )
    with pytest.raises(SystemExit, match=message):
        handler(args)


def test_invalid_grouped_issue_collection_is_not_empty_success(monkeypatch):
    """Inputs: absent issue collection. Output: failure instead of a zero-finding summary."""
    monkeypatch.setattr(scanner, "read_token", lambda *_args: "fixture-value")
    monkeypatch.setattr(
        scanner,
        "fetch_json",
        lambda *_args, **_kwargs: {"data": {"repository": {"issues": None}}},
    )
    args = argparse.Namespace(
        repository="gh/owner/repository",
        token_env="FIXTURE",
        issue_limit=10,
        occurrence_limit=2,
    )
    with pytest.raises(SystemExit, match="issue list returned invalid data"):
        scanner.summarize_deepsource_issues(args)


@pytest.mark.parametrize(
    "command,handler",
    [
        ("github-code-scanning", "summarize_github_code_scanning"),
        ("deepsource", "summarize_deepsource"),
        ("deepsource-issues", "summarize_deepsource_issues"),
    ],
)
def test_cli_dispatch_uses_the_matching_provider(monkeypatch, capsys, command, handler):
    """Inputs: parsed provider choice. Output: exactly that provider's structured result."""
    args = argparse.Namespace(command=command)
    monkeypatch.setattr(scanner, "parse_args", lambda: args)
    seen = []

    def summarize(value):
        """Inputs: original parsed arguments. Output: deterministic provider receipt."""
        seen.append(value)
        return {"provider": command}

    monkeypatch.setattr(scanner, handler, summarize)
    assert scanner.main() == 0
    assert seen == [args]
    assert json.loads(capsys.readouterr().out) == {"provider": command}


def test_cli_help_runs_without_credentials_or_network():
    """Inputs: actual command entrypoint. Output: successful help without an API call."""
    result = subprocess.run(
        [sys.executable, str(Path(scanner.__file__)), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "github-code-scanning" in result.stdout
    assert result.stderr == ""


def test_dispatch_rejects_an_unknown_provider(monkeypatch):
    """Inputs: invalid programmatic dispatch. Output: explicit unsupported-command error."""
    monkeypatch.setattr(
        scanner, "parse_args", lambda: argparse.Namespace(command="unknown")
    )
    with pytest.raises(SystemExit, match="Unsupported command: unknown"):
        scanner.main()
