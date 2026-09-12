#!/usr/bin/env python3
"""Rebuild a missing historical carrier on an isolated GitHub-hosted runner."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from typing import BinaryIO, cast

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.env_safety_guard import (
    derive_compose_project_name,
    parse_active_env_assignments,
)
from tools.prebuilt_release_metadata import (
    validate_docker_repository,
    validate_public_release_text,
    validate_release_version,
)
from tools.prepare_ci_compose_environment import (
    _contract_pairs,
    prepare_ci_compose_environment,
)
from tools.scan_prebuilt_runtime_images import scan_images
from tools.write_prebuilt_runtime_archive import write_archive

REVIEWED_BIOP_RECIPES = frozenset(
    (
        "035d5f2ddfaf0ae6d7f6f63becef10ba33bd2ee1b19ec142dcd1d9d5155de23e",
        "e1f56c095de00770078202fa62b6a6c430ebd8202e7df3073d1bff22c42f44d8",
        "ff62e9b99b36e8a9a84530753c6492f6609da31bb4f9ab028ab99f837eec0c99",
        "74506ed00b3c8bf2fcf4db82f6628e7038d4fcfe514b190855652411edb9da7c",
    )
)
LEGACY_BIOP_CLONE = (
    '    git clone --depth 1 --branch "${BIOP_OMERO_SCRIPTS_REF}" '
    '"${BIOP_OMERO_SCRIPTS_REPO}" /tmp/biop-omero-scripts; \\\n'
)
PINNED_BIOP_FETCH = (
    "    git init --quiet /tmp/biop-omero-scripts; \\\n"
    '    git -C /tmp/biop-omero-scripts remote add origin "${BIOP_OMERO_SCRIPTS_REPO}"; \\\n'
    '    git -C /tmp/biop-omero-scripts fetch --depth 1 --no-tags origin "${BIOP_OMERO_SCRIPTS_COMMIT}"; \\\n'
    "    git -C /tmp/biop-omero-scripts checkout --detach FETCH_HEAD; \\\n"
)


def correct_historical_fetch(source: Path) -> dict[str, str] | None:
    """Repair only reviewed build recipes, retaining their dependency pins.

    Inputs: isolated historical worktree. Output: complete auditable correction or None.
    """
    relative_path = "docker/omero-server.Dockerfile"
    path = source / relative_path
    if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
        raise ValueError("Historical Dockerfile must stay inside its source worktree.")
    original = path.read_bytes()
    text = original.decode("utf-8")
    if "ARG BIOP_OMERO_SCRIPTS_COMMIT=" not in text or LEGACY_BIOP_CLONE not in text:
        return None
    digest = hashlib.sha256(original).hexdigest()
    if digest not in REVIEWED_BIOP_RECIPES or text.count(LEGACY_BIOP_CLONE) != 1:
        raise ValueError(
            "Historical dependency retrieval recipe has not been reviewed."
        )
    corrected = text.replace(LEGACY_BIOP_CLONE, PINNED_BIOP_FETCH, 1)
    correction = {
        "path": relative_path,
        "reason": "Fetch the original recorded BIOP commit directly, independent of branch movement.",
        "original_sha256": digest,
        "rebuilt_sha256": hashlib.sha256(corrected.encode("utf-8")).hexdigest(),
        "patch": "".join(
            difflib.unified_diff(
                text.splitlines(keepends=True),
                corrected.splitlines(keepends=True),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
            )
        ),
    }
    path.write_text(corrected, encoding="utf-8", newline="\n")
    return correction


def executable(name: str) -> str:
    """Inputs: command name. Output: resolved executable, or a closed failure."""
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(f"Required recovery executable is unavailable: {name}")
    return path


def output(arguments: list[str], **kwargs) -> str:
    """Inputs: command argv and options. Output: checked, stripped text stdout."""
    command = [executable(arguments[0]), *arguments[1:]]
    return subprocess.check_output(command, text=True, **kwargs).strip()


def run(arguments: list[str], **kwargs) -> None:
    """Inputs: command argv and options. Output: None after successful execution."""
    subprocess.run([executable(arguments[0]), *arguments[1:]], check=True, **kwargs)


def github(repository: str, endpoint: str) -> dict:
    """Inputs: repository and API endpoint. Output: decoded GitHub metadata."""
    return json.loads(output(["gh", "api", f"repos/{repository}/{endpoint}"]))


def docker_tag(repository: str, version: str) -> dict | None:
    """Read bounded tag metadata from Docker Hub without following redirects.

    Inputs: validated repository and version. Output: tag metadata or confirmed absence.
    """
    validate_docker_repository(repository)
    validate_release_version(version)
    with requests.get(
        f"https://hub.docker.com/v2/repositories/{repository}/tags/{version}/",
        headers={"Accept": "application/json"},
        timeout=30,
        allow_redirects=False,
        verify=True,
        stream=True,
    ) as response:
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise RuntimeError("Docker Hub tag lookup failed.")
        body = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            body.extend(chunk)
            if len(body) > 1024**2:
                raise ValueError("Docker Hub tag response exceeds the metadata limit.")
    document = json.loads(body)
    if not isinstance(document, dict):
        raise ValueError("Docker Hub tag metadata is not an object.")
    return document


def require_missing_tag(repository: str, version: str) -> None:
    """Inputs: Docker repository/tag. Output: None only for confirmed absence."""
    if docker_tag(repository, version) is not None:
        raise ValueError("Recovery refuses to replace an existing Docker tag.")


def validate_original(
    manifest: dict, version: str, repository: str, sha: str
) -> list[str]:
    """Bind a historical release to its exact Git source and pinned image set.

    Inputs: manifest and expected identity. Output: validated sorted image references.
    """
    if (
        manifest.get("release") != version
        or manifest.get("carrier_image_repository") != repository
        or manifest.get("carrier_image") != f"{repository}:{version}"
        or manifest.get("git_sha") != sha
        or re.fullmatch(r"[a-f0-9]{40}", sha) is None
    ):
        raise ValueError("Historical release identity mismatch.")
    images = manifest.get("required_images")
    if (
        not isinstance(images, list)
        or not images
        or not all(isinstance(image, str) for image in images)
        or len(set(images)) != len(images)
        or any(
            not image
            or image.startswith("-")
            or any(character.isspace() for character in image)
            or image.endswith(":latest")
            or ":latest@" in image
            or (":" not in image.rsplit("/", 1)[-1] and "@sha256:" not in image)
            or image.endswith(":")
            for image in images
        )
    ):
        raise ValueError("Historical runtime inventory is invalid.")
    return sorted(images)


def release_notes(release: dict, manifest: dict, dist: Path) -> bytes:
    """Reuse existing public notes, validating any published notes checksum.

    Inputs: original release, manifest and staging directory. Output: public notes bytes.
    """
    path = dist / "release-notes.md"
    if path.exists():
        notes = path.read_bytes()
        if hashlib.sha256(notes).hexdigest() != manifest.get("release_notes_sha256"):
            raise ValueError("Historical public notes checksum mismatch.")
    else:
        body = re.sub(r"@sha256:[a-f0-9]{64}", "", release["body"])
        notes = (
            re.sub(r"sha256:[a-f0-9]{64}", "prebuilt-carrier-digest.txt", body).rstrip()
            + "\n"
        ).encode("utf-8")
    validate_public_release_text(notes.decode("utf-8"), "Historical release notes")
    path.write_bytes(notes)
    return notes


def configure_build(source: Path, work: Path) -> dict[str, str]:
    """Create synthetic build configuration only in the fresh historical worktree.

    Inputs: fresh source and scratch paths. Output: isolated build environment mapping.
    """
    values = prepare_ci_compose_environment(source, work / "synthetic-environment")
    values["COMPOSE_PROJECT_NAME"] = derive_compose_project_name(source)
    for _, target in _contract_pairs(source):
        keys = (
            values.keys()
            if target.name == ".env"
            else parse_active_env_assignments(target)
        )
        assignments = []
        for key in keys:
            value = values[key]
            if any(character in value for character in "'\r\n\x00"):
                raise ValueError("Unsupported synthetic environment literal.")
            assignments.append(f"{key}='{value}'\n")
        target.write_text("".join(assignments), encoding="utf-8")
    return {
        **os.environ,
        **values,
        "COMPOSE_FILE": str(source / "docker-compose.yml"),
        "DOCKER_BUILD_PUSH_IMAGES": "0",
        "DOCKER_BUILD_INLINE_CACHE": "1",
        "DOCKER_BUILD_NO_CACHE": "0",
        "DOCKER_BUILD_PROVENANCE": "0",
        "DOCKER_BUILD_LOCAL_CACHE_ENABLED": "0",
        "DOCKER_BUILD_BAKE_SERIAL_MODE": "always",
        "DOCKER_BUILD_FLATTEN_FINAL_IMAGE": "1",
        "APPLY_SECURITY_HARDENING": "1",
        "DOCKER_BUILD_PROGRESS": "plain",
    }


def file_digest(path: Path) -> str:
    """Inputs: file path. Output: streamed SHA256 hex digest with bounded memory."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify_archive(container: str, archive: Path) -> None:
    """Read the entire published runtime archive back and verify its checksum.

    Inputs: carrier container and expected archive. Output: None after verified readback.
    """
    command = [
        executable("docker"),
        "cp",
        f"{container}:/omero-prebuilt/{archive.name}",
        "-",
    ]
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
        try:
            if process.stdout is None:
                raise RuntimeError("Published archive stream is unavailable.")
            with tarfile.open(fileobj=process.stdout, mode="r|") as stream:
                member = stream.next()
                if (
                    member is None
                    or not member.isfile()
                    or member.size != archive.stat().st_size
                ):
                    raise ValueError("Published runtime archive metadata mismatch.")
                content = stream.extractfile(member)
                if content is None:
                    raise ValueError("Published archive content is unavailable.")
                with content:
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: content.read(1024 * 1024), b""):
                        digest.update(chunk)
                if (
                    digest.hexdigest() != file_digest(archive)
                    or stream.next() is not None
                ):
                    raise ValueError("Published runtime archive checksum mismatch.")
            process.stdout.read()
            if process.wait() != 0:
                raise RuntimeError("Published archive download failed.")
        except BaseException:
            process.terminate()
            raise


def source_assets(release: dict) -> list[tuple]:
    """Inputs: release metadata. Output: stable identities of original source assets."""
    return sorted(
        (item["id"], item["name"], item["size"], item.get("digest"))
        for item in release["assets"]
        if re.search(r"-source\.tar\.gz(?:\.sha256)?$", item["name"])
    )


def source_commit(repository: str, version: str) -> str:
    """Resolve a public tag without changing it.

    Inputs: repository and version. Output: validated source commit identifier.
    """
    item = github(repository, f"git/ref/tags/{version}")["object"]
    for _ in range(5):
        if item.get("type") == "commit":
            sha = item.get("sha", "")
            if re.fullmatch(r"[a-f0-9]{40}", sha):
                return sha
            break
        if (
            item.get("type") != "tag"
            or re.fullmatch(r"[a-f0-9]{40}", item.get("sha", "")) is None
        ):
            break
        item = github(repository, f"git/tags/{item['sha']}")["object"]
    raise ValueError("Historical GitHub tag does not resolve to a valid commit.")


def require_unchanged_release(before: dict, after: dict) -> None:
    """Reject concurrent release edits before overwriting any carrier metadata.

    Inputs: release snapshots. Output: None, or ValueError on changed content.
    """

    def identities(release):
        """Inputs: release assets. Output: stable identities excluding download counts."""
        return sorted(
            (item["id"], item["name"], item["size"], item.get("digest"))
            for item in release["assets"]
        )

    if any(
        before.get(key) != after.get(key) for key in ("id", "body", "published_at")
    ) or identities(before) != identities(after):
        raise ValueError(
            "Historical release changed during recovery; reconciliation stopped."
        )


def restore(version: str, docker_repository: str) -> None:
    """Rebuild, analyze, publish and reconcile one explicitly authorized missing tag.

    Inputs: release version and Docker repository. Output: verified recovery metadata.
    """
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
    ):
        raise ValueError("Recovery requires an isolated GitHub-hosted runner.")
    if (
        os.environ.get("DOCKER_HOST")
        or os.environ.get("DOCKER_CONTEXT", "default") != "default"
    ):
        raise ValueError("Recovery cannot use a remote Docker context.")
    repository = os.environ["GITHUB_REPOSITORY"]
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise ValueError("Invalid GitHub repository.")
    require_missing_tag(docker_repository, version)
    release = github(repository, f"releases/tags/{version}")
    if (
        release.get("draft")
        or release.get("immutable")
        or len(source_assets(release)) != 2
    ):
        raise ValueError(
            "Recovery requires an existing mutable release with source assets."
        )
    references = sorted(set(re.findall(r"sha256:[a-f0-9]{64}", release["body"])))
    if len(references) > 1:
        raise ValueError("Ambiguous historical public digest references.")
    work = Path(os.environ["RUNNER_TEMP"]) / "historical-carrier-recovery"
    work.mkdir(mode=0o700)
    dist = work / "dist"
    dist.mkdir(mode=0o700)
    original_assets = {asset["name"] for asset in release["assets"]}
    for name in ("prebuilt-manifest.json", "release-notes.md"):
        if name in original_assets:
            run(
                [
                    "gh",
                    "release",
                    "download",
                    version,
                    "--repo",
                    repository,
                    "--pattern",
                    name,
                    "--dir",
                    str(dist),
                ]
            )
    manifest = json.loads((dist / "prebuilt-manifest.json").read_text(encoding="utf-8"))
    sha = output(["git", "rev-parse", f"refs/tags/{version}^{{commit}}"], cwd=REPO_ROOT)
    if sha != source_commit(repository, version):
        raise ValueError("Fetched source tag differs from GitHub.")
    required = validate_original(manifest, version, docker_repository, sha)
    notes = release_notes(release, manifest, dist)
    source = work / "source"
    run(["git", "worktree", "add", "--detach", str(source), sha], cwd=REPO_ROOT)
    correction = correct_historical_fetch(source)
    env = configure_build(source, work)
    for operation in ("check", "compose-guard"):
        run(
            [
                sys.executable,
                str(source / "tools/env_safety_guard.py"),
                "--repo-root",
                str(source),
                operation,
            ],
            env=env,
        )
    actual = sorted(
        set(
            output(
                ["docker", "compose", "config", "--images"], cwd=source, env=env
            ).splitlines()
        )
    )
    if actual != required:
        raise ValueError("Historical source and release runtime inventories differ.")
    run(["bash", "installation/docker_buildx_compressed_push.sh"], cwd=source, env=env)
    changed_paths = output(
        ["git", "diff", "--name-only", "HEAD"], cwd=source
    ).splitlines()
    if changed_paths != ([correction["path"]] if correction else []):
        raise ValueError(
            "Historical source changed outside the recorded build correction."
        )
    if (
        correction
        and file_digest(source / correction["path"]) != correction["rebuilt_sha256"]
    ):
        raise ValueError("Historical build correction changed during the rebuild.")
    required_file = dist / "prebuilt-required-images.txt"
    required_file.write_text("\n".join(required) + "\n", encoding="utf-8")
    run(
        [
            sys.executable,
            str(REPO_ROOT / "tools/prune_non_required_docker_images.py"),
            "--required-images-file",
            str(required_file),
            "--execute",
        ]
    )
    for image in required:
        present = subprocess.run(
            [executable("docker"), "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if present.returncode:
            run(["docker", "pull", image])
    scan_images(required, work / "runtime-analysis")
    archive = dist / "runtime-images.tar.gz"
    with subprocess.Popen(
        [executable("docker"), "save", *required], stdout=subprocess.PIPE
    ) as process:
        try:
            if process.stdout is None:
                raise RuntimeError("Runtime export stream is unavailable.")
            raw_bytes = write_archive(
                input_stream=cast(BinaryIO, process.stdout),
                archive_path=archive,
                raw_bytes_path=dist / "runtime-images-uncompressed.bytes",
            )
            if process.wait() != 0:
                raise RuntimeError("Runtime export failed.")
        except BaseException:
            process.terminate()
            raise
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    image = f"{docker_repository}:{version}"
    manifest.update(
        image_archive_sha256=file_digest(archive),
        runtime_images_archive_bytes=archive.stat().st_size,
        runtime_images_uncompressed_bytes=raw_bytes,
        release_notes="release-notes.md",
        release_notes_sha256=hashlib.sha256(notes).hexdigest(),
        rebuild_timestamp=created,
        rebuild_recipe_corrections=[correction] if correction else [],
        recovery_tool_commit=output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT),
    )
    (dist / "prebuilt-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.copyfile(
        REPO_ROOT / "docker/prebuilt-carrier.Dockerfile", dist / "Dockerfile"
    )
    require_missing_tag(docker_repository, version)
    labels = {
        "org.opencontainers.image.title": "OMERO Docker Extended prebuilt carrier",
        "org.opencontainers.image.description": "Historical runtime bundle with recorded source and build provenance",
        "org.opencontainers.image.version": version,
        "org.opencontainers.image.revision": sha,
        "org.opencontainers.image.source": f"https://github.com/{repository}",
        "org.opencontainers.image.documentation": f"https://github.com/{repository}/releases/tag/{version}",
        "org.opencontainers.image.created": created,
    }
    if sha != source_commit(repository, version):
        raise ValueError("Historical source tag changed before publication.")
    require_unchanged_release(release, github(repository, f"releases/tags/{version}"))
    builder = "historical-carrier"
    run(
        [
            "docker",
            "buildx",
            "create",
            "--name",
            builder,
            "--driver",
            "docker-container",
            "--bootstrap",
        ]
    )
    try:
        command = [
            "docker",
            "buildx",
            "build",
            "--builder",
            builder,
            "--push",
            "--provenance=true",
            "--sbom=true",
            "--progress",
            "plain",
            "-t",
            image,
        ]
        for key, value in labels.items():
            command.extend(["--label", f"{key}={value}"])
        run([*command, "."], cwd=dist)
    finally:
        run(["docker", "buildx", "rm", builder])
    run(["docker", "pull", image])
    info = json.loads(output(["docker", "image", "inspect", image]))[0]
    if any(info["Config"]["Labels"].get(key) != value for key, value in labels.items()):
        raise ValueError("Published carrier labels differ from verified source.")
    digest = next(
        ref.split("@", 1)[1]
        for ref in info["RepoDigests"]
        if ref.startswith(docker_repository + "@")
    )
    published = docker_tag(docker_repository, version)
    if published is None or published.get("digest") != digest:
        raise ValueError("Docker Hub and downloaded carrier digests differ.")
    container = output(["docker", "create", image])
    try:
        for name in (
            "prebuilt-manifest.json",
            "prebuilt-required-images.txt",
            "release-notes.md",
        ):
            destination = dist / ("verified-" + name)
            run(
                [
                    "docker",
                    "cp",
                    f"{container}:/omero-prebuilt/{name}",
                    str(destination),
                ]
            )
            if destination.read_bytes() != (dist / name).read_bytes():
                raise ValueError("Published carrier content mismatch.")
        verify_archive(container, archive)
    finally:
        run(["docker", "rm", container])
    fields = {
        "PREBUILT_IMAGE_REPOSITORY": docker_repository,
        "PREBUILT_IMAGE_RELEASE": version,
        "PREBUILT_IMAGE_DIGEST": digest,
        "PREBUILT_IMAGE_REF": image + "@" + digest,
        "CARRIER_IMAGE": image,
        "GITHUB_SHA": sha,
    }
    (dist / "prebuilt-carrier-digest.txt").write_text(
        "".join(f"{key}={value}\n" for key, value in fields.items()), encoding="utf-8"
    )
    run(
        [
            "docker",
            "scout",
            "push",
            "--org",
            docker_repository.split("/")[0],
            "--sbom",
            image,
        ]
    )
    run(
        [
            "docker",
            "scout",
            "cves",
            "--format",
            "sarif",
            "--output",
            str(work / "carrier-analysis.sarif"),
            "registry://" + image,
        ]
    )
    names = ["prebuilt-manifest.json", "prebuilt-carrier-digest.txt"]
    if "release-notes.md" not in original_assets:
        names.append("release-notes.md")
    require_unchanged_release(release, github(repository, f"releases/tags/{version}"))
    run(
        [
            "gh",
            "release",
            "upload",
            version,
            "--repo",
            repository,
            "--clobber",
            *(str(dist / name) for name in names),
        ]
    )
    if references:
        body = release["body"].replace(references[0], digest)
        body_path = work / "public-body.md"
        body_path.write_text(body, encoding="utf-8")
        run(
            [
                "gh",
                "release",
                "edit",
                version,
                "--repo",
                repository,
                "--notes-file",
                str(body_path),
            ]
        )
    after = github(repository, f"releases/tags/{version}")
    if (
        after["id"] != release["id"]
        or after["published_at"] != release["published_at"]
        or source_assets(after) != source_assets(release)
        or source_commit(repository, version) != sha
    ):
        raise ValueError("Historical release or source assets changed during recovery.")
    for name in names:
        asset = next(item for item in after["assets"] if item["name"] == name)
        if asset.get("digest") != "sha256:" + file_digest(dist / name):
            raise ValueError("Published GitHub asset checksum mismatch.")
    result = {"tag": version, "git_sha": sha, "digest": digest, "rebuilt_at": created}
    (dist / "restoration-result.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Restored and verified historical carrier {version} at {digest}.", flush=True
    )


def main(argv=None) -> int:
    """Inputs: CLI arguments. Output: zero only after authorized, verified recovery."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-version", required=True, type=validate_release_version
    )
    parser.add_argument(
        "--docker-repository", required=True, type=validate_docker_repository
    )
    parser.add_argument("--authorize-replace-manifest", action="store_true")
    parser.add_argument("--authorize-replace-digest", action="store_true")
    args = parser.parse_args(argv)
    if not args.authorize_replace_manifest or not args.authorize_replace_digest:
        parser.error("Both exact release metadata replacements require authorization.")
    restore(args.release_version, args.docker_repository)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
