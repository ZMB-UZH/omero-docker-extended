"""Real HTTPS/HTTP framing tests for the standalone Imaris web client."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from email import policy
from email.parser import BytesParser
import importlib.util
import http.client
import io
import json
import os
from pathlib import Path
import socket
import ssl
import threading
from types import SimpleNamespace
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import Mock

import pytest
import numpy as np
import tifffile

from monitoring.tls import certificates


def test_export_redirect_query_does_not_falsely_report_an_expired_login(
    https_api, tmp_path
):
    """Inputs: non-login redirect whose query mentions the login path. Output: accurate export-redirect failure, not false authentication expiry."""
    module, client, fixture = https_api
    assert client.connect()
    session = client.session_id
    method, _payload = _configure_complete_export(
        module, client, fixture, "standard_tiff"
    )
    fixture.responses[("GET", "/webgateway/render_ome_tiff/i/7/")] = [
        (302, b"", [("Location", "/maintenance/?next=/webclient/login/")])
    ]
    output = tmp_path / "downloads"
    output.mkdir()
    fixture.requests.clear()
    with pytest.raises(
        RuntimeError, match="redirected instead of returning an OME-TIFF"
    ):
        method(7, output, cancel_event=threading.Event())
    assert not list(output.iterdir())
    assert client.session_id == session
    assert all(row[0] == "GET" for row in fixture.requests)


@pytest.mark.parametrize("response", ["redirect", "unauthorized"])
def test_export_poll_uses_explicitly_resupplied_credential_only_once(
    https_api, tmp_path, response
):
    """Inputs: one expired poll and an explicitly resupplied credential. Output: one reauthentication, byte-exact export and immediate credential clearing."""
    module, client, fixture = https_api
    assert client.connect()
    method, payload = _configure_complete_export(module, client, fixture, "ims")
    client.password = fixture.credential
    rejected = (
        (302, b"", [("Location", "/webclient/login/")])
        if response == "redirect"
        else (
            401,
            b'{"message":"Not logged in"}',
            [("Content-Type", "application/json")],
        )
    )
    fixture.responses[("GET", "/export/status/")].insert(0, rejected)
    output = tmp_path / "downloads"
    output.mkdir()
    fixture.requests.clear()
    result = method(7, output, cancel_event=threading.Event())
    assert Path(result).read_bytes() == payload
    assert client.password == module.CLEARED_CREDENTIAL_TEXT
    assert not client._active_ims_export_jobs
    assert (
        sum(row[:2] == ("POST", "/webclient/login/") for row in fixture.requests) == 1
    )
    assert sum(row[:2] == ("POST", "/api/v0/login/") for row in fixture.requests) == 1
    assert (
        sum(
            row[:2] == ("POST", "/omero_imaris_connector/imaris-export/")
            for row in fixture.requests
        )
        == 1
    )
    assert sum(row[:2] == ("GET", "/export/status/") for row in fixture.requests) == 2


def test_ims_connection_refusal_leaves_session_and_destination_untouched(
    https_api, tmp_path
):
    """Inputs: real refused export connection. Output: bounded transport failure, unchanged session and no partial image."""
    _module, client, fixture = https_api
    assert client.connect()
    session = client.session_id
    output = tmp_path / "downloads"
    output.mkdir()
    fixture.requests.clear()
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        client.base_url = f"https://127.0.0.1:{unavailable.getsockname()[1]}"
        with pytest.raises(RuntimeError, match="IMS export failed.*URLError"):
            client.download_ims_export(7, output)
    assert client.session_id == session
    assert not list(output.iterdir())
    assert fixture.requests == []
    assert not client._active_ims_export_jobs


def test_async_tiff_start_login_redirect_is_rejected_without_credential_replay(
    https_api, tmp_path
):
    """Inputs: login redirect at asynchronous TIFF creation. Output: explicit expiry, no replay, no download and no leaked active job."""
    module, client, fixture = https_api
    assert client.connect()
    session = client.session_id
    method, _payload = _configure_complete_export(module, client, fixture, "async_tiff")
    fixture.responses[("POST", "/omero_imaris_connector/imaris-export/")] = [
        (302, b"", [("Location", "/webclient/login/")])
    ]
    fixture.requests.clear()
    output = tmp_path / "downloads"
    output.mkdir()
    with pytest.raises(
        RuntimeError, match="Not authenticated.*starting selected Image"
    ):
        method(7, output, cancel_event=threading.Event())
    assert client.session_id == session
    assert not list(output.iterdir())
    assert not client._active_ims_export_jobs
    assert sum(row[0] == "POST" for row in fixture.requests) == 1
    assert not any(row[0] == "POST" and "login" in row[1] for row in fixture.requests)
    assert client.password == module.CLEARED_CREDENTIAL_TEXT


def test_async_tiff_cancellation_requests_server_stop_and_clears_tracking(
    https_api, tmp_path, monkeypatch
):
    """Inputs: cancellation during a real TIFF status response. Output: one server cancellation, no download, cleared job tracking and preserved session."""
    module, client, fixture = https_api
    assert client.connect()
    session = client.session_id
    method, _payload = _configure_complete_export(module, client, fixture, "async_tiff")
    _serve_json(
        fixture, "GET", "/export/status/", {"finished": False, "state": "running"}
    )
    _serve_json(fixture, "POST", "/export/status/", {"cancelled": True})
    cancel = threading.Event()
    reply = fixture.handler.reply

    def cancel_after_poll(handler, *args, **kwargs):
        """Inputs: actual status response. Output: cancellation while preserving a well-framed response for the client."""
        result = reply(handler, *args, **kwargs)
        if handler.command == "GET" and handler.path == "/export/status/":
            cancel.set()
        return result

    monkeypatch.setattr(fixture.handler, "reply", cancel_after_poll)
    fixture.requests.clear()
    output = tmp_path / "downloads"
    output.mkdir()
    with pytest.raises(module._ConnectorOperationCancelled):
        method(7, output, cancel_event=cancel)
    assert not list(output.iterdir())
    assert client.session_id == session
    assert not client._active_ims_export_jobs
    stops = [row for row in fixture.requests if row[:2] == ("POST", "/export/status/")]
    assert len(stops) == 1 and json.loads(stops[0][3]) == {"cancel": True}
    assert not any(row[1] == "/export/file/" for row in fixture.requests)


def test_unchanged_login_cookie_requires_verified_api_access_not_an_assumed_failure(
    https_api, monkeypatch, capsys
):
    """Inputs: server retains a pre-login cookie after successful login. Output: warning plus verified API authentication, with the password cleared."""
    module, client, fixture = https_api
    reply = fixture.handler.reply

    def existing_cookie(handler, status, body=b"", headers=(), *args):
        """Inputs: actual login GET. Output: pre-authentication cookie that the server later retains."""
        if handler.command == "GET" and handler.path == "/webclient/login/":
            headers = [
                *(headers or ()),
                (
                    "Set-Cookie",
                    "sessionid=fixture-session; Path=/; Secure; HttpOnly; SameSite=Lax",
                ),
            ]
        return reply(handler, status, body, headers, *args)

    monkeypatch.setattr(fixture.handler, "reply", existing_cookie)
    assert client.connect()
    assert "session cookie unchanged after POST" in capsys.readouterr().out
    assert client.password == module.CLEARED_CREDENTIAL_TEXT
    assert client.user_id == 7
    assert any(
        row[0] == "GET" and row[1].startswith("/api/v0/m/projects/")
        for row in fixture.requests
    )


@pytest.mark.parametrize(
    "status_line",
    [
        b"NOT-HTTP 200 OK",
        b"HTTP/2.0 200 OK",
        b"HTTP/1.1 099 Invalid",
        b"HTTP/1.1 0200 Invalid",
        b"HTTP/1.1 2000 Invalid",
    ],
)
def test_cancellable_transport_rejects_invalid_protocol_and_status_without_session_reset(
    https_api, monkeypatch, status_line
):
    """Inputs: malformed status line from a real trusted TLS peer. Output: protocol rejection without accepting a body or resetting credentials."""
    module, client, fixture = https_api
    assert client.connect()
    session = client.session_id
    requests_before = len(fixture.requests)

    def reply(handler, *_args, **_kwargs):
        """Inputs: actual TLS request. Output: malformed status followed by otherwise well-framed data."""
        handler.close_connection = True
        handler.wfile.write(
            status_line + b"\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
        )

    monkeypatch.setattr(fixture.handler, "reply", reply)
    request = client._create_request_with_cookies(fixture.base_url + "/fixture/")
    with pytest.raises(
        http.client.HTTPException, match="Invalid OMERO.web status line"
    ):
        with client._open_cancellable_http_request(request, 2, threading.Event()):
            pytest.fail("Malformed HTTP status was accepted")
    assert client.session_id == session
    assert client.password == module.CLEARED_CREDENTIAL_TEXT
    assert len(fixture.requests) == requests_before + 1


@pytest.mark.parametrize(
    "status_line",
    [b"HTTP/1.0 200 OK", b"HTTP/1.1 200", b"HTTP/1.1   200  OK", b"HTTP/1.2 200 OK"],
)
def test_cancellable_transport_accepts_compatible_http_one_responses(
    https_api, monkeypatch, status_line
):
    """Inputs: compatible HTTP/1.x status forms over real TLS. Output: exact body bytes, status and unchanged authenticated session."""
    _module, client, fixture = https_api
    assert client.connect()
    session = client.session_id

    def reply(handler, *_args, **_kwargs):
        """Inputs: real TLS request. Output: complete HTTP/1.x response with optional reason phrase."""
        handler.close_connection = True
        handler.wfile.write(
            status_line + b"\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
        )

    monkeypatch.setattr(fixture.handler, "reply", reply)
    request = client._create_request_with_cookies(fixture.base_url + "/fixture/")
    with client._open_cancellable_http_request(
        request, 2, threading.Event()
    ) as response:
        assert response.status == 200
        assert response.read() == b"ok"
    assert client.session_id == session


@pytest.mark.parametrize(
    "wire,expected",
    [
        (b"", "closed the response before sending headers"),
        (
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n",
            "closed the response before sending headers",
        ),
        (b"HTTP/1.1 200 OK\r\nX-Large: " + b"x" * 256, "headers were too large"),
        (
            b"HTTP/1.1 200 OK\r\nX-Large: " + b"x" * 256 + b"\r\n\r\n",
            "headers were too large",
        ),
    ],
)
def test_cancellable_transport_refuses_incomplete_and_oversized_headers(
    https_api, monkeypatch, wire, expected
):
    """Inputs: truncated or excessive real TLS response headers. Output: bounded protocol error, no usable response or session mutation."""
    module, client, fixture = https_api
    assert client.connect()
    session = client.session_id
    monkeypatch.setattr(module, "CANCELLABLE_HTTP_MAX_HEADER_BYTES", 128)

    def reply(handler, *_args, **_kwargs):
        """Inputs: actual request. Output: incomplete or over-budget header bytes, then close."""
        handler.close_connection = True
        handler.wfile.write(wire)

    monkeypatch.setattr(fixture.handler, "reply", reply)
    request = client._create_request_with_cookies(fixture.base_url + "/fixture/")
    with pytest.raises(http.client.HTTPException, match=expected):
        with client._open_cancellable_http_request(request, 2, threading.Event()):
            pytest.fail("Invalid headers yielded a usable response")
    assert client.session_id == session


@pytest.mark.parametrize(
    "url,method",
    [("ftp://example.test/file", "GET"), ("https://example.test/", "POST")],
)
def test_cancellable_transport_delegates_non_socket_protocols_without_replay(
    https_api, monkeypatch, url, method
):
    """Inputs: method/protocol outside the cancellable GET transport. Output: exactly one standard-opener request and no custom socket."""
    module, client, _fixture = https_api
    request = module.urllib.request.Request(url, method=method)
    expected = object()
    open_request = Mock(return_value=expected)
    client.opener = SimpleNamespace(open=open_request)
    connect = Mock(
        side_effect=AssertionError("Custom socket used for delegated request")
    )
    monkeypatch.setattr(module.socket, "create_connection", connect)
    assert (
        client._open_cancellable_http_request(request, 3, threading.Event()) is expected
    )
    open_request.assert_called_once_with(request, timeout=3)
    connect.assert_not_called()


def test_json_request_without_session_never_contacts_the_server(https_api):
    """Inputs: unauthenticated JSON request. Output: explicit refusal with no network request or implicit login."""
    _module, client, fixture = https_api
    assert not client.session_id
    fixture.requests.clear()
    with pytest.raises(RuntimeError, match="Not authenticated"):
        client._request_json_url(client.base_url + "/fixture-json/")
    assert fixture.requests == []


@pytest.mark.parametrize("mode", ["redirect", "login_html"])
def test_json_endpoint_login_response_is_not_accepted_as_application_data(
    https_api, mode
):
    """Inputs: real login redirect or HTML response. Output: authentication failure, without an automatic credential replay."""
    _module, client, fixture = https_api
    assert client.connect()
    original = client.session_id
    fixture.mode = mode
    fixture.requests.clear()
    with pytest.raises(RuntimeError, match="Not authenticated"):
        client._request_json_url(client.base_url + "/fixture-json/")
    assert client.session_id == original
    assert all(method == "GET" for method, _path, _headers, _body in fixture.requests)


@pytest.mark.parametrize("recover", [False, True])
def test_opted_in_json_read_retries_transient_disconnect_without_relogin(
    https_api, monkeypatch, recover
):
    """Inputs: a real disconnected TLS response. Output: bounded read-only retry or explicit failure with original authentication preserved."""
    module, client, fixture = https_api
    assert client.connect()
    original = (client.session_id, client.csrf_token, client.cookie_jar)
    monkeypatch.setenv(module.HTTP_TRANSIENT_RETRY_ATTEMPTS_ENV, "2")
    monkeypatch.setenv(module.HTTP_TRANSIENT_RETRY_DELAY_ENV, "0")
    fixture.mode = "closed_once" if recover else "closed_connection"
    fixture.requests.clear()
    if recover:
        status, payload, _text = client._request_json_url(
            client.base_url + "/fixture-json/", retry_transient=True
        )
        assert status == 200 and payload == {"data": []}
    else:
        with pytest.raises(RuntimeError, match="request failed"):
            client._request_json_url(
                client.base_url + "/fixture-json/", retry_transient=True
            )
    assert len(fixture.requests) == 2
    assert all(
        (method, path) == ("GET", "/fixture-json/")
        for method, path, _headers, _body in fixture.requests
    )
    assert (client.session_id, client.csrf_token, client.cookie_jar) == original


def test_json_post_outage_is_never_automatically_replayed(https_api):
    """Inputs: server closes a submitted request without a response. Output: failure after one POST, preserving the session and avoiding duplicate jobs."""
    _module, client, fixture = https_api
    assert client.connect()
    original = client.session_id
    fixture.mode = "closed_connection"
    fixture.requests.clear()
    with pytest.raises(RuntimeError, match="request failed"):
        client._request_json_url(
            client.base_url + "/fixture-json/", payload={"action": "start"}
        )
    assert len(fixture.requests) == 1
    method, path, headers, body = fixture.requests[0]
    assert (method, path) == ("POST", "/fixture-json/")
    assert json.loads(body) == {"action": "start"}
    assert headers["Content-Type"] == "application/json"
    assert client.session_id == original


def test_json_request_preserves_explicit_content_type_and_headers(https_api):
    """Inputs: explicit JSON media type and request correlation header. Output: exact wire contract and decoded response."""
    _module, client, fixture = https_api
    assert client.connect()
    _serve_json(fixture, "POST", "/fixture-json/", {"ok": True})
    fixture.requests.clear()
    status, payload, _text = client._request_json_url(
        client.base_url + "/fixture-json/",
        raw_data=b'{"fixture":true}',
        content_type="application/vnd.fixture+json",
        headers={"X-Request-Id": "fixture-request"},
    )
    assert (status, payload) == (200, {"ok": True})
    assert len(fixture.requests) == 1
    method, path, headers, body = fixture.requests[0]
    assert (method, path, body) == ("POST", "/fixture-json/", b'{"fixture":true}')
    assert headers["Content-Type"] == "application/vnd.fixture+json"
    assert headers["X-Request-Id"] == "fixture-request"


def test_truncated_http_error_body_retains_status_without_disclosing_partial_data(
    https_api,
):
    """Inputs: a real incomplete HTTP error response. Output: status retained, incomplete content discarded and connection closed."""
    _module, client, fixture = https_api
    assert client.connect()
    original = client.session_id
    fixture.responses[("GET", "/fixture-json/")] = [
        (503, b"partial", [("Content-Length", "100")])
    ]
    assert client._request_json_url(client.base_url + "/fixture-json/") == (
        503,
        None,
        "",
    )
    assert client.session_id == original


@pytest.mark.parametrize("needs_legacy_shape", [False, True])
def test_script_submission_preserves_inputs_and_only_falls_back_after_rejection(
    https_api, needs_legacy_shape
):
    """Inputs: current or legacy API input schema. Output: accepted job and exact field values, with no extra request after success."""
    _module, client, fixture = https_api
    assert client.connect()
    responses = [(200, b'{"jobId":19}', [("Content-Type", "application/json")])]
    if needs_legacy_shape:
        responses.insert(
            0, (400, b'{"error":"input shape"}', [("Content-Type", "application/json")])
        )
    fixture.responses[("POST", "/api/v0/scripts/7/run/")] = responses
    fixture.requests.clear()
    assert client.run_script(7, {"image": 3, "name": "fixture"}) == {"jobId": 19}
    assert len(fixture.requests) == (2 if needs_legacy_shape else 1)
    payloads = [json.loads(body) for _method, _path, _headers, body in fixture.requests]
    assert payloads[0] == {"inputs": {"image": 3, "name": "fixture"}}
    if needs_legacy_shape:
        assert payloads[1] == {
            "inputs": {"image": {"value": 3}, "name": {"value": "fixture"}}
        }


@pytest.mark.parametrize(
    "failure", ["server_error", "disconnect", "empty", "invalid_json"]
)
def test_script_submission_never_replays_an_ambiguous_outcome(https_api, failure):
    """Inputs: a submitted job with an uncertain response. Output: no second submission and no automatic login."""
    _module, client, fixture = https_api
    assert client.connect()
    original = client.session_id
    if failure == "disconnect":
        fixture.mode = "closed_connection"
    else:
        status, body = {
            "server_error": (503, b"Service unavailable"),
            "empty": (200, b""),
            "invalid_json": (200, b"invalid-json"),
        }[failure]
        fixture.responses[("POST", "/api/v0/scripts/7/run/")] = [
            (status, body, [("Content-Type", "application/json")])
        ]
    fixture.requests.clear()
    assert client.run_script(7, {"image": 3}) is None
    assert len(fixture.requests) == 1
    method, path, _headers, body = fixture.requests[0]
    assert (method, path) == ("POST", "/api/v0/scripts/7/run/")
    assert json.loads(body) == {"inputs": {"image": 3}}
    assert client.session_id == original


def test_script_schema_rejection_has_one_bounded_compatibility_fallback(https_api):
    """Inputs: both input encodings rejected by the API. Output: two attempts only, with no invented successful job."""
    _module, client, fixture = https_api
    assert client.connect()
    fixture.responses[("POST", "/api/v0/scripts/7/run/")] = [
        (400, b'{"error":"input shape"}', [("Content-Type", "application/json")])
    ]
    fixture.requests.clear()
    assert client.run_script(7, {"image": 3}) is None
    assert len(fixture.requests) == 2
    assert all(method == "POST" for method, _path, _headers, _body in fixture.requests)


@pytest.mark.parametrize(
    "action,method",
    [
        ("trigger_folder_export", "POST"),
        ("confirm_folder_export", "POST"),
        ("get_folder_export_status", "GET"),
    ],
)
@pytest.mark.parametrize(
    "payload,status",
    [
        ({"ok": True, "state": "pending"}, 200),
        ({"ok": False}, 200),
        ({"ok": 1}, 200),
        ([], 200),
        ({"ok": True}, 503),
    ],
)
def test_folder_job_actions_require_explicit_server_acceptance(
    https_api, action, method, payload, status
):
    """Inputs: real action/status responses. Output: truthful success only on explicit acceptance, original session and CSRF retained."""
    _module, client, fixture = https_api
    assert client.connect()
    original = (client.session_id, client.csrf_token, client.cookie_jar)
    _serve_json(fixture, method, "/folder-action/", payload, status=status)
    fixture.requests.clear()
    operation = getattr(client, action)
    if isinstance(payload, dict) and payload.get("ok") is True and status < 400:
        assert operation(client.base_url + "/folder-action/") == payload
    else:
        with pytest.raises(RuntimeError) as caught:
            operation(client.base_url + "/folder-action/")
        assert str(caught.value) == json.dumps(payload)
    assert len(fixture.requests) == 1
    verb, path, headers, body = fixture.requests[0]
    assert (verb, path) == (method, "/folder-action/")
    assert "sessionid=" + original[0] in headers["Cookie"]
    if method == "POST":
        assert json.loads(body) == {}
        assert headers["X-Csrftoken"] == original[1]
    assert (client.session_id, client.csrf_token, client.cookie_jar) == original


@pytest.mark.parametrize(
    "action",
    ["trigger_folder_export", "confirm_folder_export", "get_folder_export_status"],
)
def test_missing_folder_job_url_never_sends_a_request(https_api, action):
    """Inputs: missing server capability URL. Output: fail before network access, without guessing an endpoint."""
    _module, client, fixture = https_api
    fixture.requests.clear()
    with pytest.raises(RuntimeError, match="URL is missing"):
        getattr(client, action)(None)
    assert fixture.requests == []


def test_folder_job_start_normalizes_inventory_and_pins_returned_urls_to_origin(
    https_api,
):
    """Inputs: mixed inventory rows and internal backend URLs. Output: stable idempotency token, normalized sizes, public-origin URLs."""
    _module, client, fixture = https_api
    assert client.connect()
    endpoint_names = (
        "upload_url",
        "import_step_url",
        "status_url",
        "confirm_url",
        "prune_url",
    )
    _serve_json(
        fixture,
        "POST",
        "/omeroweb_import/start/",
        {
            "ok": True,
            **{key: "https://backend.example.test/" + key for key in endpoint_names},
        },
    )
    fixture.requests.clear()
    result = client.start_folder_export_job(
        "  fixture dataset  ",
        [
            None,
            {},
            {"relative_path": ""},
            {"relative_path": " image.tif ", "size": "42"},
            {"relative_path": "negative.tif", "size": -1},
            {"relative_path": "invalid.tif", "size": "invalid"},
        ],
    )
    assert result == {
        "ok": True,
        **{key: client.base_url + "/" + key for key in endpoint_names},
    }
    assert len(fixture.requests) == 1
    method, path, headers, body = fixture.requests[0]
    assert (method, path) == ("POST", "/omeroweb_import/start/")
    sent = json.loads(body)
    assert len(sent["client_upload_id"]) == 32
    int(sent["client_upload_id"], 16)
    assert sent["dataset_name_override"] == "fixture dataset"
    assert sent["compatibility_enabled"] is True
    assert sent["files"] == [
        {"relative_path": "image.tif", "size": 42},
        {"relative_path": "negative.tif", "size": 0},
        {"relative_path": "invalid.tif", "size": 0},
    ]
    assert headers["X-Csrftoken"] == client.csrf_token


@pytest.mark.parametrize(
    "name,entries,error",
    [
        (None, [{"relative_path": "image.tif"}], "folder name"),
        (" ", [], "folder name"),
        ("fixture", [None, {}], "does not contain any files"),
    ],
)
def test_invalid_folder_start_has_no_network_or_storage_side_effects(
    https_api, name, entries, error
):
    """Inputs: invalid folder inventory. Output: no job created and actionable local error."""
    _module, client, fixture = https_api
    fixture.requests.clear()
    with pytest.raises(RuntimeError, match=error):
        client.start_folder_export_job(name, entries)
    assert not fixture.requests


def test_cancellable_reads_drain_tls_buffer_without_waiting_for_peer_close(
    https_api, monkeypatch
):
    """Inputs: one TLS record with the peer still open. Output: small reads drain decrypted bytes without timing out."""
    _module, client, fixture = https_api
    assert client.connect()
    original = (client.session_id, client.csrf_token, client.cookie_jar)
    send_body, release_peer = threading.Event(), threading.Event()

    def respond(handler):
        """Inputs: request on the isolated TLS server. Output: headers, then a gated record while the peer stays open."""
        handler.send_response(200)
        handler.send_header("Content-Length", "3")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.flush()
        if send_body.wait(5):
            handler.wfile.write(b"abc")
            handler.wfile.flush()
        release_peer.wait(5)

    monkeypatch.setattr(fixture.handler, "route", respond)
    request = client._create_request_with_cookies(client.base_url + "/buffered/")
    try:
        with client._open_request_response(request, 2, threading.Event()) as response:
            send_body.set()
            assert response.read(1) == b"a"
            assert response.read(1) == b"b"
            assert response.read(1) == b"c"
            assert response.read(1) == b""
        assert response.closed
    finally:
        send_body.set()
        release_peer.set()
    assert (client.session_id, client.csrf_token, client.cookie_jar) == original


@pytest.mark.parametrize("oversized_headers", [False, True])
def test_cancellable_header_limit_applies_to_headers_not_coalesced_body(
    https_api, monkeypatch, oversized_headers
):
    """Inputs: real HTTPS headers/body across the size boundary. Output: reject oversized headers only, preserving login."""
    module, client, fixture = https_api
    assert client.connect()
    original = (client.session_id, client.csrf_token, client.cookie_jar)
    monkeypatch.setattr(module, "CANCELLABLE_HTTP_MAX_HEADER_BYTES", 1024)
    payload = b"image-body" * 4096
    headers = [("X-Boundary", "x" * (1024 if oversized_headers else 16))]
    fixture.responses[("GET", "/framing-boundary/")] = [(200, payload, headers)]
    request = client._create_request_with_cookies(
        client.base_url + "/framing-boundary/"
    )
    if oversized_headers:
        with pytest.raises(
            module.http.client.HTTPException, match="headers were too large"
        ):
            with client._open_request_response(request, 5, threading.Event()):
                pytest.fail("Oversized headers were accepted")
    else:
        with client._open_request_response(request, 5, threading.Event()) as response:
            assert response.read() == payload
        assert response.closed
    assert (client.session_id, client.csrf_token, client.cookie_jar) == original


@pytest.mark.parametrize("operation", ["api_post", "ims", "standard_tiff"])
def test_discarded_http_error_bodies_are_not_downloaded(
    https_api, tmp_path, monkeypatch, operation
):
    """Inputs: actual failed HTTPS responses. Output: close without reading unused bodies or replaying requests."""
    _module, client, fixture = https_api
    assert client.connect()
    original_session = client.session_id
    original_cookies = [(cookie.name, cookie.value) for cookie in client.cookie_jar]
    output = tmp_path / "downloads"
    output.mkdir()
    prior = output / "original.ims"
    prior.write_bytes(b"preserve this user file")
    if operation == "api_post":
        route = ("POST", "/api/v0/fixture/")
    elif operation == "ims":
        route = ("POST", "/omero_imaris_connector/imaris-export/")
    else:
        _serve_json(fixture, "GET", "/omero_imaris_connector/imaris-export/", {})
        route = ("GET", "/webgateway/render_ome_tiff/i/7/")
    fixture.responses[route] = [(500, b"private upstream diagnostic" * 4096, [])]
    errors, reads = [], []
    original_open = client.opener.open

    def record_error(*args, **kwargs):
        """Inputs: real request. Output: unchanged HTTP exception with observed body consumption."""
        try:
            return original_open(*args, **kwargs)
        except urllib.error.HTTPError as error:
            errors.append(error)
            original_read = error.read

            def read(size=-1):
                """Inputs: requested bytes. Output: real stream bytes and consumption evidence."""
                reads.append(size)
                return original_read(size)

            error.read = read
            raise

    monkeypatch.setattr(client.opener, "open", record_error)
    fixture.requests.clear()
    if operation == "api_post":
        assert client._api_post("fixture/", {}) is None
    else:
        download = (
            client.download_ims_export
            if operation == "ims"
            else client.download_selected_image_ome_tiff
        )
        with pytest.raises(RuntimeError, match="HTTPError 500"):
            download(7, output)
    assert len(errors) == 1 and errors[0].closed
    assert not reads, "Unused HTTP error bodies must not be downloaded for logging"
    assert client.session_id == original_session
    assert [
        (cookie.name, cookie.value) for cookie in client.cookie_jar
    ] == original_cookies
    assert prior.read_bytes() == b"preserve this user file"
    assert list(output.iterdir()) == [prior]
    assert (
        sum(
            (method, urllib.parse.urlsplit(path).path) == route
            for method, path, _, _ in fixture.requests
        )
        == 1
    )


@pytest.mark.parametrize(
    ("https_api", "failure"),
    [
        ("127.0.0.1", "reset"),
        ("localhost", "reset"),
        ("omero.example.test", "reset"),
        ("127.0.0.1", "permission"),
        ("127.0.0.1", "authentication"),
    ],
    indirect=["https_api"],
)
def test_manual_refresh_recovery_uses_original_https_session(
    https_api, monkeypatch, failure
):
    """Inputs: real HTTPS failure then browser retry. Output: GET-only recovery with unchanged cookies."""
    module, client, fixture = https_api
    assert client.connect()
    original_session = (client.session_id, client.session_key, client.csrf_token)
    original_jar = client.cookie_jar
    original_cookies = [(cookie.name, cookie.value) for cookie in original_jar]
    reauthenticate = Mock(
        side_effect=AssertionError("Read recovery must not authenticate")
    )
    monkeypatch.setattr(client, "reauthenticate", reauthenticate)
    monkeypatch.setattr(module, "_http_retry_attempts", lambda: 1)
    monkeypatch.setattr(module, "_refresh_retry_attempts", lambda: 3)
    monkeypatch.setattr(module, "_refresh_retry_delay_seconds", lambda: 0)
    fixture.requests.clear()
    if failure == "reset":
        fixture.mode = "closed_once"
    elif failure == "permission":
        fixture.mode = "forbidden"
    else:
        fixture.responses[("GET", "/api/v0/m/projects/")] = [
            (
                403,
                b'{"message":"Not logged in"}',
                [("Content-Type", "application/json")],
            )
        ]

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.client = client
    dialog._refresh_generation = 1
    results, errors = [], []
    dialog._invoke_on_ui_thread = lambda callback, wait=True: callback()
    dialog._apply_refresh_result = lambda *args: results.append(args)
    dialog._finish_refresh_error = lambda *args: errors.append(args)
    dialog._refresh_worker(None, None, 1)

    reauthenticate.assert_not_called()
    assert client.cookie_jar is original_jar
    assert [(cookie.name, cookie.value) for cookie in original_jar] == original_cookies
    assert (
        client.session_id,
        client.session_key,
        client.csrf_token,
    ) == original_session
    assert (
        len(fixture.requests)
        == {"reset": 2, "permission": 3, "authentication": 1}[failure]
    )
    for method, path, headers, _body in fixture.requests:
        assert (
            method == "GET"
            and urllib.parse.urlsplit(path).path == "/api/v0/m/projects/"
        )
        assert "sessionid=fixture-session" in headers["Cookie"]
    assert bool(results) == (failure == "reset")
    assert bool(errors) == (failure != "reset")
    if errors:
        assert isinstance(errors[0][1], module._OMEROAuthenticationError) == (
            failure == "authentication"
        )


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("identifier_key", ["@id", "id"])
@pytest.mark.parametrize("requested_id", [7, "7"])
def test_image_metadata_uses_the_server_identity_and_name(
    https_api, wrapped, identifier_key, requested_id
):
    """Inputs: documented wrapped or direct OMERO object. Output: actual image identity and name."""
    _module, client, fixture = https_api
    assert client.connect()
    image = {identifier_key: 7, "Name": "Verified fixture image"}
    _serve_json(
        fixture, "GET", "/api/v0/m/images/7/", {"data": image} if wrapped else image
    )
    fixture.requests.clear()
    assert client.get_image_metadata(requested_id) == {
        "id": 7,
        "name": "Verified fixture image",
    }
    assert len(fixture.requests) == 1 and fixture.requests[0][0] == "GET"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "invalid",
        {"data": []},
        {"data": None},
        {"data": {"@id": 8}},
        {"data": {"@id": True}},
        {"data": {"@id": 7.0}},
        {"data": {"@id": 0}},
        {"Name": "Missing ID"},
    ],
)
def test_image_metadata_never_fabricates_a_requested_identity(https_api, payload):
    """Inputs: missing, malformed or mismatched image. Output: no invented success or incidental type error."""
    _module, client, fixture = https_api
    assert client.connect()
    _serve_json(fixture, "GET", "/api/v0/m/images/7/", payload)
    assert client.get_image_metadata(7) == {}


@pytest.mark.parametrize("cancellable", [False, True])
def test_ims_permission_denial_never_attempts_reauthentication(
    https_api, tmp_path, monkeypatch, cancellable
):
    """Inputs: real HTTPS 403 permission denial. Output: original session preserved, no login replay."""
    module, client, fixture = https_api
    output = tmp_path / "downloads"
    output.mkdir()
    assert client.connect()
    original_session = client.session_id
    original_cookies = [(cookie.name, cookie.value) for cookie in client.cookie_jar]
    _serve_json(
        fixture,
        "POST",
        "/omero_imaris_connector/imaris-export/",
        {"job_id": "fixture", "status_url": "/export/status/"},
    )
    _serve_json(
        fixture, "GET", "/export/status/", {"error": "Permission denied"}, status=403
    )
    reauthenticate = Mock(return_value=False)
    monkeypatch.setattr(client, "_attempt_reauth", reauthenticate)
    fixture.requests.clear()
    with pytest.raises(RuntimeError, match="HTTPError 403"):
        client.download_ims_export(
            7, output, cancel_event=threading.Event() if cancellable else None
        )
    reauthenticate.assert_not_called()
    assert client.session_id == original_session
    assert [
        (cookie.name, cookie.value) for cookie in client.cookie_jar
    ] == original_cookies
    assert [request[0] for request in fixture.requests] == ["POST", "GET"]
    assert not list(output.iterdir()) and not client._active_ims_export_jobs


@pytest.mark.parametrize("export_kind", ["ims", "async_tiff"])
@pytest.mark.parametrize("phase", ["start", "poll"])
@pytest.mark.parametrize("payload", [None, [], "private fixture response", 7])
def test_export_invalid_response_shape_is_reported_without_payload_disclosure(
    https_api, tmp_path, phase, payload, export_kind
):
    """Inputs: valid JSON with the wrong type. Output: actionable bounded error, no partial artifact."""
    module, client, fixture = https_api
    output = tmp_path / "downloads"
    output.mkdir()
    assert client.connect()
    _serve_json(
        fixture,
        "GET",
        "/omero_imaris_connector/imaris-export/",
        {
            module.OMERO_IMS_EXPORT_CAPABILITY_KEY: module.OMERO_IMS_EXPORT_CAPABILITY_FLAG,
            "ome_tiff_async_export": True,
        },
    )
    _serve_json(
        fixture,
        "POST",
        "/omero_imaris_connector/imaris-export/",
        payload
        if phase == "start"
        else {"job_id": "fixture", "status_url": "/export/status/"},
    )
    if phase == "poll":
        _serve_json(fixture, "GET", "/export/status/", payload)
    download = (
        client.download_ims_export
        if export_kind == "ims"
        else client.download_selected_image_ome_tiff
    )
    with pytest.raises(RuntimeError, match="export.*JSON object") as caught:
        download(7, output)
    assert "private fixture response" not in str(caught.value)
    assert not list(output.iterdir()) and not client._active_ims_export_jobs


@pytest.mark.parametrize("export_kind", ["ims", "async_tiff"])
def test_export_missing_job_fields_do_not_echo_server_payload(
    https_api, tmp_path, export_kind
):
    """Inputs: malformed start object with private detail. Output: public schema error only."""
    module, client, fixture = https_api
    output = tmp_path / "downloads"
    output.mkdir()
    assert client.connect()
    _serve_json(
        fixture,
        "GET",
        "/omero_imaris_connector/imaris-export/",
        {
            module.OMERO_IMS_EXPORT_CAPABILITY_KEY: module.OMERO_IMS_EXPORT_CAPABILITY_FLAG,
            "ome_tiff_async_export": True,
        },
    )
    _serve_json(
        fixture,
        "POST",
        "/omero_imaris_connector/imaris-export/",
        {"internal_detail": "private fixture response"},
    )
    download = (
        client.download_ims_export
        if export_kind == "ims"
        else client.download_selected_image_ome_tiff
    )
    with pytest.raises(RuntimeError, match="export.*job") as caught:
        download(7, output)
    assert "private fixture response" not in str(caught.value)
    assert not list(output.iterdir()) and not client._active_ims_export_jobs


@pytest.mark.parametrize("cancellable", [False, True])
@pytest.mark.parametrize(
    "mode",
    ["unauthorized", "expired", "invalid_json", "failed", "no_download", "timeout"],
)
def test_ims_poll_failure_keeps_original_session_and_output(
    https_api, tmp_path, monkeypatch, mode, cancellable
):
    """Inputs: real export status failures. Output: exact diagnostic, no duplicate job or damaged files."""
    module, client, fixture = https_api
    assert client.connect()
    original_session = client.session_id
    original_cookies = [(cookie.name, cookie.value) for cookie in client.cookie_jar]
    output = tmp_path / "downloads"
    output.mkdir()
    prior = output / "export.ims"
    prior.write_bytes(b"retained original export")
    _serve_json(
        fixture,
        "POST",
        "/omero_imaris_connector/imaris-export/",
        {"job_id": "fixture", "status_url": "/export/status/"},
    )
    if mode in {"unauthorized", "expired"}:
        _serve_json(
            fixture,
            "GET",
            "/export/status/",
            {"message": "Not logged in"},
            status=401 if mode == "unauthorized" else 403,
        )
        expected = "Authentication error"
    elif mode == "invalid_json":
        fixture.responses[("GET", "/export/status/")] = [(200, b"invalid-json", [])]
        expected = "poll failed: server returned a non-JSON response"
    elif mode == "failed":
        _serve_json(
            fixture,
            "GET",
            "/export/status/",
            {"failed": True, "error": "fixture conversion failed"},
        )
        expected = "IMS export failed: fixture conversion failed"
    elif mode == "no_download":
        _serve_json(fixture, "GET", "/export/status/", {"finished": True})
        expected = "finished without a download URL"
    else:
        _serve_json(fixture, "GET", "/export/status/", {"state": "RUNNING"})
        monkeypatch.setattr(module, "EXPORT_TIMEOUT", 0.05)
        monkeypatch.setattr(module, "EXPORT_POLL_INTERVAL", 0.06)
        expected = "timed out"
    fixture.requests.clear()
    with pytest.raises(RuntimeError, match=expected):
        client.download_ims_export(
            7, output, cancel_event=threading.Event() if cancellable else None
        )
    assert prior.read_bytes() == b"retained original export"
    assert list(output.iterdir()) == [prior]
    assert not client._active_ims_export_jobs
    assert client.session_id == original_session
    assert [
        (cookie.name, cookie.value) for cookie in client.cookie_jar
    ] == original_cookies
    assert sum(request[0] == "POST" for request in fixture.requests) == 1
    assert all(
        urllib.parse.urlsplit(request[1]).path
        in {"/omero_imaris_connector/imaris-export/", "/export/status/"}
        for request in fixture.requests
    )


@pytest.mark.parametrize("mode", ["invalid_json", "server_error", "login_redirect"])
def test_ims_start_failure_does_not_replay_job_or_disclose_error_body(
    https_api, tmp_path, mode, capsys
):
    """Inputs: failed real export start. Output: no retry or partial download and private body omitted."""
    _module, client, fixture = https_api
    assert client.connect()
    output = tmp_path / "downloads"
    output.mkdir()
    if mode == "invalid_json":
        response = (200, b"private-fixture-detail", [])
        expected = "non-JSON response"
    elif mode == "server_error":
        response = (503, b"private-fixture-detail", [])
        expected = "HTTPError 503"
    else:
        response = (302, b"", [("Location", "/webclient/login/")])
        expected = "Not authenticated"
    fixture.responses[("POST", "/omero_imaris_connector/imaris-export/")] = [response]
    fixture.requests.clear()
    with pytest.raises(RuntimeError, match=expected) as caught:
        client.download_ims_export(7, output)
    assert sum(request[0] == "POST" for request in fixture.requests) == 1
    assert not list(output.iterdir()) and not client._active_ims_export_jobs
    captured = capsys.readouterr()
    assert "private-fixture-detail" not in captured.out + captured.err + str(
        caught.value
    )


@pytest.mark.parametrize("cancellable", [False, True])
@pytest.mark.parametrize("phase", ["start", "poll"])
@pytest.mark.parametrize("mode", ["invalid_json", "no_download", "timeout"])
def test_async_tiff_protocol_failures_preserve_session_and_prior_files(
    https_api, tmp_path, monkeypatch, cancellable, phase, mode
):
    """Inputs: malformed or incomplete export response. Output: no replay, false timeout or damaged file."""
    module, client, fixture = https_api
    assert client.connect()
    original_session = client.session_id
    original_cookies = [(cookie.name, cookie.value) for cookie in client.cookie_jar]
    output = tmp_path / "downloads"
    output.mkdir()
    prior = output / "image.ome.tif"
    prior.write_bytes(b"prior image")
    _serve_json(
        fixture,
        "GET",
        "/omero_imaris_connector/imaris-export/",
        {
            module.OMERO_IMS_EXPORT_CAPABILITY_KEY: module.OMERO_IMS_EXPORT_CAPABILITY_FLAG,
            "ome_tiff_async_export": True,
        },
    )
    _serve_json(
        fixture,
        "POST",
        "/omero_imaris_connector/imaris-export/",
        {"job_id": "fixture", "status_url": "/export/status/"},
    )
    method, path = (
        ("POST", "/omero_imaris_connector/imaris-export/")
        if phase == "start"
        else ("GET", "/export/status/")
    )
    if mode == "invalid_json":
        fixture.responses[(method, path)] = [(200, b"private-fixture-detail", [])]
        expected = "non-JSON response"
    elif mode == "no_download":
        _serve_json(fixture, method, path, {"finished": True})
        expected = (
            "missing its job ID" if phase == "start" else "without a download URL"
        )
    else:
        _serve_json(fixture, method, path, {"state": "RUNNING"})
        monkeypatch.setattr(module, "EXPORT_TIMEOUT", 0.05)
        monkeypatch.setattr(module, "EXPORT_POLL_INTERVAL", 0.06)
        expected = "missing its job ID" if phase == "start" else "timed out"
    fixture.requests.clear()
    with pytest.raises(RuntimeError, match=expected) as caught:
        client.download_selected_image_ome_tiff(
            7, output, cancel_event=threading.Event() if cancellable else None
        )
    assert "private-fixture-detail" not in str(caught.value)
    assert list(output.iterdir()) == [prior] and prior.read_bytes() == b"prior image"
    assert not client._active_ims_export_jobs and client.session_id == original_session
    assert [
        (cookie.name, cookie.value) for cookie in client.cookie_jar
    ] == original_cookies
    assert sum(request[0] == "POST" for request in fixture.requests) == 1


@pytest.mark.parametrize("cancellable", [False, True])
@pytest.mark.parametrize("phase", ["start", "poll", "download"])
@pytest.mark.parametrize("status", [401, 403, 503])
def test_async_tiff_http_failures_release_response_without_reauthentication(
    https_api, tmp_path, monkeypatch, cancellable, phase, status
):
    """Inputs: real HTTP failure at each job phase. Output: closed response, unchanged login/files, one job."""
    module, client, fixture = https_api
    assert client.connect()
    original_session = client.session_id
    original_cookies = [(cookie.name, cookie.value) for cookie in client.cookie_jar]
    output = tmp_path / "downloads"
    output.mkdir()
    prior = output / "image.ome.tif"
    prior.write_bytes(b"prior image")
    _serve_json(
        fixture,
        "GET",
        "/omero_imaris_connector/imaris-export/",
        {
            module.OMERO_IMS_EXPORT_CAPABILITY_KEY: module.OMERO_IMS_EXPORT_CAPABILITY_FLAG,
            "ome_tiff_async_export": True,
        },
    )
    _serve_json(
        fixture,
        "POST",
        "/omero_imaris_connector/imaris-export/",
        {"job_id": "fixture", "status_url": "/export/status/"},
    )
    _serve_json(
        fixture,
        "GET",
        "/export/status/",
        {"finished": True, "download_url": "/export/file/"},
    )
    route = {
        "start": ("POST", "/omero_imaris_connector/imaris-export/"),
        "poll": ("GET", "/export/status/"),
        "download": ("GET", "/export/file/"),
    }[phase]
    fixture.responses[route] = [(status, b"private-fixture-detail", [])]
    errors = []
    original_open = client._open_request_response

    def record_error(*args, **kwargs):
        """Inputs: original network call. Output: same response/error, retained for resource checks."""
        try:
            return original_open(*args, **kwargs)
        except urllib.error.HTTPError as error:
            errors.append(error)
            raise

    monkeypatch.setattr(client, "_open_request_response", record_error)
    fixture.requests.clear()
    with pytest.raises((RuntimeError, urllib.error.HTTPError)) as caught:
        client.download_selected_image_ome_tiff(
            7, output, cancel_event=threading.Event() if cancellable else None
        )
    assert len(errors) == 1 and errors[0].fp.closed
    assert str(status) in str(caught.value) and "private-fixture-detail" not in str(
        caught.value
    )
    assert list(output.iterdir()) == [prior] and prior.read_bytes() == b"prior image"
    assert not client._active_ims_export_jobs and client.session_id == original_session
    assert [
        (cookie.name, cookie.value) for cookie in client.cookie_jar
    ] == original_cookies
    assert sum(request[0] == "POST" for request in fixture.requests) == 1


@pytest.fixture
def https_api(tmp_path, monkeypatch, request):
    """Inputs: private PKI and loopback listener. Output: authenticated HTTPS protocol fixture."""
    source = (
        Path(__file__).resolve().parents[1]
        / "omero_imaris_connector"
        / "XTOmeroConnector.py"
    )
    spec = importlib.util.spec_from_file_location("xt_https_client", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    host = getattr(request, "param", "127.0.0.1")
    if host.endswith(".test"):
        original_resolver = module.socket.getaddrinfo

        def fixture_resolver(name, *args, **kwargs):
            """Inputs: reserved fixture hostname. Output: local-only DNS mapping for real TLS."""
            return original_resolver(
                "127.0.0.1" if name == host else name, *args, **kwargs
            )

        monkeypatch.setattr(module.socket, "getaddrinfo", fixture_resolver)
    state, trust, targets = (
        tmp_path / name for name in ("private", "trust", "servers")
    )
    for directory in (state, trust, targets, targets / "api"):
        directory.mkdir(mode=0o700)
    identities = (certificates.Identity("api", (host,), os.getuid(), os.getgid()),)
    certificates.reconcile(state, trust, targets, identities)
    monkeypatch.setenv("SSL_CERT_FILE", str(trust / "ca.pem"))
    fixture = SimpleNamespace(
        mode="ok",
        requests=[],
        responses={},
        csrf="fixture-csrf",
        credential="fixture + &= value",
    )

    class Handler(BaseHTTPRequestHandler):
        """A strict, local-only model of the documented OMERO.web login/API protocol."""

        protocol_version = "HTTP/1.1"

        def log_message(self, _format, *_args):
            """Inputs: server log event. Output: request history is recorded structurally instead."""
            return None

        def reply(self, status, body=b"", headers=(), reason=None, omit_length=False):
            """Inputs: response status/bytes/headers. Output: bounded complete HTTP response."""
            self.send_response(status, message=reason)
            if not omit_length and not any(
                name.lower() in {"content-length", "transfer-encoding"}
                for name, _ in headers
            ):
                self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            """Inputs: real GET request. Output: CSRF bootstrap, redirect target or API response."""
            self.route()

        def do_POST(self):
            """Inputs: real POST request. Output: login/JSON protocol response after validation."""
            self.route()

        def route(self):
            """Inputs: parsed HTTP request. Output: deterministic response and request evidence."""
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            path = urllib.parse.urlsplit(self.path).path
            fixture.requests.append((self.command, self.path, dict(self.headers), body))
            if fixture.mode == "closed_once":
                fixture.mode = "ok"
                self.close_connection = True
                return
            if fixture.mode == "closed_connection":
                self.close_connection = True
                return
            if fixture.mode == "invalid_status":
                self.close_connection = True
                self.wfile.write(b"NOT-HTTP\r\nContent-Length: 0\r\n\r\n")
                return
            login_html = b'<form action="/webclient/login/"><input name="username"><input name="csrfmiddlewaretoken"></form>'
            if path == "/webclient/login/" and self.command == "GET":
                headers = [("Content-Type", "text/html")]
                if fixture.mode != "no_csrf":
                    headers.append(
                        ("Set-Cookie", f"csrftoken={fixture.csrf}; Path=/; Secure")
                    )
                self.reply(200, login_html, headers)
                return
            if self.command == "POST" and path in {
                "/webclient/login/",
                "/api/v0/login/",
            }:
                fields = urllib.parse.parse_qs(body.decode())
                valid = (
                    fields.get("username") == ["fixture-user"]
                    and fields.get("password") == [fixture.credential]
                    and fields.get("csrfmiddlewaretoken") == [fixture.csrf]
                    and self.headers.get("X-CSRFToken") == fixture.csrf
                    and f"csrftoken={fixture.csrf}" in self.headers.get("Cookie", "")
                    and self.headers.get("Referer", "").startswith(fixture.base_url)
                )
                if not valid or fixture.mode == "forbidden":
                    self.reply(403, b"Rejected login")
                elif fixture.mode == "login_html":
                    self.reply(200, login_html, [("Content-Type", "text/html")])
                elif path == "/webclient/login/":
                    headers = [("Location", "/webclient/")]
                    if fixture.mode != "no_session":
                        headers.append(
                            (
                                "Set-Cookie",
                                "sessionid=fixture-session; Path=/; Secure; HttpOnly; SameSite=Lax",
                            )
                        )
                    self.reply(302, headers=headers)
                else:
                    self.reply(
                        200,
                        b'{"eventContext":{"userId":7}}',
                        [("Content-Type", "application/json")],
                    )
                return
            if path == "/webclient/":
                self.reply(200, b"Workspace", [("Content-Type", "text/html")])
                return
            responses = fixture.responses.get((self.command, path))
            if responses:
                response = responses.pop(0) if len(responses) > 1 else responses[0]
                self.reply(*response)
                return
            if path == "/foreign-target/":
                self.reply(200, b'{"data":[]}', [("Content-Type", "application/json")])
            elif fixture.mode == "foreign_redirect":
                self.reply(302, headers=[("Location", fixture.foreign_url)])
            elif fixture.mode == "transient":
                fixture.mode = "ok"
                self.reply(503, reason="Service temporarily unavailable")
            elif fixture.mode == "redirect":
                self.reply(302, headers=[("Location", "/webclient/login/")])
            elif fixture.mode == "forbidden":
                self.reply(403, b"fixture-private-error-body")
            elif fixture.mode == "invalid_json":
                self.reply(200, b"invalid-json", [("Content-Type", "application/json")])
            elif fixture.mode == "empty":
                self.reply(204)
            elif fixture.mode == "login_html":
                self.reply(200, login_html, [("Content-Type", "text/html")])
            elif fixture.mode == "chunked":
                self.send_response(200)
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b"3\r\nabc\r\n2\r\nde\r\n0\r\n\r\n")
            else:
                self.reply(200, b'{"data":[]}', [("Content-Type", "application/json")])

    class FixtureServer(ThreadingHTTPServer):
        """Local listener with the address family of the tested endpoint."""

        address_family = socket.AF_INET6 if host == "::1" else socket.AF_INET

    server = FixtureServer(("::1" if host == "::1" else "127.0.0.1", 0), Handler)
    context = ssl.SSLContext(
        ssl.PROTOCOL_TLS_SERVER,  # DevSkim: ignore DS440072 -- negotiating server context
    )
    context.minimum_version = (
        ssl.TLSVersion.TLSv1_2  # DevSkim: ignore DS440001 -- minimum, not maximum
    )
    context.load_cert_chain(targets / "api" / "cert.pem", targets / "api" / "key.pem")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    authority_host = f"[{host}]" if host == "::1" else host
    fixture.base_url = f"https://{authority_host}:{server.server_port}"
    fixture.context = context
    fixture.handler = Handler
    client = module.OMEROWebClient(
        host,
        server.server_port,
        "fixture-user",
        fixture.credential,
        scheme="https",
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield module, client, fixture
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


@pytest.mark.parametrize(
    "https_api", ["127.0.0.1", "::1", "localhost", "omero.example.test"], indirect=True
)
@pytest.mark.parametrize("cancellable", [False, True])
def test_authenticated_download_preserves_endpoint_authority(https_api, cancellable):
    """Inputs: fresh requests over real TLS. Output: correct authority and original session cookies."""
    module, client, fixture = https_api
    assert client.connect()
    original = (client.session_id, client.csrf_token, client.cookie_jar)
    payload = b"verified download bytes"
    fixture.responses[("GET", "/fixture-bytes/")] = [(200, payload, [])]
    fixture.requests.clear()
    request = client._create_request_with_cookies(fixture.base_url + "/fixture-bytes/")
    # A request reused after urllib.open can already contain a corrected Host header.
    assert request.get_header("Host") is None
    with client._open_request_response(
        request, 5, threading.Event() if cancellable else None
    ) as response:
        assert response.status == 200
        assert response.read() == payload
    assert response.closed
    assert len(fixture.requests) == 1
    method, path, headers, body = fixture.requests[0]
    assert (method, path, body) == ("GET", "/fixture-bytes/", b"")
    assert headers["Host"] == urllib.parse.urlsplit(fixture.base_url).netloc
    assert "sessionid=" + original[0] in headers["Cookie"]
    assert (client.session_id, client.csrf_token, client.cookie_jar) == original
    assert (
        module.OMEROWebClient._host_header_for_url(
            urllib.parse.urlsplit(client.base_url)
        )
        == urllib.parse.urlsplit(fixture.base_url).netloc
    )


@pytest.mark.parametrize("cancellable", [False, True])
@pytest.mark.parametrize("export_kind", ["standard_tiff", "async_tiff", "ims"])
@pytest.mark.parametrize(
    "transfer_mode",
    [
        "complete",
        "truncated",
        "chunked",
        "chunked_truncated",
        "close_delimited",
        "invalid_length",
        "invalid_format",
        "ambiguous",
    ],
)
def test_export_transport_atomicity(
    https_api, tmp_path, cancellable, export_kind, transfer_mode
):
    """Inputs: real TLS export framing. Output: only complete valid downloads replace old files."""
    module, client, fixture = https_api
    assert client.connect()
    output = tmp_path / "downloads"
    output.mkdir()
    if export_kind == "ims":
        # A valid HDF5 signature alone cannot establish transfer completeness.
        payload = b"\x89HDF\r\n\x1a\n" + b"fixture" * 128
        filename = "image.ims"
    else:
        stream = io.BytesIO()
        tifffile.imwrite(stream, np.arange(256, dtype=np.uint16).reshape(16, 16))
        payload = stream.getvalue()
        filename = "image.ome.tif"
    original = output / filename
    original.write_bytes(b"original artifact")
    headers = [
        ("Content-Type", "application/octet-stream"),
        ("Content-Disposition", f'attachment; filename="{filename}"'),
    ]
    wire = payload
    if transfer_mode in {"chunked", "chunked_truncated", "ambiguous"}:
        headers.append(("Transfer-Encoding", "chunked"))
        wire = f"{len(payload):x}\r\n".encode() + payload + b"\r\n0\r\n\r\n"
        if transfer_mode == "chunked_truncated":
            wire = f"{len(payload):x}\r\n".encode() + payload[:32]
        elif transfer_mode == "ambiguous":
            headers.append(("Content-Length", str(len(wire))))
    elif transfer_mode != "close_delimited":
        if transfer_mode == "invalid_format":
            wire = b"not an image"
        headers.append(
            (
                "Content-Length",
                "-1" if transfer_mode == "invalid_length" else str(len(wire)),
            )
        )
        if transfer_mode == "truncated":
            wire = payload[:32]
    response = (200, wire, headers, None, transfer_mode == "close_delimited")
    capabilities = {
        module.OMERO_IMS_EXPORT_CAPABILITY_KEY: module.OMERO_IMS_EXPORT_CAPABILITY_FLAG,
        "ome_tiff_async_export": export_kind == "async_tiff",
    }
    fixture.responses[("GET", "/omero_imaris_connector/imaris-export/")] = [
        (200, json.dumps(capabilities).encode(), [])
    ]
    if export_kind == "standard_tiff":
        fixture.responses[("GET", "/webgateway/render_ome_tiff/i/7/")] = [response]
    else:
        fixture.responses[("POST", "/omero_imaris_connector/imaris-export/")] = [
            (200, b'{"job_id":"fixture","status_url":"/export/status/"}', [])
        ]
        fixture.responses[("GET", "/export/status/")] = [
            (200, b'{"finished":true,"download_url":"/export/file/"}', [])
        ]
        fixture.responses[("GET", "/export/file/")] = [response]
    download = (
        client.download_ims_export
        if export_kind == "ims"
        else client.download_selected_image_ome_tiff
    )
    kwargs = {
        "target_filename": filename,
        "duplicate_policy": module.DUPLICATE_DOWNLOAD_POLICY_REPLACE,
        "cancel_event": threading.Event() if cancellable else None,
    }
    if transfer_mode in {"complete", "chunked", "close_delimited"}:
        assert Path(download(7, output, **kwargs)) == original
        assert original.read_bytes() == payload
        if export_kind != "ims":
            assert np.array_equal(
                tifffile.imread(original),
                np.arange(256, dtype=np.uint16).reshape(16, 16),
            )
    else:
        messages = {
            "truncated": "[Ii]ncomplete",
            "chunked_truncated": "[Ii]ncomplete",
            "invalid_length": "Invalid HTTP Content-Length",
            "invalid_format": "format validation",
            "ambiguous": "Ambiguous HTTP response framing",
        }
        with pytest.raises(
            (RuntimeError, http.client.HTTPException), match=messages[transfer_mode]
        ):
            download(7, output, **kwargs)
        assert original.read_bytes() == b"original artifact"
    assert sorted(path.name for path in output.iterdir()) == [filename]
    assert not client._active_ims_export_jobs


def _configure_complete_export(module, client, fixture, kind):
    """Inputs: real TLS fixture and export kind. Output: configured download method and exact valid image bytes."""
    if kind == "ims":
        payload = b"\x89HDF\r\n\x1a\n" + b"fixture" * 16
    else:
        stream = io.BytesIO()
        tifffile.imwrite(stream, np.arange(64, dtype=np.uint16).reshape(8, 8))
        payload = stream.getvalue()
    _serve_json(
        fixture,
        "GET",
        "/omero_imaris_connector/imaris-export/",
        {
            module.OMERO_IMS_EXPORT_CAPABILITY_KEY: module.OMERO_IMS_EXPORT_CAPABILITY_FLAG,
            "ome_tiff_async_export": kind == "async_tiff",
        },
    )
    file_path = "/webgateway/render_ome_tiff/i/7/"
    if kind != "standard_tiff":
        _serve_json(
            fixture,
            "POST",
            "/omero_imaris_connector/imaris-export/",
            {"job_id": "fixture", "status_url": "/export/status/"},
        )
        _serve_json(
            fixture,
            "GET",
            "/export/status/",
            {"finished": True, "download_url": "/export/file/"},
        )
        file_path = "/export/file/"
    fixture.responses[("GET", file_path)] = [
        (200, payload, [("Content-Disposition", 'attachment; filename="measurement"')])
    ]
    method = (
        client.download_ims_export
        if kind == "ims"
        else client.download_selected_image_ome_tiff
    )
    return method, payload


@pytest.mark.parametrize("kind", ["ims", "standard_tiff", "async_tiff"])
@pytest.mark.parametrize("phase", ["poll", "file"])
def test_export_login_redirect_preserves_session_and_never_saves_html(
    https_api, tmp_path, kind, phase
):
    """Inputs: real authenticated export redirected during polling/download. Output: explicit failure, unchanged login and no local artifact or replay."""
    module, client, fixture = https_api
    assert client.connect()
    session = client.session_id
    method, _payload = _configure_complete_export(module, client, fixture, kind)
    path = (
        "/webgateway/render_ome_tiff/i/7/"
        if kind == "standard_tiff"
        else "/export/status/"
        if phase == "poll"
        else "/export/file/"
    )
    fixture.responses[("GET", path)] = [(302, b"", [("Location", "/webclient/login/")])]
    fixture.requests.clear()
    output = tmp_path / "downloads"
    output.mkdir()
    with pytest.raises(RuntimeError, match="Not authenticated"):
        method(7, output, cancel_event=threading.Event())
    assert list(output.iterdir()) == []
    assert client.session_id == session
    assert not client._active_ims_export_jobs
    assert not any("login" in path for _method, path, *_ in fixture.requests)
    assert sum(method == "POST" for method, *_ in fixture.requests) == int(
        kind != "standard_tiff"
    )


@pytest.mark.parametrize("mode", ["redirect", "html", "connection_refused"])
def test_standard_tiff_rejects_non_image_responses_without_fallback_download(
    https_api, tmp_path, mode
):
    """Inputs: redirect, maintenance page or refused transport. Output: clear error without saving bytes or requesting an original file."""
    module, client, fixture = https_api
    assert client.connect()
    session = client.session_id
    method, _payload = _configure_complete_export(
        module, client, fixture, "standard_tiff"
    )
    output = tmp_path / "downloads"
    output.mkdir()
    fixture.requests.clear()
    expected = "URLError"
    if mode != "connection_refused":
        fixture.responses[("GET", "/webgateway/render_ome_tiff/i/7/")] = [
            (302, b"", [("Location", "/maintenance/")])
            if mode == "redirect"
            else (200, b"<html>Maintenance</html>", [("Content-Type", "text/html")])
        ]
        expected = "redirected instead" if mode == "redirect" else "returned HTML"
    with socket.socket() as reserved:
        if mode == "connection_refused":
            reserved.bind(("127.0.0.1", 0))
            client.base_url = f"https://127.0.0.1:{reserved.getsockname()[1]}"
        with pytest.raises(RuntimeError, match=expected):
            method(7, output, cancel_event=threading.Event())
    assert not list(output.iterdir())
    assert client.session_id == session
    assert all(method == "GET" for method, *_ in fixture.requests)


@pytest.mark.parametrize("mode", ["absent", "accepted", "rejected", "login", "closed"])
def test_ims_cancellation_requires_server_acknowledgement_without_relogin(
    https_api, mode
):
    """Inputs: absent target or real TLS cancellation responses. Output: success only after explicit acknowledgement, with one mutation at most."""
    _module, client, fixture = https_api
    assert client.connect()
    session = client.session_id
    fixture.requests.clear()
    if mode in {"accepted", "rejected"}:
        _serve_json(
            fixture, "POST", "/export/cancel/", {"cancelled": mode == "accepted"}
        )
    elif mode in {"login", "closed"}:
        fixture.mode = "login_html" if mode == "login" else "closed_connection"
    assert client.cancel_ims_export("" if mode == "absent" else "/export/cancel/") is (
        mode == "accepted"
    )
    assert client.session_id == session
    assert len(fixture.requests) == int(mode != "absent")
    if fixture.requests:
        method, path, _headers, body = fixture.requests[0]
        assert (method, path, json.loads(body)) == (
            "POST",
            "/export/cancel/",
            {"cancel": True},
        )


@pytest.mark.parametrize("authenticated", [False, True])
def test_folder_capability_failure_is_unavailable_without_credential_replay(
    https_api, authenticated
):
    """Inputs: missing authentication or disconnected capability endpoint. Output: unavailable reason, unchanged session and no login replay."""
    _module, client, fixture = https_api
    if authenticated:
        assert client.connect()
    session = client.session_id
    fixture.requests.clear()
    fixture.mode = "closed_connection"
    result = client.get_folder_export_capability()
    assert result["available"] is False
    assert result["reason"]
    assert client.session_id == session
    assert len(fixture.requests) == int(authenticated)


@pytest.mark.parametrize("strict", [False, True])
def test_api_without_session_is_refused_before_network_access(https_api, strict):
    """Inputs: unauthenticated API read in strict/permissive mode. Output: explicit refusal with no network traffic."""
    module, client, fixture = https_api
    if strict:
        with pytest.raises(module._OMEROAuthenticationError):
            client._api_request("fixture/", raise_on_error=True)
    else:
        assert client._api_request("fixture/") is None
    assert not client.has_omero_ims_export_capability()
    assert not client.has_async_ome_tiff_export_capability()
    assert not client.list_projects()
    client._remember_active_ims_export("")
    assert not client._active_ims_export_jobs
    assert fixture.requests == []


@pytest.mark.parametrize("operation", ["start", "upload"])
@pytest.mark.parametrize(
    "payload,status",
    [({"ok": False, "error": "Quota exceeded"}, 409), ([], 200), ({"ok": 1}, 200)],
)
def test_folder_mutations_report_rejection_without_replay_or_session_loss(
    https_api, operation, payload, status
):
    """Inputs: rejected real TLS job creation or upload. Output: one mutation, explicit error and unchanged authentication."""
    module, client, fixture = https_api
    assert client.connect()
    original = (client.session_id, client.csrf_token, client.cookie_jar)
    path = "/omeroweb_import/start/" if operation == "start" else "/upload/"
    _serve_json(fixture, "POST", path, payload, status=status)
    fixture.requests.clear()
    with pytest.raises(RuntimeError) as caught:
        if operation == "start":
            client.start_folder_export_job(
                "dataset", [{"relative_path": "image.tif", "size": 4}]
            )
        else:
            client.upload_folder_chunk(
                client.base_url + path, "image.tif", 4, 0, b"data", True
            )
    expected = payload.get("error") if isinstance(payload, dict) else None
    assert str(caught.value) == (expected or json.dumps(payload))
    assert len(fixture.requests) == 1
    method, requested, headers, body = fixture.requests[0]
    assert (method, requested) == ("POST", path)
    assert headers["X-Csrftoken"] == original[1]
    assert "sessionid=" + original[0] in headers["Cookie"]
    assert fixture.credential.encode() not in body
    assert (client.session_id, client.csrf_token, client.cookie_jar) == original
    assert client.password == module.CLEARED_CREDENTIAL_TEXT


@pytest.mark.parametrize(
    "url,path,error",
    [(None, "image.tif", "URL is missing"), ("/upload/", "  ", "file path is missing")],
)
def test_folder_chunk_missing_target_fails_before_any_network_access(
    https_api, url, path, error
):
    """Inputs: incomplete upload coordinates. Output: local validation failure without sending a request."""
    _module, client, fixture = https_api
    with pytest.raises(RuntimeError, match=error):
        client.upload_folder_chunk(url, path, 4, 0, b"data", True)
    assert fixture.requests == []


def test_folder_cancel_connection_loss_is_not_reported_as_cancellation(https_api):
    """Inputs: lost cancellation response over TLS. Output: false acknowledgement without replaying the mutation or login."""
    module, client, fixture = https_api
    assert client.connect()
    session = client.session_id
    fixture.requests.clear()
    fixture.mode = "closed_connection"
    assert not client.cancel_folder_export_job({"prune_url": "/prune/"})
    assert len(fixture.requests) == 1
    method, path, _headers, body = fixture.requests[0]
    assert (method, path) == ("POST", "/prune/")
    assert json.loads(body) == {"keep_paths": []}
    assert client.session_id == session
    assert client.password == module.CLEARED_CREDENTIAL_TEXT


def test_cancellable_transport_preserves_semicolon_path_and_query(https_api):
    """Inputs: parameterized URL through real TLS. Output: exact request target and byte-exact response."""
    _module, client, fixture = https_api
    assert client.connect()
    fixture.responses[("GET", "/download;image=7")] = [(200, b"fixture-data", [])]
    target = "/download;image=7?format=ome%2Btiff&part=2"
    fixture.requests.clear()
    request = client._create_request_with_cookies(client.base_url + target)
    with client._open_cancellable_http_request(
        request, 2, threading.Event()
    ) as response:
        assert response.read() == b"fixture-data"
    assert len(fixture.requests) == 1
    assert fixture.requests[0][1] == target


@pytest.mark.parametrize("mode", ["redirect", "login_html", "forbidden"])
def test_optional_api_read_rejects_authentication_response_without_relogin(
    https_api, mode
):
    """Inputs: authentication rejection from a real API. Output: no data, no credential replay and preserved session identity."""
    module, client, fixture = https_api
    assert client.connect()
    original = (client.session_id, client.csrf_token, client.cookie_jar)
    fixture.mode = mode
    fixture.requests.clear()
    assert client._api_request("fixture/") is None
    assert fixture.requests and all(row[0] == "GET" for row in fixture.requests)
    assert (client.session_id, client.csrf_token, client.cookie_jar) == original
    assert client.password == module.CLEARED_CREDENTIAL_TEXT


@pytest.mark.parametrize("missing", ["password", "csrf"])
def test_user_context_lookup_requires_both_credential_and_csrf(https_api, missing):
    """Inputs: incomplete login context. Output: no secondary login request and no invented user identity."""
    _module, client, fixture = https_api
    client.csrf_token = fixture.csrf if missing == "password" else None
    password = "" if missing == "password" else fixture.credential
    assert not client._refresh_current_user_context(password)
    assert client.user_id is None
    assert fixture.requests == []


def test_user_context_missing_user_id_does_not_invent_identity(https_api, monkeypatch):
    """Inputs: valid real TLS API login with no user id. Output: failed context refresh, retaining the established browser session."""
    _module, client, fixture = https_api
    assert client.connect()
    original = client.session_id
    client.user_id = None
    reply = fixture.handler.reply

    def missing_user(handler, status, body=b"", headers=(), *args):
        """Inputs: actual API login response. Output: syntactically valid context with no user id."""
        if handler.path == "/api/v0/login/":
            body = b'{"eventContext":{}}'
        return reply(handler, status, body, headers, *args)

    monkeypatch.setattr(fixture.handler, "reply", missing_user)
    fixture.requests.clear()
    assert not client._refresh_current_user_context(fixture.credential)
    assert client.user_id is None
    assert client.session_id == original
    assert len(fixture.requests) == 1
    assert fixture.requests[0][:2] == ("POST", "/api/v0/login/")


def test_connect_without_password_does_not_destroy_an_existing_session(https_api):
    """Inputs: repeated connect after successful credential clearing. Output: no request and no replacement of the live session."""
    _module, client, fixture = https_api
    assert client.connect()
    original = (client.session_id, client.csrf_token, client.cookie_jar)
    fixture.requests.clear()
    assert not client.connect()
    assert fixture.requests == []
    assert (client.session_id, client.csrf_token, client.cookie_jar) == original


@pytest.mark.parametrize("kind", ["ims", "standard_tiff", "async_tiff"])
@pytest.mark.parametrize("change", ["removed", "empty", "corrupted"])
def test_download_postconditions_detect_external_file_changes(
    https_api, tmp_path, monkeypatch, kind, change
):
    """Inputs: valid TLS download changed immediately after atomic save. Output: explicit error, no success or session reset."""
    module, client, fixture = https_api
    assert client.connect()
    session = client.session_id
    method, payload = _configure_complete_export(module, client, fixture, kind)
    output = tmp_path / "downloads"
    output.mkdir()
    saver = module._save_download_response
    saved = []

    def change_after_commit(*args, **kwargs):
        """Inputs: a validated download. Output: model an external filesystem change after commit, not during streaming."""
        path = Path(saver(*args, **kwargs))
        assert path.read_bytes() == payload
        saved.append(path)
        if change == "removed":
            path.unlink()
        else:
            path.write_bytes(b"" if change == "empty" else b"external replacement")
        return str(path)

    monkeypatch.setattr(module, "_save_download_response", change_after_commit)
    message = {
        "removed": "file not found",
        "empty": "empty",
        "corrupted": "not a (valid IMS|readable TIFF)",
    }[change]
    with pytest.raises(RuntimeError, match=message):
        method(7, output)
    assert len(saved) == 1
    assert not client._active_ims_export_jobs
    assert client.session_id == session
    assert sorted(output.iterdir()) == ([] if change == "removed" else saved)
    assert len(
        [
            r
            for r in fixture.requests
            if r[0] == "POST" and r[1] == "/omero_imaris_connector/imaris-export/"
        ]
    ) == int(kind != "standard_tiff")


@pytest.mark.parametrize("kind", ["ims", "standard_tiff"])
def test_export_default_directory_is_created_only_under_configured_temp_root(
    https_api, tmp_path, monkeypatch, kind
):
    """Inputs: no explicit export folder and a private temporary root. Output: valid download under that root with a suitable extension."""
    module, client, fixture = https_api
    assert client.connect()
    method, payload = _configure_complete_export(module, client, fixture, kind)
    root = tmp_path / "configured-temporary-root"
    root.mkdir()
    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: str(root))
    output = Path(method(7, None))
    assert output.relative_to(root).parts == (
        "ImarisOMEROExports",
        "measurement.ims" if kind == "ims" else "measurement.ome.tif",
    )
    assert output.read_bytes() == payload
    assert not client._active_ims_export_jobs


@pytest.mark.parametrize("kind", ["ims", "standard_tiff"])
@pytest.mark.parametrize("failure", ["missing_directory", "missing_session"])
def test_export_preconditions_fail_without_network_or_directory_creation(
    https_api, tmp_path, kind, failure
):
    """Inputs: absent folder or authenticated session. Output: explicit refusal before transport or new directory creation."""
    _module, client, fixture = https_api
    assert client.connect()
    method = (
        client.download_ims_export
        if kind == "ims"
        else client.download_selected_image_ome_tiff
    )
    folder = tmp_path / "downloads"
    if failure == "missing_session":
        folder.mkdir()
        client.session_id = None
    before = len(fixture.requests)
    with pytest.raises(RuntimeError, match="does not exist|Not logged in"):
        method(7, folder)
    assert len(fixture.requests) == before
    assert folder.exists() is (failure == "missing_session")
    assert not client._active_ims_export_jobs


@pytest.mark.parametrize("kind", ["standard_tiff", "ims", "async_tiff"])
@pytest.mark.parametrize("stage", ["start", "download"])
def test_export_login_html_never_becomes_a_download_or_replays_credentials(
    https_api, tmp_path, kind, stage
):
    """Inputs: login page at export start or download. Output: refused export, empty destination, unchanged session, no login replay."""
    module, client, fixture = https_api
    assert client.connect()
    session = client.session_id
    method, _payload = _configure_complete_export(module, client, fixture, kind)
    path = (
        "/webgateway/render_ome_tiff/i/7/"
        if kind == "standard_tiff"
        else "/export/file/"
    )
    verb = "GET"
    if stage == "start" and kind != "standard_tiff":
        verb, path = "POST", "/omero_imaris_connector/imaris-export/"
    fixture.responses[(verb, path)] = [
        (
            200,
            b'<form action="/webclient/login/"><input name="username"><input name="csrfmiddlewaretoken"></form>',
            [("Content-Type", "text/html")],
        )
    ]
    output = tmp_path / "downloads"
    output.mkdir()
    before = len(fixture.requests)
    expected = (
        "non-JSON response"
        if stage == "start" and kind != "standard_tiff"
        else "[Aa]uthenticated|format validation"
    )
    with pytest.raises(RuntimeError, match=expected):
        method(7, output)
    assert list(output.iterdir()) == []
    assert not client._active_ims_export_jobs
    assert client.session_id == session
    assert not any(
        r[0] == "POST" and "login" in r[1] for r in fixture.requests[before:]
    )


@pytest.mark.parametrize(
    "https_api", ["127.0.0.1", "localhost", "omero.example.test"], indirect=True
)
def test_real_https_login_cookies_context_and_json_post(https_api):
    """Inputs: full login over verified TLS. Output: scoped cookies, CSRF, cleared credential, JSON."""
    module, client, fixture = https_api
    assert client.connect()
    assert client.password == module.CLEARED_CREDENTIAL_TEXT
    assert client.user_id == 7
    assert client.session_id == "fixture-session"
    assert client._api_post("fixture/", {"value": "unicode \u03bc and spaces"}) == {
        "data": []
    }
    method, endpoint, headers, body = fixture.requests[-1]
    assert method == "POST" and endpoint == "/api/v0/fixture/"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Csrftoken"] == fixture.csrf
    assert headers["Referer"] == fixture.base_url
    assert "sessionid=fixture-session" in headers["Cookie"]
    assert json.loads(body) == {"value": "unicode \u03bc and spaces"}
    assert fixture.credential.encode() not in body


@pytest.mark.parametrize(
    "mode",
    [
        "no_csrf",
        "no_session",
        "forbidden",
        "login_html",
        "invalid_json",
        "closed_connection",
    ],
)
def test_login_failures_clear_credentials_without_authentication(https_api, mode):
    """Inputs: actual transport/protocol failures. Output: no successful login or retained password."""
    module, client, fixture = https_api
    fixture.mode = mode
    assert not client.connect()
    assert client.password == module.CLEARED_CREDENTIAL_TEXT
    assert not client.reauthenticate("failed-login")


@pytest.mark.parametrize(
    "mode",
    [
        "redirect",
        "forbidden",
        "invalid_json",
        "empty",
        "login_html",
        "closed_connection",
    ],
)
def test_api_post_failure_has_no_false_success_or_response_body_disclosure(
    https_api, mode, caplog
):
    """Inputs: authenticated client and failing API. Output: explicit no-result with body kept private."""
    module, client, fixture = https_api
    assert client.connect()
    fixture.mode = mode
    caplog.set_level("DEBUG", logger=module.logger.name)
    assert client._api_post("fixture/", {"test": True}) is None
    assert "fixture-private-error-body" not in caplog.text
    assert fixture.credential not in caplog.text


def test_unauthenticated_post_never_sends_request(https_api):
    """Inputs: client without session. Output: no network request and no fabricated result."""
    _, client, fixture = https_api
    assert client._api_post("fixture/") is None
    assert fixture.requests == []


def _serve_json(fixture, method, path, payload, status=200):
    """Inputs: route and JSON payload. Output: a real, bounded HTTPS fixture response."""
    fixture.responses[(method, path)] = [
        (status, json.dumps(payload).encode(), [("Content-Type", "application/json")])
    ]


@pytest.mark.parametrize("wrapper", ["data", "datasets", "results", "items", "objects"])
def test_real_https_dataset_listing_preserves_identity_and_session(https_api, wrapper):
    """Inputs: dataset response wrappers and incomplete rows. Output: valid identities without a second query or login."""
    _, client, fixture = https_api
    assert client.connect()
    original = client.session_id
    fixture.requests.clear()
    rows = [
        None,
        "invalid-row",
        {"Name": "no identity"},
        {"@id": 11, "Name": "Primary"},
        {"Id": 12, "label": "Alternate"},
        {"ID": 13},
    ]
    _serve_json(fixture, "GET", "/api/v0/m/projects/7/datasets/", {wrapper: rows})
    assert client.list_datasets(7) == [
        {"id": 11, "name": "Primary"},
        {"id": 12, "name": "Alternate"},
        {"id": 13, "name": "Dataset 13"},
    ]
    assert len(fixture.requests) == 1
    method, path, headers, body = fixture.requests[0]
    assert method == "GET" and not body
    assert path == "/api/v0/m/projects/7/datasets/?group=-1"
    assert "sessionid=" + original in headers["Cookie"]
    assert client.session_id == original


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        (
            {"data": {"Datasets": [{"id": 11, "name": "Nested"}]}},
            [{"id": 11, "name": "Nested"}],
        ),
        ({"datasets": [{"id": 12}]}, [{"id": 12, "name": "Dataset 12"}]),
        ({"data": {"data": [{"id": 13}]}}, [{"id": 13, "name": "Dataset 13"}]),
        ({}, []),
        ([], []),
        (None, []),
    ],
)
def test_real_https_empty_dataset_route_uses_project_details(
    https_api, details, expected
):
    """Inputs: empty collection and version-dependent project details. Output: validated fallback rows, never fabricated datasets."""
    _, client, fixture = https_api
    assert client.connect()
    fixture.requests.clear()
    _serve_json(fixture, "GET", "/api/v0/m/projects/7/datasets/", {"data": []})
    _serve_json(fixture, "GET", "/api/v0/m/projects/7/", details)
    assert client.list_datasets(7) == expected
    assert [(method, path) for method, path, _, _ in fixture.requests] == [
        ("GET", "/api/v0/m/projects/7/datasets/?group=-1"),
        ("GET", "/api/v0/m/projects/7/?group=-1"),
    ]


@pytest.mark.parametrize("state_key", ["status", "state"])
@pytest.mark.parametrize(
    "state",
    [
        "FINISHED",
        "SUCCESS",
        "COMPLETE",
        "DONE",
        "FAILED",
        "ERROR",
        "CANCELLED",
        "CANCELED",
    ],
)
def test_real_https_activity_polling_returns_terminal_state_without_replaying_job(
    https_api, state_key, state
):
    """Inputs: pending then terminal script activity. Output: exact terminal record and only read requests."""
    _, client, fixture = https_api
    assert client.connect()
    original = client.session_id
    fixture.requests.clear()
    terminal = {state_key: state.lower(), "job": 17, "results": {"count": 3}}
    _serve_json(fixture, "GET", "/api/v0/activities/17/", terminal)
    fixture.responses[("GET", "/api/v0/activities/17/")].insert(
        0,
        (200, b'{"status":"RUNNING"}', [("Content-Type", "application/json")]),
    )
    assert client.poll_activity(17, timeout=3, interval=0) == terminal
    assert [(method, path) for method, path, _, _ in fixture.requests] == [
        ("GET", "/api/v0/activities/17/"),
        ("GET", "/api/v0/activities/17/"),
    ]
    assert client.session_id == original


def test_real_https_missing_or_expired_activity_has_no_false_completion(https_api):
    """Inputs: absent activity or exhausted deadline. Output: no success and no request after an exhausted deadline."""
    _, client, fixture = https_api
    assert client.connect()
    _serve_json(fixture, "GET", "/api/v0/activities/17/", None)
    assert client.poll_activity(17, timeout=3, interval=0) is None
    fixture.requests.clear()
    assert client.poll_activity(17, timeout=0) is None
    assert fixture.requests == []


@pytest.mark.parametrize(
    ("mode", "ims_expected", "tiff_expected"),
    [
        ("both", True, True),
        ("tiff_only", False, True),
        ("ims_only", True, False),
        ("wrong_flag", False, False),
        ("non_object", False, False),
        ("missing_converter", False, True),
        ("invalid_json", False, False),
        ("forbidden", False, False),
        ("redirect", False, False),
    ],
)
def test_real_https_export_capabilities_require_explicit_supported_flags(
    https_api, mode, ims_expected, tiff_expected
):
    """Inputs: advertised, disabled or malformed export support. Output: accurate choices with original session retained."""
    module, client, fixture = https_api
    assert client.connect()
    original = client.session_id
    fixture.requests.clear()
    path = "/omero_imaris_connector/imaris-export/"
    payload = {
        module.OMERO_IMS_EXPORT_CAPABILITY_KEY: module.OMERO_IMS_EXPORT_CAPABILITY_FLAG,
        "omero_ims_export": mode != "tiff_only",
        "ome_tiff_async_export": mode != "ims_only",
        "converters": {"OMERO": True},
    }
    if mode == "wrong_flag":
        payload[module.OMERO_IMS_EXPORT_CAPABILITY_KEY] = "unsupported-version"
    elif mode == "non_object":
        payload = []
    elif mode == "missing_converter":
        payload.pop("converters")
    if mode in {"invalid_json", "forbidden", "redirect"}:
        fixture.mode = mode
    else:
        _serve_json(fixture, "GET", path, payload)
    assert client.has_omero_ims_export_capability(log_unavailable=True) is ims_expected
    assert client.has_async_ome_tiff_export_capability() is tiff_expected
    assert client.session_id == original
    assert all(method == "GET" for method, _, _, _ in fixture.requests)


@pytest.mark.parametrize(
    ("payload", "status", "expected"),
    [
        ({"error": "No files provided."}, 400, {"available": True, "reason": ""}),
        (
            {"error": "Please login as regular user"},
            403,
            {
                "available": False,
                "reason": "Folder export is unavailable for the OMERO root user.",
            },
        ),
        (
            {"ok": False, "error": "Disabled by operator"},
            400,
            {"available": False, "reason": "Disabled by operator"},
        ),
        (
            {},
            200,
            {
                "available": False,
                "reason": "Folder export is not available on this OMERO.web instance.",
            },
        ),
    ],
)
def test_real_https_folder_capability_reports_operator_restrictions(
    https_api, payload, status, expected
):
    """Inputs: documented folder-start validation responses. Output: explicit capability without uploading files or retrying credentials."""
    _, client, fixture = https_api
    assert client.connect()
    original = client.session_id
    fixture.requests.clear()
    _serve_json(fixture, "POST", "/omeroweb_import/start/", payload, status=status)
    assert client.get_folder_export_capability() == expected
    assert len(fixture.requests) == 1
    method, path, headers, body = fixture.requests[0]
    assert (method, path, json.loads(body)) == ("POST", "/omeroweb_import/start/", {})
    assert {key.casefold(): value for key, value in headers.items()}[
        "x-csrftoken"
    ] == fixture.csrf
    assert client.session_id == original


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"data": [{"id": 14, "name": "Export.py"}]}, 14),
        ({"scripts": [{"@id": 14, "Name": "/scripts/Export.py"}]}, 14),
        ({"data": {"scripts": [{"id": 14, "scriptName": "Export.py"}]}}, 14),
        ({"data": [{"id": 14, "path": "Export.py"}]}, 14),
        ({"data": [{"id": 14, "Path": "/scripts/Export.py"}]}, 14),
        ({"data": [{"id": 14, "name": "Export"}]}, 14),
        ({"data": [{"id": 14, "path": "/scripts/Export"}]}, 14),
        ({"data": [{"name": "Export.py"}, {"id": 15, "name": "Other.py"}]}, None),
        ({"data": [{"id": 14}]}, None),
        ({"scripts": {"data": []}}, None),
        ({}, None),
        ([], None),
        (None, None),
    ],
)
def test_real_https_script_lookup_handles_documented_response_shapes(
    https_api, payload, expected
):
    """Inputs: script API wrappers and name aliases. Output: exact ID with original session intact."""
    _, client, fixture = https_api
    assert client.connect()
    original = client.session_id
    _serve_json(fixture, "GET", "/api/v0/scripts/", payload)
    assert client.find_script_id("Export.py") == expected
    method, path, headers, body = fixture.requests[-1]
    assert (method, path, body) == ("GET", "/api/v0/scripts/", b"")
    assert "sessionid=" + original in headers["Cookie"]
    assert client.session_id == original


@pytest.mark.parametrize("wrapper", ["data", "results", "items", "objects", "images"])
def test_real_https_image_metadata_preserves_dimensions_and_skips_invalid_rows(
    https_api, wrapper
):
    """Inputs: nested image wrappers with malformed rows. Output: complete dimensions and valid identities."""
    _, client, fixture = https_api
    assert client.connect()
    rows = [
        None,
        "not an image",
        {"name": "missing identity"},
        {
            "@id": 21,
            "Name": "full image",
            "Pixels": {"SizeX": 3, "SizeY": 4, "SizeZ": 5, "SizeC": 2, "SizeT": 7},
        },
        {"id": 22, "pixels": {"sizeX": 6, "sizeY": 8}},
    ]
    _serve_json(
        fixture, "GET", "/api/v0/m/datasets/9/images/", {wrapper: {wrapper: rows}}
    )
    assert client.list_images(9) == [
        {
            "id": 21,
            "name": "full image",
            "sizeX": 3,
            "sizeY": 4,
            "sizeZ": 5,
            "sizeC": 2,
            "sizeT": 7,
        },
        {
            "id": 22,
            "name": "Image 22",
            "sizeX": 6,
            "sizeY": 8,
            "sizeZ": 1,
            "sizeC": 1,
            "sizeT": 1,
        },
    ]
    assert fixture.requests[-1][1] == "/api/v0/m/datasets/9/images/?group=-1"


@pytest.mark.parametrize(
    "payload", [None, [], {}, {"data": "invalid"}, {"data": {"results": []}}]
)
def test_real_https_empty_image_collection_has_no_fabricated_rows(https_api, payload):
    """Inputs: empty or malformed collection. Output: empty results rather than invented images."""
    _, client, fixture = https_api
    assert client.connect()
    _serve_json(fixture, "GET", "/api/v0/m/datasets/9/images/", payload)
    assert client.list_images(9) == []


@pytest.mark.parametrize(
    "status, payload, expected",
    [
        (200, {"ok": True}, True),
        (200, {"ok": False}, False),
        (200, {"ok": 1}, False),
        (200, {"ok": "true"}, False),
        (200, {}, False),
        (200, [], False),
        (200, None, False),
        (403, {"ok": False}, False),
        (500, {"ok": False}, False),
    ],
)
def test_real_https_folder_cancellation_requires_explicit_acceptance(
    https_api, status, payload, expected
):
    """Inputs: server cancellation outcome. Output: no false success, with CSRF and session preserved."""
    _, client, fixture = https_api
    assert client.connect()
    original = client.session_id
    _serve_json(fixture, "POST", "/prune/", payload, status=status)
    assert client.cancel_folder_export_job({"prune_url": "/prune/"}) is expected
    method, path, headers, body = fixture.requests[-1]
    assert (method, path) == ("POST", "/prune/")
    assert json.loads(body) == {"keep_paths": []}
    assert headers["X-Csrftoken"] == fixture.csrf
    assert "sessionid=" + original in headers["Cookie"]
    assert client.session_id == original


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"prune_url": ""}],
)
def test_invalid_cancellation_target_never_sends_a_request(https_api, payload):
    """Inputs: absent cancellation URL. Output: rejection before any authenticated request."""
    _, client, fixture = https_api
    assert client.connect()
    initial = len(fixture.requests)
    assert client.cancel_folder_export_job(payload) is False
    assert len(fixture.requests) == initial


def test_server_cancellation_url_stays_on_configured_origin(https_api):
    """Inputs: internal server URL. Output: cancellation uses the configured public origin and session."""
    _, client, fixture = https_api
    assert client.connect()
    original = client.session_id
    _serve_json(fixture, "POST", "/prune/", {"ok": True})
    assert client.cancel_folder_export_job(
        {"prune_url": "https://internal-service.invalid/prune/"}
    )
    method, path, headers, body = fixture.requests[-1]
    assert (method, path) == ("POST", "/prune/")
    assert headers["Host"] == urllib.parse.urlsplit(client.base_url).netloc
    assert headers["X-Csrftoken"] == fixture.csrf
    assert "sessionid=" + original in headers["Cookie"]
    assert json.loads(body) == {"keep_paths": []}
    assert client.session_id == original


def multipart_parts(content_type, body):
    """Inputs: actual wire headers and bytes. Output: independently parsed MIME parts."""
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii")
        + body
    )
    assert message.is_multipart()
    assert not message.defects
    return {
        part.get_param("name", header="content-disposition"): part
        for part in message.iter_parts()
    }


@pytest.mark.parametrize("file_name", ["data.ome.tif", '../unsafe"\r\nheader.bin', ""])
def test_multipart_body_round_trip_preserves_binary_data(https_api, file_name):
    """Inputs: binary bytes and unsafe names. Output: exact parts without header injection or warnings."""
    module, _, _ = https_api
    content = bytes(range(256)) + b"\r\n--arbitrary-boundary--\r\n"
    fields = {"text": "spectrum \u03bc", "binary": b"\x00\xff", "offset": 3}
    boundary, body = module._multipart_form_body(fields, "file", file_name, content)
    parts = multipart_parts(f"multipart/form-data; boundary={boundary}", body)
    assert set(parts) == {*fields, "file"}
    for name, expected in fields.items():
        assert parts[name].get_payload(decode=True) == (
            expected if isinstance(expected, bytes) else str(expected).encode()
        )
    assert parts["file"].get_payload(decode=True) == content
    assert parts["file"].get_filename() == module._safe_download_filename(
        file_name, "upload.bin"
    )
    assert len(parts["file"].get_all("Content-Disposition")) == 1
    assert body.endswith(f"--{boundary}--\r\n".encode())
    assert (
        module._multipart_form_body(fields, "file", file_name, content)[0] != boundary
    )


@pytest.mark.parametrize("last_chunk", [False, True])
def test_real_https_folder_upload_preserves_chunk_metadata_and_session(
    https_api, last_chunk
):
    """Inputs: authenticated chunk upload over TLS. Output: byte-exact multipart, CSRF and original cookie."""
    module, client, fixture = https_api
    assert client.connect()
    original_session = client.session_id
    chunk = bytes(range(256))
    fixture.responses[("POST", "/upload/")] = [
        (200, b'{"ok":true,"received":256}', [("Content-Type", "application/json")])
    ]
    result = client.upload_folder_chunk(
        fixture.base_url + "/upload/",
        "dataset/spectrum \u03bc.tif",
        1024,
        512,
        chunk,
        last_chunk,
    )
    assert result == {"ok": True, "received": 256}
    method, endpoint, headers, body = fixture.requests[-1]
    assert method == "POST" and endpoint == "/upload/"
    assert headers["X-Csrftoken"] == fixture.csrf
    assert "sessionid=" + original_session in headers["Cookie"]
    assert client.session_id == original_session
    parts = multipart_parts(headers["Content-Type"], body)
    fields = {
        name: part.get_payload(decode=True).decode("utf-8")
        for name, part in parts.items()
        if name != "file"
    }
    assert fields == {
        "upload_mode": "chunked",
        "relative_path": "dataset/spectrum \u03bc.tif",
        "chunk_start": "512",
        "chunk_end": "768",
        "file_size": "1024",
        "is_last_chunk": "1" if last_chunk else "0",
        "chunk_sha256": module.hashlib.sha256(chunk).hexdigest(),
    }
    assert parts["file"].get_payload(decode=True) == chunk
    assert fixture.credential.encode() not in body


@pytest.mark.parametrize("mode", ["ok", "chunked"])
def test_cancellable_https_reads_actual_framing_and_cookies(https_api, mode):
    """Inputs: TLS stream with fixed/chunked body. Output: exact bytes through cancellable transport."""
    _, client, fixture = https_api
    assert client.connect()
    fixture.mode = mode
    request = client._create_request_with_cookies(fixture.base_url + "/api/v0/stream/")
    with client._open_cancellable_http_request(
        request, timeout=5, cancel_event=threading.Event()
    ) as response:
        chunks = []
        while piece := response.read(2):
            chunks.append(piece)
    assert b"".join(chunks) == (b"abcde" if mode == "chunked" else b'{"data":[]}')
    assert "sessionid=fixture-session" in fixture.requests[-1][2]["Cookie"]


def test_wrong_certificate_hostname_is_rejected_before_credentials(https_api):
    """Inputs: otherwise trusted certificate for a different hostname. Output: zero HTTP requests."""
    module, client, fixture = https_api
    client.host = "localhost"
    client.base_url = module.OMEROWebClient._build_base_url(
        "localhost", client.port, "https"
    )
    client.api_url = client.base_url + "/api/v0"
    assert not client.connect()
    assert fixture.requests == []
    assert client.password == module.CLEARED_CREDENTIAL_TEXT


@pytest.mark.parametrize(
    "operation",
    ["api_get", "api_raise", "api_post", "user_context", "ims", "ome_tiff", "json_url"],
)
def test_http_failures_close_owned_responses(https_api, monkeypatch, operation):
    """Inputs: real HTTP errors across client APIs. Output: closed responses on every exit."""
    _, client, fixture = https_api
    assert client.connect()
    fixture.mode = "forbidden"
    errors = []
    original_open = client.opener.open

    def record_error(*args, **kwargs):
        """Inputs: actual request. Output: unchanged response/error, retaining closure evidence."""
        try:
            return original_open(*args, **kwargs)
        except urllib.error.HTTPError as error:
            errors.append(error)
            raise

    monkeypatch.setattr(client.opener, "open", record_error)
    try:
        if operation == "api_get":
            assert client._api_request("fixture/") is None
        elif operation == "api_raise":
            with pytest.raises(RuntimeError, match="HTTP 403"):
                client._api_request("fixture/", raise_on_error=True)
        elif operation == "api_post":
            assert client._api_post("fixture/", {}) is None
        elif operation == "user_context":
            assert not client._refresh_current_user_context(fixture.credential)
        elif operation == "ims":
            assert not client.has_omero_ims_export_capability(log_unavailable=True)
        elif operation == "ome_tiff":
            assert not client.has_async_ome_tiff_export_capability()
        else:
            status, payload, text = client._request_json_url(
                fixture.base_url + "/fixture/"
            )
            assert (status, payload, text) == (403, None, "fixture-private-error-body")
        assert errors and all(error.closed for error in errors)
    finally:
        for error in errors:
            error.close()


def test_retried_http_failure_closes_before_success(https_api, monkeypatch):
    """Inputs: actual transient GET failure then recovery. Output: closed error and exact retry."""
    module, client, fixture = https_api
    assert client.connect()
    fixture.mode = "transient"
    errors = []
    original_open = client.opener.open

    def record_error(*args, **kwargs):
        """Inputs: real request. Output: response with prior error resource ownership checked."""
        assert all(error.closed for error in errors)
        try:
            return original_open(*args, **kwargs)
        except urllib.error.HTTPError as error:
            errors.append(error)
            raise

    monkeypatch.setattr(client.opener, "open", record_error)
    monkeypatch.setattr(module, "_http_retry_delay_seconds", lambda: 0)
    try:
        assert client._api_request("fixture/", retry_transient=True) == {"data": []}
        assert len(errors) == 1 and errors[0].closed
    finally:
        for error in errors:
            error.close()


@pytest.mark.parametrize("operation", ["read_retry", "read_once", "write"])
def test_connection_closure_retries_only_opted_in_reads(
    https_api, monkeypatch, operation
):
    """Inputs: a real dropped HTTPS response. Output: bounded reads, no replayed writes or re-login."""
    module, client, fixture = https_api
    assert client.connect()
    original_session = client.session_id
    fixture.requests.clear()
    fixture.mode = "closed_once"
    monkeypatch.setattr(module, "_http_retry_attempts", lambda: 2)
    monkeypatch.setattr(module, "_http_retry_delay_seconds", lambda: 0)
    if operation == "read_retry":
        assert client._api_request("fixture/", retry_transient=True) == {"data": []}
        assert len(fixture.requests) == 2
    elif operation == "read_once":
        assert client._api_request("fixture/") is None
        assert len(fixture.requests) == 1
    else:
        assert client._api_post("fixture/", {"value": "one mutation"}) is None
        assert len(fixture.requests) == 1
    expected_method = "POST" if operation == "write" else "GET"
    for method, path, headers, _body in fixture.requests:
        assert method == expected_method and path.endswith("/fixture/")
        assert f"sessionid={original_session}" in headers["Cookie"]
        assert f"csrftoken={fixture.csrf}" in headers["Cookie"]
    assert client.session_id == original_session


def test_persistent_transport_failure_is_bounded_and_preserves_login(
    https_api, monkeypatch
):
    """Inputs: every HTTPS read loses its response. Output: exact attempt limit with no session reset."""
    module, client, fixture = https_api
    assert client.connect()
    original_session = client.session_id
    fixture.requests.clear()
    fixture.mode = "closed_connection"
    monkeypatch.setattr(module, "_http_retry_attempts", lambda: 2)
    monkeypatch.setattr(module, "_http_retry_delay_seconds", lambda: 0)
    with pytest.raises(RuntimeError, match="OMERO.web API request failed"):
        client._api_request("fixture/", retry_transient=True, raise_on_error=True)
    assert len(fixture.requests) == 2
    assert all(row[0] == "GET" for row in fixture.requests)
    assert client.session_id == original_session


@pytest.mark.parametrize(
    "mode,authentication_failure",
    [
        ("closed_connection", False),
        ("forbidden", False),
        ("invalid_json", False),
        ("unavailable", False),
        ("unauthorized", True),
        ("not_logged_in", True),
        ("redirect", True),
        ("login_html", True),
    ],
)
def test_health_check_distinguishes_authentication_from_outage(
    https_api, mode, authentication_failure
):
    """Inputs: real TLS failure responses. Output: typed authentication failure, no credential replay."""
    module, client, fixture = https_api
    assert client.connect()
    original_cookies = [(cookie.name, cookie.value) for cookie in client.cookie_jar]
    original_session = client.session_id
    fixture.requests.clear()
    if mode == "not_logged_in":
        _serve_json(
            fixture,
            "GET",
            "/api/v0/m/projects/",
            {"message": "Not logged in"},
            status=403,
        )
    elif mode in {"unauthorized", "unavailable"}:
        _serve_json(
            fixture,
            "GET",
            "/api/v0/m/projects/",
            {"error": "fixture-only rejection"},
            status=401 if mode == "unauthorized" else 503,
        )
    else:
        fixture.mode = mode
    with pytest.raises(RuntimeError) as caught:
        client.ping(timeout=2)
    assert (
        isinstance(caught.value, module._OMEROAuthenticationError)
        == authentication_failure
    )
    assert client.session_id == original_session
    assert [
        (cookie.name, cookie.value) for cookie in client.cookie_jar
    ] == original_cookies
    assert all(row[0] == "GET" for row in fixture.requests)
    assert all(fixture.credential.encode() not in row[3] for row in fixture.requests)

    fixture.mode = "ok"
    fixture.responses.clear()
    assert client.ping(timeout=2)
    method, path, headers, _body = fixture.requests[-1]
    assert method == "GET" and path.startswith("/api/v0/m/projects/")
    assert f"sessionid={original_session}" in headers["Cookie"]
    assert f"csrftoken={fixture.csrf}" in headers["Cookie"]


def test_health_check_login_query_is_not_authentication_rejection(https_api):
    """Inputs: an API URL mentioning login only in its query. Output: authenticated JSON remains valid."""
    _, client, fixture = https_api
    assert client.connect()
    fixture.responses[("GET", "/api/v0/fixture/")] = [
        (302, b"", [("Location", "/api/v0/result/?next=/webclient/login/")])
    ]
    assert client._api_request("fixture/", raise_on_error=True) == {"data": []}


def test_successful_api_response_location_header_is_not_a_redirect(https_api):
    """Inputs: successful JSON with a Location header. Output: only actual redirects invalidate login."""
    _, client, fixture = https_api
    assert client.connect()
    fixture.responses[("GET", "/api/v0/fixture/")] = [
        (
            200,
            b'{"data":[]}',
            [("Content-Type", "application/json"), ("Location", "/webclient/login/")],
        )
    ]
    assert client._api_request("fixture/", raise_on_error=True) == {"data": []}
    assert client.session_id == "fixture-session"


@pytest.mark.parametrize(
    "body,content_type",
    [
        (b'{"message":"Forbidden"}', "application/json"),
        (b'{"message":"Not logged in"}', "text/html"),
        (b'{"message":"Not logged in"}', ""),
        (b'["Not logged in"]', "application/json"),
        (b'"Not logged in"', "application/json"),
        (b"null", "application/json"),
        (b"invalid-json", "application/json"),
        (b"\xff", "application/json"),
        (b'{"message":"Not logged in"}' + b" " * 4096, "application/json"),
    ],
)
def test_unconfirmed_forbidden_response_does_not_invalidate_session(
    https_api, body, content_type, caplog
):
    """Inputs: non-authentication, malformed or oversized 403 bodies. Output: generic failure, unchanged login."""
    module, client, fixture = https_api
    assert client.connect()
    fixture.responses[("GET", "/api/v0/m/projects/")] = [
        (403, body, [("Content-Type", content_type)])
    ]
    caplog.set_level("DEBUG", logger=module.logger.name)
    with pytest.raises(RuntimeError) as caught:
        client.ping(timeout=2)
    assert not isinstance(caught.value, module._OMEROAuthenticationError)
    assert client.session_id == "fixture-session"
    assert "Not logged in" not in caplog.text
    assert fixture.credential not in caplog.text


def test_truncated_authentication_error_does_not_discard_session(https_api):
    """Inputs: an incomplete HTTP error response. Output: transport uncertainty is not an auth reset."""
    module, client, fixture = https_api
    assert client.connect()
    body = b'{"message":"Not logged in"}'
    fixture.responses[("GET", "/api/v0/m/projects/")] = [
        (
            403,
            body,
            [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body) + 10)),
            ],
        )
    ]
    with pytest.raises(RuntimeError) as caught:
        client.ping(timeout=2)
    assert not isinstance(caught.value, module._OMEROAuthenticationError)
    assert client.session_id == "fixture-session"


@pytest.mark.parametrize(
    "mode,attempts,error_type",
    [
        ("unauthorized", 1, "_OMEROAuthenticationError"),
        ("not_logged_in", 1, "_OMEROAuthenticationError"),
        ("forbidden", 3, "RuntimeError"),
        ("closed_connection", 3, "RuntimeError"),
        ("null_json", 3, "RuntimeError"),
        ("closed_once", 2, None),
    ],
)
def test_health_worker_uses_bounded_reads_without_reauthentication(
    https_api, monkeypatch, mode, attempts, error_type
):
    """Inputs: actual health worker and TLS failures. Output: bounded reads and classified completion."""
    module, client, fixture = https_api
    assert client.connect()
    fixture.requests.clear()
    if mode == "not_logged_in":
        _serve_json(
            fixture,
            "GET",
            "/api/v0/m/projects/",
            {"message": "Not logged in"},
            status=403,
        )
    elif mode in {"unauthorized", "null_json"}:
        _serve_json(
            fixture,
            "GET",
            "/api/v0/m/projects/",
            None,
            status=401 if mode == "unauthorized" else 200,
        )
    else:
        fixture.mode = mode
    monkeypatch.setattr(module, "_health_ping_retry_attempts", lambda: 3)
    monkeypatch.setattr(module, "_health_ping_retry_delay_seconds", lambda: 0)
    monkeypatch.setattr(module, "_health_ping_timeout_seconds", lambda: 2)
    finishes = []
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.client = client
    dialog._health_ping_generation = 4
    dialog._invoke_on_ui_thread = lambda callback, wait=False: callback()
    dialog._finish_health_ping = lambda generation, error: finishes.append(
        (generation, error)
    )
    dialog._health_ping_worker(4)
    assert len(fixture.requests) == attempts
    assert len(finishes) == 1 and finishes[0][0] == 4
    assert (type(finishes[0][1]).__name__ if finishes[0][1] else None) == error_type
    assert all(row[0] == "GET" for row in fixture.requests)
    assert client.session_id == "fixture-session"
    assert all(
        "sessionid=fixture-session" in row[2]["Cookie"] for row in fixture.requests
    )


def test_cancellable_http_error_retains_status_and_body(https_api):
    """Inputs: real forbidden download. Output: HTTP status remains distinguishable from transport loss."""
    _, client, fixture = https_api
    assert client.connect()
    fixture.mode = "forbidden"
    request = client._create_request_with_cookies(fixture.base_url + "/download/")
    with pytest.raises(urllib.error.HTTPError) as caught:
        client._open_cancellable_http_request(request, 5, threading.Event())
    try:
        with caught.value as error:
            assert not error.closed
            assert error.code == 403
            assert error.read() == b"fixture-private-error-body"
        assert error.closed
    finally:
        caught.value.close()


def test_cancellable_malformed_status_closes_socket(https_api, monkeypatch):
    """Inputs: malformed response from a real TLS peer. Output: protocol failure and closed socket."""
    module, client, fixture = https_api
    assert client.connect()
    fixture.mode = "invalid_status"
    sockets = []
    original_wrap = ssl.SSLContext.wrap_socket

    def record_socket(context, *args, **kwargs):
        """Inputs: actual TLS wrap. Output: real socket, retaining client closure evidence."""
        sock = original_wrap(context, *args, **kwargs)
        if not kwargs.get("server_side"):
            sockets.append(sock)
        return sock

    monkeypatch.setattr(module.ssl.SSLContext, "wrap_socket", record_socket)
    request = client._create_request_with_cookies(fixture.base_url + "/download/")
    try:
        with pytest.raises(http.client.HTTPException, match="Invalid OMERO.web status"):
            client._open_cancellable_http_request(request, 5, threading.Event())
        assert sockets and all(sock.fileno() == -1 for sock in sockets)
    finally:
        for sock in sockets:
            sock.close()


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_authenticated_redirect_cannot_escape_configured_origin(https_api, method):
    """Inputs: redirect to another real HTTPS listener. Output: no session or CSRF leaves its origin."""
    _, client, fixture = https_api
    assert client.connect()
    foreign = ThreadingHTTPServer(("127.0.0.1", 0), fixture.handler)
    foreign.socket = fixture.context.wrap_socket(foreign.socket, server_side=True)
    worker = threading.Thread(target=foreign.serve_forever, daemon=True)
    worker.start()
    fixture.foreign_url = f"https://127.0.0.1:{foreign.server_port}/foreign-target/"
    fixture.mode = "foreign_redirect"
    try:
        if method == "GET":
            assert client._api_request("fixture/") is None
        else:
            assert client._api_post("fixture/", {"value": "private-fixture"}) is None
        assert not any(path == "/foreign-target/" for _, path, _, _ in fixture.requests)
    finally:
        foreign.shutdown()
        foreign.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()
