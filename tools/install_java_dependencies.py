"""Install reviewed Java dependency sets in a disposable Docker build layer.

The CycloneDX lock records both the expected upstream input and the replacement.
This is not an in-place updater for a running installation.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET  # nosec B405 - reviewed build lock; DTDs rejected below
import zipfile


MAVEN_REPOSITORIES = {
    "central": "https://repo.maven.apache.org/maven2/",
    "unidata": "https://artifacts.unidata.ucar.edu/releases/",
}
CYCLONEDX_NAMESPACE = "{http://cyclonedx.org/schema/bom/1.6}"  # DevSkim: ignore DS137138 - XML namespace identifier, never a network request


@dataclass(frozen=True)
class Artifact:
    """One reviewed Maven artifact and its expected distribution input."""

    group: str
    name: str
    version: str
    sha256: str
    source_version: str | None
    source_sha256: str | None
    repository: str = "central"
    pom_sha256: str | None = None
    source_absent: bool = False
    manifest_version: str | None = None

    @property
    def filename(self) -> str:
        """Return the Maven filename. Inputs: self. Output: filename string."""
        return f"{self.name}-{self.version}.jar"


def _token(value: object) -> str:
    """Validate a coordinate segment. Inputs: value. Output: safe token."""
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*", value
    ):
        raise ValueError("Invalid Maven coordinate or source version")
    return value


def _checksum(value: object) -> str:
    """Validate a SHA-256 pin. Inputs: value. Output: hexadecimal digest."""
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Every Java artifact requires a lowercase SHA-256 pin")
    return value


def read_xml(text: str, description: str) -> ET.Element:
    """Parse metadata without DTDs or entities.

    Inputs: XML text and diagnostic description. Output: parsed root or ValueError.
    """
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.IGNORECASE):
        raise ValueError(f"{description} must not declare a DTD or entities")
    try:
        return ET.fromstring(text)  # nosec B314 - declarations rejected before parsing
    except ET.ParseError as error:
        raise ValueError(f"Malformed {description}") from error


def read_lock(lock: Path) -> object:
    """Read a strict CycloneDX document. Inputs: lock path. Output: parsed lock."""
    text = lock.read_text(encoding="utf-8")
    if lock.suffix != ".xml":
        return json.loads(text)
    root = read_xml(text, "XML dependency lock")
    namespace = CYCLONEDX_NAMESPACE
    if root.tag != namespace + "bom" or root.get("version") != "1":
        raise ValueError("Expected a version 1 CycloneDX 1.6 dependency lock")
    components = []
    for component in root.findall(f"{namespace}components/{namespace}component"):
        values: dict[str, object] = {"type": component.get("type")}
        for key in ("group", "name", "version", "purl"):
            elements = component.findall(namespace + key)
            if len(elements) != 1:
                raise ValueError("Missing or duplicate XML component field")
            values[key] = elements[0].text
        values["hashes"] = [
            {"alg": item.get("alg"), "content": item.text}
            for item in component.findall(f"{namespace}hashes/{namespace}hash")
        ]
        values["properties"] = [
            {"name": item.get("name"), "value": item.text}
            for item in component.findall(f"{namespace}properties/{namespace}property")
        ]
        components.append(values)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "components": components,
    }


def load_artifacts(lock: Path, profile: str) -> list[Artifact]:
    """Read a strict, scanner-readable lock. Inputs: lock, profile. Output: artifacts."""
    if profile not in {
        "server",
        "client",
        "converter",
        "server-plugin",
        "client-plugin",
    }:
        raise ValueError("Unknown Java dependency profile")
    data = read_lock(lock)
    if not isinstance(data, dict) or (
        data.get("bomFormat"),
        data.get("specVersion"),
        data.get("version"),
    ) != ("CycloneDX", "1.6", 1):
        raise ValueError("Expected a version 1 CycloneDX 1.6 dependency lock")
    components = data.get("components")
    if not isinstance(components, list):
        raise ValueError("Dependency lock has no component list")
    artifacts = []
    seen = set()
    for component in components:
        if not isinstance(component, dict) or component.get("type") != "library":
            raise ValueError("Expected a library component")
        group, name, version = (
            _token(component.get(key)) for key in ("group", "name", "version")
        )
        if (group, name) in seen:
            raise ValueError("Duplicate Java dependency coordinate")
        seen.add((group, name))
        if component.get("purl") != f"pkg:maven/{group}/{name}@{version}":
            raise ValueError("Maven package URL does not match its coordinate")
        hashes = component.get("hashes")
        if (
            not isinstance(hashes, list)
            or len(hashes) != 1
            or not isinstance(hashes[0], dict)
            or hashes[0].get("alg") != "SHA-256"
        ):
            raise ValueError("Expected exactly one SHA-256 artifact hash")
        checksum = _checksum(hashes[0].get("content"))
        properties = component.get("properties")
        if not isinstance(properties, list):
            raise ValueError("Missing reviewed source properties")
        values = {}
        for prop in properties:
            if (
                not isinstance(prop, dict)
                or not isinstance(prop.get("name"), str)
                or not isinstance(prop.get("value"), str)
                or prop["name"] in values
            ):
                raise ValueError("Invalid or duplicate source property")
            values[prop["name"]] = prop["value"]
        source_profile = profile
        if profile == "client" and not any(
            key.startswith("omero:client:") for key in values
        ):
            source_profile = "server"
        source_version = values.get(f"omero:{source_profile}:source-version")
        source_checksum = values.get(f"omero:{source_profile}:source-sha256")
        source_state = values.get(f"omero:{source_profile}:source-state")
        repository = values.get("omero:repository", "central")
        if repository not in MAVEN_REPOSITORIES:
            raise ValueError("Unknown reviewed Maven repository")
        pom_checksum = values.get("omero:pom-sha256")
        manifest_version = values.get("omero:manifest-version")
        if manifest_version is not None and pom_checksum is None:
            raise ValueError(
                "Noncanonical manifest versions require a separately pinned POM"
            )
        if source_state is not None:
            if (
                source_state not in {"absent", "present"}
                or profile not in {"server-plugin", "client-plugin"}
                or (
                    source_state == "absent"
                    and (source_version is not None or source_checksum is not None)
                )
            ):
                raise ValueError(
                    "Only new server-plugin or client-plugin manifests may declare explicit source state"
                )
        elif source_version is None and source_checksum is None:
            continue
        artifacts.append(
            Artifact(
                group,
                name,
                version,
                checksum,
                None
                if source_state == "absent"
                or (source_state == "present" and source_version is None)
                else _token(source_version),
                None if source_state == "absent" else _checksum(source_checksum),
                repository,
                _checksum(pom_checksum) if pom_checksum is not None else None,
                source_state == "absent",
                _token(manifest_version) if manifest_version is not None else None,
            )
        )
    if not artifacts:
        raise ValueError("Dependency profile is empty")
    return artifacts


def file_digest(path: Path) -> str:
    """Hash without loading whole JARs. Inputs: path. Output: SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def plan_installation(
    root: Path, profile: str, artifacts: list[Artifact]
) -> list[tuple[Path | None, Path, Artifact]]:
    """Verify all inputs before downloads or writes. Inputs: layout. Output: plan."""
    directories = {
        "server": ("lib/client", "lib/server"),
        "client": ("lib/client",),
        "converter": ("lib",),
        "server-plugin": ("lib/server",),
        "client-plugin": ("lib/client",),
    }[profile]
    plan: list[tuple[Path | None, Path, Artifact]] = []
    targets: set[Path] = set()
    for subdirectory in directories:
        directory = root / subdirectory
        if not directory.is_dir() or directory.resolve() != directory:
            raise ValueError("Java classpath directory is missing or is a symlink")
        for artifact in artifacts:
            old_name = (
                f"{artifact.name}.jar"
                if profile != "converter"
                else f"{artifact.name}-{artifact.source_version}.jar"
            )
            source = directory / old_name
            addition = artifact.source_absent
            destination = (
                directory / artifact.filename
                if addition or profile == "converter"
                else source
            )
            if destination in targets:
                raise ValueError("Colliding Java artifact destinations")
            targets.add(destination)
            if addition:
                if (
                    profile not in {"server-plugin", "client-plugin"}
                    or artifact.source_sha256 is not None
                    or artifact.source_version is not None
                ):
                    raise ValueError(
                        "Unexpected source absence outside server-plugin profile"
                    )
                conflicts = {
                    source,
                    destination,
                    *directory.glob(f"{artifact.name}-[0-9]*.jar"),
                }
                if any(path.exists() or path.is_symlink() for path in conflicts):
                    raise ValueError(
                        f"New JAR conflicts with an existing classpath entry: {artifact.name}"
                    )
                plan.append((None, destination, artifact))
                continue
            if not source.is_file() or source.is_symlink():
                raise ValueError(f"Missing regular source JAR: {old_name}")
            if file_digest(source) != artifact.source_sha256:
                raise ValueError(f"Unreviewed source JAR: {old_name}")
            if destination != source and destination.exists():
                raise ValueError(f"Replacement JAR already exists: {destination.name}")
            alternatives = set(directory.glob(f"{artifact.name}-[0-9]*.jar")) - {source}
            if alternatives:
                raise ValueError(f"Ambiguous classpath versions: {artifact.name}")
            plan.append((source, destination, artifact))
    return plan


def updated_launcher(text: str, artifacts: list[Artifact]) -> str:
    """Update Gradle's explicit classpath only. Inputs: text, artifacts. Output: text."""
    lines = text.splitlines(keepends=True)
    matches = [
        index for index, line in enumerate(lines) if line.startswith("CLASSPATH=")
    ]
    if len(matches) != 1:
        raise ValueError("Expected one static converter CLASSPATH assignment")
    index = matches[0]
    line = lines[index]
    ending = line[len(line.rstrip("\r\n")) :]
    entries = line.rstrip("\r\n").removeprefix("CLASSPATH=").split(":")
    for artifact in artifacts:
        old = f"$APP_HOME/lib/{artifact.name}-{artifact.source_version}.jar"
        new = f"$APP_HOME/lib/{artifact.filename}"
        if entries.count(old) != 1 or (new != old and new in entries):
            raise ValueError(f"Unexpected converter classpath entry: {artifact.name}")
        entries[entries.index(old)] = new
    lines[index] = "CLASSPATH=" + ":".join(entries) + ending
    return "".join(lines)


def download_artifact(artifact: Artifact, destination: Path) -> None:
    """Download from Maven Central with bounds. Inputs: artifact, destination. Output: file."""
    curl = shutil.which("curl")
    if curl is None:
        raise RuntimeError("curl is required to build Java dependency updates")
    url = (
        MAVEN_REPOSITORIES[artifact.repository]
        + f"{artifact.group.replace('.', '/')}/{artifact.name}/{artifact.version}/"
        + f"{artifact.name}-{artifact.version}"
        + (".pom" if destination.suffix == ".pom" else ".jar")
    )
    subprocess.run(
        [
            curl,
            "--fail",
            "--silent",
            "--show-error",
            "--proto",
            "=https",
            "--connect-timeout",
            "15",
            "--max-time",
            "120",
            "--retry",
            "2",
            "--max-filesize",
            "33554432",
            "--output",
            str(destination),
            url,
        ],
        check=True,
        timeout=400,
    )


def verify_maven_pom(path: Path, artifact: Artifact) -> None:
    """Verify a literal Maven identity with an independent content pin.

    Inputs: approved POM bytes and artifact coordinate. Output: validated identity;
    rejects entities, expressions, duplicate fields and conflicting coordinates.
    """
    if file_digest(path) != artifact.pom_sha256:
        raise ValueError(f"Downloaded POM SHA-256 mismatch: {artifact.filename}")
    text = path.read_text(encoding="utf-8")
    root = read_xml(text, "reviewed Maven POM")
    namespace = "{http://maven.apache.org/POM/4.0.0}"  # DevSkim: ignore DS137138 - XML namespace identifier, never a network request
    if root.tag == "project":
        namespace = ""
    parents = root.findall(namespace + "parent")
    if (
        root.tag != namespace + "project"
        or len(parents) > 1
        or len(root.findall(namespace + "modelVersion")) != 1
        or root.findtext(namespace + "modelVersion") != "4.0.0"
    ):
        raise ValueError("Expected one Maven project and at most one parent")
    identity = []
    for key in ("groupId", "artifactId", "version"):
        fields = root.findall(namespace + key)
        if not fields and key != "artifactId" and parents:
            fields = parents[0].findall(namespace + key)
        if len(fields) != 1:
            raise ValueError("Missing or duplicate Maven POM identity field")
        identity.append(fields[0].text)
    if tuple(identity) != (artifact.group, artifact.name, artifact.version):
        raise ValueError(f"Downloaded Maven POM identity mismatch: {artifact.filename}")


def verify_artifact(path: Path, artifact: Artifact, pom: Path | None = None) -> None:
    """Check content and embedded version. Inputs: path, artifact. Output: validated JAR."""
    if file_digest(path) != artifact.sha256:
        raise ValueError(f"Downloaded SHA-256 mismatch: {artifact.filename}")
    if artifact.pom_sha256 is not None:
        if pom is None:
            raise ValueError("Missing separately pinned Maven POM")
        verify_maven_pom(pom, artifact)
    with zipfile.ZipFile(path) as archive:
        properties = f"META-INF/maven/{artifact.group}/{artifact.name}/pom.properties"
        if properties in archive.namelist():
            values = dict(
                line.split("=", 1)
                for line in archive.read(properties).decode("utf-8").splitlines()
                if "=" in line and not line.startswith("#")
            )
            valid = (
                values.get("groupId"),
                values.get("artifactId"),
                values.get("version"),
            ) == (artifact.group, artifact.name, artifact.version)
        else:
            manifest = archive.read("META-INF/MANIFEST.MF").decode("utf-8").splitlines()
            valid = any(
                f"{key}: {artifact.manifest_version or artifact.version}" in manifest
                for key in ("Implementation-Version", "Bundle-Version")
            )
            if not any(
                line.startswith(("Implementation-Version:", "Bundle-Version:"))
                for line in manifest
            ):
                valid = artifact.pom_sha256 is not None
        if not valid:
            raise ValueError(f"Downloaded Maven identity mismatch: {artifact.filename}")


def install(root: Path, lock: Path, profile: str) -> None:
    """Install a complete set in a build layer. Inputs: root, lock, profile. Output: files."""
    root = root.resolve(strict=True)
    artifacts = load_artifacts(lock, profile)
    plan = plan_installation(root, profile, artifacts)
    launcher = root / "bin/bioformats2raw"
    launcher_text = None
    if profile == "converter":
        if (
            not launcher.is_file()
            or launcher.is_symlink()
            or launcher.parent.is_symlink()
        ):
            raise ValueError("Converter launcher must be a regular distribution file")
        launcher_text = updated_launcher(
            launcher.read_text(encoding="utf-8"), artifacts
        )
    with tempfile.TemporaryDirectory(prefix="omero-java-dependencies-") as staging:
        staged = {}
        for artifact in artifacts:
            path = Path(staging) / artifact.filename
            download_artifact(artifact, path)
            pom = None
            if artifact.pom_sha256 is not None:
                pom = path.with_suffix(".pom")
                download_artifact(artifact, pom)
            verify_artifact(path, artifact, pom)
            staged[artifact] = path
        # Docker discards the entire RUN layer on failure. Never invoke on live files.
        for source, destination, artifact in plan:
            metadata = (source or destination.parent).stat()
            mode = stat.S_IMODE(metadata.st_mode) if source is not None else 0o644
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
            try:
                shutil.copyfile(staged[artifact], temporary)
                temporary.chmod(mode)
                os.chown(temporary, metadata.st_uid, metadata.st_gid)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            if source is not None and source != destination:
                source.unlink()
        if launcher_text is not None:
            launcher.write_text(launcher_text, encoding="utf-8")
    print(f"Installed {len(artifacts)} verified Java dependencies for {profile}")


def main(argv: list[str] | None = None) -> int:
    """Run the build-time installer. Inputs: argv. Output: exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument(
        "--profile",
        choices=("server", "client", "converter", "server-plugin", "client-plugin"),
        required=True,
    )
    args = parser.parse_args(argv)
    try:
        install(args.root, args.lock, args.profile)
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ) as error:
        print(f"Java dependency installation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
