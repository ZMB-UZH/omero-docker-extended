"""Failure and degenerate-input contracts for dependency, documentation and recovery tools."""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import extract_dockerfile_pip_deps as dependencies
from tools import lint_docs_structure as docs
from tools import restore_prebuilt_carrier as recovery
from tools import write_branding_logo_fallback as branding
from tools import git_push_with_pat as human_git
from tools import regression_guard
from startup import repo_root_sync_helper as repository_paths


def test_repository_dispatch_rejects_an_unimplemented_parser_command(
    monkeypatch, capsys
):
    """Inputs: parser extended without a corresponding handler. Output: explicit error, no repository operations."""
    parser = repository_paths._build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if hasattr(action, "choices") and isinstance(action.choices, dict)
    )
    subparsers.add_parser("unimplemented")
    monkeypatch.setattr(repository_paths, "_build_parser", lambda: parser)
    assert repository_paths.main(["unimplemented"]) == 2
    assert "Unsupported command: unimplemented" in capsys.readouterr().err


def test_regression_dispatch_rejects_an_unimplemented_parser_command(
    monkeypatch, tmp_path
):
    """Inputs: an unknown parsed command. Output: explicit refusal without running a different gate."""
    monkeypatch.setattr(
        regression_guard,
        "parse_args",
        lambda _argv: SimpleNamespace(command="unimplemented", repo_root=tmp_path),
    )
    with pytest.raises(SystemExit, match="Unknown command: unimplemented"):
        regression_guard.main([])


def test_dependency_extraction_ignores_empty_arguments_and_nonpackage_tokens(tmp_path):
    """Inputs: a build command with options and separators. Output: only actual package requirements, without invoking a package manager."""
    path = tmp_path / "Dockerfile"
    path.write_text(
        "RUN pip install --no-cache-dir '' ./local.whl @invalid ${OPTIONAL_PACKAGE} fixture-pkg==1.2.3\n",
        encoding="utf-8",
    )
    assert dependencies.extract(path) == ["fixture-pkg==1.2.3"]


def test_documentation_index_reports_each_missing_contract_link(tmp_path):
    """Inputs: a partial docs index. Output: precise missing-link failures, not a false clean result."""
    index = tmp_path / "docs" / "index.md"
    index.parent.mkdir()
    retained, *missing = docs.REQUIRED_INDEX_LINKS
    index.write_text(retained + "\n", encoding="utf-8")
    errors = docs.validate_index_links(tmp_path)
    assert len(errors) == len(missing)
    assert all(token in str(error) for token, error in zip(missing, errors))


def test_degenerate_logo_segment_has_exact_point_distance():
    """Inputs: a zero-length line segment. Output: Euclidean point distance without division by zero."""
    assert branding._distance_to_segment(3, 4, 0, 0, 0, 0) == 5
    assert branding._distance_to_segment(2, -3, 2, -3, 2, -3) == 0


@pytest.mark.parametrize("status", [0, 7])
def test_carrier_checked_process_preserves_native_failure_status(tmp_path, status):
    """Inputs: a real isolated child process. Output: completed side effect and original failure status."""
    target = tmp_path / "process-evidence"
    command = [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('complete'); sys.exit(int(sys.argv[2]))",
        str(target),
        str(status),
    ]
    if status:
        with pytest.raises(subprocess.CalledProcessError) as caught:
            recovery.run(command)
        assert caught.value.returncode == status
    else:
        assert recovery.run(command) is None
    assert target.read_text() == "complete"


def test_carrier_metadata_read_uses_exact_repository_and_endpoint(monkeypatch):
    """Inputs: repository and endpoint. Output: structured metadata, with no network access in this contract test."""
    payload = {"tag_name": "1.2.3-main.1", "draft": False}
    output = Mock(return_value=json.dumps(payload))
    monkeypatch.setattr(recovery, "output", output)
    assert recovery.github("example/fixture", "releases/tags/1.2.3-main.1") == payload
    output.assert_called_once_with(
        ["gh", "api", "repos/example/fixture/releases/tags/1.2.3-main.1"]
    )


def test_carrier_authorized_cli_dispatches_the_exact_requested_release(monkeypatch):
    """Inputs: both exact metadata approvals. Output: one matching dispatch; no registry mutation in the test."""
    restore = Mock()
    monkeypatch.setattr(recovery, "restore", restore)
    assert (
        recovery.main(
            [
                "--release-version",
                "1.2.3-main.1",
                "--docker-repository",
                "example/fixture",
                "--authorize-replace-manifest",
                "--authorize-replace-digest",
            ]
        )
        == 0
    )
    restore.assert_called_once_with("1.2.3-main.1", "example/fixture")


@pytest.mark.parametrize("value", ["reference\tvalue", "reference\nvalue"])
def test_human_git_arguments_reject_control_characters(value):
    """Inputs: control bytes in a Git argument. Output: rejection before any process or credential access."""
    with pytest.raises(SystemExit, match="control characters"):
        human_git._validate_git_argument("remote", value)


@pytest.mark.parametrize("status,output", [(0, "\n"), (128, "unresolved")])
def test_human_git_missing_remote_fails_without_authentication(status, output):
    """Inputs: failed or empty push/fetch URL lookups. Output: bounded lookup with no push attempt."""
    runner = Mock(return_value=subprocess.CompletedProcess([], status, output))
    with pytest.raises(SystemExit, match="Could not resolve"):
        human_git._resolve_remote_url("git", "fixture", env={}, runner=runner)
    assert [call.args[0] for call in runner.call_args_list] == [
        ["git", "remote", "get-url", "--push", "fixture"],
        ["git", "remote", "get-url", "fixture"],
    ]


def test_human_git_rejects_embedded_credentials_without_disclosing_them():
    """Inputs: a synthetic credential-bearing remote. Output: rejection with no credential in the error."""
    credential = secrets.token_hex(16)
    with pytest.raises(SystemExit, match="must not embed credentials") as caught:
        human_git._validate_github_https_remote(
            f"https://fixture:{credential}@github.com/example/project.git"
        )
    assert credential not in str(caught.value)


@pytest.mark.parametrize(
    "value,message",
    [
        ("refs/heads/main:\t12", "control characters"),
        ("refs/heads/main:-12", "option-like"),
    ],
)
def test_human_git_lease_rejects_option_and_control_bytes(value, message):
    """Inputs: unsafe explicit lease. Output: no command construction from malformed input."""
    with pytest.raises(SystemExit, match=message):
        human_git._validate_force_with_lease(value)


@pytest.mark.parametrize("interactive", [False, True])
def test_human_git_empty_credentials_fail_before_any_push(monkeypatch, interactive):
    """Inputs: no configured credential and an optional empty prompt. Output: explicit failure and no noninteractive prompt."""
    monkeypatch.setattr(human_git.sys.stdin, "isatty", lambda: interactive)
    reader = Mock(return_value=" \n")
    with pytest.raises(SystemExit, match="FIXTURE_GIT_AUTH is required"):
        human_git._read_token({}, "FIXTURE_GIT_AUTH", reader)
    assert reader.call_count == int(interactive)


def test_human_git_missing_executable_never_reads_a_credential(monkeypatch):
    """Inputs: Git absent. Output: actionable failure before token or network access."""
    monkeypatch.setattr(human_git.shutil, "which", lambda _name: None)
    reader, runner = Mock(), Mock()
    with pytest.raises(SystemExit, match="git is required"):
        human_git.run_push(
            human_git.parse_args(["fixture", "main"]),
            env={},
            token_reader=reader,
            runner=runner,
        )
    reader.assert_not_called()
    runner.assert_not_called()


def test_repository_seed_paths_do_not_invent_shared_directories():
    """Inputs: a user-first template. Output: no shared prefix to create or re-own."""
    assert (
        repository_paths.configured_seed_paths("%user%/%year%", "", "false", "") == []
    )


def test_repository_group_expansion_rejects_unresolved_percent_syntax():
    """Inputs: a group whose name injects template syntax. Output: explicit rejection, not an ambiguous storage path."""
    with pytest.raises(ValueError, match="left unresolved token syntax"):
        repository_paths.configured_seed_paths("%group%/%user%", "lab%one", "false", "")


def test_regression_catalog_markdown_is_the_same_complete_rule_catalog(capsys):
    """Inputs: public Markdown catalog CLI. Output: the complete canonical catalog, without scanning or mutations."""
    assert regression_guard.main(["catalog", "--format", "markdown"]) == 0
    assert capsys.readouterr().out == regression_guard.render_markdown() + "\n"


def test_carrier_rejects_malformed_repository_before_registry_access(monkeypatch):
    """Inputs: invalid hosted repository identity. Output: failure before any registry or release operation."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/fixture/extra")
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    remote = Mock(side_effect=AssertionError("Invalid repository reached registry"))
    monkeypatch.setattr(recovery, "require_missing_tag", remote)
    with pytest.raises(ValueError, match="Invalid GitHub repository"):
        recovery.restore("1.2.3-main.1", "example/fixture")
    remote.assert_not_called()
