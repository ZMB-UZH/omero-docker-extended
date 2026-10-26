"""Exercise pinned Java dependency installation without network or live files."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import zipfile

import pytest

from tools import install_java_dependencies as installer


def jar_bytes(version="2.0", *, pom=True, group="example", name="library"):
    """Create a Maven JAR fixture. Inputs: identity. Output: archive bytes."""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "META-INF/MANIFEST.MF",
            f"Implementation-Version: {version}\n"
            if version is not None
            else "Manifest-Version: 1.0\n",
        )
        if pom:
            archive.writestr(
                f"META-INF/maven/{group}/{name}/pom.properties",
                f"#fixture\ngroupId={group}\nartifactId={name}\nversion={version}\n",
            )
    return stream.getvalue()


def pom_bytes(*, inherited=False, namespaced=True):
    """Build a literal published-POM fixture.

    Inputs: whether group/version are inherited. Output: namespace-qualified XML bytes.
    """
    identity = "<groupId>example</groupId><version>2.0</version>"
    if inherited:
        identity = "<parent>" + identity + "<artifactId>parent</artifactId></parent>"
    text = (
        '<project xmlns="http://maven.apache.org/POM/4.0.0">'
        "<modelVersion>4.0.0</modelVersion>"
        + identity
        + "<artifactId>library</artifactId></project>"
    )
    if not namespaced:
        text = text.replace(' xmlns="http://maven.apache.org/POM/4.0.0"', "")
    return text.encode()


@pytest.fixture
def distribution(tmp_path):
    """Provide server and converter layouts. Inputs: tmp_path. Output: fixture factory."""

    def create(profile="server", names=("library",)):
        """Build isolated fixtures. Inputs: profile, names. Output: root, lock, payloads."""
        root = tmp_path / profile
        root.mkdir()
        components = []
        payloads = {}
        source_profile = "server" if profile == "client" else profile
        for name in names:
            before = jar_bytes("1.0", name=name)
            after = jar_bytes(name=name)
            payloads[f"{name}-2.0.jar"] = after
            components.append(
                {
                    "type": "library",
                    "group": "example",
                    "name": name,
                    "version": "2.0",
                    "purl": f"pkg:maven/example/{name}@2.0",
                    "hashes": [
                        {"alg": "SHA-256", "content": hashlib.sha256(after).hexdigest()}
                    ],
                    "properties": [
                        {
                            "name": f"omero:{source_profile}:source-version",
                            "value": "1.0",
                        },
                        {
                            "name": f"omero:{source_profile}:source-sha256",
                            "value": hashlib.sha256(before).hexdigest(),
                        },
                    ],
                }
            )
            directories = {
                "server": ("lib/client", "lib/server"),
                "client": ("lib/client",),
                "converter": ("lib",),
                "server-plugin": ("lib/server",),
                "client-plugin": ("lib/client",),
            }[profile]
            for directory in directories:
                parent = root / directory
                parent.mkdir(parents=True, exist_ok=True)
                path = parent / (
                    f"{name}.jar" if profile != "converter" else f"{name}-1.0.jar"
                )
                path.write_bytes(before)
                path.chmod(0o640)
        if profile == "converter":
            (root / "bin").mkdir()
            launcher = root / "bin/bioformats2raw"
            launcher.write_text(
                "#!/bin/sh\nCLASSPATH="
                + ":".join(f"$APP_HOME/lib/{name}-1.0.jar" for name in names)
                + ':$APP_HOME/lib/unrelated.jar\nexec java -cp "$CLASSPATH" Main "$@"\n'
            )
            launcher.chmod(0o755)
        lock = tmp_path / f"{profile}.json"
        lock.write_text(
            json.dumps(
                {
                    "bomFormat": "CycloneDX",
                    "specVersion": "1.6",
                    "version": 1,
                    "components": components,
                }
            )
        )
        return root, lock, payloads

    return create


@pytest.mark.parametrize(
    "profile", ["server", "client", "converter", "server-plugin", "client-plugin"]
)
def test_installs_complete_profile_preserving_permissions(
    distribution, monkeypatch, profile
):
    """Install both layouts exactly. Inputs: isolated distributions. Output: expected bytes/modes."""
    root, lock, payloads = distribution(profile, ("library", "other"))
    monkeypatch.setattr(
        installer,
        "download_artifact",
        lambda artifact, path: path.write_bytes(payloads[artifact.filename]),
    )
    before = {
        path.relative_to(root): (path.stat().st_mode, path.stat().st_uid)
        for path in root.rglob("*.jar")
    }
    original_launcher = (
        (root / "bin/bioformats2raw").read_text() if profile == "converter" else None
    )
    assert (
        installer.main(["--root", str(root), "--lock", str(lock), "--profile", profile])
        == 0
    )
    for relative, (mode, owner) in before.items():
        name = relative.name.removesuffix(".jar").removesuffix("-1.0")
        destination = (
            root / relative
            if profile != "converter"
            else root / relative.parent / f"{name}-2.0.jar"
        )
        assert destination.read_bytes() == payloads[f"{name}-2.0.jar"]
        assert (destination.stat().st_mode, destination.stat().st_uid) == (mode, owner)
    assert not list(root.rglob("tmp*"))
    if profile == "converter":
        launcher = root / "bin/bioformats2raw"
        assert launcher.read_text() == original_launcher.replace("-1.0.jar", "-2.0.jar")
        assert launcher.stat().st_mode & 0o777 == 0o755
        assert not list(root.rglob("*-1.0.jar"))


@pytest.fixture
def plugin_addition(distribution):
    """Provide an explicitly new server-only dependency.

    Inputs: synthetic distribution factory. Output: root, manifest and pinned bytes.
    """
    root, lock, payloads = distribution("server-plugin")
    (root / "lib/server/library.jar").unlink()
    data = json.loads(lock.read_text())
    data["components"][0]["properties"] = [
        {"name": "omero:server-plugin:source-state", "value": "absent"}
    ]
    lock.write_text(json.dumps(data))
    return root, lock, payloads


def test_new_plugin_dependencies_are_explicit_and_server_only(
    plugin_addition, monkeypatch
):
    """Install only approved new JARs without touching the client classpath.

    Inputs: source-absence manifest. Output: verified bytes, ordinary read mode and parent ownership.
    """
    root, lock, payloads = plugin_addition
    client = root / "lib/client"
    client.mkdir()
    sentinel = client / "unrelated.jar"
    sentinel.write_bytes(b"unchanged client")
    parent = root / "lib/server"
    parent.chmod(0o750)
    monkeypatch.setattr(
        installer,
        "download_artifact",
        lambda artifact, path: path.write_bytes(payloads[artifact.filename]),
    )
    assert (
        installer.main(
            ["--root", str(root), "--lock", str(lock), "--profile", "server-plugin"]
        )
        == 0
    )
    installed = parent / "library-2.0.jar"
    assert installed.read_bytes() == payloads[installed.name]
    assert installed.stat().st_mode & 0o777 == 0o644
    assert (installed.stat().st_uid, installed.stat().st_gid) == (
        parent.stat().st_uid,
        parent.stat().st_gid,
    )
    assert list(client.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"unchanged client"


def test_new_client_dependencies_are_isolated_from_server_classpath(
    distribution, monkeypatch
):
    """Give the browser-import JVM the same strict addition contract in its own classpath.

    Inputs: explicitly absent client dependency. Output: verified client JAR without a server directory.
    """
    root, lock, payloads = distribution("client-plugin")
    (root / "lib/client/library.jar").unlink()
    data = json.loads(lock.read_text())
    data["components"][0]["properties"] = [
        {"name": "omero:client-plugin:source-state", "value": "absent"}
    ]
    lock.write_text(json.dumps(data))
    monkeypatch.setattr(
        installer,
        "download_artifact",
        lambda artifact, path: path.write_bytes(payloads[artifact.filename]),
    )
    assert (
        installer.main(
            ["--root", str(root), "--lock", str(lock), "--profile", "client-plugin"]
        )
        == 0
    )
    assert (root / "lib/client/library-2.0.jar").read_bytes() == payloads[
        "library-2.0.jar"
    ]
    assert not (root / "lib/server").exists()


@pytest.mark.parametrize(
    "collision", ["generic", "target", "other-version", "dangling-symlink"]
)
def test_new_plugin_dependencies_refuse_existing_classpath_entries(
    plugin_addition, monkeypatch, collision
):
    """Never reinterpret a new dependency as permission to replace a present JAR.

    Inputs: conflicting generic, versioned or symlinked entries. Output: failure before downloads.
    """
    root, lock, _ = plugin_addition
    names = {
        "generic": "library.jar",
        "target": "library-2.0.jar",
        "other-version": "library-1.0.jar",
        "dangling-symlink": "library.jar",
    }
    conflict = root / "lib/server" / names[collision]
    if collision == "dangling-symlink":
        conflict.symlink_to(root / "not-present")
    else:
        conflict.write_bytes(b"preserve")
    calls = []
    monkeypatch.setattr(installer, "download_artifact", lambda *_: calls.append(True))
    with pytest.raises(ValueError, match="conflicts"):
        installer.install(root, lock, "server-plugin")
    assert not calls
    if collision == "dangling-symlink":
        assert conflict.is_symlink()
    else:
        assert conflict.read_bytes() == b"preserve"


@pytest.mark.parametrize(
    "problem",
    ["unknown-state", "state-and-version", "state-and-hash", "unknown-repository"],
)
def test_invalid_plugin_source_contract_is_rejected(plugin_addition, problem):
    """Reject ambiguous source claims and unreviewed download origins.

    Inputs: malformed source-state declarations. Output: validation failure.
    """
    _, lock, _ = plugin_addition
    data = json.loads(lock.read_text())
    props = data["components"][0]["properties"]
    if problem == "unknown-state":
        props[0]["value"] = "optional"
    elif problem == "state-and-version":
        props.append({"name": "omero:server-plugin:source-version", "value": "1.0"})
    elif problem == "state-and-hash":
        props.append({"name": "omero:server-plugin:source-sha256", "value": "0" * 64})
    else:
        props.append({"name": "omero:repository", "value": "unreviewed"})
    lock.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        installer.load_artifacts(lock, "server-plugin")


@pytest.mark.parametrize("profile", ["server", "client", "converter"])
def test_existing_profiles_cannot_opt_into_source_absence(distribution, profile):
    """Preserve exact replacement-source requirements for all existing profiles.

    Inputs: absence declaration on an existing profile. Output: explicit rejection.
    """
    _, lock, _ = distribution(profile)
    data = json.loads(lock.read_text())
    source = "server" if profile == "client" else profile
    data["components"][0]["properties"] = [
        {"name": f"omero:{source}:source-state", "value": "absent"}
    ]
    lock.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Only new server-plugin"):
        installer.load_artifacts(lock, profile)


def test_new_jar_plan_defends_against_invalid_programmatic_artifacts(plugin_addition):
    """Keep source-absence restrictions even when the parser is not the caller.

    Inputs: directly constructed invalid plans. Output: no filesystem mutation.
    """
    root, lock, _ = plugin_addition
    artifact = installer.load_artifacts(lock, "server-plugin")[0]
    for profile, altered in [
        ("server-plugin", replace(artifact, source_sha256="0" * 64)),
        ("client", artifact),
    ]:
        (root / "lib/client").mkdir(exist_ok=True)
        with pytest.raises(ValueError, match="Unexpected source absence"):
            installer.plan_installation(root, profile, [altered])


def test_reviewed_unidata_repository_uses_bounded_native_transport(
    plugin_addition, monkeypatch, tmp_path
):
    """Keep a non-Central artifact bound to an explicit reviewed repository.

    Inputs: pinned Unidata selection. Output: exact HTTPS URL with existing transfer bounds.
    """
    _, lock, _ = plugin_addition
    data = json.loads(lock.read_text())
    data["components"][0]["properties"].append(
        {"name": "omero:repository", "value": "unidata"}
    )
    lock.write_text(json.dumps(data))
    artifact = installer.load_artifacts(lock, "server-plugin")[0]
    calls = []
    monkeypatch.setattr(installer.shutil, "which", lambda _: "/usr/bin/curl")
    monkeypatch.setattr(
        installer.subprocess, "run", lambda args, **kwargs: calls.append(args)
    )
    installer.download_artifact(artifact, tmp_path / artifact.filename)
    assert (
        calls[0][-1]
        == "https://artifacts.unidata.ucar.edu/releases/example/library/2.0/library-2.0.jar"
    )
    assert "--location" not in calls[0]


@pytest.mark.parametrize("failure", ["hash", "download", "identity"])
def test_failed_download_never_changes_any_source(distribution, monkeypatch, failure):
    """Stage the whole set first. Inputs: failed second artifact. Output: unchanged distribution."""
    root, lock, payloads = distribution("converter", ("library", "other"))
    if failure == "identity":
        payloads["other-2.0.jar"] = jar_bytes("9.0", name="other")
        data = json.loads(lock.read_text())
        data["components"][1]["hashes"][0]["content"] = hashlib.sha256(
            payloads["other-2.0.jar"]
        ).hexdigest()
        lock.write_text(json.dumps(data))
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    def download(artifact, path):
        """Inject one failure. Inputs: artifact, path. Output: fixture or exception."""
        if artifact.name == "other" and failure == "download":
            raise subprocess.CalledProcessError(22, ["curl"])
        path.write_bytes(
            b"corrupt"
            if artifact.name == "other" and failure == "hash"
            else payloads[artifact.filename]
        )

    monkeypatch.setattr(installer, "download_artifact", download)
    assert (
        installer.main(
            ["--root", str(root), "--lock", str(lock), "--profile", "converter"]
        )
        == 1
    )
    assert before == {
        path: path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize(
    "problem", ["missing", "changed", "symlink", "directory", "alternate", "collision"]
)
def test_rejects_unreviewed_sources_before_network(distribution, monkeypatch, problem):
    """Fail closed on upstream drift. Inputs: invalid layout. Output: preflight rejection."""
    root, lock, _ = distribution("converter")
    source = root / "lib/library-1.0.jar"
    if problem == "missing":
        source.unlink()
    elif problem == "changed":
        source.write_bytes(b"unreviewed")
    elif problem == "symlink":
        target = root / "original.jar"
        source.rename(target)
        source.symlink_to(target)
    elif problem == "directory":
        (root / "lib").rename(root / "elsewhere")
        (root / "lib").symlink_to(root / "elsewhere", target_is_directory=True)
    else:
        (
            root
            / "lib"
            / ("library-2.0.jar" if problem == "collision" else "library-9.0.jar")
        ).write_bytes(b"alternate")

    def forbidden(*_args):
        """Reject network use. Inputs: ignored. Output: assertion failure."""
        pytest.fail("Preflight must finish before any download")

    monkeypatch.setattr(installer, "download_artifact", forbidden)
    with pytest.raises(ValueError):
        installer.install(root, lock, "converter")


@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "duplicate",
        "missing-entry",
        "duplicate-entry",
        "new-entry",
        "symlink",
    ],
)
def test_rejects_launcher_drift(distribution, monkeypatch, problem):
    """Require the reviewed launcher shape. Inputs: changed launcher. Output: rejection."""
    root, lock, _ = distribution("converter")
    launcher = root / "bin/bioformats2raw"
    text = launcher.read_text()
    if problem == "missing":
        launcher.unlink()
    elif problem == "symlink":
        launcher.rename(root / "original-launcher")
        launcher.symlink_to(root / "original-launcher")
    else:
        mutations = {
            "duplicate": text + "CLASSPATH=again\n",
            "missing-entry": text.replace("library-1.0", "different-1.0"),
            "duplicate-entry": text.replace("unrelated.jar", "library-1.0.jar"),
            "new-entry": text.replace("unrelated.jar", "library-2.0.jar"),
        }
        launcher.write_text(mutations[problem])
    monkeypatch.setattr(
        installer, "download_artifact", lambda *_: pytest.fail("Unexpected download")
    )
    with pytest.raises(ValueError):
        installer.install(root, lock, "converter")


@pytest.mark.parametrize(
    "field,value",
    [
        ("type", "application"),
        ("group", "../escape"),
        ("name", "--output"),
        ("version", None),
        ("purl", "pkg:maven/wrong/library@2.0"),
        ("hashes", []),
        ("hashes", [None]),
        ("hashes", [{"alg": "SHA-512", "content": "0" * 128}]),
        ("hashes", [{"alg": "SHA-256", "content": "0" * 63}]),
        ("properties", None),
        ("properties", [None]),
        ("properties", [{"name": "name", "value": None}]),
        ("properties", [{"name": "x", "value": "a"}, {"name": "x", "value": "b"}]),
        ("properties", [{"name": "omero:server:source-version", "value": "1.0"}]),
        ("properties", [{"name": "omero:server:source-sha256", "value": "0" * 64}]),
    ],
)
def test_invalid_component_is_rejected(distribution, field, value):
    """Validate coordinates and pins. Inputs: malformed component. Output: rejection."""
    _, lock, _ = distribution()
    data = json.loads(lock.read_text())
    data["components"][0][field] = value
    lock.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        installer.load_artifacts(lock, "server")


@pytest.mark.parametrize(
    "problem",
    [
        "not-object",
        "format",
        "components",
        "empty",
        "component",
        "duplicate",
        "profile",
    ],
)
def test_invalid_document_is_rejected(distribution, problem):
    """Require an unambiguous lock. Inputs: malformed document. Output: rejection."""
    _, lock, _ = distribution()
    data = json.loads(lock.read_text())
    if problem == "not-object":
        data = []
    elif problem == "format":
        data["specVersion"] = "0"
    elif problem == "components":
        data["components"] = None
    elif problem == "empty":
        data["components"] = []
    elif problem == "component":
        data["components"] = [None]
    elif problem == "duplicate":
        data["components"] *= 2
    lock.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        installer.load_artifacts(lock, "invalid" if problem == "profile" else "server")


def test_manifest_identity_and_download_bounds(tmp_path, monkeypatch):
    """Verify fallback metadata and bounded HTTPS. Inputs: fake curl. Output: verified invocation."""
    content = jar_bytes(pom=False)
    artifact = installer.Artifact(
        "example",
        "library",
        "2.0",
        hashlib.sha256(content).hexdigest(),
        "1.0",
        "0" * 64,
    )
    path = tmp_path / "library.jar"
    path.write_bytes(content)
    installer.verify_artifact(path, artifact)
    with pytest.raises(ValueError, match="identity"):
        installer.verify_artifact(path, replace(artifact, version="3.0"))
    calls = []
    monkeypatch.setattr(installer.shutil, "which", lambda _: "/usr/bin/curl")
    monkeypatch.setattr(
        installer.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs))
    )
    installer.download_artifact(artifact, path)
    args, kwargs = calls[0]
    assert (
        args[-1]
        == "https://repo.maven.apache.org/maven2/example/library/2.0/library-2.0.jar"
    )
    assert args[args.index("--proto") + 1] == "=https"
    assert args[args.index("--max-time") + 1] == "120"
    assert args[args.index("--max-filesize") + 1] == "33554432"
    assert "--location" not in args
    assert kwargs == {"check": True, "timeout": 400}
    monkeypatch.setattr(installer.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="curl"):
        installer.download_artifact(artifact, path)


def test_colliding_plan_and_failed_install_cleanup(distribution, monkeypatch):
    """Refuse collisions and clean staging after I/O failure. Inputs: fixtures. Output: fail closed."""
    root, lock, payloads = distribution()
    artifacts = installer.load_artifacts(lock, "server")
    with pytest.raises(ValueError, match="Colliding"):
        installer.plan_installation(root, "server", artifacts * 2)
    monkeypatch.setattr(
        installer,
        "download_artifact",
        lambda artifact, path: path.write_bytes(payloads[artifact.filename]),
    )
    monkeypatch.setattr(
        installer.os, "chown", lambda *_: (_ for _ in ()).throw(OSError("injected"))
    )
    before = sorted(
        path.relative_to(root) for path in root.rglob("*") if path.is_file()
    )
    with pytest.raises(OSError, match="injected"):
        installer.install(root, lock, "server")
    assert (
        sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file())
        == before
    )


def test_repository_lock_keeps_dependency_families_aligned():
    """Protect curated compatibility sets. Inputs: committed lock. Output: family contracts."""
    repo = Path(__file__).resolve().parents[1]
    lock = repo / "docker/java-dependencies.cdx.xml"
    server = {item.name: item for item in installer.load_artifacts(lock, "server")}
    converter = {
        item.name: item for item in installer.load_artifacts(lock, "converter")
    }
    assert len(server) == 23
    client = {item.name: item for item in installer.load_artifacts(lock, "client")}
    assert len(client) == 28
    assert all(client[name] == artifact for name, artifact in server.items())
    assert len(converter) == 28
    netty = [item for item in converter.values() if item.group == "io.netty"]
    assert len(netty) == 10
    assert {item.version for item in netty} == {"4.1.139.Final"}
    assert (
        converter["logback-core"].version
        == converter["logback-classic"].version
        == client["logback-core"].version
        == client["logback-classic"].version
        == "1.6.6"
    )
    for profile in (server, converter):
        assert (
            profile["jackson-core"].version
            == profile["jackson-databind"].version
            == "2.22.4"
        )
        assert profile["jackson-annotations"].version == "2.22"
    assert server["json-smart"].version == server["accessors-smart"].version == "2.6.0"
    assert server["slf4j-api"].version == converter["slf4j-api"].version == "2.0.20"
    assert client["pdfbox"].version == client["fontbox"].version == "2.0.37"
    assert client["postgresql"].version == "42.7.14"
    assert server["snakeyaml"].version == "2.7"
    assert server["httpclient5"].version == "5.6.5"
    assert server["httpcore5"].version == server["httpcore5-h2"].version == "5.4.4"
    assert server["junit"].version == "4.13.2"
    assert server["asm"].version == "9.11.1"
    assert converter["ion-java"].group == "com.amazon.ion"
    assert converter["ion-java"].version == "1.12.1"
    assert converter["tika-core"].version == "3.3.3"
    assert {
        converter["aws-java-sdk-" + name].version for name in ("core", "s3", "kms")
    } == {"1.12.797"}
    assert (
        server["commons-lang3"].version
        == converter["commons-lang3"].version
        == "3.21.0"
    )
    for filename, profile in (
        ("omero-server.Dockerfile", "server"),
        ("omero-web.Dockerfile", "converter"),
    ):
        text = (repo / "docker" / filename).read_text()
        assert f"--profile {profile}" in text
        assert "COPY docker/java-dependencies.cdx.xml" in text
        assert text.index("COPY tools/install_java_dependencies.py") < text.index(
            "COPY docker/remove-build-dependencies.sh"
        )
    server_text = (repo / "docker/omero-server.Dockerfile").read_text()
    web_text = (repo / "docker/omero-web.Dockerfile").read_text()
    upstream_server = next(
        line for line in server_text.splitlines() if line.startswith("FROM ")
    )
    assert upstream_server + " AS omero-client" in web_text
    assert "COPY --from=omero-client" in web_text
    assert "--profile client --root /opt/omero/client" in web_text
    assert "ENV OMERO_IMPORT_CLIENT_DIR=/opt/omero/client/lib/client" in web_text
    assert "OMERO_IMPORT_JAVA_HOME=/usr/lib/jvm/jre-17-openjdk" in web_text


def test_pixel_runtime_lock_preserves_complete_compatible_cohort():
    """Check reviewed classpath and scanner scope.

    Inputs: committed runtime/core locks and recipes. Output: aligned dependency assertions.
    """
    repo = Path(__file__).resolve().parents[1]
    lock = repo / "docker/zarr-pixel-runtime.cdx.xml"
    components = installer.read_lock(lock)["components"]
    runtime = {
        (item["group"], item["name"]): (
            item["version"],
            item["hashes"][0]["content"],
        )
        for item in components
    }
    assert len(runtime) == len(components) == 86
    server = installer.load_artifacts(lock, "server-plugin")
    client = installer.load_artifacts(lock, "client-plugin")
    assert len(server) == 69
    assert len(client) == 5
    assert {
        version
        for (group, _), (version, _) in runtime.items()
        if group == "software.amazon.awssdk"
    } == {"2.57.3"}
    assert {
        version for (group, _), (version, _) in runtime.items() if group == "io.netty"
    } == {"4.1.139.Final"}
    assert runtime["dev.zarr", "zarr-java"][0] == "0.3.1"
    assert runtime["edu.ucar", "cdm-core"][0] == "5.11.0"
    assert runtime["com.google.guava", "guava"][0] == "33.7.2-jre"
    core_lock = repo / "docker/java-dependencies.cdx.xml"
    for profile in ("server", "client", "converter"):
        for artifact in installer.load_artifacts(core_lock, profile):
            coordinate = artifact.group, artifact.name
            if coordinate in runtime:
                assert runtime[coordinate] == (artifact.version, artifact.sha256)
    for suffix, profile in (("server", "server-plugin"), ("web", "client-plugin")):
        text = (repo / f"docker/omero-{suffix}.Dockerfile").read_text()
        assert "COPY docker/zarr-pixel-runtime.cdx.xml" in text
        assert f"--profile {profile}" in text
        assert "--lock /usr/local/share/omero-zarr-pixel-runtime.cdx.xml" in text
    server_text = (repo / "docker/omero-server.Dockerfile").read_text()
    assert '--profile client-plugin --root "${SERVER_DIR}"' in server_text
    assert server_text.index(
        '--profile server --root "${SERVER_DIR}"'
    ) < server_text.index('--profile client-plugin --root "${SERVER_DIR}"')
    pixel_version, pixel_hash = runtime[
        "com.glencoesoftware.omero", "omero-zarr-pixel-buffer"
    ]
    assert f"ARG OMERO_ZARR_PIXEL_BUFFER_VERSION={pixel_version}" in server_text
    assert f"ARG OMERO_ZARR_PIXEL_BUFFER_SHA256={pixel_hash}" in server_text


def test_explicit_client_source_overrides_shared_server_source(distribution):
    """Check consumer-specific pins. Inputs: fixture lock. Output: source assertions."""
    _root, lock, _payloads = distribution()
    document = json.loads(lock.read_text())
    document["components"][0]["properties"].extend(
        [
            {"name": "omero:client:source-version", "value": "0.9"},
            {"name": "omero:client:source-sha256", "value": "c" * 64},
        ]
    )
    lock.write_text(json.dumps(document))
    assert installer.load_artifacts(lock, "server")[0].source_version == "1.0"
    assert installer.load_artifacts(lock, "client")[0].source_version == "0.9"
    document["components"][0]["properties"].pop()
    lock.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="SHA-256"):
        installer.load_artifacts(lock, "client")


@pytest.mark.parametrize(
    "problem",
    [
        "declaration",
        "entity",
        "malformed",
        "namespace",
        "version",
        "duplicate",
        "missing",
        "empty",
    ],
)
def test_xml_lock_rejects_unsafe_or_ambiguous_documents(tmp_path, problem):
    """Reject invalid XML before downloads. Inputs: lock variants. Output: assertions."""
    source = Path(__file__).resolve().parents[1] / "docker/java-dependencies.cdx.xml"
    text = source.read_text()
    if problem == "declaration":
        text = text.replace(
            "<bom ", '<!DOCTYPE bom [<!ENTITY test "expansion">]><bom ', 1
        )
    elif problem == "entity":
        text = text.replace("<bom ", '<!ENTITY test "expansion"><bom ', 1)
    elif problem == "malformed":
        text = "<bom"
    elif problem == "namespace":
        text = text.replace("schema/bom/1.6", "schema/bom/0.0")
    elif problem == "version":
        text = text.replace('version="1"', 'version="2"')
    elif problem == "duplicate":
        text = text.replace("<group>", "<group>unexpected</group><group>", 1)
    elif problem == "missing":
        text = text.replace("<group>", "<other>", 1).replace("</group>", "</other>", 1)
    else:
        text = text[: text.index("  <components>")] + "</bom>"
    lock = tmp_path / "dependency.cdx.xml"
    lock.write_text(text)
    with pytest.raises(ValueError):
        installer.load_artifacts(lock, "server")


def test_module_entrypoint_reports_invalid_root(tmp_path, monkeypatch):
    """Exercise the real CLI entrypoint. Inputs: absent root. Output: nonzero exit."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "install_java_dependencies.py",
            "--root",
            str(tmp_path / "absent"),
            "--lock",
            str(tmp_path / "absent.json"),
            "--profile",
            "server",
        ],
    )
    with pytest.raises(SystemExit) as result:
        runpy.run_path(installer.__file__, run_name="__main__")
    assert result.value.code == 1


@pytest.mark.parametrize("inherited", [False, True])
@pytest.mark.parametrize("namespaced", [False, True])
def test_metadata_less_jar_requires_independently_pinned_pom(
    plugin_addition, monkeypatch, inherited, namespaced
):
    """Verify a metadata-less JAR through two content pins and literal coordinates.

    Inputs: native-style empty manifest and a reviewed POM. Output: verified installation.
    """
    root, lock, payloads = plugin_addition
    jar = jar_bytes(None, pom=False)
    pom = pom_bytes(inherited=inherited, namespaced=namespaced)
    data = json.loads(lock.read_text())
    data["components"][0]["hashes"][0]["content"] = hashlib.sha256(jar).hexdigest()
    data["components"][0]["properties"].append(
        {"name": "omero:pom-sha256", "value": hashlib.sha256(pom).hexdigest()}
    )
    lock.write_text(json.dumps(data))
    payloads.update({"library-2.0.jar": jar, "library-2.0.pom": pom})
    monkeypatch.setattr(
        installer,
        "download_artifact",
        lambda _, path: path.write_bytes(payloads[path.name]),
    )
    installer.install(root, lock, "server-plugin")
    assert (root / "lib/server/library-2.0.jar").read_bytes() == jar
    assert not list(root.rglob("*.pom"))


@pytest.mark.parametrize(
    "problem",
    [
        "hash",
        "xml",
        "doctype",
        "root",
        "model",
        "duplicate-model",
        "parents",
        "missing-group",
        "missing-artifact",
        "duplicate-artifact",
        "missing-parent-version",
        "group",
        "artifact",
        "version",
        "expression",
        "namespace",
    ],
)
def test_paired_pom_identity_fails_closed(plugin_addition, tmp_path, problem):
    """Reject malformed or conflicting metadata even when its bytes are pinned.

    Inputs: damaged literal-POM fixtures. Output: explicit validation failure.
    """
    _, lock, _ = plugin_addition
    artifact = installer.load_artifacts(lock, "server-plugin")[0]
    original = pom_bytes(inherited=problem == "missing-parent-version").decode()
    changes = {
        "xml": ("</project>", ""),
        "doctype": ("<project", '<!DOCTYPE project [<!ENTITY x "text">]><project'),
        "root": ("<project ", "<wrong "),
        "model": ("<modelVersion>4.0.0</modelVersion>", ""),
        "duplicate-model": (
            "<modelVersion>4.0.0</modelVersion>",
            "<modelVersion>4.0.0</modelVersion>" * 2,
        ),
        "parents": ("</project>", "<parent/><parent/></project>"),
        "missing-group": ("<groupId>example</groupId>", ""),
        "missing-artifact": ("<artifactId>library</artifactId>", ""),
        "duplicate-artifact": (
            "<artifactId>library</artifactId>",
            "<artifactId>library</artifactId>" * 2,
        ),
        "missing-parent-version": ("<version>2.0</version>", ""),
        "group": ("<groupId>example</groupId>", "<groupId>other</groupId>"),
        "artifact": (
            "<artifactId>library</artifactId>",
            "<artifactId>other</artifactId>",
        ),
        "version": ("<version>2.0</version>", "<version>9.0</version>"),
        "expression": ("<version>2.0</version>", "<version>${revision}</version>"),
        "namespace": ("POM/4.0.0", "POM/unknown"),
    }
    text = original if problem == "hash" else original.replace(*changes[problem])
    if problem == "root":
        text = text.replace("</project>", "</wrong>")
    path = tmp_path / "reviewed.pom"
    path.write_text(text)
    digest = (
        "0" * 64 if problem == "hash" else hashlib.sha256(path.read_bytes()).hexdigest()
    )
    with pytest.raises(ValueError):
        installer.verify_maven_pom(path, replace(artifact, pom_sha256=digest))


def test_pom_pin_cannot_hide_conflicting_embedded_identity(plugin_addition, tmp_path):
    """Keep the original embedded-version check authoritative when it exists.

    Inputs: valid POM beside contradictory JAR metadata. Output: both contradictions fail.
    """
    _, lock, _ = plugin_addition
    base = installer.load_artifacts(lock, "server-plugin")[0]
    pom = tmp_path / "library.pom"
    pom.write_bytes(pom_bytes())
    for embedded_pom in (False, True):
        path = tmp_path / "library.jar"
        path.write_bytes(jar_bytes("9.0", pom=embedded_pom))
        artifact = replace(
            base,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            pom_sha256=hashlib.sha256(pom.read_bytes()).hexdigest(),
        )
        with pytest.raises(ValueError, match="identity mismatch"):
            installer.verify_artifact(path, artifact, pom)
    with pytest.raises(ValueError, match="Missing separately pinned"):
        installer.verify_artifact(path, artifact)


def test_noncanonical_upstream_manifest_requires_exact_reviewed_value_and_pom(
    plugin_addition, tmp_path
):
    """Bind a legacy publisher's manifest label without weakening default version checks.

    Inputs: JDOM-style release label plus canonical POM. Output: only the exact reviewed pair passes.
    """
    _, lock, _ = plugin_addition
    data = json.loads(lock.read_text())
    component = data["components"][0]
    path = tmp_path / "library.jar"
    path.write_bytes(jar_bytes("2.x-2021.11.08.17.25", pom=False))
    component["hashes"][0]["content"] = hashlib.sha256(path.read_bytes()).hexdigest()
    component["properties"].append(
        {"name": "omero:manifest-version", "value": "2.x-2021.11.08.17.25"}
    )
    lock.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="separately pinned POM"):
        installer.load_artifacts(lock, "server-plugin")
    pom = tmp_path / "library.pom"
    pom.write_bytes(pom_bytes())
    component["properties"].append(
        {
            "name": "omero:pom-sha256",
            "value": hashlib.sha256(pom.read_bytes()).hexdigest(),
        }
    )
    lock.write_text(json.dumps(data))
    artifact = installer.load_artifacts(lock, "server-plugin")[0]
    installer.verify_artifact(path, artifact, pom)
    with pytest.raises(ValueError, match="identity mismatch"):
        installer.verify_artifact(
            path, replace(artifact, manifest_version="2.x-other"), pom
        )


def test_pom_download_uses_its_own_filename_and_bounds(
    plugin_addition, tmp_path, monkeypatch
):
    """Fetch metadata from the exact artifact directory with bounded HTTPS.

    Inputs: approved artifact and metadata destination. Output: native .pom request.
    """
    _, lock, _ = plugin_addition
    artifact = installer.load_artifacts(lock, "server-plugin")[0]
    calls = []
    monkeypatch.setattr(installer.shutil, "which", lambda _: "/usr/bin/curl")
    monkeypatch.setattr(
        installer.subprocess, "run", lambda args, **kwargs: calls.append(args)
    )
    installer.download_artifact(artifact, tmp_path / "library-2.0.pom")
    assert (
        calls[0][-1]
        == "https://repo.maven.apache.org/maven2/example/library/2.0/library-2.0.pom"
    )
    assert calls[0][calls[0].index("--max-time") + 1] == "120"
    assert calls[0][calls[0].index("--max-filesize") + 1] == "33554432"


@pytest.mark.parametrize("source", ["valid", "missing-hash", "changed-bytes"])
def test_plugin_replacement_with_unavailable_version_still_requires_exact_bytes(
    distribution, monkeypatch, source
):
    """Never invent a source version when a distribution omits its metadata.

    Inputs: explicit present state and exact input digest. Output: verified replacement or no mutation.
    """
    root, lock, payloads = distribution("server-plugin")
    data = json.loads(lock.read_text())
    original = data["components"][0]["properties"][1]
    props = [{"name": "omero:server-plugin:source-state", "value": "present"}]
    if source != "missing-hash":
        props.append(original)
    data["components"][0]["properties"] = props
    lock.write_text(json.dumps(data))
    path = root / "lib/server/library.jar"
    if source == "changed-bytes":
        path.write_bytes(b"unexpected source")
    before = path.read_bytes()
    calls = []

    def download(artifact, destination):
        """Inputs: approved coordinate and stage path. Output: deterministic bytes and call receipt."""
        calls.append(artifact)
        destination.write_bytes(payloads[artifact.filename])

    monkeypatch.setattr(installer, "download_artifact", download)
    if source == "valid":
        installer.install(root, lock, "server-plugin")
        assert path.read_bytes() == payloads["library-2.0.jar"]
        assert calls[0].source_version is None
    else:
        with pytest.raises(ValueError):
            installer.install(root, lock, "server-plugin")
        assert path.read_bytes() == before
        assert not calls
