"""Contract tests for the host-side CocoIndex Code agent workflow."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest import mock

import pytest

from tools import cocoindex_agent_search


def test_package_pin_and_hashes_are_exact() -> None:
    assert cocoindex_agent_search.PACKAGE_REQUIREMENT == (
        "cocoindex-code[full]==0.2.31"
    )
    assert "latest" not in cocoindex_agent_search.PACKAGE_REQUIREMENT


def test_benchmark_doc_records_package_hash_evidence() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    text = (
        repo_root / "docs/reference/cocoindex-code-agent-benchmark-2026-04-27.md"
    ).read_text(encoding="utf-8")

    assert "Wheel SHA256:" in text
    assert "Source SHA256:" in text


def test_default_artifact_root_uses_xdg_not_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(cocoindex_agent_search.ARTIFACT_ROOT_ENV, raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))

    root = cocoindex_agent_search.default_artifact_root()

    assert root == (tmp_path / "xdg-data" / "agent-cocoindex-code").resolve()


def test_timeout_env_override_is_positive_integer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_COCOINDEX_TIMEOUT_INDEX", "28800")

    assert cocoindex_agent_search.timeout_seconds("index") == 28800


@pytest.mark.parametrize("raw_value", ("0", "-1", "slow"))
def test_timeout_env_override_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch, raw_value: str
) -> None:
    monkeypatch.setenv("AGENT_COCOINDEX_TIMEOUT_SEARCH", raw_value)

    with pytest.raises(RuntimeError, match="positive integer"):
        cocoindex_agent_search.timeout_seconds("search")


def test_discover_git_root_candidate_walks_from_nested_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "src" / "package"
    nested.mkdir(parents=True)
    (repo / ".git").mkdir()

    assert cocoindex_agent_search.discover_git_root_candidate(nested) == repo.resolve()


def test_resolve_repo_root_uses_command_scoped_safe_directory_from_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = (tmp_path / "repo").resolve()
    nested = repo / "docs"
    nested.mkdir(parents=True)
    (repo / ".git").mkdir()

    def fake_checked_command(
        args: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert env is None
        assert timeout is None
        assert cwd == nested
        assert args[:3] == [
            "/usr/bin/git",
            "-c",
            f"safe.directory={repo}",
        ]
        assert args[3:] == ["rev-parse", "--show-toplevel"]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{repo}\n")

    monkeypatch.chdir(nested)
    monkeypatch.delenv(cocoindex_agent_search.REPO_ROOT_ENV, raising=False)
    monkeypatch.setattr(
        cocoindex_agent_search,
        "resolve_required_executable",
        mock.Mock(return_value="/usr/bin/git"),
    )
    monkeypatch.setattr(
        cocoindex_agent_search,
        "checked_command",
        fake_checked_command,
    )

    assert cocoindex_agent_search.resolve_repo_root() == repo


def test_resolve_repo_root_rejects_env_override_that_is_not_repo_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = (tmp_path / "repo").resolve()
    nested = repo / "docs"
    nested.mkdir(parents=True)
    (repo / ".git").mkdir()

    monkeypatch.setenv(cocoindex_agent_search.REPO_ROOT_ENV, str(nested))
    monkeypatch.setattr(
        cocoindex_agent_search,
        "resolve_required_executable",
        mock.Mock(return_value="/usr/bin/git"),
    )
    monkeypatch.setattr(
        cocoindex_agent_search,
        "checked_command",
        mock.Mock(
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=f"{repo}\n"
            )
        ),
    )

    with pytest.raises(RuntimeError, match="must point at the Git repository root"):
        cocoindex_agent_search.resolve_repo_root()


def test_tracked_files_uses_command_scoped_safe_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = (tmp_path / "repo").resolve()
    repo.mkdir()

    def fake_checked_command(
        args: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert env is None
        assert timeout is None
        assert cwd == repo
        assert args[:3] == [
            "/usr/bin/git",
            "-c",
            f"safe.directory={repo}",
        ]
        assert args[3:] == [
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ]
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="tools/cocoindex_agent_search.py\0",
        )

    monkeypatch.setattr(
        cocoindex_agent_search,
        "resolve_required_executable",
        mock.Mock(return_value="/usr/bin/git"),
    )
    monkeypatch.setattr(
        cocoindex_agent_search,
        "checked_command",
        fake_checked_command,
    )

    assert cocoindex_agent_search.tracked_files(repo) == [
        PurePosixPath("tools/cocoindex_agent_search.py")
    ]


@pytest.mark.parametrize(
    "raw_path",
    ("", "/abs", "../escape", "dir/../escape", "dir//file", "dir\\file", "bad\nfile"),
)
def test_validate_repo_relative_path_rejects_unsafe_paths(raw_path: str) -> None:
    with pytest.raises(RuntimeError):
        cocoindex_agent_search.validate_repo_relative_path(raw_path)


def test_validate_repo_relative_path_accepts_clean_posix_paths() -> None:
    assert cocoindex_agent_search.validate_repo_relative_path(
        "tools/cocoindex_agent_search.py"
    ) == PurePosixPath("tools/cocoindex_agent_search.py")


@pytest.mark.parametrize(
    "raw_path",
    (".env", "local.env", "env/production.env", ".cocoindex_code/settings.yml"),
)
def test_is_denied_mirror_path_blocks_runtime_artifacts(raw_path: str) -> None:
    assert cocoindex_agent_search.is_denied_mirror_path(PurePosixPath(raw_path))


def test_is_denied_mirror_path_allows_example_contracts() -> None:
    assert not cocoindex_agent_search.is_denied_mirror_path(
        PurePosixPath("env/service_example.env")
    )
    assert not cocoindex_agent_search.is_denied_mirror_path(
        PurePosixPath("env/service.example.env")
    )


def test_load_benchmark_cases_validates_required_schema(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        '[{"name": "case", "query": "semantic query", "rg": "pattern", '
        '"expected": ["path.py"]}]\n',
        encoding="utf-8",
    )

    assert cocoindex_agent_search.load_benchmark_cases(cases_path) == [
        cocoindex_agent_search.BenchmarkCase(
            name="case",
            query="semantic query",
            rg="pattern",
            expected=("path.py",),
        )
    ]


def test_load_benchmark_cases_rejects_missing_fields(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text('[{"name": "case"}]\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="missing fields"):
        cocoindex_agent_search.load_benchmark_cases(cases_path)


def test_file_digest_refuses_tracked_symlink(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "target.txt").write_text("payload", encoding="utf-8")
    (repo / "link.txt").symlink_to("target.txt")

    with pytest.raises(RuntimeError, match="tracked symlink"):
        cocoindex_agent_search.file_digest_and_mirror_source(
            repo.resolve(), [PurePosixPath("link.txt")]
        )


def test_file_digest_includes_worktree_content(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / "tracked.txt"
    path.write_text("first", encoding="utf-8")
    digest_one, files_one = cocoindex_agent_search.file_digest_and_mirror_source(
        repo.resolve(), [PurePosixPath("tracked.txt")]
    )
    path.write_text("second", encoding="utf-8")
    digest_two, files_two = cocoindex_agent_search.file_digest_and_mirror_source(
        repo.resolve(), [PurePosixPath("tracked.txt")]
    )

    assert digest_one != digest_two
    assert files_one["tracked.txt"] == b"first"
    assert files_two["tracked.txt"] == b"second"


def test_repo_relative_path_if_inside_validates_repo_member(tmp_path: Path) -> None:
    repo = (tmp_path / "repo").resolve()
    repo.mkdir()
    cases_path = repo / "docs" / "cases.json"
    cases_path.parent.mkdir()
    cases_path.write_text("[]", encoding="utf-8")

    assert cocoindex_agent_search.repo_relative_path_if_inside(
        repo, cases_path
    ) == PurePosixPath("docs/cases.json")
    assert (
        cocoindex_agent_search.repo_relative_path_if_inside(
            repo, tmp_path / "outside.json"
        )
        is None
    )


def test_ccc_env_maps_database_and_display_paths_outside_repo(tmp_path: Path) -> None:
    context = cocoindex_agent_search.CocoIndexContext(
        repo_root=(tmp_path / "repo").resolve(),
        artifact_root=(tmp_path / "artifacts").resolve(),
        mirror_repo=(tmp_path / "artifacts" / "mirrors" / "abc" / "repo").resolve(),
        mirror_digest="abc",
    )

    env = cocoindex_agent_search.ccc_env(context)

    assert env["COCOINDEX_CODE_DIR"] == str(context.settings_dir)
    assert env["COCOINDEX_CODE_RUNTIME_DIR"] == str(context.runtime_dir)
    assert env["COCOINDEX_CODE_DB_PATH_MAPPING"] == (
        f"{context.mirror_repo}={context.db_dir}"
    )
    assert "COCOINDEX_CODE_HOST_PATH_MAPPING" not in env


def test_verify_install_executes_console_entrypoint(tmp_path: Path) -> None:
    context = cocoindex_agent_search.CocoIndexContext(
        repo_root=tmp_path / "repo",
        artifact_root=tmp_path / "artifacts",
        mirror_repo=tmp_path / "artifacts" / "mirrors" / "abc" / "repo",
        mirror_digest="abc",
    )

    with mock.patch("tools.cocoindex_agent_search.checked_command") as mocked_checked:
        cocoindex_agent_search.verify_install(context)

    assert mocked_checked.call_args_list[-1].args[0] == [str(context.ccc_bin), "--help"]


def test_multiple_repositories_share_one_install_but_use_separate_indexes(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    repo_one = (tmp_path / "repo-one").resolve()
    repo_two = (tmp_path / "repo-two").resolve()
    context_one = cocoindex_agent_search.CocoIndexContext(
        repo_root=repo_one,
        artifact_root=artifact_root,
        mirror_repo=artifact_root / "mirrors" / "digest-one" / "repo",
        mirror_digest="digest-one",
    )
    context_two = cocoindex_agent_search.CocoIndexContext(
        repo_root=repo_two,
        artifact_root=artifact_root,
        mirror_repo=artifact_root / "mirrors" / "digest-two" / "repo",
        mirror_digest="digest-two",
    )

    assert context_one.venv_dir == context_two.venv_dir
    assert context_one.settings_dir == context_two.settings_dir
    assert context_one.runtime_dir != context_two.runtime_dir
    assert context_one.mirror_repo != context_two.mirror_repo
    assert context_one.db_dir != context_two.db_dir
    assert cocoindex_agent_search.lock_path(
        artifact_root, f"mirror-{context_one.mirror_digest}"
    ) != cocoindex_agent_search.lock_path(
        artifact_root, f"mirror-{context_two.mirror_digest}"
    )
    assert cocoindex_agent_search.lock_path(
        artifact_root, f"init-{context_one.mirror_digest}"
    ) != cocoindex_agent_search.lock_path(
        artifact_root, f"init-{context_two.mirror_digest}"
    )
    assert (
        cocoindex_agent_search.ccc_env(context_one)["COCOINDEX_CODE_DB_PATH_MAPPING"]
        != cocoindex_agent_search.ccc_env(context_two)["COCOINDEX_CODE_DB_PATH_MAPPING"]
    )


def test_mcp_config_is_workspace_agnostic_by_default(tmp_path: Path) -> None:
    context = cocoindex_agent_search.CocoIndexContext(
        repo_root=tmp_path / "repo",
        artifact_root=tmp_path / "artifacts",
        mirror_repo=tmp_path / "artifacts" / "mirrors" / "abc" / "repo",
        mirror_digest="abc",
    )

    payload = cocoindex_agent_search.mcp_config_payload(context, pin_repo=False)

    assert payload["name"] == "cocoindex-code"
    assert payload["transport"] == "stdio"
    assert payload["env"] == {
        cocoindex_agent_search.ARTIFACT_ROOT_ENV: str(context.artifact_root)
    }
    assert cocoindex_agent_search.REPO_ROOT_ENV in str(
        payload["working_directory_contract"]
    )


def test_mcp_config_can_pin_repo_for_static_clients(tmp_path: Path) -> None:
    context = cocoindex_agent_search.CocoIndexContext(
        repo_root=tmp_path / "repo",
        artifact_root=tmp_path / "artifacts",
        mirror_repo=tmp_path / "artifacts" / "mirrors" / "abc" / "repo",
        mirror_digest="abc",
    )

    payload = cocoindex_agent_search.mcp_config_payload(context, pin_repo=True)

    assert payload["env"] == {
        cocoindex_agent_search.ARTIFACT_ROOT_ENV: str(context.artifact_root),
        cocoindex_agent_search.REPO_ROOT_ENV: str(context.repo_root),
    }


def test_mcp_install_does_not_duplicate_existing_codex_server(tmp_path: Path) -> None:
    context = cocoindex_agent_search.CocoIndexContext(
        repo_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
        mirror_repo=tmp_path / "artifacts" / "mirrors" / "abc" / "repo",
        mirror_digest="abc",
    )
    completed = subprocess.CompletedProcess(
        args=["codex", "mcp", "get", "cocoindex-code"],
        returncode=0,
        stdout="configured",
        stderr="",
    )

    with (
        mock.patch(
            "tools.cocoindex_agent_search.resolve_context",
            return_value=context,
        ),
        mock.patch(
            "tools.cocoindex_agent_search.resolve_required_executable",
            return_value="/usr/bin/codex",
        ),
        mock.patch(
            "tools.cocoindex_agent_search.run_command",
            return_value=completed,
        ) as mocked_run,
        mock.patch("tools.cocoindex_agent_search.checked_command") as mocked_checked,
    ):
        cocoindex_agent_search.command_mcp_install(mock.Mock())

    mocked_run.assert_called_once()
    mocked_checked.assert_not_called()


def test_mcp_install_uses_workspace_agnostic_codex_registration(
    tmp_path: Path,
) -> None:
    context = cocoindex_agent_search.CocoIndexContext(
        repo_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
        mirror_repo=tmp_path / "artifacts" / "mirrors" / "abc" / "repo",
        mirror_digest="abc",
    )
    missing = subprocess.CompletedProcess(
        args=["codex", "mcp", "get", "cocoindex-code"],
        returncode=1,
        stdout="",
        stderr="Error: No MCP server named 'cocoindex-code' found.",
    )

    with (
        mock.patch(
            "tools.cocoindex_agent_search.resolve_context",
            return_value=context,
        ),
        mock.patch(
            "tools.cocoindex_agent_search.resolve_required_executable",
            return_value="/usr/bin/codex",
        ),
        mock.patch(
            "tools.cocoindex_agent_search.run_command",
            return_value=missing,
        ),
        mock.patch("tools.cocoindex_agent_search.checked_command") as mocked_checked,
    ):
        cocoindex_agent_search.command_mcp_install(mock.Mock())

    command = mocked_checked.call_args.args[0]
    assert (
        f"{cocoindex_agent_search.ARTIFACT_ROOT_ENV}={context.artifact_root}" in command
    )
    assert not any(
        part.startswith(f"{cocoindex_agent_search.REPO_ROOT_ENV}=") for part in command
    )


def test_repo_benchmark_cases_file_is_valid() -> None:
    cases_path = (
        Path(__file__).resolve().parents[1]
        / "docs/reference/cocoindex-code-agent-benchmark-2026-04-27-cases.json"
    )

    cases = cocoindex_agent_search.load_benchmark_cases(cases_path)

    assert len(cases) == 10
    assert all(case.expected for case in cases)


def test_mcp_command_runs_installed_cli_in_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = cocoindex_agent_search.CocoIndexContext(
        repo_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
        mirror_repo=tmp_path / "artifacts" / "mirrors" / "abc" / "repo",
        mirror_digest="abc",
    )
    app = mock.Mock(return_value=0)
    cli_module = mock.Mock(app=app)
    context.mirror_repo.mkdir(parents=True)

    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(
        cocoindex_agent_search,
        "resolve_context",
        mock.Mock(return_value=context),
    )
    monkeypatch.setattr(cocoindex_agent_search, "ensure_ready", mock.Mock())
    monkeypatch.setattr(
        cocoindex_agent_search,
        "venv_site_package_paths",
        mock.Mock(return_value=[tmp_path / "site-packages"]),
    )
    monkeypatch.setattr(
        cocoindex_agent_search.importlib,
        "import_module",
        mock.Mock(return_value=cli_module),
    )
    monkeypatch.setattr(sys, "argv", ["pytest"])

    original_sys_path = list(sys.path)
    original_cwd = Path.cwd()
    try:
        with pytest.raises(SystemExit) as exc_info:
            cocoindex_agent_search.command_mcp(mock.Mock())
        assert Path.cwd() == context.mirror_repo
    finally:
        os.chdir(original_cwd)
        sys.path[:] = original_sys_path

    assert exc_info.value.code == 0
    assert sys.argv == [str(context.ccc_bin), "mcp"]
    assert app.call_count == 1
    assert "COCOINDEX_CODE_DB_PATH_MAPPING" in dict(cocoindex_agent_search.os.environ)


def test_mcp_smoke_uses_workspace_root_and_minimal_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = cocoindex_agent_search.CocoIndexContext(
        repo_root=tmp_path / "repo",
        artifact_root=tmp_path / "artifacts",
        mirror_repo=tmp_path / "artifacts" / "mirrors" / "abc" / "repo",
        mirror_digest="abc",
    )
    captured_params: dict[str, object] = {}

    class FakeFailAfter:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *args: object) -> bool:
            return False

    class FakeServerParameters:
        def __init__(
            self,
            *,
            command: str,
            args: list[str],
            env: dict[str, str],
            cwd: str,
        ) -> None:
            captured_params.update(
                {"command": command, "args": args, "env": env, "cwd": cwd}
            )

    class FakeStdioClient:
        def __init__(self, params: FakeServerParameters) -> None:
            self.params = params

        async def __aenter__(self) -> tuple[object, object]:
            return object(), object()

        async def __aexit__(self, *args: object) -> bool:
            return False

    class FakeSession:
        def __init__(self, read_stream: object, write_stream: object) -> None:
            self.streams = (read_stream, write_stream)

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def initialize(self) -> object:
            self.initialized = True
            return SimpleNamespace(
                serverInfo=SimpleNamespace(name="fake", version="1.0")
            )

        async def list_tools(self) -> object:
            self.listed_tools = True
            return SimpleNamespace(
                tools=[SimpleNamespace(name="search"), SimpleNamespace(name="index")]
            )

    fake_anyio = mock.Mock()
    fake_anyio.fail_after = mock.Mock(return_value=FakeFailAfter())
    fake_anyio.run.side_effect = lambda function: __import__("asyncio").run(function())
    fake_mcp = mock.Mock(
        ClientSession=FakeSession,
        StdioServerParameters=FakeServerParameters,
    )
    fake_stdio = mock.Mock(stdio_client=FakeStdioClient)

    def fake_import_module(name: str) -> object:
        return {
            "anyio": fake_anyio,
            "mcp": fake_mcp,
            "mcp.client.stdio": fake_stdio,
        }[name]

    monkeypatch.setattr(
        cocoindex_agent_search,
        "venv_site_package_paths",
        mock.Mock(return_value=[tmp_path / "site-packages"]),
    )
    monkeypatch.setattr(
        cocoindex_agent_search.importlib,
        "import_module",
        fake_import_module,
    )

    original_sys_path = list(sys.path)
    try:
        assert cocoindex_agent_search.run_mcp_stdio_smoke(context) == {
            "server_name": "fake",
            "server_version": "1.0",
            "tools": ["index", "search"],
        }
    finally:
        sys.path[:] = original_sys_path
    assert captured_params["command"] == sys.executable
    assert captured_params["args"][-1] == "mcp"
    assert captured_params["env"] == {
        cocoindex_agent_search.ARTIFACT_ROOT_ENV: str(context.artifact_root)
    }
    assert captured_params["cwd"] == str(context.repo_root)


def test_cross_agent_surfaces_describe_generic_cocoindex_workflow() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tracked_surfaces = (
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        ".github/copilot-instructions.md",
        ".cursor/rules/00-omero-core.mdc",
        "README.md",
        "docs/reference/ai-agent-skills.md",
        "docs/reference/ai-agent-integrations.md",
    )

    for relative_path in tracked_surfaces:
        text = (repo_root / relative_path).read_text(encoding="utf-8")
        assert "cocoindex-code-search" in text, relative_path
        assert "MCP" in text and "cocoindex-code" in text, relative_path
        assert "semantic routing" in text, relative_path
        assert "mcp-smoke" in text, relative_path
        assert "rg" in text, relative_path
        assert "AGENT_COCOINDEX_HOME" in text, relative_path
        assert ".cocoindex_code/" in text or "outside the live checkout" in text, (
            relative_path
        )


def test_repo_has_no_stale_omero_specific_cocoindex_install_name() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    stale_name = "omero" + "-agent-cocoindex"
    completed = subprocess.run(
        [
            cocoindex_agent_search.resolve_required_executable("git"),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    checked_paths = [
        repo_root / raw_path.decode("utf-8")
        for raw_path in completed.stdout.split(b"\0")
        if raw_path
    ]

    for path in checked_paths:
        if path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".ico", ".sqlite3"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert stale_name not in text, path


def test_cli_supports_help() -> None:
    result = subprocess.run(
        [sys.executable, "tools/cocoindex_agent_search.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()
