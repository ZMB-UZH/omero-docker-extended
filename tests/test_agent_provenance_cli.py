"""Verify provenance checks fail on drift without changing the vendored sources."""

from pathlib import Path
import runpy
import shutil
import subprocess
import sys

import pytest

from tools import agent_skill_provenance as provenance
from tools import verify_agent_skill_provenance as verifier


ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_metadata_derives_names_and_rejects_empty_skill_sets():
    """Inputs: trailing-slash vendor root and absent references. Output: stable path identity, not an empty verified source."""
    sources = provenance.AgentSkillUpstreamSources(
        "example/skills", "v1", "a" * 40, "third_party/skills-v1/", {}
    )
    assert sources.snapshot_dir_name == "skills-v1"
    with pytest.raises(RuntimeError, match="No upstream skill paths"):
        _ = sources.upstream_skill_root


@pytest.mark.parametrize(
    "mode", ["missing", "empty", "no_skills", "no_caveman", "outside_caveman"]
)
def test_incomplete_provenance_document_fails_before_upstream_access(tmp_path, mode):
    """Inputs: malformed copied provenance document. Output: precise rejection before constructing upstream requests."""
    path = tmp_path / provenance.UPSTREAM_SOURCES_DOC_PATH
    path.parent.mkdir(parents=True)
    text = (ROOT / provenance.UPSTREAM_SOURCES_DOC_PATH).read_text()
    if mode in {"missing", "empty"}:
        text = provenance.UPSTREAM_REPOSITORY_RE.sub(
            "" if mode == "missing" else "- Upstream repository: ` `", text
        )
        expected = "missing the required" if mode == "missing" else "empty"
    elif mode == "no_skills":
        text = provenance.SKILL_TABLE_ROW_RE.sub("", text)
        expected = "does not list any"
    elif mode == "no_caveman":
        text = provenance.CAVEMAN_SECTION_RE.sub("", text)
        expected = "missing the caveman"
    else:
        text = provenance.CAVEMAN_SKILL_PATH_RE.sub(
            "- Selected upstream reference: `outside/SKILL.md`", text
        )
        expected = "escapes"
    path.write_text(text)
    loader = (
        provenance.load_caveman_upstream_sources
        if "caveman" in mode
        else provenance.load_upstream_sources
    )
    with pytest.raises(RuntimeError, match=expected):
        loader(tmp_path)


@pytest.fixture
def source_snapshot(tmp_path, monkeypatch):
    """Inputs: documented vendor files. Output: isolated files and controlled upstream bytes."""
    sources = provenance.load_upstream_sources(ROOT)
    caveman = provenance.load_caveman_upstream_sources(ROOT)
    paths = [
        provenance.UPSTREAM_SOURCES_DOC_PATH,
        *sources.skill_vendor_paths.values(),
        *caveman.vendor_files.values(),
    ]
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    upstream = {
        sources.raw_skill_url(name): provenance.strip_local_scanner_annotations(
            (ROOT / relative).read_text()
        )
        for name, relative in sources.skill_vendor_paths.items()
    }
    upstream.update(
        {
            caveman.raw_file_url(name): (ROOT / relative).read_text()
            for name, relative in caveman.vendor_files.items()
        }
    )
    commits = {
        (sources.repo_slug, sources.tag): sources.commit,
        (caveman.repo_slug, caveman.tag): caveman.commit,
    }
    fetched = []

    def resolve(repository, tag, *, cwd):
        """Inputs: upstream identity. Output: the exact independently recorded release commit."""
        assert cwd == tmp_path
        return commits[(repository, tag)]

    def fetch(url, *, timeout):
        """Inputs: expected immutable source URL. Output: fixture upstream content."""
        assert timeout == 13
        fetched.append(url)
        return upstream[url]

    monkeypatch.setattr(provenance, "resolve_remote_tag_commit", resolve)
    monkeypatch.setattr(provenance, "fetch_text", fetch)
    return tmp_path, sources, caveman, commits, upstream, fetched


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "annotation",
        "skill",
        "skill_tag",
        "reference",
        "reference_tag",
        "both_tags",
    ],
)
def test_provenance_cli_checks_all_sources_and_reports_each_mismatch(
    source_snapshot, capsys, change
):
    """Inputs: exact snapshots or altered tags/files. Output: accurate failure with no source edits."""
    root, sources, caveman, commits, upstream, fetched = source_snapshot
    if change in {"skill_tag", "both_tags"}:
        commits[(sources.repo_slug, sources.tag)] = "upstream-commit-drift"
    if change in {"reference_tag", "both_tags"}:
        commits[(caveman.repo_slug, caveman.tag)] = "upstream-commit-drift"
    if change in {"annotation", "skill", "reference"}:
        relative = next(
            iter(
                caveman.vendor_files.values()
                if change == "reference"
                else sources.skill_vendor_paths.values()
            )
        )
        target = root / relative
        prefix = (
            "<!-- skipcq: SCT-A000 -->\n"
            if change == "annotation"
            else "Substantive unexpected change.\n"
        )
        target.write_text(prefix + target.read_text())
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    expected = 0 if change in {"none", "annotation"} else 1
    assert verifier.main(["--repo-root", str(root), "--timeout", "13"]) == expected
    output = capsys.readouterr()
    assert sorted(fetched) == sorted(upstream)
    assert {path: path.read_bytes() for path in before} == before
    if expected:
        assert "FAIL" in output.err
        assert "Verified vendored upstream snapshots" not in output.out
        if change == "both_tags":
            assert output.err.count("commit mismatch") == 2
        elif change.endswith("tag"):
            assert "commit mismatch" in output.err
        else:
            assert "mismatch for" in output.err
    else:
        assert not output.err
        assert "Verified vendored upstream snapshots" in output.out


def test_direct_script_entrypoint_checks_sources(source_snapshot, monkeypatch, capsys):
    """Inputs: valid source fixtures. Output: the actual script exits successfully after verification."""
    root = source_snapshot[0]
    script = ROOT / "tools/verify_agent_skill_provenance.py"
    monkeypatch.setattr(
        sys, "argv", [str(script), "--repo-root", str(root), "--timeout", "13"]
    )
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(script), run_name="__main__")
    assert error.value.code == 0
    assert "Verified vendored upstream snapshots" in capsys.readouterr().out


@pytest.mark.parametrize("annotated", [False, True])
def test_remote_tag_resolution_prefers_peeled_commit(monkeypatch, tmp_path, annotated):
    """Inputs: lightweight or annotated native Git refs. Output: commit rather than tag object."""
    tag, commit = "a" * 40, "b" * 40
    output = f"{tag}\trefs/tags/v1\n"
    if annotated:
        output += f"{commit}\trefs/tags/v1^{{}}\n"
    calls = []

    def run(command, **kwargs):
        """Inputs: Git query. Output: recorded remote-ref response."""
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=output)

    monkeypatch.setattr(
        provenance, "resolve_required_executable", lambda _name: "/usr/bin/git"
    )
    monkeypatch.setattr(provenance.subprocess, "run", run)
    assert provenance.resolve_remote_tag_commit(
        "example/skills", "v1", cwd=tmp_path
    ) == (commit if annotated else tag)
    assert calls[0][0][-2:] == ["refs/tags/v1", "refs/tags/v1^{}"]
    assert calls[0][1]["cwd"] == tmp_path
    assert calls[0][1]["check"] is True


def test_absent_upstream_tag_is_not_treated_as_verified(monkeypatch, tmp_path):
    """Inputs: no matching Git refs. Output: explicit provenance failure."""
    monkeypatch.setattr(
        provenance, "resolve_required_executable", lambda _name: "/usr/bin/git"
    )
    monkeypatch.setattr(
        provenance.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=""),
    )
    with pytest.raises(RuntimeError, match="Could not resolve remote tag"):
        provenance.resolve_remote_tag_commit("example/skills", "missing", cwd=tmp_path)
