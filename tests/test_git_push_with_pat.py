"""Regression tests for one-shot GitHub PAT Git pushes."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "git_push_with_pat.py"
SPEC = importlib.util.spec_from_file_location("git_push_with_pat", MODULE_PATH)
git_push_with_pat = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = git_push_with_pat
SPEC.loader.exec_module(git_push_with_pat)

TEST_GITHUB_CREDENTIAL = "-".join(("placeholder", "credential"))
TEST_GITHUB_REMOTE = "https://github.com/ZMB-UZH/omero-docker-extended.git"


def _is_remote_lookup(command: list[str]) -> bool:
    """Return whether the command is a git remote URL lookup.

    Inputs: `command` (list[str]). Output: `bool`.
    """
    return command[:3] == ["/usr/bin/git", "remote", "get-url"]


def _remote_lookup_result(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Return a successful fake remote lookup result.

    Inputs: `command` (list[str]). Output: `CompletedProcess`.
    """
    return subprocess.CompletedProcess(command, 0, stdout=f"{TEST_GITHUB_REMOTE}\n")


def test_pat_push_uses_one_shot_askpass_without_leaking_token(monkeypatch) -> None:
    """Check that PAT push uses one shot askpass without leaking token keeps sensitive data out of output.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in PAT push uses one shot askpass without leaking token.
    """
    monkeypatch.setattr(git_push_with_pat.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(git_push_with_pat.sys.stdin, "isatty", lambda: True)
    captured: dict[str, object] = {}

    def fake_run(command, *, env, check, **kwargs):
        """Simulate run so the surrounding test controls that dependency.

        Inputs: `command`, `env` environment mapping, `check`. Output:
        `CompletedProcess` result.
        """
        if _is_remote_lookup(command):
            return _remote_lookup_result(command)
        captured["command"] = command
        captured["env"] = env
        captured["check"] = check
        askpass_path = Path(env["GIT_ASKPASS"])
        socket_path = Path(env["GIT_PAT_SOCKET"])
        assert askpass_path.exists()
        assert socket_path.exists()
        username = subprocess.check_output(
            [str(askpass_path), "Username for https://github.com:"],
            env=env,
            text=True,
        )
        password = subprocess.check_output(
            [str(askpass_path), "Password for https://github.com:"],
            env=env,
            text=True,
        )
        assert username == "x-access-token\n"
        assert password == f"{TEST_GITHUB_CREDENTIAL}\n"
        return subprocess.CompletedProcess(command, 0)

    args = git_push_with_pat.parse_args(["origin", "main"])
    result = git_push_with_pat.run_push(
        args,
        env={"PATH": "/usr/bin"},
        token_reader=lambda _prompt: TEST_GITHUB_CREDENTIAL,
        runner=fake_run,
    )

    assert result == 0
    command = captured["command"]
    assert command == [
        "/usr/bin/git",
        "-c",
        "credential.helper=",
        "-c",
        "credential.https://github.com.helper=",
        "push",
        "origin",
        "main",
    ]
    push_env = captured["env"]
    assert push_env["GIT_ASKPASS"].endswith("askpass.py")
    assert push_env["GIT_PAT_ALLOWED_HOST"] == "github.com"
    assert push_env["GIT_TERMINAL_PROMPT"] == "0"
    assert push_env["GIT_PAT_USERNAME"] == "x-access-token"
    assert TEST_GITHUB_CREDENTIAL not in " ".join(command)
    assert all(value != TEST_GITHUB_CREDENTIAL for value in push_env.values())
    assert "GIT_PAT_FILE" not in push_env
    assert "GITHUB_TOKEN" not in push_env
    assert not Path(push_env["GIT_PAT_SOCKET"]).exists()
    assert not Path(push_env["GIT_ASKPASS"]).exists()


def test_pat_push_accepts_env_token_without_prompt(monkeypatch) -> None:
    """Check that PAT push accepts env token without prompt keeps sensitive data out of output.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in PAT push accepts env token without prompt.
    """
    monkeypatch.setattr(git_push_with_pat.shutil, "which", lambda _name: "/usr/bin/git")
    prompted = False

    def fail_prompt(_prompt):
        """Return the fail prompt.

        Inputs: `_prompt`. Output: `str`.
        """
        nonlocal prompted
        prompted = True
        return "wrong"

    def fake_run(command, *, env, check, **kwargs):
        """Simulate run so the surrounding test controls that dependency.

        Inputs: `command`, `env` environment mapping, `check`. Output:
        `CompletedProcess` result.
        """
        if _is_remote_lookup(command):
            return _remote_lookup_result(command)
        password = subprocess.check_output(
            [env["GIT_ASKPASS"], "Password for https://github.com:"],
            env=env,
            text=True,
        )
        assert password == f"{TEST_GITHUB_CREDENTIAL}\n"
        return subprocess.CompletedProcess(command, 0)

    args = git_push_with_pat.parse_args(["--dry-run", "origin", "main"])
    result = git_push_with_pat.run_push(
        args,
        env={"PATH": "/usr/bin", "GITHUB_TOKEN": TEST_GITHUB_CREDENTIAL},
        token_reader=fail_prompt,
        runner=fake_run,
    )

    assert result == 0
    assert prompted is False


def test_pat_push_accepts_explicit_force_with_lease(monkeypatch) -> None:
    """Verify PAT push accepts explicit force with lease.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in PAT push accepts explicit force with lease.
    """
    monkeypatch.setattr(git_push_with_pat.shutil, "which", lambda _name: "/usr/bin/git")
    captured: dict[str, object] = {}
    expected = "".join(format(value % 16, "x") for value in range(40))

    def fake_run(command, *, env, check, **kwargs):
        """Simulate run so the surrounding test controls that dependency.

        Inputs: `command`, `env` environment mapping, `check`. Output:
        `CompletedProcess` result.
        """
        if _is_remote_lookup(command):
            return _remote_lookup_result(command)
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0)

    args = git_push_with_pat.parse_args(
        [
            "--force-with-lease",
            f"refs/heads/main:{expected}",
            "origin",
            "HEAD:main",
        ]
    )
    result = git_push_with_pat.run_push(
        args,
        env={"PATH": "/usr/bin", "GITHUB_TOKEN": TEST_GITHUB_CREDENTIAL},
        runner=fake_run,
    )

    assert result == 0
    assert captured["command"] == [
        "/usr/bin/git",
        "-c",
        "credential.helper=",
        "-c",
        "credential.https://github.com.helper=",
        "push",
        f"--force-with-lease=refs/heads/main:{expected}",
        "origin",
        "HEAD:main",
    ]


def test_pat_push_does_not_write_credential_to_temp_tree(monkeypatch) -> None:
    """Verify PAT push does not write credential to temp tree.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in PAT push does not write credential to temp tree.
    """
    monkeypatch.setattr(git_push_with_pat.shutil, "which", lambda _name: "/usr/bin/git")
    observed_files: dict[str, str] = {}

    def fake_run(command, *, env, check, **kwargs):
        """Simulate run so the surrounding test controls that dependency.

        Inputs: `command`, `env` environment mapping, `check`. Output:
        `CompletedProcess` result.
        """
        if _is_remote_lookup(command):
            return _remote_lookup_result(command)
        temp_root = Path(env["GIT_ASKPASS"]).parent
        for path in temp_root.iterdir():
            if path.is_file() or path.is_socket():
                try:
                    observed_files[path.name] = path.read_text(encoding="utf-8")
                except OSError:
                    observed_files[path.name] = ""
        return subprocess.CompletedProcess(command, 0)

    args = git_push_with_pat.parse_args(["origin", "main"])
    result = git_push_with_pat.run_push(
        args,
        env={
            "PATH": os.environ.get("PATH", ""),
            "GITHUB_TOKEN": TEST_GITHUB_CREDENTIAL,
        },
        runner=fake_run,
    )

    assert result == 0
    assert set(observed_files) == {"askpass.py", "credential.sock"}
    assert all(
        TEST_GITHUB_CREDENTIAL not in content for content in observed_files.values()
    )


@pytest.mark.parametrize(
    ("remote", "refspec"),
    [("-origin", "main"), ("origin", "-main")],
)
def test_pat_push_rejects_option_like_git_arguments(remote, refspec) -> None:
    """Confirm PAT push rejects option like git arguments is rejected at the boundary.

    Inputs: pytest provides `remote`, `refspec`. Output: fails on regressions in PAT push rejects option like git arguments.
    """
    args = git_push_with_pat.argparse.Namespace(
        remote=remote,
        refspec=refspec,
        username="x-access-token",
        token_env="GITHUB_TOKEN",
        dry_run=False,
        force_with_lease=None,
    )
    with pytest.raises(SystemExit, match="must be a non-option Git argument"):
        git_push_with_pat.run_push(
            args,
            env={"GITHUB_TOKEN": TEST_GITHUB_CREDENTIAL},
        )


@pytest.mark.parametrize(
    "force_with_lease",
    [
        "main:" + ("".join(format(value, "x") for value in range(16)) * 2),
        "refs/heads/main",
        "refs/heads/main:-1234",
        "refs/heads/main:not-a-sha",
    ],
)
def test_pat_push_rejects_invalid_force_with_lease(force_with_lease) -> None:
    """Confirm PAT push rejects invalid force with lease is rejected at the boundary.

    Inputs: pytest provides `force_with_lease`. Output: fails on regressions in PAT push rejects invalid force with lease.
    """
    args = git_push_with_pat.argparse.Namespace(
        remote="origin",
        refspec="HEAD:main",
        username="x-access-token",
        token_env="GITHUB_TOKEN",
        dry_run=False,
        force_with_lease=force_with_lease,
    )
    with pytest.raises(SystemExit, match="force-with-lease"):
        git_push_with_pat.run_push(
            args,
            env={"GITHUB_TOKEN": TEST_GITHUB_CREDENTIAL},
        )


def test_pat_push_rejects_direct_non_github_https_remote_without_prompt(
    monkeypatch,
) -> None:
    """Confirm literal HTTPS remotes outside GitHub fail before token handling.

    Inputs: pytest provides `monkeypatch`. Output: asserts no prompt happens for
    an arbitrary HTTPS remote.
    """
    monkeypatch.setattr(git_push_with_pat.shutil, "which", lambda _name: "/usr/bin/git")
    prompted = False

    def token_reader(_prompt: str) -> str:
        """Return a fake token while recording prompt usage.

        Inputs: `_prompt`. Output: test credential string.
        """
        nonlocal prompted
        prompted = True
        return TEST_GITHUB_CREDENTIAL

    args = git_push_with_pat.parse_args(["https://example.com/repo.git", "main"])
    with pytest.raises(SystemExit, match="https://github.com"):
        git_push_with_pat.run_push(
            args,
            env={"PATH": "/usr/bin"},
            token_reader=token_reader,
        )
    assert prompted is False


def test_pat_push_rejects_configured_non_github_remote_without_askpass(
    monkeypatch,
) -> None:
    """Confirm named remotes outside GitHub fail before askpass setup.

    Inputs: pytest provides `monkeypatch`. Output: asserts askpass is not built
    for a remote name that resolves outside GitHub.
    """
    monkeypatch.setattr(git_push_with_pat.shutil, "which", lambda _name: "/usr/bin/git")
    observed_commands: list[list[str]] = []

    def fake_run(command, *, env, check, **kwargs):
        """Return an attacker-controlled remote URL for remote lookup.

        Inputs: `command`, `env`, `check`. Output: `CompletedProcess`.
        """
        observed_commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="https://example.com/repo.git\n",
        )

    args = git_push_with_pat.parse_args(["origin", "main"])
    with pytest.raises(SystemExit, match="https://github.com"):
        git_push_with_pat.run_push(
            args,
            env={"PATH": "/usr/bin", "GITHUB_TOKEN": TEST_GITHUB_CREDENTIAL},
            runner=fake_run,
        )

    assert observed_commands == [
        ["/usr/bin/git", "remote", "get-url", "--push", "origin"]
    ]
