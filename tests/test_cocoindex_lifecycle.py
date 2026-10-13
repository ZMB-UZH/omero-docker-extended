"""Exercise host-tool lifecycle decisions without downloading another runtime."""

from __future__ import annotations

import errno
from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tomllib
from types import SimpleNamespace
from unittest.mock import Mock
import venv

import pytest

from tools import cocoindex_agent_search as search


def test_invalid_embedding_device_environment_fails_before_runtime_access(
    lifecycle_context, monkeypatch
):
    """Inputs: unsupported device override. Output: explicit rejection, no index or runtime mutation."""
    monkeypatch.setenv(search.DEVICE_ENV, "unknown-device")
    runtime = Mock(side_effect=AssertionError("runtime must remain untouched"))
    monkeypatch.setattr(search, "run_runtime_python", runtime)
    with pytest.raises(RuntimeError, match="must be one of"):
        search.configure_embedding_device(lifecycle_context, None)
    runtime.assert_not_called()


@pytest.mark.parametrize("inside", [False, True])
def test_benchmark_cli_preserves_source_scope_and_explicit_options(
    tmp_path, monkeypatch, capsys, inside
):
    """Inputs: in-tree or external cases file. Output: exact exclusion, authority, device and report dispatch."""
    root = tmp_path / "repo"
    root.mkdir()
    cases_path = (root if inside else tmp_path) / "cases.json"
    cases_path.write_text(
        json.dumps(
            [
                {
                    "name": "fixture",
                    "query": "needle",
                    "rg": "needle",
                    "expected": ["source.py"],
                }
            ]
        )
    )
    context = object()
    clean = Mock()
    resolve = Mock(return_value=context)
    benchmark = Mock(return_value={"summary": {"cases": 1}})
    monkeypatch.setattr(search, "resolve_repo_root", lambda: root)
    monkeypatch.setattr(search, "require_clean_index_target", clean)
    monkeypatch.setattr(search, "resolve_context", resolve)
    monkeypatch.setattr(search, "run_benchmark", benchmark)
    output = tmp_path / "report.json"
    search.command_benchmark(
        SimpleNamespace(
            cases=cases_path, output=output, allow_dirty_index=True, device="cpu"
        )
    )
    excluded = frozenset({PurePosixPath("cases.json")} if inside else {})
    clean.assert_called_once_with(root, allow_dirty=True)
    resolve.assert_called_once_with(excluded, repo_root=root)
    arguments = benchmark.call_args
    assert arguments.args == (
        context,
        search.load_benchmark_cases(cases_path),
        output,
        excluded,
    )
    assert arguments.kwargs == {"allow_dirty": True, "requested_device": "cpu"}
    assert json.loads(capsys.readouterr().out) == {"summary": {"cases": 1}}


def test_discovery_rejects_nonrepository_without_creating_a_marker(tmp_path):
    """Inputs: directory outside Git. Output: explicit refusal without initializing a repository."""
    with pytest.raises(RuntimeError, match="not inside a Git work tree"):
        search.discover_git_root_candidate(tmp_path)
    assert not (tmp_path / ".git").exists()


def test_mirror_source_rejects_parent_escape_and_ignores_missing_files(tmp_path):
    """Inputs: traversal and a removed tracked file. Output: no outside read and no invented mirror entry."""
    root = tmp_path / "source"
    root.mkdir()
    (tmp_path / "private").write_text("not repository source")
    with pytest.raises(RuntimeError, match="escapes repository root"):
        search.verified_repo_source_path(root, PurePosixPath("../private"))
    present = PurePosixPath("present.py")
    (root / str(present)).write_text("present = True\n")
    paths = [present, PurePosixPath("missing.py")]
    digest, files = search.file_digest_and_mirror_source(root, paths)
    assert digest == search.file_digest(root, paths)
    assert files == {"present.py": b"present = True\n"}


@pytest.mark.parametrize("device", ["cuda", "mps"])
@pytest.mark.parametrize("available", [False, True])
def test_explicit_accelerator_requires_runtime_capability(
    lifecycle_context, monkeypatch, device, available
):
    """Inputs: an explicitly selected accelerator. Output: persist only a verified available device, never silently fall back."""
    probe = Mock(return_value={"cuda": available, "mps": available})
    persist = Mock()
    monkeypatch.setattr(search, "probe_embedding_devices", probe)
    monkeypatch.setattr(search, "run_runtime_python", persist)
    if available:
        assert search.configure_embedding_device(lifecycle_context, device) == device
        assert persist.call_args.args[0] is lifecycle_context
        assert persist.call_args.args[-1] == device
    else:
        with pytest.raises(RuntimeError, match="unavailable in the installed"):
            search.configure_embedding_device(lifecycle_context, device)
        persist.assert_not_called()
    probe.assert_called_once_with(lifecycle_context)


@pytest.mark.parametrize("warm", [False, True])
def test_cold_index_notice_depends_on_the_bound_index(
    lifecycle_context, monkeypatch, capsys, warm
):
    """Inputs: absent or existing database. Output: cold-start notice only when needed, no index creation."""
    database = lifecycle_context.repo_root / "fixture.sqlite"
    if warm:
        database.touch()
    monkeypatch.setattr(search, "target_sqlite_db", lambda _context: database)
    search.emit_cold_index_notice_if_needed(lifecycle_context)
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ("" if warm else search.COLD_INDEX_NOTICE + "\n")
    assert database.exists() is warm


def test_project_initialization_rechecks_after_acquiring_its_lock(
    lifecycle_context, monkeypatch
):
    """Inputs: another writer completes initialization while this process waits. Output: no destructive second initialization."""
    context = lifecycle_context
    context.settings_dir.mkdir(parents=True)
    (context.settings_dir / "global_settings.yml").write_text("fixture: global\n")
    project = context.mirror_repo / ".cocoindex_code" / "settings.yml"

    @contextmanager
    def acquired(_path):
        """Inputs: project lock. Output: simulate only a concurrent writer finishing before acquisition."""
        project.parent.mkdir(parents=True)
        project.write_text("fixture: existing\n")
        yield

    launch = Mock(
        side_effect=AssertionError("Existing settings must not be reinitialized")
    )
    monkeypatch.setattr(search, "FileLock", acquired)
    monkeypatch.setattr(search, "checked_command", launch)
    search.ensure_project_initialized(context)
    launch.assert_not_called()
    assert project.read_text() == "fixture: existing\n"


def test_failed_semantic_search_never_becomes_a_benchmark_success(
    lifecycle_context, monkeypatch
):
    """Inputs: a nonzero provider result. Output: retained provider diagnostics and no timing/result success."""
    execute = Mock(
        return_value=subprocess.CompletedProcess([], 9, "partial", "provider failed")
    )
    monkeypatch.setattr(search, "run_ccc_existing", execute)
    case = SimpleNamespace(name="fixture", query="specific contract")
    with pytest.raises(RuntimeError, match="CocoIndex search failed") as caught:
        search.run_coco_search(lifecycle_context, case, manage_daemon=False)
    assert "partial" in str(caught.value) and "provider failed" in str(caught.value)
    assert execute.call_args.args == (
        lifecycle_context,
        ["search", "--limit", "5", case.query],
    )
    assert execute.call_args.kwargs["manage_daemon"] is False


def test_index_command_preserves_explicit_dirty_and_device_options(
    lifecycle_context, monkeypatch, capsys
):
    """Inputs: explicit current-root indexing options. Output: guarded index dispatch with unchanged provider output."""
    context = lifecycle_context
    clean, resolve = Mock(), Mock(return_value=context)
    index = Mock(return_value="fixture index output\n")
    monkeypatch.setattr(search, "resolve_repo_root", lambda: context.repo_root)
    monkeypatch.setattr(search, "require_clean_index_target", clean)
    monkeypatch.setattr(search, "resolve_context", resolve)
    monkeypatch.setattr(search, "run_index", index)
    search.command_index(SimpleNamespace(allow_dirty_index=True, device="cpu"))
    clean.assert_called_once_with(context.repo_root, allow_dirty=True)
    resolve.assert_called_once_with(repo_root=context.repo_root)
    index.assert_called_once_with(context, allow_dirty=True, requested_device="cpu")
    assert capsys.readouterr().out == "fixture index output\n"


def test_status_uses_only_the_existing_active_index(
    lifecycle_context, monkeypatch, capsys
):
    """Inputs: status command. Output: current provider status without installation or reindexing."""
    execute = Mock(
        return_value=subprocess.CompletedProcess([], 0, "fixture status\n", "")
    )
    monkeypatch.setattr(
        search, "resolve_active_index_context", lambda: lifecycle_context
    )
    monkeypatch.setattr(search, "run_ccc_existing", execute)
    search.command_status(SimpleNamespace())
    assert execute.call_args.args == (lifecycle_context, ["status"])
    assert execute.call_args.kwargs == {"timeout": search.timeout_seconds("status")}
    assert capsys.readouterr().out == "fixture status\n"


def test_mcp_install_failure_never_rewrites_configuration_or_launcher(
    lifecycle_context, tmp_path, monkeypatch
):
    """Inputs: a provider error rather than a missing registration. Output: stop before any registration or launcher mutation."""
    config = tmp_path / "config.toml"
    config.write_text("original = true\n")
    monkeypatch.setattr(
        search, "resolve_mcp_handshake_context", lambda: lifecycle_context
    )
    monkeypatch.setattr(
        search, "resolve_required_executable", lambda _name: "fixture-codex"
    )
    monkeypatch.setattr(search, "codex_config_path", lambda: config)
    monkeypatch.setattr(search, "expected_codex_mcp_server", lambda _context: {})
    monkeypatch.setattr(
        search,
        "run_command",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 7, "", "provider unavailable"
        ),
    )
    launcher, write = Mock(), Mock()
    monkeypatch.setattr(search, "ensure_mcp_launcher", launcher)
    monkeypatch.setattr(search, "checked_command", write)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        search.command_mcp_install(SimpleNamespace())
    launcher.assert_not_called()
    write.assert_not_called()
    assert config.read_text() == "original = true\n"


@pytest.mark.parametrize(
    "failed_step",
    [
        None,
        "ensure_installed",
        "ensure_mirror",
        "ensure_project_initialized",
        "ensure_project_settings_match_mirror",
        "configure_embedding_device",
    ],
)
def test_index_preparation_stops_at_first_failed_dependency(
    lifecycle_context, monkeypatch, failed_step
):
    """Inputs: preparation failure at each boundary. Output: no later setup can conceal or compound it."""
    steps = [
        "ensure_installed",
        "ensure_mirror",
        "ensure_project_initialized",
        "ensure_project_settings_match_mirror",
        "configure_embedding_device",
    ]
    calls = []

    def operation(name):
        """Inputs: named provider boundary. Output: operation preserving call order and arguments."""

        def run(context, *arguments):
            """Inputs: exact context and options. Output: controlled success or dependency failure."""
            assert context is lifecycle_context
            calls.append((name, arguments))
            if name == failed_step:
                raise RuntimeError("fixture preparation failure")

        return run

    for name in steps:
        monkeypatch.setattr(search, name, operation(name))
    if failed_step:
        with pytest.raises(RuntimeError, match="fixture preparation failure"):
            search.ensure_ready(lifecycle_context, requested_device="cpu")
    else:
        search.ensure_ready(lifecycle_context, requested_device="cpu")
    expected = steps[: steps.index(failed_step) + 1] if failed_step else steps
    assert [name for name, _arguments in calls] == expected
    if calls[-1][0] == "configure_embedding_device":
        assert calls[-1][1] == ("cpu",)


def test_context_resolution_uses_real_git_inventory_without_indexing(
    lifecycle_context, monkeypatch
):
    """Inputs: private real Git worktree and explicitly bound root. Output: source-bound digest without cache mutation."""
    context = lifecycle_context
    git = shutil.which("git")
    assert git
    subprocess.run([git, "init", "--quiet", str(context.repo_root)], check=True)
    (context.repo_root / "tracked.py").write_text("tracked = True\n")
    (context.repo_root / "new.py").write_text("new = True\n")
    subprocess.run([git, "add", "tracked.py"], cwd=context.repo_root, check=True)
    monkeypatch.setenv(search.REPO_ROOT_ENV, str(context.repo_root))
    monkeypatch.setattr(search, "default_artifact_root", lambda: context.artifact_root)
    resolved = search.resolve_context()
    assert resolved.repo_root == context.repo_root
    assert resolved.mirror_digest == search.file_digest(
        context.repo_root, search.tracked_files(context.repo_root)
    )
    assert resolved.mirror_repo.parent.name == resolved.mirror_digest
    handshake = search.resolve_mcp_handshake_context()
    assert (
        handshake.repo_root == context.repo_root
        and handshake.mirror_digest == "mcp-handshake"
    )
    assert not context.artifact_root.exists()
    (context.repo_root / "new.py").write_text("new = False\n")
    assert search.resolve_context().mirror_digest != resolved.mirror_digest
    (context.repo_root / "operator.env").write_text("FIXTURE=do-not-index\n")
    with pytest.raises(RuntimeError, match="Refusing to mirror deployment-local"):
        search.resolve_context()
    assert not context.artifact_root.exists()


@pytest.mark.parametrize(
    "refresh,allow_index", [(True, False), (False, True), (False, False)]
)
def test_explicit_search_indexing_and_filters_are_preserved(
    lifecycle_context, monkeypatch, refresh, allow_index
):
    """Inputs: absent index with explicit indexing options. Output: only authorized index creation and exact query filters."""
    index, execute = (
        Mock(),
        Mock(return_value=SimpleNamespace(stdout="fixture results")),
    )
    monkeypatch.setattr(search, "run_index", index)
    monkeypatch.setattr(search, "run_ccc_existing", execute)
    kwargs = dict(
        query=["specific query"],
        limit=3,
        path="tools/*",
        langs=["python", "markdown"],
        refresh=refresh,
        allow_index=allow_index,
        allow_dirty=True,
        requested_device="cpu",
    )
    if refresh or allow_index:
        assert search.run_search(lifecycle_context, **kwargs) == "fixture results"
        index.assert_called_once_with(
            lifecycle_context, allow_dirty=True, requested_device="cpu"
        )
        assert execute.call_args.args[1] == [
            "search",
            "--limit",
            "3",
            "--path",
            "tools/*",
            "--lang",
            "python",
            "--lang",
            "markdown",
            "specific query",
        ]
    else:
        with pytest.raises(search.IndexRequiredError):
            search.run_search(lifecycle_context, **kwargs)
        index.assert_not_called()
        execute.assert_not_called()


@pytest.mark.parametrize(
    "initial",
    [
        "",
        '# retained\n[other]\nvalue = "unchanged"',
        '[mcp_servers.cocoindex-code]\ncommand = "retained"',
    ],
)
def test_timeout_updates_round_trip_without_changing_other_configuration(
    tmp_path, initial
):
    """Inputs: real TOML with or without a final newline. Output: valid idempotent timeout update and preserved fields."""
    path = tmp_path / "config.toml"
    path.write_text(initial)
    search.ensure_codex_mcp_timeouts(path)
    first = path.read_bytes()
    parsed = tomllib.loads(first.decode())
    server = parsed["mcp_servers"]["cocoindex-code"]
    assert server["startup_timeout_sec"] == search.MCP_STARTUP_TIMEOUT_SECONDS
    assert server["tool_timeout_sec"] == search.MCP_TOOL_TIMEOUT_SECONDS
    if "[other]" in initial:
        assert parsed["other"] == {"value": "unchanged"}
        assert "# retained" in first.decode()
    if 'command = "retained"' in initial:
        assert server["command"] == "retained"
    search.ensure_codex_mcp_timeouts(path)
    assert path.read_bytes() == first


@pytest.mark.parametrize("value", [True, False, 3, 1.5, 'quoted "name"\nsecond line'])
def test_toml_scalar_encoding_preserves_type_and_value(value):
    """Inputs: supported scalar including quotes/newlines. Output: exact parsed value and type."""
    actual = tomllib.loads("key = " + search.format_toml_scalar(value))["key"]
    assert actual == value and type(actual) is type(value)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        [None],
        [{"name": 1, "query": "query", "rg": "pattern", "expected": ["file.py"]}],
        [{"name": "case", "query": "query", "rg": "pattern", "expected": []}],
        [{"name": "case", "query": "query", "rg": "pattern", "expected": [None]}],
    ],
)
def test_invalid_benchmark_cases_fail_without_running_search(tmp_path, payload):
    """Inputs: malformed benchmark definitions. Output: explicit schema failure, never fabricated recall."""
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="Benchmark case"):
        search.load_benchmark_cases(path)


@pytest.mark.parametrize("hit", [False, True])
def test_benchmark_combines_real_rg_results_with_selected_semantic_candidates(
    tmp_path, monkeypatch, hit
):
    """Inputs: real candidate files and fixed semantic response. Output: exact recall, ranks, and observed character counts."""
    rg = shutil.which("rg")
    assert rg, "Native benchmark tests require ripgrep"
    (tmp_path / "expected.py").write_text("value = 'needle'\n")
    (tmp_path / "other.py").write_text("value = 'unrelated'\n")
    context = SimpleNamespace(repo_root=tmp_path)
    selected = "expected.py" if hit else "other.py"
    semantic = f"--- Result 1 (score: 1.0) ---\nFile: {selected}:1-1 [python]\nvalue\n"
    monkeypatch.setattr(
        search,
        "run_ccc_existing",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, semantic, ""),
    )
    case = search.BenchmarkCase("fixture", "find value", "needle", ("expected.py",))
    result = search.benchmark_case(context, rg, case, [])
    assert result.rg_returncode == 0 and result.rg_expected_rank == 1
    assert result.coco_expected_rank == (1 if hit else None)
    assert result.coco_first_files == [selected]
    assert result.focused_rg_unique_files == int(hit)
    assert result.coco_chars == len(semantic)
    assert result.hybrid_chars == result.coco_chars + result.focused_rg_chars


@pytest.mark.parametrize("raw", [None, "invalid", "42\n"])
def test_owned_daemon_metadata_handles_absent_or_invalid_pid(lifecycle_context, raw):
    """Inputs: missing or malformed owned PID and log files. Output: bounded absence or exact stored identity."""
    context = lifecycle_context
    context.runtime_dir.mkdir(parents=True)
    if raw is not None:
        (context.runtime_dir / "daemon.pid").write_text(raw)
    assert search.daemon_pid(context) == (42 if raw == "42\n" else None)
    assert search.read_daemon_log(context) == ""
    search.daemon_log_path(context).write_text("  startup diagnostic\n")
    assert search.read_daemon_log(context) == "startup diagnostic"


def test_owned_daemon_stop_does_not_stop_replacement_process(
    lifecycle_context, monkeypatch
):
    """Inputs: PID file taken over by a different daemon. Output: only the wrapper-owned process is reaped."""
    process = SimpleNamespace(pid=42)
    stop, reap = Mock(), Mock()
    monkeypatch.setattr(search, "daemon_pid", lambda _context: 43)
    monkeypatch.setattr(search, "run_runtime_python", stop)
    monkeypatch.setattr(search, "reap_started_daemon_process", reap)
    search.stop_owned_daemon(lifecycle_context, process)
    stop.assert_not_called()
    reap.assert_called_once_with(process, terminate_first=True)


def test_daemon_stop_reports_a_remaining_listener_and_still_reaps_owned_child(
    lifecycle_context, monkeypatch
):
    """Inputs: daemon accepts a handshake after stop. Output: explicit failure with guaranteed owned-child cleanup."""
    process = SimpleNamespace(pid=42)
    reap = Mock()
    monkeypatch.setattr(search, "daemon_pid", lambda _context: 42)
    monkeypatch.setattr(search, "run_runtime_python", Mock())
    monkeypatch.setattr(search, "daemon_handshake_succeeds", lambda _context: True)
    monkeypatch.setattr(search, "reap_started_daemon_process", reap)
    with pytest.raises(RuntimeError, match="still accepts handshakes"):
        search.stop_owned_daemon(lifecycle_context, process)
    reap.assert_called_once_with(process)


@pytest.mark.parametrize("state", ["exited", "terminates", "unkillable"])
def test_owned_daemon_reaping_escalates_only_when_required(monkeypatch, state):
    """Inputs: completed, cooperative or unresponsive child. Output: precise termination sequence or explicit failure."""
    process = Mock(pid=42)
    process.poll.return_value = 0 if state == "exited" else None
    timeout = subprocess.TimeoutExpired("fixture-owned-child", 1)
    process.wait.side_effect = [timeout, 0] if state == "terminates" else timeout
    monkeypatch.setattr(search, "timeout_seconds", lambda _key: 1)
    if state == "unkillable":
        with pytest.raises(RuntimeError, match="did not exit after kill"):
            search.reap_started_daemon_process(process)
        assert process.wait.call_count == 3
        process.kill.assert_called_once()
    else:
        search.reap_started_daemon_process(process)
        assert process.wait.call_count == (0 if state == "exited" else 2)
        process.kill.assert_not_called()
    assert process.terminate.call_count == (0 if state == "exited" else 1)


@pytest.mark.parametrize("contents", [None, '[tool]\nname="fixture"\n', "[broken"])
def test_codex_configuration_is_parsed_without_modification(tmp_path, contents):
    """Inputs: missing, valid or malformed TOML. Output: exact data or diagnostic; original bytes retained."""
    path = tmp_path / "config.toml"
    if contents is not None:
        path.write_text(contents)
    if contents == "[broken":
        with pytest.raises(RuntimeError, match="Could not parse Codex config"):
            search.load_codex_config(path)
    else:
        assert search.load_codex_config(path) == (
            {} if contents is None else {"tool": {"name": "fixture"}}
        )
    assert (path.read_text() if path.exists() else None) == contents


@pytest.mark.parametrize("include_search", [False, True])
def test_native_mcp_smoke_routes_only_the_requested_probes(
    monkeypatch, capsys, include_search
):
    """Inputs: handshake-only or explicit search request. Output: correct contexts and structured results."""
    handshake, active = object(), object()
    monkeypatch.setattr(search, "resolve_mcp_handshake_context", lambda: handshake)
    resolver = Mock(return_value=active)
    stdio = Mock(
        side_effect=lambda context, include_search: {"searched": include_search}
    )
    protocol = Mock(return_value={"compatible": True})
    monkeypatch.setattr(search, "resolve_active_index_context", resolver)
    monkeypatch.setattr(search, "run_mcp_stdio_smoke", stdio)
    monkeypatch.setattr(search, "run_mcp_jsonrpc_smoke", protocol)
    search.command_mcp_smoke(SimpleNamespace(include_search=include_search))
    output = json.loads(capsys.readouterr().out)
    assert output["stdio_probe"] == {"searched": False}
    assert output["jsonrpc_protocol_probes"] == {"compatible": True}
    protocol.assert_called_once_with(handshake)
    assert stdio.call_args_list[0].args == (handshake,)
    assert stdio.call_args_list[0].kwargs == {"include_search": False}
    assert resolver.call_count == int(include_search)
    if include_search:
        assert output["stdio_search_probe"] == {"searched": True}
        assert stdio.call_args_list[1].args == (active,)
        assert stdio.call_args_list[1].kwargs == {"include_search": True}
    else:
        assert len(stdio.call_args_list) == 1 and "stdio_search_probe" not in output


@pytest.mark.parametrize("failure", [False, True])
def test_cli_operational_failure_is_nonzero_and_never_success(
    monkeypatch, capsys, failure
):
    """Inputs: command completion or operational failure. Output: exact exit status and stderr diagnostic."""
    operation = Mock(
        side_effect=RuntimeError("fixture operation failed") if failure else None
    )
    args = SimpleNamespace(func=operation)
    monkeypatch.setattr(
        search, "build_parser", lambda: SimpleNamespace(parse_args=lambda: args)
    )
    assert search.main() == int(failure)
    operation.assert_called_once_with(args)
    output = capsys.readouterr()
    assert not output.out
    assert output.err == ("ERROR: fixture operation failed\n" if failure else "")


@pytest.mark.parametrize("manage_daemon", [False, True])
def test_existing_runtime_executes_with_exact_context_and_daemon_ownership(
    tmp_path, monkeypatch, manage_daemon
):
    """Inputs: an existing launcher and private working directory. Output: actual child receives unchanged arguments/environment."""
    context = SimpleNamespace(ccc_bin=Path(sys.executable), mirror_repo=tmp_path)
    require = Mock()
    monkeypatch.setattr(search, "require_existing_search_artifacts", require)
    monkeypatch.setattr(
        search,
        "ccc_supervised_env",
        lambda _context: os.environ | {"FIXTURE_CONTEXT": "unchanged"},
    )
    events = []

    @contextmanager
    def managed(candidate):
        """Inputs: selected context. Output: track owned daemon lifetime around the native child."""
        assert candidate is context
        events.append("start")
        try:
            yield
        finally:
            events.append("stop")

    monkeypatch.setattr(search, "daemon_session", managed)
    child = "import json,os,sys;print(json.dumps([os.getcwd(),os.environ['FIXTURE_CONTEXT'],sys.argv[1:]]))"
    result = search.run_ccc_existing(
        context,
        ["-c", child, "query with spaces", "--limit", "3"],
        timeout=10,
        manage_daemon=manage_daemon,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == [
        str(tmp_path),
        "unchanged",
        ["query with spaces", "--limit", "3"],
    ]
    require.assert_called_once_with(context)
    assert events == (["start", "stop"] if manage_daemon else [])


@pytest.mark.parametrize("candidate_exists", [False, True])
def test_focused_search_never_scans_outside_selected_candidates(
    tmp_path, candidate_exists
):
    """Inputs: selected/missing path plus unrelated match. Output: only selected live source searched."""
    (tmp_path / "unrelated.py").write_text("sensitive matching phrase\n")
    if candidate_exists:
        (tmp_path / "selected.py").write_text("matching phrase\n")
    executable = shutil.which("rg")
    assert executable, "The documented navigation workflow requires ripgrep"
    case = search.BenchmarkCase(
        "fixture", "matching phrase", "matching", ("selected.py",)
    )
    result, elapsed, hits = search.run_focused_rg(
        SimpleNamespace(repo_root=tmp_path),
        executable,
        case,
        ["selected.py", "missing.py"],
    )
    assert elapsed >= 0
    assert hits == (["selected.py"] if candidate_exists else [])
    assert result.returncode == (0 if candidate_exists else 1)
    assert "unrelated" not in result.stdout and "sensitive" not in result.stdout


@pytest.mark.parametrize("maximum,allowed", [(31, False), (32, True), (33, True)])
def test_artifact_budget_preserves_over_budget_cache(
    tmp_path, monkeypatch, maximum, allowed
):
    """Inputs: actual cache bytes at the configured boundary. Output: refusal never deletes or truncates artifacts."""
    artifact = tmp_path / "retained.bin"
    artifact.write_bytes(b"x" * 32)
    monkeypatch.setenv(search.DISK_BYTES_ENV_PREFIX + "MIN_FREE_BYTES", "1")
    monkeypatch.setenv(
        search.DISK_BYTES_ENV_PREFIX + "MAX_ARTIFACT_BYTES", str(maximum)
    )
    context = SimpleNamespace(artifact_root=tmp_path)
    if allowed:
        search.require_disk_budget(context, "index")
    else:
        with pytest.raises(RuntimeError, match="above the configured"):
            search.require_disk_budget(context, "index")
    assert artifact.read_bytes() == b"x" * 32


@pytest.mark.parametrize("with_input", [False, True])
def test_native_subprocess_start_failure_has_a_useful_diagnostic(tmp_path, with_input):
    """Inputs: a missing executable. Output: operational failure rather than apparent empty success."""
    operation = search.run_command_with_input if with_input else search.run_command
    kwargs = {"input_text": "fixture input"} if with_input else {}
    with pytest.raises(RuntimeError, match="Could not execute command"):
        operation(
            [str(tmp_path / "missing-command")], cwd=tmp_path, timeout=1, **kwargs
        )


def test_checked_child_failure_preserves_status_and_diagnostic(tmp_path):
    """Inputs: real nonzero child. Output: nonzero status and both output streams remain observable."""
    with pytest.raises(RuntimeError) as caught:
        search.checked_command(
            [
                sys.executable,
                "-c",
                "import sys;print('out-fixture');print('err-fixture',file=sys.stderr);sys.exit(7)",
            ],
            cwd=tmp_path,
            timeout=10,
        )
    assert (
        "7" in str(caught.value)
        and "out-fixture" in str(caught.value)
        and "err-fixture" in str(caught.value)
    )


def test_missing_required_executable_does_not_fall_back_to_another_tool(monkeypatch):
    """Inputs: no resolved native executable. Output: explicit failure with the required tool name."""
    monkeypatch.setattr(search.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="Required command.*fixture-tool"):
        search.resolve_required_executable("fixture-tool")


def test_unknown_timeout_is_not_replaced_with_an_unbounded_default():
    """Inputs: invalid operation name. Output: fail before any child process."""
    with pytest.raises(RuntimeError, match="Unknown CocoIndex timeout"):
        search.timeout_seconds("not-an-operation")


def test_artifact_override_and_absent_cache_do_not_create_paths(tmp_path, monkeypatch):
    """Inputs: explicit external path that does not exist. Output: resolved location, zero bytes and no writes."""
    cache = tmp_path / "external" / "cache"
    monkeypatch.setenv(search.ARTIFACT_ROOT_ENV, str(cache))
    assert search.default_artifact_root() == cache
    assert search.artifact_usage_bytes(cache) == 0
    assert not cache.exists()


@pytest.mark.parametrize("missing", ["database", "launcher", "mirror", "manifest"])
def test_existing_search_requires_every_artifact_without_repair(
    tmp_path, monkeypatch, missing
):
    """Inputs: incomplete pre-existing state. Output: explicit indexing requirement; nothing silently repaired."""
    context = SimpleNamespace(
        ccc_bin=tmp_path / "ccc",
        mirror_repo=tmp_path / "mirror",
        db_dir=tmp_path / "db",
    )
    if missing != "launcher":
        context.ccc_bin.write_text("preserved launcher")
    if missing != "mirror":
        context.mirror_repo.mkdir()
    context.db_dir.mkdir()
    if missing != "database":
        search.target_sqlite_db(context).write_bytes(b"preserved database")
    before = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(
        search, "existing_mirror_ready", lambda _context: missing != "manifest"
    )
    with pytest.raises(search.IndexRequiredError):
        search.require_existing_search_artifacts(context)
    after = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert context.ccc_bin.exists() == (missing != "launcher")
    assert context.mirror_repo.exists() == (missing != "mirror")


@pytest.mark.parametrize("allowed", [False, True])
def test_prepare_checks_dirty_authority_before_preparing_the_runtime(
    monkeypatch, tmp_path, capsys, allowed
):
    """Inputs: dirty source and explicit dirty opt-in. Output: no preparation without the corresponding authority."""
    context = SimpleNamespace(
        mirror_repo=tmp_path / "mirror", mirror_digest="fixture-digest"
    )
    events = []
    monkeypatch.setattr(search, "resolve_repo_root", lambda: tmp_path)

    def require(root, allow_dirty):
        """Inputs: requested root and flag. Output: enforce explicit dirty opt-in before mutations."""
        assert root == tmp_path and allow_dirty is allowed
        events.append("guard")
        if not allow_dirty:
            raise RuntimeError("dirty source rejected")

    monkeypatch.setattr(search, "require_clean_index_target", require)
    monkeypatch.setattr(
        search, "resolve_context", lambda **kwargs: events.append("resolve") or context
    )
    monkeypatch.setattr(
        search,
        "ensure_ready",
        lambda selected: (
            events.append("ready")
            if selected is context
            else pytest.fail("wrong context")
        ),
    )
    args = SimpleNamespace(allow_dirty_mirror=allowed)
    if allowed:
        search.command_prepare(args)
        assert json.loads(capsys.readouterr().out) == {
            "mirror_repo": str(context.mirror_repo),
            "digest": "fixture-digest",
        }
        assert events == ["guard", "resolve", "ready"]
    else:
        with pytest.raises(RuntimeError, match="dirty source rejected"):
            search.command_prepare(args)
        assert events == ["guard"] and not capsys.readouterr().out


@pytest.fixture
def lifecycle_context(tmp_path, monkeypatch):
    """Inputs: private filesystem. Output: isolated source, mirror and runtime paths."""
    source = tmp_path / "source"
    source.mkdir()
    artifacts = tmp_path / "artifacts"
    digest = "a" * 32
    context = search.CocoIndexContext(
        source, artifacts, artifacts / "mirrors" / digest / "repo", digest
    )
    monkeypatch.setattr(search, "require_disk_budget", lambda *_args: None)
    return context


@pytest.mark.parametrize("state", ["invalid", "incomplete", "symlink", "file"])
def test_install_preserves_existing_unusable_runtime(
    lifecycle_context, monkeypatch, tmp_path, state
):
    """Inputs: pre-existing invalid runtime. Output: refusal without deletion or reinstall."""
    context = lifecycle_context
    context.venv_dir.parent.mkdir(parents=True)
    if state == "file":
        context.venv_dir.write_text("preserved evidence")
        sentinel = context.venv_dir
    else:
        root = tmp_path / "outside" if state == "symlink" else context.venv_dir
        (root / "bin").mkdir(parents=True)
        sentinel = root / "evidence.txt"
        sentinel.write_text("preserved evidence")
        if state == "symlink":
            context.venv_dir.symlink_to(root, target_is_directory=True)
        if state != "incomplete":
            (root / "bin" / "ccc").write_text("unusable launcher")
    verify = Mock(side_effect=RuntimeError("invalid runtime"))
    create = Mock(side_effect=AssertionError("must not recreate an existing runtime"))
    command = Mock(side_effect=AssertionError("must not install into existing state"))
    monkeypatch.setattr(search, "verify_install", verify)
    monkeypatch.setattr(search.venv, "EnvBuilder", create)
    monkeypatch.setattr(search, "checked_command", command)

    with pytest.raises(RuntimeError, match="Existing CocoIndex runtime.*preserved"):
        search.ensure_installed(context)

    assert sentinel.read_text() == "preserved evidence"
    assert context.venv_dir.is_symlink() == (state == "symlink")
    create.assert_not_called()
    command.assert_not_called()


def test_install_reuses_verified_runtime(lifecycle_context, monkeypatch):
    """Inputs: existing verified runtime. Output: one verification and no installation."""
    context = lifecycle_context
    context.ccc_bin.parent.mkdir(parents=True)
    context.ccc_bin.write_text("existing launcher")
    verify = Mock()
    monkeypatch.setattr(search, "verify_install", verify)
    command = Mock(side_effect=AssertionError("verified runtime must be reused"))
    monkeypatch.setattr(search, "checked_command", command)
    search.ensure_installed(context)
    verify.assert_called_once_with(context)
    command.assert_not_called()
    assert context.ccc_bin.read_text() == "existing launcher"


@pytest.mark.parametrize("install_fails", [False, True])
def test_fresh_install_is_pinned_and_never_clears_an_existing_directory(
    lifecycle_context, monkeypatch, install_fails
):
    """Inputs: real temporary venv and a pip boundary. Output: pinned install and preserved failure."""
    context = lifecycle_context
    original_builder = venv.EnvBuilder
    builders = []

    def builder(**kwargs):
        """Inputs: installer settings. Output: real offline venv without pip downloads."""
        builders.append(kwargs)
        return original_builder(with_pip=False)

    def command(args, **kwargs):
        """Inputs: pip invocation. Output: validate pin, isolation, working directory and failure."""
        assert args == [
            str(context.venv_dir / "bin" / "python"),
            "-m",
            "pip",
            "install",
            search.PACKAGE_REQUIREMENT,
        ]
        assert kwargs["cwd"] == context.repo_root
        assert kwargs["env"]["PIP_CACHE_DIR"] == str(context.pip_cache)
        assert kwargs["timeout"] == search.timeout_seconds("install")
        assert context.pip_cache.is_dir()
        if install_fails:
            raise RuntimeError("fixture installation failed")
        context.ccc_bin.write_text("installed launcher")
        return subprocess.CompletedProcess(args, 0, "", "")

    verify = Mock()
    monkeypatch.setattr(search.venv, "EnvBuilder", builder)
    monkeypatch.setattr(search, "checked_command", command)
    monkeypatch.setattr(search, "verify_install", verify)
    if install_fails:
        with pytest.raises(RuntimeError, match="fixture installation failed"):
            search.ensure_installed(context)
        assert (context.venv_dir / "pyvenv.cfg").is_file()
        with pytest.raises(RuntimeError, match="preserved"):
            search.ensure_installed(context)
        verify.assert_not_called()
    else:
        search.ensure_installed(context)
        verify.assert_called_once_with(context)
    assert builders == [{"with_pip": True}]


@pytest.mark.parametrize("raw", ["invalid", "0", "-1"])
def test_disk_byte_limits_reject_invalid_overrides(monkeypatch, raw):
    """Inputs: invalid configured byte counts. Output: explicit refusal, never unbounded use."""
    monkeypatch.setenv(search.DISK_BYTES_ENV_PREFIX + "MIN_FREE_BYTES", raw)
    with pytest.raises(RuntimeError, match="positive integer byte count"):
        search.env_bytes("MIN_FREE_BYTES", 100)


def test_disk_byte_limits_honor_exact_positive_override(monkeypatch):
    """Inputs: configured byte count. Output: no rounding or unit conversion."""
    monkeypatch.setenv(search.DISK_BYTES_ENV_PREFIX + "MIN_FREE_BYTES", "12345")
    assert search.env_bytes("MIN_FREE_BYTES", 100) == 12345


def test_artifact_usage_does_not_follow_external_symlinks(tmp_path, monkeypatch):
    """Inputs: nested bytes, symlinks and a disappearing file. Output: owned-byte count only."""
    root = tmp_path / "artifacts"
    (root / "nested").mkdir(parents=True)
    (root / "nested" / "data").write_bytes(b"owned")
    vanished = root / "vanished"
    vanished.write_bytes(b"gone")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "large").write_bytes(b"x" * 8192)
    (root / "directory-link").symlink_to(outside, target_is_directory=True)
    link = root / "file-link"
    link.symlink_to(outside / "large")
    expected = 5 + link.lstat().st_size
    original_stat = Path.stat

    def stat(path, *args, **kwargs):
        """Inputs: stat target. Output: simulate disappearance at the filesystem boundary."""
        if path == vanished:
            raise FileNotFoundError(errno.ENOENT, "disappeared", path)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    assert search.artifact_usage_bytes(root) == expected
    assert (outside / "large").stat().st_size == 8192


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("schema", -1, "schema"),
        ("package", "different-provider", "package is stale"),
        ("source_repo", "different-root", "does not match"),
        ("mirror_digest", "wrong", "invalid digest"),
    ],
)
def test_active_index_rejects_wrong_identity(
    lifecycle_context, monkeypatch, field, value, error
):
    """Inputs: altered metadata. Output: no wrong-root, wrong-package or malformed index reuse."""
    context = lifecycle_context
    search.write_active_index_metadata(context)
    path = search.active_index_path(context.artifact_root, context.repo_root)
    payload = json.loads(path.read_text())
    payload[field] = value
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(search, "resolve_repo_root", lambda: context.repo_root)
    monkeypatch.setattr(search, "default_artifact_root", lambda: context.artifact_root)
    with pytest.raises(RuntimeError, match=error):
        search.resolve_active_index_context()
    assert json.loads(path.read_text()) == payload


@pytest.mark.parametrize("payload", ["{invalid", "[]", None])
def test_active_index_requires_readable_object(lifecycle_context, monkeypatch, payload):
    """Inputs: missing or invalid metadata. Output: explicit failure without implicit indexing."""
    context = lifecycle_context
    path = search.active_index_path(context.artifact_root, context.repo_root)
    path.parent.mkdir(parents=True)
    if payload is not None:
        path.write_text(payload)
    monkeypatch.setattr(search, "resolve_repo_root", lambda: context.repo_root)
    monkeypatch.setattr(search, "default_artifact_root", lambda: context.artifact_root)
    with pytest.raises(RuntimeError, match="invalid JSON|must be an object|index"):
        search.resolve_active_index_context()
    assert not context.mirror_repo.exists()


@pytest.mark.parametrize("global_exists", [False, True])
def test_project_initialization_is_mirror_scoped_and_idempotent(
    lifecycle_context, monkeypatch, global_exists
):
    """Inputs: fresh or shared settings. Output: initialize once in the mirror, never source."""
    context = lifecycle_context
    context.mirror_repo.mkdir(parents=True)
    context.settings_dir.mkdir(parents=True)
    global_settings = context.settings_dir / "global_settings.yml"
    project_settings = context.mirror_repo / ".cocoindex_code" / "settings.yml"
    if global_exists:
        global_settings.write_text("shared settings")
    calls = []

    def initialize(command, **kwargs):
        """Inputs: provider invocation. Output: create isolated provider settings once."""
        calls.append(command)
        assert command == [str(context.ccc_bin), "init", "--force"]
        assert kwargs["cwd"] == context.mirror_repo
        assert kwargs["env"]["COCOINDEX_CODE_DIR"] == str(context.settings_dir)
        project_settings.parent.mkdir(parents=True)
        project_settings.write_text("project settings")
        if not global_exists:
            global_settings.write_text("new settings")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(search, "checked_command", initialize)
    search.ensure_project_initialized(context)
    search.ensure_project_initialized(context)
    assert len(calls) == 1
    assert not (context.repo_root / ".cocoindex_code").exists()
    assert global_settings.read_text() == (
        "shared settings" if global_exists else "new settings"
    )


@pytest.mark.parametrize(
    "payload",
    [[], {"cuda": True}, {"cuda": 1, "mps": False}, {"cuda": False, "mps": "yes"}],
)
def test_device_probe_rejects_malformed_capabilities(
    lifecycle_context, monkeypatch, payload
):
    """Inputs: invalid provider JSON. Output: fail closed instead of selecting an unsupported GPU."""
    monkeypatch.setattr(
        search,
        "checked_command",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(payload)),
    )
    with pytest.raises(RuntimeError, match="invalid payload|non-boolean"):
        search.probe_embedding_devices(lifecycle_context)


def test_device_probe_accepts_only_boolean_capabilities(lifecycle_context, monkeypatch):
    """Inputs: valid provider output. Output: exact accelerator availability."""
    monkeypatch.setattr(
        search,
        "checked_command",
        lambda *_args, **_kwargs: SimpleNamespace(stdout='{"cuda":false,"mps":true}'),
    )
    assert search.probe_embedding_devices(lifecycle_context) == {
        "cuda": False,
        "mps": True,
    }


@pytest.mark.parametrize("reason", ["success", "exit", "timeout"])
@pytest.mark.parametrize("log", ["", "diagnostic detail"])
def test_daemon_wait_is_bounded_and_reports_failure(
    lifecycle_context, monkeypatch, reason, log
):
    """Inputs: handshake, process and clock states. Output: bounded wait with retained diagnostic."""
    clock = [0.0]
    handshake = Mock(
        side_effect=[False, True] if reason == "success" else None, return_value=False
    )
    process = SimpleNamespace(poll=lambda: 2 if reason == "exit" else None)
    monkeypatch.setattr(search, "timeout_seconds", lambda _name: 1)
    monkeypatch.setattr(search.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        search.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    monkeypatch.setattr(search, "daemon_handshake_succeeds", handshake)
    monkeypatch.setattr(search, "read_daemon_log", lambda _context: log)
    if reason == "success":
        search.wait_for_daemon_handshake(lifecycle_context, process)
        assert handshake.call_count == 2
    else:
        message = "exited before" if reason == "exit" else "in time"
        with pytest.raises(RuntimeError, match=message) as error:
            search.wait_for_daemon_handshake(lifecycle_context, process)
        assert ("Daemon log:" in str(error.value)) == bool(log)
        assert clock[0] <= 1.2


def test_daemon_start_failure_closes_log(lifecycle_context, monkeypatch):
    """Inputs: process creation failure. Output: bounded error and closed log descriptor."""
    context = lifecycle_context
    outputs = []

    def fail_start(*_args, **kwargs):
        """Inputs: native Popen settings. Output: retained log handle and injected exec failure."""
        outputs.append(kwargs["stdout"])
        assert kwargs["stdout"] is kwargs["stderr"]
        assert kwargs["start_new_session"] is True
        raise OSError(errno.ENOENT, "fixture executable missing")

    monkeypatch.setattr(search.subprocess, "Popen", fail_start)
    with pytest.raises(RuntimeError, match="Could not start"):
        search.start_daemon_process(context)
    assert len(outputs) == 1 and outputs[0].closed
    assert search.daemon_log_path(context).is_file()
