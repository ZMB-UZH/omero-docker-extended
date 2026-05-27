#!/usr/bin/env python3
"""Prune local docker images outside an explicit required-image set."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


DockerRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class LocalImage:
    """Local docker image reference and immutable image ID."""

    reference: str
    image_id: str


def default_docker_runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run docker with text output captured.

    Inputs: docker CLI arguments. Output: completed process result.
    """
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker executable is required.")
    return subprocess.run(
        [docker, *args],
        check=False,
        capture_output=True,
        text=True,
    )


def validate_image_reference(value: str) -> str:
    """Validate the image reference contract used by this release helper.

    Inputs: image reference string. Output: validated image reference.
    """
    if not value or value != value.strip() or any(char.isspace() for char in value):
        raise ValueError("Image references must be non-empty and whitespace-free.")
    if value.startswith("-"):
        raise ValueError("Image references must not start with '-'.")
    if value == "latest" or value.endswith(":latest") or ":latest@" in value:
        raise ValueError("Image references must not use latest.")
    return value


def read_required_images(path: Path) -> list[str]:
    """Read required image references from a line-oriented file.

    Inputs: required-image list path. Output: sorted unique image references.
    """
    images = {
        validate_image_reference(line.strip())
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    return sorted(images)


def image_reference_from_listing(image_listing: dict[str, str]) -> str | None:
    """Build a removable image reference from `docker image ls` JSON data.

    Inputs: docker image listing JSON object. Output: image ref or `None`.
    """
    repository = image_listing.get("Repository", "")
    tag = image_listing.get("Tag", "")
    if not repository or not tag or repository == "<none>" or tag == "<none>":
        return None
    return validate_image_reference(f"{repository}:{tag}")


def inspect_present_required_image_ids(
    required_images: Sequence[str],
    runner: DockerRunner,
) -> set[str]:
    """Inspect required images already present in the local docker daemon.

    Inputs: required refs and docker runner. Output: present required image IDs.
    """
    image_ids: set[str] = set()
    for image_ref in required_images:
        result = runner(["image", "inspect", "--format", "{{.Id}}", image_ref])
        if result.returncode != 0:
            continue
        image_id = result.stdout.strip()
        if image_id:
            image_ids.add(image_id)
    return image_ids


def list_named_local_images(runner: DockerRunner) -> list[LocalImage]:
    """List named local docker images.

    Inputs: docker runner. Output: named local docker images with IDs.
    """
    result = runner(["image", "ls", "--all", "--no-trunc", "--format", "{{json .}}"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "docker image ls failed.")

    images: list[LocalImage] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            image_listing = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError("docker image ls returned invalid JSON.") from exc
        reference = image_reference_from_listing(image_listing)
        image_id = image_listing.get("ID", "").strip()
        if reference is None:
            continue
        if not image_id:
            raise RuntimeError(f"docker image ls returned no ID for {reference}.")
        images.append(LocalImage(reference=reference, image_id=image_id))
    return images


def removable_image_references(
    *,
    required_images: Sequence[str],
    local_images: Sequence[LocalImage],
    required_image_ids: set[str],
) -> list[str]:
    """Return named local image refs outside the required image set.

    Inputs: required refs, local images, and required IDs. Output: removable refs.
    """
    required_refs = set(required_images)
    removable = {
        image.reference
        for image in local_images
        if image.reference not in required_refs
        and image.image_id not in required_image_ids
    }
    return sorted(removable)


def prune_images(image_refs: Sequence[str], runner: DockerRunner) -> None:
    """Remove non-required image references, then prune dangling image data.

    Inputs: image references and docker runner. Output: removes docker image data.
    """
    for image_ref in image_refs:
        result = runner(["image", "rm", image_ref])
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"Failed to remove docker image {image_ref}: {message}")
    result = runner(["image", "prune", "--force"])
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Failed to prune dangling docker images: {message}")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse command-line arguments.

    Inputs: command-line argument list. Output: parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Prune local docker images that are not part of the release "
            "required-image list."
        )
    )
    parser.add_argument("--required-images-file", type=Path, required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually remove images. Without this flag, only prints candidates.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the pruning helper.

    Inputs: optional command-line arguments. Output: process exit status.
    """
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        required_images = read_required_images(args.required_images_file)
        required_image_ids = inspect_present_required_image_ids(
            required_images,
            default_docker_runner,
        )
        local_images = list_named_local_images(default_docker_runner)
        removable_refs = removable_image_references(
            required_images=required_images,
            local_images=local_images,
            required_image_ids=required_image_ids,
        )
        print(f"Required image references: {len(required_images)}")
        print(f"Present required image IDs: {len(required_image_ids)}")
        print(f"Non-required local image references: {len(removable_refs)}")
        for image_ref in removable_refs:
            print(f"Prune candidate: {image_ref}")
        if args.execute:
            prune_images(removable_refs, default_docker_runner)
            if removable_refs:
                print("Pruned non-required local docker image references.")
            else:
                print("No non-required named docker image references to prune.")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
