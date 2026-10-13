"""Exercise editor-independent execution receipts and failure-closed gates."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
from unittest import mock

import pytest
import yaml

from tests.agent_instruction_helpers import read_instruction_contract
from tools import agent_preflight as gate
from tools.agent_context_policy import AGENT_ADAPTER_LINKS


@pytest.fixture
def receipt(tmp_path, monkeypatch):
    """Inputs: temporary state and patch fixture. Output: isolated receipt destination."""
    target = tmp_path / "state" / "receipt.json"
    monkeypatch.setattr(gate, "receipt_path", lambda: target)
    monkeypatch.setattr(gate, "policy_digest", lambda: "policy-v1")
    return target


def evidence(script, arguments, timeout):
    """Inputs: intercepted tool call. Output: deterministic protocol-shaped evidence."""
    if script == "cocoindex_agent_search.py":
        assert arguments[:5] == ["search", "--require-current", "--limit", "3", "task"]
        assert timeout == 600
        return "A source-verified routing result\n"
    assert arguments == ["read", "https://docs.example.org/guide"]
    assert timeout == 120
    return json.dumps(
        {
            "tool": "crawl4ai",
            "markdown": "Official source text",
            "sha256": "content",
            "fetched_at": "2026-01-01T00:00:00+00:00",
            "success": True,
            "native_sha256": "native-evidence-digest",
            "native_receipt": "private-external-capture",
        }
    )


def test_real_commands_precede_receipt_and_keep_source_details_private(receipt, capsys):
    """Inputs: successful tool results. Output: ordered execution and private receipt proof."""
    with mock.patch.object(gate, "execute", side_effect=evidence) as execute:
        gate.begin("task", ["https://docs.example.org/guide"])
    assert execute.call_count == 2
    gate.check()
    output = capsys.readouterr().out
    assert "Never remove `not`, `never`, `no`, `only`, or `except`" in output
    assert "Official source text" in output
    serialized = receipt.read_text()
    for private_text in (
        "task",
        "docs.example.org",
        "Official source text",
        str(gate.ROOT),
    ):
        assert private_text not in serialized
    if os.name == "posix":
        assert receipt.stat().st_mode & 0o777 == 0o600
    assert not list(receipt.parent.glob("tmp*"))


@pytest.mark.parametrize(
    "failure", [RuntimeError("failed"), subprocess.TimeoutExpired("reader", 90)]
)
def test_failed_rerun_invalidates_prior_success(receipt, failure):
    """Inputs: previous success and a failed retry. Output: the old receipt is unusable."""
    with mock.patch.object(gate, "execute", side_effect=evidence):
        gate.begin("task", [])
    gate.check()
    with (
        mock.patch.object(gate, "execute", side_effect=failure),
        pytest.raises(type(failure)),
    ):
        gate.begin("task", [])
    with pytest.raises(ValueError, match="not completed"):
        gate.check()


@pytest.mark.parametrize(
    "record", [[], {}, {"schema": 2}, {"schema": 1, "complete": False}]
)
def test_malformed_or_incomplete_receipts_block(receipt, record):
    """Inputs: invalid receipt records. Output: each record blocks the gate."""
    receipt.parent.mkdir()
    receipt.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        gate.check()


@pytest.mark.parametrize("change", ["policy", "old", "future", "research", "evidence"])
def test_receipt_scope_and_freshness_are_enforced(receipt, change):
    """Inputs: altered policy, time or evidence. Output: stale or incomplete proof is rejected."""
    with mock.patch.object(gate, "execute", side_effect=evidence):
        gate.begin("task", [])
    record = json.loads(receipt.read_text())
    if change == "policy":
        record["policy"] = "different"
    elif change in ("old", "future"):
        delta = timedelta(hours=-13 if change == "old" else 1)
        record["created_at"] = (datetime.now(timezone.utc) + delta).isoformat()
    elif change == "research":
        record["research_required"] = True
    else:
        record.pop("cocoindex_output_sha256")
    gate.write_receipt(receipt, record)
    with pytest.raises(ValueError):
        gate.check()


def test_missing_receipt_blocks_every_agent_hook(receipt, capsys):
    """Inputs: absent receipt and hook mode. Output: hook rejection with a diagnostic."""
    assert gate.main(["check", "--hook"]) == 2
    assert "blocked" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["Test User", "Test Automation", ""])
def test_gate_cannot_be_bypassed_by_commit_identity(receipt, monkeypatch, name):
    """Inputs: varied Git identities. Output: only execution evidence permits the gate."""
    monkeypatch.setenv("GIT_AUTHOR_NAME", name)
    monkeypatch.setenv("GIT_COMMITTER_NAME", name)
    assert gate.main(["check"]) == 1
    with mock.patch.object(gate, "execute", side_effect=evidence):
        gate.begin("task", [])
    assert gate.main(["check"]) == 0


def test_begin_requires_query_and_does_not_silently_substitute(receipt):
    """Inputs: missing query or unavailable index. Output: no substitute success receipt."""
    assert gate.main(["begin"]) == 1
    with mock.patch.object(
        gate,
        "execute",
        side_effect=subprocess.CalledProcessError(
            1, "cocoindex", stderr="index unavailable"
        ),
    ):
        assert gate.main(["begin", "--query", "task"]) == 1
    assert gate.main(["check"]) == 1


def test_empty_tool_output_is_not_execution_evidence():
    """Inputs: zero-exit tool with empty stdout. Output: evidence validation fails."""
    with mock.patch.object(
        gate.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "")
    ):
        with pytest.raises(RuntimeError, match="no execution evidence"):
            gate.execute("cocoindex_agent_search.py", ["search"], 10)


@pytest.mark.parametrize(
    "page", [[], {}, {"tool": "different", "markdown": "text", "sha256": "hash"}]
)
def test_crawler_success_is_validated(receipt, page):
    """Inputs: malformed crawler records. Output: both begin and later check reject them."""
    with mock.patch.object(gate, "execute", side_effect=["routing", json.dumps(page)]):
        with pytest.raises(RuntimeError, match="invalid execution evidence"):
            gate.begin("task", ["https://docs.example.org/guide"])
    assert gate.main(["check"]) == 1


def test_external_receipts_are_checkout_specific(tmp_path, monkeypatch):
    """Inputs: alternate roots and state paths. Output: checkout isolation and path rejection."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    one = gate.receipt_path()
    monkeypatch.setattr(gate, "ROOT", tmp_path / "different-checkout")
    assert gate.receipt_path() != one
    monkeypatch.setenv("XDG_STATE_HOME", str(gate.ROOT / "state"))
    with pytest.raises(ValueError, match="outside"):
        gate.receipt_path()
    monkeypatch.setenv("XDG_STATE_HOME", "relative")
    with pytest.raises(ValueError, match="absolute"):
        gate.receipt_path()


def test_digest_binds_executable_and_skill_content(tmp_path, monkeypatch):
    """Inputs: individually changed policy files. Output: every change alters the digest."""
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "__file__", str(tmp_path / "tools/agent_preflight.py"))
    paths = [
        "AGENTS.md",
        "docs/reference/ai-agent-task-contracts.md",
        "tools/agent_preflight.py",
        "tools/cocoindex_agent_search.py",
        "tools/crawl4ai_research.py",
        ".github/requirements/crawl4ai.txt",
        ".github/requirements/crawl4ai-build.txt",
        "tools/source_advisory_guard.py",
        ".github/requirements/crawl4ai-source/nltk.cdx.xml",
        ".github/requirements/crawl4ai-source/review.toml",
        ".github/requirements/crawl4ai-source/osv-scanner.toml",
    ]
    paths += [f".agents/skills/{name}/SKILL.md" for name in gate.SKILLS]
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    baseline = gate.policy_digest()
    for name in paths:
        path = tmp_path / name
        original = path.read_text()
        path.write_text(original + "changed")
        assert gate.policy_digest() != baseline
        path.write_text(original)


def test_all_present_and_registered_future_adapters_inherit_same_gate():
    """Inputs: registered adapters and hook configuration. Output: universal gate inheritance."""
    for adapter in ["AGENTS.md", *AGENT_ADAPTER_LINKS]:
        policy = read_instruction_contract(gate.ROOT, adapter)
        for required in (
            "tools/agent_preflight.py begin",
            "Crawl4AI",
            "CocoIndex",
            "caveman",
            "not opt-in",
        ):
            assert required in policy, (adapter, required)
    precommit = yaml.safe_load((gate.ROOT / ".pre-commit-config.yaml").read_text())
    hooks = [hook for repository in precommit["repos"] for hook in repository["hooks"]]
    gate_hook = next(hook for hook in hooks if hook["id"] == "agent-tool-preflight")
    assert gate_hook["entry"] == "python3 tools/agent_preflight.py check"
    assert gate_hook["always_run"] and not gate_hook["pass_filenames"]
    assert "stages" not in gate_hook


def test_claude_hooks_add_enforcement_without_weakening_shared_gate():
    """Inputs: optional native hooks. Output: policy delivery and failure-closed edit checks."""
    hooks = json.loads((gate.ROOT / ".claude/settings.json").read_text())["hooks"]
    assert "agent_preflight.py" in hooks["SessionStart"][0]["hooks"][0]["command"]
    edit_gate = next(item for item in hooks["PreToolUse"] if "Edit" in item["matcher"])
    command = edit_gate["hooks"][0]["command"]
    assert "check --hook" in command
    assert "|| true" not in command


def test_cocoindex_preflight_refuses_stale_search_before_running_engine():
    """Inputs: mismatched index and source identities. Output: search engine is never called."""
    from tools import cocoindex_agent_search as coco
    from types import SimpleNamespace

    args = coco.build_parser().parse_args(["search", "--require-current", "task"])
    active = SimpleNamespace(repo_root=Path("/repo"), mirror_digest="old")
    with (
        mock.patch.object(coco, "resolve_active_index_context", return_value=active),
        mock.patch.object(
            coco, "resolve_context", return_value=SimpleNamespace(mirror_digest="new")
        ),
        mock.patch.object(coco, "run_search") as search,
    ):
        with pytest.raises(coco.IndexRequiredError, match="stale"):
            coco.command_search(args)
    search.assert_not_called()


def test_policy_delivery_is_explicit(capsys):
    """Inputs: policy command. Output: all three mandatory tools are named without substitution."""
    assert gate.main(["policy"]) == 0
    text = capsys.readouterr().out
    assert all(
        name in text
        for name in ("Caveman", "CocoIndex", "Crawl4AI", "no silent substitution")
    )


def test_actual_tool_help_runs_without_indexing_or_installing():
    """Inputs: real CLI help invocation. Output: usage text without provisioning or indexing."""
    assert "usage:" in gate.execute("cocoindex_agent_search.py", ["--help"], 20)


def test_preflight_cli_entrypoint_delivers_policy_without_mutating_source(monkeypatch):
    """Inputs: script entrypoint arguments. Output: policy delivery exits successfully."""
    import runpy

    monkeypatch.setattr(gate.sys, "argv", ["agent_preflight.py", "policy"])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(gate.ROOT / "tools/agent_preflight.py"), run_name="__main__")
    assert result.value.code == 0


def test_real_git_hook_requires_execution_receipt_not_an_author_name(
    tmp_path, monkeypatch
):
    """Inputs: disposable Git repo and hook. Output: commit is denied until receipt validation."""
    import shlex
    import shutil
    import sys

    git = shutil.which("git")
    assert git is not None
    repo = tmp_path / "checkout"
    repo.mkdir()
    env = {
        "PATH": os.defpath,
        "HOME": str(tmp_path),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.org",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.org",
    }
    subprocess.run([git, "init", "-q", str(repo)], check=True, env=env, timeout=15)
    hook = repo / ".git/hooks/pre-commit"
    hook.write_text(
        "#!/bin/sh\nexec "
        + shlex.join(
            [
                sys.executable,
                str(gate.ROOT / "tools/agent_preflight.py"),
                "check",
            ]
        )
        + "\n"
    )
    hook.chmod(0o700)
    command = [git, "commit", "--allow-empty", "-m", "Gate integration fixture"]
    denied = subprocess.run(
        command, cwd=repo, env=env, capture_output=True, text=True, timeout=20
    )
    assert denied.returncode != 0 and "preflight blocked" in denied.stderr
    assert (
        subprocess.run(
            [git, "rev-parse", "--verify", "HEAD"],
            cwd=repo,
            env=env,
            capture_output=True,
            timeout=15,
        ).returncode
        != 0
    )
    monkeypatch.setenv("XDG_STATE_HOME", env["XDG_STATE_HOME"])
    with mock.patch.object(gate, "execute", return_value="Test-only routing evidence"):
        gate.begin("task", [])
    allowed = subprocess.run(
        command, cwd=repo, env=env, capture_output=True, text=True, timeout=20
    )
    assert allowed.returncode == 0, allowed.stderr
