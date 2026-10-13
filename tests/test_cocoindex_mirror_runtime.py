"""Exercise index-mirror publication against real temporary filesystems."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from threading import Barrier

import pytest

from tools import cocoindex_agent_search as search


@pytest.fixture
def mirror_context(tmp_path, monkeypatch):
    """Inputs: temporary directory. Output: source files and an external mirror context."""
    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "sample.py").write_text("value = 7\n", encoding="utf-8")
    (repo / "image.bin").write_bytes(bytes(range(256)) * 4096)
    paths = [PurePosixPath(name) for name in ("sample.py", "image.bin", "gone.py")]
    digest = search.file_digest(repo, paths)
    context = search.CocoIndexContext(
        repo_root=repo,
        artifact_root=tmp_path / "external",
        mirror_repo=tmp_path / "external" / "mirrors" / digest / "repo",
        mirror_digest=digest,
    )
    monkeypatch.setattr(search, "tracked_files", lambda *_args: paths)
    monkeypatch.setattr(search, "require_disk_budget", lambda *_args: None)
    monkeypatch.setattr(search, "require_mirror_write_budget", lambda *_args: None)
    return context, paths


def test_mirror_publishes_complete_copy_and_reuses_it(mirror_context, monkeypatch):
    """Inputs: binary/text source fixtures. Output: byte-exact, idempotent mirror publication."""
    context, paths = mirror_context
    search.ensure_mirror(context)
    assert search.file_digest(context.mirror_repo, paths) == context.mirror_digest
    manifest = json.loads(
        (context.mirror_repo.parent / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["digest"] == context.mirror_digest
    assert manifest["mirrored_files"] == 2
    assert manifest["git_visible_non_ignored_files"] == 3
    assert not (context.mirror_repo / "gone.py").exists()
    monkeypatch.setattr(
        search,
        "copy_repo_files",
        lambda *_args: pytest.fail("an admitted mirror was copied again"),
    )
    search.ensure_mirror(context)


@pytest.mark.parametrize("operation", ["copy", "manifest", "publish"])
def test_failed_mirror_leaves_no_partial_publication(
    mirror_context, monkeypatch, operation
):
    """Inputs: injected filesystem failures. Output: no partial publication and a successful retry."""
    context, paths = mirror_context
    original_copy = search.copy_repo_files
    original_write = Path.write_text
    original_replace = search.os.replace

    def copy(*args):
        """Inputs: mirror-copy arguments. Output: copied bytes or an injected I/O failure."""
        result = original_copy(*args)
        if operation == "copy":
            raise OSError("injected copy failure")
        return result

    def write(path, *args, **kwargs):
        """Inputs: manifest-write arguments. Output: real write or injected manifest failure."""
        if operation == "manifest" and path.name == "manifest.json":
            raise OSError("injected manifest failure")
        return original_write(path, *args, **kwargs)

    def replace(source, target):
        """Inputs: publication paths. Output: real rename or injected publication failure."""
        if operation == "publish":
            raise OSError("injected publication failure")
        return original_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(search, "copy_repo_files", copy)
        patch.setattr(Path, "write_text", write)
        patch.setattr(search.os, "replace", replace)
        with pytest.raises(OSError, match="injected"):
            search.ensure_mirror(context)
    assert not context.mirror_repo.parent.exists()
    assert list((context.artifact_root / "mirrors").iterdir()) == []
    search.ensure_mirror(context)
    assert search.file_digest(context.mirror_repo, paths) == context.mirror_digest


def test_source_change_during_copy_does_not_publish(mirror_context, monkeypatch):
    """Inputs: mutation during copying. Output: rejected digest and no published mirror."""
    context, _ = mirror_context
    original = search.copy_repo_files

    def changed_copy(*args):
        """Inputs: copy arguments. Output: copied content after a deliberate source mutation."""
        (context.repo_root / "sample.py").write_text("value = 8\n")
        return original(*args)

    monkeypatch.setattr(search, "copy_repo_files", changed_copy)
    with pytest.raises(RuntimeError, match="contents changed"):
        search.ensure_mirror(context)
    assert not context.mirror_repo.parent.exists()
    assert list((context.artifact_root / "mirrors").iterdir()) == []


@pytest.mark.parametrize("manifest", [None, "{broken-json", "{}", "[]"])
def test_existing_incomplete_mirror_is_rejected_without_deletion(
    mirror_context, manifest
):
    """Inputs: incomplete existing cache. Output: explicit rejection with evidence preserved."""
    context, _ = mirror_context
    context.mirror_repo.mkdir(parents=True)
    sentinel = context.mirror_repo / "operator-evidence.txt"
    sentinel.write_text("preserve this existing artifact")
    manifest_path = context.mirror_repo.parent / "manifest.json"
    if manifest is not None:
        manifest_path.write_text(manifest)
    with pytest.raises(RuntimeError, match="mirror.*incomplete|mirror.*invalid"):
        search.ensure_mirror(context)
    assert sentinel.read_text() == "preserve this existing artifact"
    assert manifest_path.exists() == (manifest is not None)
    if manifest is not None:
        assert manifest_path.read_text() == manifest


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema", -1),
        ("digest", "different-source"),
        ("package", "different-provider"),
        ("mirrored_files", -1),
        ("mirrored_files", True),
        ("mirrored_files", 4),
        ("git_visible_non_ignored_files", "3"),
        ("git_visible_non_ignored_files", False),
    ],
)
def test_mirror_manifest_requires_matching_identity_and_counts(
    mirror_context, key, value
):
    """Inputs: malformed manifest identity/counts. Output: rejection without replacing evidence."""
    context, _ = mirror_context
    search.ensure_mirror(context)
    manifest_path = context.mirror_repo.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest[key] = value
    payload = json.dumps(manifest)
    manifest_path.write_text(payload)
    with pytest.raises(RuntimeError, match="manifest is invalid"):
        search.ensure_mirror(context)
    assert manifest_path.read_text() == payload


@pytest.mark.parametrize("target", ["directory", "repo", "manifest"])
def test_mirror_rejects_symlinks_without_touching_their_targets(
    mirror_context, target, tmp_path
):
    """Inputs: symlinked mirror components. Output: rejection with external targets untouched."""
    context, _ = mirror_context
    search.ensure_mirror(context)
    selected = {
        "directory": context.mirror_repo.parent,
        "repo": context.mirror_repo,
        "manifest": context.mirror_repo.parent / "manifest.json",
    }[target]
    outside = tmp_path / "preserved-target"
    selected.rename(outside)
    selected.symlink_to(outside, target_is_directory=outside.is_dir())
    with pytest.raises(RuntimeError, match="mirror is incomplete"):
        search.ensure_mirror(context)
    assert selected.is_symlink()
    assert outside.exists()
    if target == "manifest":
        assert json.loads(outside.read_text())["digest"] == context.mirror_digest
    else:
        source = outside / "repo" if target == "directory" else outside
        assert (source / "sample.py").read_text() == "value = 7\n"


@pytest.mark.parametrize(
    "error", [PermissionError("read denied"), UnicodeError("invalid encoding")]
)
def test_unreadable_mirror_manifest_fails_without_replacement(
    mirror_context, monkeypatch, error
):
    """Inputs: manifest read failures. Output: rejection without automatic cache replacement."""
    context, _ = mirror_context
    search.ensure_mirror(context)
    manifest_path = context.mirror_repo.parent / "manifest.json"
    original = Path.read_text
    payload = original(manifest_path)

    def read(path, *args, **kwargs):
        """Inputs: requested path. Output: normal text except for the injected manifest failure."""
        if path == manifest_path:
            raise error
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", read)
        with pytest.raises(RuntimeError, match="manifest is invalid"):
            search.ensure_mirror(context)
    assert manifest_path.read_text() == payload


def test_changed_source_is_rejected_before_any_copy(mirror_context, monkeypatch):
    """Inputs: a stale source digest. Output: rejection before copying or creating cache state."""
    context, _ = mirror_context
    (context.repo_root / "sample.py").write_text("value = 8\n")
    monkeypatch.setattr(
        search, "copy_repo_files", lambda *_args: pytest.fail("stale source copied")
    )
    with pytest.raises(RuntimeError, match="contents changed while resolving"):
        search.ensure_mirror(context)
    assert not context.artifact_root.exists()


def test_concurrent_mirror_creation_publishes_only_once(mirror_context, monkeypatch):
    """Inputs: simultaneous mirror requests. Output: one publication shared by both callers."""
    context, paths = mirror_context
    rendezvous = Barrier(2)
    original_digest = search.file_digest
    original_copy = search.copy_repo_files
    copies = []

    def digest(*args):
        """Inputs: source paths. Output: real digest after both callers reach the same checkpoint."""
        result = original_digest(*args)
        rendezvous.wait(timeout=10)
        return result

    def copy(*args):
        """Inputs: copy arguments. Output: real copy with its invocation recorded."""
        copies.append(args[2])
        return original_copy(*args)

    with monkeypatch.context() as patch:
        patch.setattr(search, "file_digest", digest)
        patch.setattr(search, "copy_repo_files", copy)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(search.ensure_mirror, context) for _ in range(2)]
            for future in futures:
                future.result(timeout=15)
    assert len(copies) == 1
    assert search.file_digest(context.mirror_repo, paths) == context.mirror_digest
    assert list((context.artifact_root / "mirrors").iterdir()) == [
        context.mirror_repo.parent
    ]


def test_existing_search_requires_valid_mirror_manifest(mirror_context):
    """Inputs: complete search artifacts plus a damaged manifest. Output: search refusal."""
    context, _ = mirror_context
    search.ensure_mirror(context)
    context.ccc_bin.parent.mkdir(parents=True)
    context.ccc_bin.touch()
    database = search.target_sqlite_db(context)
    database.parent.mkdir(parents=True)
    database.touch()
    search.require_existing_search_artifacts(context)
    (context.mirror_repo.parent / "manifest.json").write_text("{}")
    with pytest.raises(RuntimeError, match="manifest is invalid"):
        search.require_existing_search_artifacts(context)
