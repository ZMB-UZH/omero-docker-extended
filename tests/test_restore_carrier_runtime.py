"""Exercise carrier-recovery orchestration against strict external-service doubles.

Metadata, archives, hashes, notes and readback checks use real temporary files.
No registry, GitHub release, Docker daemon or operator installation is modified.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
from types import SimpleNamespace

import pytest

from tools import restore_prebuilt_carrier as recovery


@pytest.fixture
def carrier(tmp_path, monkeypatch):
    """Inputs: isolated filesystem and environment. Output: a strict recovery harness."""
    repository = tmp_path / "repository"
    (repository / "docker").mkdir(parents=True)
    (repository / "docker" / "prebuilt-carrier.Dockerfile").write_bytes(
        (recovery.REPO_ROOT / "docker" / "prebuilt-carrier.Dockerfile").read_bytes()
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(recovery, "REPO_ROOT", repository)
    for key, value in {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_REPOSITORY": "example/project",
        "RUNNER_TEMP": str(scratch),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)

    sha = "a" * 40
    digest = "sha256:" + hashlib.sha256(b"synthetic carrier identity").hexdigest()
    old_digest = "sha256:" + hashlib.sha256(b"original carrier identity").hexdigest()
    version = "1.2.3-main.1"
    docker_repository = "example/carrier"
    notes = b"Changed: Improved image imports.\n"
    manifest = {
        "release": version,
        "carrier_image_repository": docker_repository,
        "carrier_image": f"{docker_repository}:{version}",
        "git_sha": sha,
        "required_images": ["example/runtime:1.2.3"],
        "release_notes_sha256": hashlib.sha256(notes).hexdigest(),
    }
    release = {
        "id": 10,
        "published_at": "2025-01-01T00:00:00Z",
        "body": notes.decode(),
        "draft": False,
        "immutable": False,
        "assets": [
            {"id": 1, "name": "project-source.tar.gz", "size": 100, "digest": digest},
            {
                "id": 2,
                "name": "project-source.tar.gz.sha256",
                "size": 64,
                "digest": digest,
            },
            {
                "id": 3,
                "name": "prebuilt-manifest.json",
                "size": 80,
                "digest": old_digest,
            },
            {
                "id": 4,
                "name": "prebuilt-carrier-digest.txt",
                "size": 80,
                "digest": old_digest,
            },
            {"id": 5, "name": "release-notes.md", "size": len(notes), "digest": digest},
        ],
    }
    state = SimpleNamespace(
        fault=None,
        corrected=False,
        events=[],
        published={},
        labels={},
        release=release,
        source=sha,
        digest=digest,
        old_digest=old_digest,
        work=scratch / "historical-carrier-recovery",
        tag_reads=0,
        source_reads=0,
        release_reads=0,
        uploads=[],
        terminated=0,
        raw_export=b"synthetic Docker save bytes\0" * 200,
    )

    def github(repo, endpoint):
        """Inputs: expected GitHub endpoint. Output: independent metadata snapshots."""
        assert repo == "example/project"
        if endpoint == f"git/ref/tags/{version}":
            state.source_reads += 1
            value = sha
            if state.fault == "tag-before-build" or (
                state.fault == "tag-before-publish" and state.source_reads == 2
            ):
                value = "b" * 40
            return {"object": {"type": "commit", "sha": value}}
        assert endpoint == f"releases/tags/{version}"
        state.release_reads += 1
        result = copy.deepcopy(release)
        if (state.fault == "release-before-publish" and state.release_reads == 2) or (
            state.fault == "release-before-metadata" and state.release_reads == 3
        ):
            result["body"] += "Concurrent edit.\n"
        if state.fault == "source-asset-after-publish" and state.release_reads == 4:
            result["assets"][0]["id"] += 100
        if state.fault == "metadata-digest" and state.release_reads == 4:
            next(a for a in result["assets"] if a["name"] == "prebuilt-manifest.json")[
                "digest"
            ] = old_digest
        if state.fault == "public-body" and state.release_reads == 4:
            result["body"] = "Unexpected public release text.\n"
        return result

    def tag(repo, tag_name):
        """Inputs: expected registry tag. Output: absence or exact published digest."""
        assert (repo, tag_name) == (docker_repository, version)
        state.tag_reads += 1
        if state.fault == "tag-appears" and state.tag_reads == 2:
            return {"digest": old_digest}
        if state.published:
            return {"digest": old_digest if state.fault == "hub-digest" else digest}
        return None

    def output(command, **_kwargs):
        """Inputs: external read command. Output: validated deterministic protocol data."""
        state.events.append(tuple(command))
        if command[:2] == ["git", "rev-parse"]:
            return sha
        if command[:3] == ["docker", "compose", "config"]:
            return (
                "example/runtime:9"
                if state.fault == "inventory"
                else "example/runtime:1.2.3\n"
            )
        if command[:3] == ["git", "diff", "--name-only"]:
            if state.fault == "source-change":
                return "unrelated.py"
            return "docker/omero-server.Dockerfile" if state.corrected else ""
        if command[:3] == ["docker", "image", "inspect"]:
            labels = dict(state.labels)
            if state.fault == "labels":
                labels["org.opencontainers.image.revision"] = "b" * 40
            return json.dumps(
                [
                    {
                        "Config": {"Labels": labels},
                        "RepoDigests": [docker_repository + "@" + digest],
                    }
                ]
            )
        if command[:2] == ["docker", "create"]:
            return "isolated-carrier-reader"
        raise AssertionError(f"Unexpected read command: {command}")

    def run(command, **kwargs):
        """Inputs: external command. Output: recorded side effects within the fixture."""
        state.events.append(tuple(command))
        if command[:3] == ["gh", "release", "download"]:
            name = command[command.index("--pattern") + 1]
            destination = Path(command[command.index("--dir") + 1]) / name
            destination.write_bytes(
                json.dumps(manifest).encode()
                if name == "prebuilt-manifest.json"
                else notes
            )
        elif command[:3] == ["git", "worktree", "add"]:
            source = Path(command[-2])
            (source / "docker").mkdir(parents=True)
            recipe = "FROM scratch\n"
            if state.corrected:
                recipe = (
                    f'ARG BIOP_OMERO_SCRIPTS_COMMIT="{sha}"\n'
                    + recovery.LEGACY_BIOP_CLONE
                )
                monkeypatch.setattr(
                    recovery,
                    "REVIEWED_BIOP_RECIPES",
                    frozenset({hashlib.sha256(recipe.encode()).hexdigest()}),
                )
            (source / "docker" / "omero-server.Dockerfile").write_text(recipe)
        elif command[-1] in {"check", "compose-guard"}:
            assert command[1].endswith("tools/env_safety_guard.py")
        elif command == ["bash", "installation/docker_buildx_compressed_push.sh"]:
            if state.fault == "correction-change":
                (kwargs["cwd"] / "docker" / "omero-server.Dockerfile").write_text(
                    "changed after review"
                )
        elif any(
            str(item).endswith("prune_non_required_docker_images.py")
            for item in command
        ):
            path = Path(command[command.index("--required-images-file") + 1])
            assert path.read_text().splitlines() == manifest["required_images"]
        elif command[:2] == ["docker", "pull"]:
            assert command[-1] in [
                *manifest["required_images"],
                manifest["carrier_image"],
            ]
        elif command[:3] in (
            ["docker", "buildx", "create"],
            ["docker", "buildx", "rm"],
        ):
            pass
        elif command[:3] == ["docker", "buildx", "build"]:
            if state.fault == "push":
                raise subprocess.CalledProcessError(1, command)
            state.labels = dict(
                command[index + 1].split("=", 1)
                for index, item in enumerate(command)
                if item == "--label"
            )
            state.published = {
                path.name: path.read_bytes()
                for path in kwargs["cwd"].iterdir()
                if path.is_file()
            }
        elif command[:2] == ["docker", "cp"]:
            name = command[2].rsplit("/", 1)[1]
            payload = state.published[name]
            if state.fault == "carrier-file" and name == "prebuilt-manifest.json":
                payload += b"corruption"
            Path(command[3]).write_bytes(payload)
        elif command[:2] == ["docker", "rm"]:
            assert command == ["docker", "rm", "isolated-carrier-reader"]
        elif command[:2] == ["docker", "scout"]:
            if state.fault == "carrier-scan":
                raise subprocess.CalledProcessError(1, command)
        elif command[:3] == ["gh", "release", "upload"]:
            for raw_path in command[command.index("--clobber") + 1 :]:
                path = Path(raw_path)
                state.uploads.append(path.name)
                asset = next(
                    (a for a in release["assets"] if a["name"] == path.name), None
                )
                if asset is None:
                    asset = {"name": path.name, "id": 99}
                    release["assets"].append(asset)
                asset.update(
                    size=path.stat().st_size,
                    digest="sha256:" + recovery.file_digest(path),
                )
        elif command[:3] == ["gh", "release", "edit"]:
            release["body"] = Path(
                command[command.index("--notes-file") + 1]
            ).read_text()
        else:
            raise AssertionError(f"Unexpected mutation command: {command}")

    class Process:
        """Bounded Docker stream double with observable termination and real bytes."""

        def __init__(self, command, **_kwargs):
            """Inputs: save or archive-read command. Output: an owned binary stream."""
            state.events.append(tuple(command))
            self.saving = command[:2] == ["docker", "save"]
            if self.saving:
                self.stdout = (
                    None
                    if state.fault == "save-stream"
                    else io.BytesIO(state.raw_export)
                )
            else:
                assert command[:2] == ["docker", "cp"]
                assert command[-1] == "-"
                payload = state.published["runtime-images.tar.gz"]
                if state.fault == "archive":
                    payload = bytes([payload[0] ^ 1]) + payload[1:]
                self.stdout = io.BytesIO()
                with tarfile.open(fileobj=self.stdout, mode="w") as archive:
                    member = tarfile.TarInfo("runtime-images.tar.gz")
                    member.size = len(payload)
                    archive.addfile(member, io.BytesIO(payload))
                self.stdout.seek(0)

        def __enter__(self):
            """Inputs: context entry. Output: this process double."""
            return self

        def __exit__(self, *_args):
            """Inputs: context outcome. Output: closed stream without swallowing errors."""
            if self.stdout is not None:
                self.stdout.close()

        def wait(self):
            """Inputs: completion request. Output: the selected export exit status."""
            return 1 if self.saving and state.fault == "save-status" else 0

        def terminate(self):
            """Inputs: abort request. Output: recorded stream-process termination."""
            state.terminated += 1

    def scan(images, destination):
        """Inputs: runtime identities and evidence path. Output: scan ordering receipt."""
        state.events.append(("runtime-scan", *images))
        assert images == manifest["required_images"]
        assert destination.parent == state.work
        if state.fault == "runtime-scan":
            raise RuntimeError("runtime analysis failed")

    def inspect(command, **_kwargs):
        """Inputs: image-presence request. Output: missing-image status to test pulls."""
        assert command == ["docker", "image", "inspect", "example/runtime:1.2.3"]
        state.events.append(tuple(command))
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(recovery, "github", github)
    monkeypatch.setattr(recovery, "docker_tag", tag)
    monkeypatch.setattr(recovery, "output", output)
    monkeypatch.setattr(recovery, "run", run)
    monkeypatch.setattr(
        recovery, "configure_build", lambda _source, _work: {"ISOLATED_BUILD": "1"}
    )
    monkeypatch.setattr(recovery, "scan_images", scan)
    monkeypatch.setattr(recovery, "executable", lambda name: name)
    monkeypatch.setattr(recovery.subprocess, "run", inspect)
    monkeypatch.setattr(recovery.subprocess, "Popen", Process)
    state.invoke = lambda: recovery.restore(version, docker_repository)
    return state


@pytest.mark.parametrize("legacy_notes", [False, True])
@pytest.mark.parametrize("corrected", [False, True])
def test_recovery_preserves_release_identity_and_verifies_real_archive(
    carrier, legacy_notes, corrected
):
    """Inputs: historical release variants. Output: verified bytes and exact mutation scope."""
    carrier.corrected = corrected
    if legacy_notes:
        carrier.release["assets"] = [
            a for a in carrier.release["assets"] if a["name"] != "release-notes.md"
        ]
        carrier.release["body"] += (
            "Carrier: example/carrier@" + carrier.old_digest + "\n"
        )
    original_sources = recovery.source_assets(carrier.release)
    original_id = carrier.release["id"]
    original_date = carrier.release["published_at"]
    carrier.invoke()
    dist = carrier.work / "dist"
    result = json.loads((dist / "restoration-result.json").read_text())
    manifest = json.loads((dist / "prebuilt-manifest.json").read_text())
    assert result["digest"] == carrier.digest
    assert result["git_sha"] == carrier.source
    assert manifest["image_archive_sha256"] == recovery.file_digest(
        dist / "runtime-images.tar.gz"
    )
    assert (
        gzip.decompress((dist / "runtime-images.tar.gz").read_bytes())
        == carrier.raw_export
    )
    assert manifest["runtime_images_uncompressed_bytes"] == len(carrier.raw_export)
    assert bool(manifest["rebuild_recipe_corrections"]) is corrected
    assert carrier.release["id"] == original_id
    assert carrier.release["published_at"] == original_date
    assert recovery.source_assets(carrier.release) == original_sources
    assert carrier.uploads == [
        "prebuilt-manifest.json",
        "prebuilt-carrier-digest.txt",
    ] + (["release-notes.md"] if legacy_notes else [])
    assert carrier.tag_reads == 3
    assert carrier.terminated == 0
    assert ("docker", "buildx", "rm", "historical-carrier") in carrier.events
    assert ("docker", "rm", "isolated-carrier-reader") in carrier.events
    scan_index = carrier.events.index(("runtime-scan", "example/runtime:1.2.3"))
    push_index = next(
        i
        for i, command in enumerate(carrier.events)
        if command[:3] == ("docker", "buildx", "build")
    )
    assert scan_index < push_index
    if legacy_notes:
        assert carrier.old_digest not in carrier.release["body"]
        assert carrier.digest in carrier.release["body"]


@pytest.mark.parametrize(
    "fault",
    [
        "tag-before-build",
        "inventory",
        "source-change",
        "correction-change",
        "runtime-scan",
        "save-stream",
        "save-status",
        "tag-appears",
        "tag-before-publish",
        "release-before-publish",
        "push",
        "labels",
        "hub-digest",
        "carrier-file",
        "archive",
        "carrier-scan",
        "release-before-metadata",
        "source-asset-after-publish",
        "metadata-digest",
        "public-body",
    ],
)
def test_recovery_fails_closed_at_every_publication_boundary(carrier, fault):
    """Inputs: one failed boundary. Output: no success receipt or unsafe follow-up mutation."""
    carrier.fault = fault
    carrier.corrected = fault == "correction-change"
    with pytest.raises((ValueError, RuntimeError, subprocess.CalledProcessError)):
        carrier.invoke()
    assert not (carrier.work / "dist" / "restoration-result.json").exists()
    if fault not in {"source-asset-after-publish", "metadata-digest", "public-body"}:
        assert carrier.uploads == []
    if fault in {"save-stream", "save-status", "archive"}:
        assert carrier.terminated == 1
    if fault == "push":
        assert ("docker", "buildx", "rm", "historical-carrier") in carrier.events
    if fault in {"carrier-file", "archive"}:
        assert ("docker", "rm", "isolated-carrier-reader") in carrier.events
    if fault in {
        "tag-before-build",
        "inventory",
        "source-change",
        "correction-change",
        "runtime-scan",
        "save-stream",
        "save-status",
        "tag-appears",
        "tag-before-publish",
        "release-before-publish",
    }:
        assert not carrier.published


@pytest.mark.parametrize(
    "fault", ["draft", "immutable", "source-count", "ambiguous-digest"]
)
def test_recovery_rejects_unrecoverable_release_before_creating_work(carrier, fault):
    """Inputs: unsafe release metadata. Output: rejection before local build side effects."""
    if fault in {"draft", "immutable"}:
        carrier.release[fault] = True
    elif fault == "source-count":
        carrier.release["assets"].pop(0)
    else:
        carrier.release["body"] += carrier.digest + " " + carrier.old_digest
    with pytest.raises(ValueError):
        carrier.invoke()
    assert not carrier.work.exists()
    assert carrier.events == []
