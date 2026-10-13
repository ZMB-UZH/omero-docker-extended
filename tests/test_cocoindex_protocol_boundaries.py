"""Exercise MCP framing, validation and isolation without an embedding download."""

from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import cocoindex_agent_search as search


def test_stdio_smoke_reports_native_failure_without_fabricating_a_receipt(
    tmp_path, monkeypatch
):
    """Inputs: provider process exits nonzero. Output: exact failure status and diagnostic, no handshake success."""
    context = SimpleNamespace(repo_root=tmp_path, artifact_root=tmp_path / "cache")
    child = Mock(
        return_value=subprocess.CompletedProcess(
            [], 7, "partial output", "provider error"
        )
    )
    monkeypatch.setattr(search, "run_command_with_input", child)
    with pytest.raises(RuntimeError, match="exit 7") as caught:
        search.run_mcp_stdio_smoke(context, include_search=False)
    assert "partial output" in str(caught.value) and "provider error" in str(
        caught.value
    )
    assert child.call_args.kwargs["timeout"] > 0


def test_protocol_smoke_tests_every_declared_version_once(monkeypatch):
    """Inputs: the supported protocol inventory. Output: one exact probe per version, retaining order and results."""
    context = object()
    probe = Mock(side_effect=lambda _context, version: {"version": version})
    monkeypatch.setattr(search, "run_mcp_jsonrpc_protocol_probe", probe)
    assert search.run_mcp_jsonrpc_smoke(context) == [
        {"version": version} for version in search.MCP_PROTOCOL_VERSIONS
    ]
    assert [call.args for call in probe.call_args_list] == [
        (context, version) for version in search.MCP_PROTOCOL_VERSIONS
    ]


@pytest.mark.parametrize("server", [None, "invalid", []])
def test_malformed_registration_is_never_treated_as_a_matching_provider(server):
    """Inputs: absent or malformed server stanza. Output: mismatch, never permission to claim a verified binding."""
    assert not search.codex_mcp_server_matches_expected(
        {"mcp_servers": {search.MCP_SERVER_NAME: server}}, {}
    )


@pytest.mark.parametrize(
    "fault,message",
    [
        ("exit", "exit 7"),
        ("initialize", "initialize did not return"),
        ("tools", "tools/list did not return"),
        ("missing_search", "did not include search"),
    ],
)
def test_raw_protocol_probe_rejects_incomplete_provider_evidence(
    tmp_path, monkeypatch, fault, message
):
    """Inputs: bounded child-process failures. Output: no handshake receipt from invalid replies."""
    context = SimpleNamespace(repo_root=tmp_path, artifact_root=tmp_path / "cache")
    protocol = search.MCP_PROTOCOL_VERSIONS[0]
    initialize = {"protocolVersion": protocol}
    tools = {"tools": [{"name": "search"}]}
    if fault == "initialize":
        initialize = []
    elif fault == "tools":
        tools = []
    elif fault == "missing_search":
        tools = {"tools": [{"name": "unrelated"}]}
    stdout = "\n".join(
        json.dumps({"jsonrpc": "2.0", "id": identity, "result": result})
        for identity, result in ((1, initialize), (2, tools))
    )
    child = Mock(
        return_value=subprocess.CompletedProcess(
            [], 7 if fault == "exit" else 0, stdout, "fixture diagnostic"
        )
    )
    monkeypatch.setattr(search, "run_command_with_input", child)
    with pytest.raises(RuntimeError, match=message):
        search.run_mcp_jsonrpc_protocol_probe_once(context, protocol)
    child.assert_called_once()
    assert child.call_args.kwargs["cwd"] == tmp_path
    assert child.call_args.kwargs["timeout"] > 0
    messages = [
        json.loads(line) for line in child.call_args.kwargs["input_text"].splitlines()
    ]
    assert [item["method"] for item in messages] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
    ]
    assert all(item.get("method") != "tools/call" for item in messages)


@pytest.mark.parametrize("eventual_success", [False, True])
def test_empty_tool_list_retry_is_bounded_and_retains_failure(
    monkeypatch, eventual_success
):
    """Inputs: transient empty tool list. Output: at most the configured attempts with bounded waits."""
    failure = search.McpSearchToolUnavailable("fixture tool missing")
    verified = {"tools": ["search"]}
    probe = Mock(side_effect=[failure, verified] if eventual_success else failure)
    sleep = Mock()
    monkeypatch.setattr(search, "run_mcp_jsonrpc_protocol_probe_once", probe)
    monkeypatch.setattr(search, "MCP_PROTOCOL_PROBE_ATTEMPTS", 2)
    monkeypatch.setattr(search.time, "sleep", sleep)
    context = object()
    protocol = search.MCP_PROTOCOL_VERSIONS[0]
    if eventual_success:
        assert search.run_mcp_jsonrpc_protocol_probe(context, protocol) is verified
    else:
        with pytest.raises(search.McpSearchToolUnavailable) as error:
            search.run_mcp_jsonrpc_protocol_probe(context, protocol)
        assert error.value is failure
    assert probe.call_args_list == [((context, protocol),), ((context, protocol),)]
    sleep.assert_called_once_with(search.MCP_PROTOCOL_PROBE_RETRY_DELAY_SECONDS)


def test_zero_probe_budget_cannot_report_success(monkeypatch):
    """Inputs: an invalid zero-attempt probe budget. Output: explicit failure without contacting the provider."""
    probe = Mock(side_effect=AssertionError("probe budget is empty"))
    monkeypatch.setattr(search, "MCP_PROTOCOL_PROBE_ATTEMPTS", 0)
    monkeypatch.setattr(search, "run_mcp_jsonrpc_protocol_probe_once", probe)
    with pytest.raises(RuntimeError, match="probe did not run"):
        search.run_mcp_jsonrpc_protocol_probe(object(), search.MCP_PROTOCOL_VERSIONS[0])
    probe.assert_not_called()


@pytest.mark.parametrize("include_search", [False, True])
def test_smoke_separates_provider_handshake_from_repository_search(
    monkeypatch, capsys, include_search
):
    """Inputs: explicit search opt-in. Output: no index access for handshake-only qualification."""
    handshake, active = object(), object()
    resolver = Mock(return_value=active)
    monkeypatch.setattr(search, "resolve_mcp_handshake_context", lambda: handshake)
    monkeypatch.setattr(search, "resolve_active_index_context", resolver)
    calls = []

    def stdio(context, *, include_search):
        """Inputs: qualification context. Output: labeled fixture response, not an actual search receipt."""
        calls.append((context, include_search))
        return {"fixture": "search" if include_search else "handshake"}

    monkeypatch.setattr(search, "run_mcp_stdio_smoke", stdio)
    protocols = [{"fixture": "protocol"}]
    probe = Mock(return_value=protocols)
    monkeypatch.setattr(search, "run_mcp_jsonrpc_smoke", probe)
    search.command_mcp_smoke(SimpleNamespace(include_search=include_search))
    output = json.loads(capsys.readouterr().out)
    assert output["stdio_probe"] == {"fixture": "handshake"}
    assert output["jsonrpc_protocol_probes"] == protocols
    assert calls == (
        [(handshake, False), (active, True)] if include_search else [(handshake, False)]
    )
    assert resolver.call_count == int(include_search)
    assert ("stdio_search_probe" in output) is include_search
    probe.assert_called_once_with(handshake)


@pytest.mark.parametrize("payload", [[], None, 7, "invalid"])
def test_mcp_invalid_request_receives_protocol_error(payload):
    """Inputs: non-object JSON request. Output: a null-ID error instead of a client hang."""
    output = io.StringIO()
    search.run_lightweight_mcp_server(io.StringIO(json.dumps(payload) + "\n"), output)
    response = json.loads(output.getvalue())
    assert response["id"] is None
    assert response["jsonrpc"] == "2.0" and response["error"]["code"] == -32600


def test_mcp_null_request_id_is_not_a_notification():
    """Inputs: explicit null ID followed by a notification. Output: exactly one ping response."""
    output = io.StringIO()
    messages = [
        {"jsonrpc": "2.0", "id": None, "method": "ping"},
        {"jsonrpc": "2.0", "method": "ping"},
    ]
    search.run_lightweight_mcp_server(
        io.StringIO("\n".join(map(json.dumps, messages))), output
    )
    assert json.loads(output.getvalue()) == {"jsonrpc": "2.0", "id": None, "result": {}}


@pytest.mark.parametrize("payload", [[], None, 7, "invalid"])
def test_mcp_probe_rejects_non_object_responses_with_diagnostic(payload):
    """Inputs: malformed provider stdout. Output: explicit probe failure, never an incidental exception."""
    with pytest.raises(RuntimeError, match="response must be an object"):
        search.parse_mcp_response_lines(json.dumps(payload))


@pytest.mark.parametrize(
    "arguments",
    [
        None,
        [],
        {"query": ""},
        {"query": 1},
        {"query": "read", "limit": True},
        {"query": "read", "limit": 0},
        {"query": "read", "path": ""},
        {"query": "read", "path": 1},
        {"query": "read", "lang": "python"},
        {"query": "read", "lang": [""]},
        {"query": "read", "refresh_index": False},
    ],
)
def test_mcp_bad_search_arguments_never_start_repository_work(monkeypatch, arguments):
    """Inputs: unsupported search arguments. Output: JSON-RPC parameter error before index access."""
    resolver = Mock(
        side_effect=AssertionError("invalid input must not reach repository")
    )
    monkeypatch.setattr(search, "resolve_active_index_context", resolver)
    with pytest.raises(search.JsonRpcError) as caught:
        search.run_mcp_search_tool(arguments)
    assert caught.value.code == -32602
    resolver.assert_not_called()


def test_mcp_search_options_preserve_exact_filter_and_count():
    """Inputs: supported explicit options. Output: unchanged scope, not defaulted or expanded."""
    assert search.mcp_search_arguments(
        {"query": "session", "limit": 2, "path": "tools/*.py", "lang": ["python"]}
    ) == {"query": "session", "limit": 2, "path": "tools/*.py", "langs": ["python"]}


def test_mcp_stream_recovers_after_parse_and_method_errors():
    """Inputs: malformed frame, invalid method and ping. Output: bounded errors followed by a usable server."""
    output = io.StringIO()
    source = (
        "\nnot-json\n"
        + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "invalid"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    )
    search.run_lightweight_mcp_server(io.StringIO(source), output)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [response.get("error", {}).get("code") for response in responses] == [
        -32700,
        -32601,
        None,
    ]
    assert responses[-1]["id"] == 2 and responses[-1]["result"] == {}


@pytest.mark.parametrize(
    "failure",
    [
        OSError("fixture I/O failure"),
        RuntimeError("fixture provider failure"),
        TypeError("fixture invalid type"),
        ValueError("fixture invalid value"),
    ],
)
def test_mcp_request_failure_is_returned_only_for_requests(monkeypatch, failure):
    """Inputs: provider failure for a request and notification. Output: one bounded protocol error."""

    def fail(_message):
        """Inputs: parsed frame. Output: selected operational fault."""
        raise failure

    monkeypatch.setattr(search, "handle_mcp_request", fail)
    output = io.StringIO()
    frames = [{"id": 1, "method": "ping"}, {"method": "notification"}]
    search.run_lightweight_mcp_server(
        io.StringIO("\n".join(map(json.dumps, frames))), output
    )
    assert json.loads(output.getvalue())["error"]["code"] == -32000


def test_mcp_call_requires_object_parameters():
    """Inputs: a list where a tool-call object is required. Output: deterministic parameter error."""
    with pytest.raises(search.JsonRpcError) as caught:
        search.mcp_tool_call_result([])
    assert caught.value.code == -32602


@pytest.mark.parametrize(
    "result,message",
    [
        ({"serverInfo": []}, "omitted serverInfo"),
        (
            {"serverInfo": {"name": "unrelated", "version": search.PACKAGE_VERSION}},
            "wrong server",
        ),
        (
            {"serverInfo": {"name": search.MCP_SERVER_NAME, "version": "unreviewed"}},
            "wrong version",
        ),
    ],
)
def test_probe_does_not_admit_wrong_provider_or_version(result, message):
    """Inputs: unexpected provider identity. Output: failed qualification, not a successful handshake."""
    with pytest.raises(RuntimeError, match=message):
        search.mcp_server_info(result, {"id": 1, "result": result})


def test_probe_requires_object_results_and_the_search_tool():
    """Inputs: malformed result or missing advertised search. Output: no usable-provider receipt."""
    with pytest.raises(RuntimeError, match="did not return a result"):
        search.mcp_response_result({1: {"result": []}}, 1, "initialize")
    responses = {
        1: {
            "result": {
                "serverInfo": {
                    "name": search.MCP_SERVER_NAME,
                    "version": search.PACKAGE_VERSION,
                }
            }
        },
        2: {"result": {"tools": []}},
    }
    with pytest.raises(RuntimeError, match="did not include search"):
        search.parse_mcp_stdio_probe_result(responses)


@pytest.mark.parametrize(
    "payload,message",
    [
        ("not-json", "non-JSON stdout"),
        ('{"id":1,"error":{"code":-1}}', "error response"),
    ],
)
def test_probe_reports_invalid_wire_payload(payload, message):
    """Inputs: malformed or error stdout. Output: no invented success response."""
    with pytest.raises(RuntimeError, match=message):
        search.parse_mcp_response_lines(payload)
    assert search.parse_mcp_response_lines(
        '\n{"method":"notification"}\n{"id":1,"result":{}}'
    ) == {1: {"id": 1, "result": {}}}


@pytest.mark.parametrize("resolution_error", [False, True])
def test_mcp_redaction_survives_failed_optional_path_resolution(
    tmp_path, monkeypatch, resolution_error
):
    """Inputs: unavailable repo/cache resolution. Output: home and known context paths still redacted."""
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)

    def unavailable():
        """Inputs: optional path lookup. Output: controlled configuration failure."""
        raise RuntimeError("unavailable")

    monkeypatch.setattr(search, "default_artifact_root", unavailable)
    monkeypatch.setattr(search, "resolve_repo_root", unavailable)
    if resolution_error:
        monkeypatch.setattr(
            Path, "resolve", Mock(side_effect=OSError("unavailable mount"))
        )
    context = SimpleNamespace(repo_root=home / "source", artifact_root=home / "cache")
    message = f"{context.repo_root}/module.py {context.artifact_root}/index {home}/file"
    result = search.sanitize_mcp_error_text(message, context)
    assert str(home) not in result
    assert f"${search.REPO_ROOT_ENV}/module.py" in result
    assert f"${search.ARTIFACT_ROOT_ENV}/index" in result
    assert "$HOME/file" in result
