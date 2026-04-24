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


def test_pat_push_uses_one_shot_askpass_without_leaking_token(monkeypatch) -> None:
    monkeypatch.setattr(git_push_with_pat.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(git_push_with_pat.sys.stdin, "isatty", lambda: True)
    captured: dict[str, object] = {}

    def fake_run(command, *, env, check):
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
    assert push_env["GIT_TERMINAL_PROMPT"] == "0"
    assert push_env["GIT_PAT_USERNAME"] == "x-access-token"
    assert TEST_GITHUB_CREDENTIAL not in " ".join(command)
    assert all(value != TEST_GITHUB_CREDENTIAL for value in push_env.values())
    assert "GIT_PAT_FILE" not in push_env
    assert "GITHUB_TOKEN" not in push_env
    assert not Path(push_env["GIT_PAT_SOCKET"]).exists()
    assert not Path(push_env["GIT_ASKPASS"]).exists()


def test_pat_push_accepts_env_token_without_prompt(monkeypatch) -> None:
    monkeypatch.setattr(git_push_with_pat.shutil, "which", lambda _name: "/usr/bin/git")
    prompted = False

    def fail_prompt(_prompt):
        nonlocal prompted
        prompted = True
        return "wrong"

    def fake_run(command, *, env, check):
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


def test_pat_push_does_not_write_credential_to_temp_tree(monkeypatch) -> None:
    monkeypatch.setattr(git_push_with_pat.shutil, "which", lambda _name: "/usr/bin/git")
    observed_files: dict[str, str] = {}

    def fake_run(command, *, env, check):
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
    args = git_push_with_pat.argparse.Namespace(
        remote=remote,
        refspec=refspec,
        username="x-access-token",
        token_env="GITHUB_TOKEN",
        dry_run=False,
    )
    with pytest.raises(SystemExit, match="must be a non-option Git argument"):
        git_push_with_pat.run_push(
            args,
            env={"GITHUB_TOKEN": TEST_GITHUB_CREDENTIAL},
        )
