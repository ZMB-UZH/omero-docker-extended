"""Exercise badge generation against isolated Git repositories and real files."""

import json
from pathlib import Path
import shutil
import subprocess
from unittest.mock import Mock

import pytest

from tools import agent_skill_provenance
from tools import update_readme_badges as badges


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def git_repo(tmp_path):
    """Inputs: existing history. Output: an isolated clone without new authorship."""
    git = agent_skill_provenance.resolve_required_executable("git")
    root = tmp_path / "repository"
    subprocess.run(
        [
            git,
            "clone",
            "--quiet",
            "--no-checkout",
            "--shared",
            "--",
            str(ROOT),
            str(root),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )

    def command(*args):
        """Inputs: fixture Git arguments. Output: checked native Git output."""
        return badges._run_git(root, *args)

    command("remote", "set-url", "origin", "https://github.com/example/project.git")
    return root, command


@pytest.mark.parametrize(
    "mode", ["upstream", "configured", "origin", "single", "ambiguous"]
)
def test_remote_selection_uses_actual_git_configuration(git_repo, mode):
    """Inputs: tracking and remote configurations. Output: deterministic choice or refusal."""
    root, git = git_repo
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    git("config", "--remove-section", f"branch.{branch}")
    git("remote", "add", "upstream", "https://github.com/example/upstream.git")
    if mode in {"upstream", "configured"}:
        git("config", f"branch.{branch}.remote", "upstream")
        git("config", f"branch.{branch}.merge", "refs/heads/release/stable")
        if mode == "upstream":
            git("update-ref", "refs/remotes/upstream/release/stable", "HEAD")
    elif mode in {"single", "ambiguous"}:
        git("remote", "remove", "origin")
        if mode == "ambiguous":
            git("remote", "add", "second", "https://github.com/example/second.git")
    if mode == "ambiguous":
        with pytest.raises(RuntimeError, match="determine which Git remote"):
            badges._resolve_remote_name(root)
    else:
        assert badges._resolve_remote_name(root) == (
            "origin" if mode == "origin" else "upstream"
        )


def test_symbolic_default_branch_preserves_slashes(git_repo):
    """Inputs: a real hierarchical default ref. Output: full branch in generated URLs."""
    root, git = git_repo
    git("update-ref", "refs/remotes/origin/release/stable", "HEAD")
    git(
        "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/release/stable"
    )
    metadata = badges.resolve_repo_metadata(root)
    assert (metadata.owner, metadata.repo, metadata.branch_name) == (
        "example",
        "project",
        "release/stable",
    )
    assert metadata.branch_query_value == "release%2Fstable"


@pytest.mark.parametrize(
    "description,expected",
    [
        ("  HEAD branch: release/stable\n", "release/stable"),
        ("No HEAD information", "working"),
    ],
)
def test_default_branch_fallback_does_not_invent_a_branch(
    monkeypatch, tmp_path, description, expected
):
    """Inputs: missing local HEAD metadata. Output: advertised or actual working branch."""
    command = Mock(
        side_effect=[subprocess.CalledProcessError(1, ["git"]), description, "working"]
    )
    monkeypatch.setattr(badges, "_run_git", command)
    assert badges._resolve_branch_name(tmp_path, "upstream") == expected
    assert command.call_args_list[1].args == (tmp_path, "remote", "show", "upstream")


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"host": None, "owner": "o", "repo": "r", "branch_name": "main"},
        {"host": "github.com", "owner": " ", "repo": "r", "branch_name": "main"},
    ],
)
def test_invalid_canonical_metadata_fails_before_badge_changes(tmp_path, payload):
    """Inputs: invalid canonical JSON. Output: a controlled error rather than broken links."""
    metadata = tmp_path / badges.CANONICAL_METADATA_PATH
    metadata.parent.mkdir()
    metadata.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError):
        badges.resolve_repo_metadata(tmp_path)


@pytest.mark.parametrize(
    "text",
    [
        "no badge markers",
        badges.BADGE_BLOCK_BEGIN,
        badges.BADGE_BLOCK_END + "\nKeep this body\n" + badges.BADGE_BLOCK_BEGIN,
        badges.BADGE_BLOCK_BEGIN * 2 + badges.BADGE_BLOCK_END,
        badges.BADGE_BLOCK_BEGIN + badges.BADGE_BLOCK_END * 2,
    ],
)
def test_invalid_markers_never_rewrite_unrelated_readme_text(text):
    """Inputs: missing, reversed or duplicate markers. Output: refusal before replacement."""
    with pytest.raises(RuntimeError, match="badge markers"):
        badges.update_readme_text(text, "replacement")


@pytest.mark.parametrize("trailing_newline", [False, True])
def test_cli_check_write_and_idempotence_preserve_readme_body(
    tmp_path, capsys, trailing_newline
):
    """Inputs: stale badge files. Output: nonmutating check, exact write and idempotent rerun."""
    for relative in (
        badges.CANONICAL_METADATA_PATH,
        agent_skill_provenance.UPSTREAM_SOURCES_DOC_PATH,
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    readme = tmp_path / "README.md"
    prefix, suffix = "# Operator project\n\n", "\n\nKeep all operator documentation."
    original = (
        prefix
        + badges.BADGE_BLOCK_BEGIN
        + "\nold badge\n"
        + badges.BADGE_BLOCK_END
        + suffix
    )
    if trailing_newline:
        original += "\n"
    readme.write_text(original)
    assert badges.main(["--repo-root", str(tmp_path), "--check"]) == 1
    assert "out of date" in capsys.readouterr().err
    assert readme.read_text() == original
    assert badges.main(["--repo-root", str(tmp_path), "--write"]) == 0
    rendered = badges.render_badge_block(
        badges.resolve_repo_metadata(tmp_path),
        agent_skill_provenance.load_upstream_sources(tmp_path),
    )
    assert readme.read_text() == prefix + rendered + suffix + "\n"
    before = readme.stat().st_mtime_ns
    assert badges.main(["--repo-root", str(tmp_path), "--check"]) == 0
    assert badges.main(["--repo-root", str(tmp_path), "--write"]) == 0
    assert readme.stat().st_mtime_ns == before


@pytest.mark.parametrize(
    "remote",
    [
        "not-a-remote",
        "https:///owner/repository",
        "https://github.com/owner",
        "git@github.com:owner/.git",
    ],
)
def test_invalid_remote_urls_cannot_generate_badges(remote):
    """Inputs: unsupported clone URLs. Output: explicit validation failure."""
    with pytest.raises(RuntimeError, match="Unsupported Git remote URL"):
        badges._parse_remote_url(remote)
