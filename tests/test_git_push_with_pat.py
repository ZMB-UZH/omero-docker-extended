"""Regression tests for one-shot GitHub PAT Git pushes."""

from __future__ import annotations

import importlib.util
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
        token_path = Path(env["GIT_PAT_FILE"])
        assert token_path.read_text(encoding="utf-8") == TEST_GITHUB_CREDENTIAL
        assert token_path.parent.exists()
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
    assert push_env["GIT_ASKPASS"].endswith("askpass.sh")
    assert push_env["GIT_TERMINAL_PROMPT"] == "0"
    assert push_env["GIT_PAT_USERNAME"] == "x-access-token"
    assert TEST_GITHUB_CREDENTIAL not in " ".join(command)
    assert all(value != TEST_GITHUB_CREDENTIAL for value in push_env.values())
    assert not Path(push_env["GIT_PAT_FILE"]).exists()
    assert not Path(push_env["GIT_ASKPASS"]).exists()


def test_pat_push_accepts_env_token_without_prompt(monkeypatch) -> None:
    monkeypatch.setattr(git_push_with_pat.shutil, "which", lambda _name: "/usr/bin/git")
    prompted = False

    def fail_prompt(_prompt):
        nonlocal prompted
        prompted = True
        return "wrong"

    def fake_run(command, *, env, check):
        assert (
            Path(env["GIT_PAT_FILE"]).read_text(encoding="utf-8")
            == TEST_GITHUB_CREDENTIAL
        )
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
