from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "startup" / "51-install-imarisconvert.sh"
BASH_BIN = shutil.which("bash") or "/bin/bash"
SHA256SUM_BIN = shutil.which("sha256sum") or "/usr/bin/sha256sum"


def _prepare_java_home(tmp_path: Path) -> Path:
    """Create a JDK layout for shell boundary checks.

    Inputs: `tmp_path` temporary directory. Output: fake JDK root.
    """
    java_home = tmp_path / "selected jdk"
    for name in ("java", "javac"):
        executable = java_home / "bin" / name
        executable.parent.mkdir(parents=True, exist_ok=True)
        _write_executable(executable)
    for relative in ("include/jni.h", "lib/server/libjvm.so"):
        target = java_home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture", encoding="utf-8")
    return java_home


def _resolve_java_home(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the actual shell resolver without installer side effects.

    Inputs: `env` process environment. Output: resolver process result.
    """
    functions = SCRIPT_PATH.read_text(encoding="utf-8").split(
        'INSTALL_MODE="verify"', 1
    )[0]
    return subprocess.run(
        [BASH_BIN, "-c", functions + "\nresolve_java_build_home\n"],
        check=False,
        env=env,
        text=True,
        capture_output=True,
    )


def test_imaris_build_honors_explicit_java_home_with_spaces(tmp_path):
    """Keep explicit JDK selection independent of distribution paths.

    Inputs: `tmp_path` temporary directory. Output: fails on JDK path changes.
    """
    java_home = _prepare_java_home(tmp_path)
    result = _resolve_java_home({**os.environ, "JAVA_HOME": str(java_home)})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(java_home)


def test_imaris_build_discovers_jdk_from_symlinked_compiler(tmp_path):
    """Resolve the compiler target instead of assuming vendor directories.

    Inputs: `tmp_path` temporary directory. Output: fails on discovery regressions.
    """
    java_home = _prepare_java_home(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "javac").symlink_to(java_home / "bin" / "javac")
    result = _resolve_java_home(
        {
            **os.environ,
            "JAVA_HOME": "",
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(java_home)


@pytest.mark.parametrize(
    "missing", ["bin/java", "bin/javac", "include/jni.h", "lib/server/libjvm.so"]
)
def test_imaris_build_rejects_incomplete_explicit_jdk(tmp_path, missing):
    """Do not fall back silently from an invalid explicit JDK selection.

    Inputs: temporary directory and missing component. Output: requires failure.
    """
    java_home = _prepare_java_home(tmp_path)
    (java_home / missing).unlink()
    result = _resolve_java_home({**os.environ, "JAVA_HOME": str(java_home)})
    assert result.returncode != 0
    assert "complete JDK with JNI support" in result.stderr


def test_imaris_build_reports_missing_compiler(tmp_path):
    """Fail before build side effects when no JDK can be selected.

    Inputs: `tmp_path` empty executable search directory. Output: requires failure.
    """
    result = _resolve_java_home({**os.environ, "JAVA_HOME": "", "PATH": str(tmp_path)})
    assert result.returncode != 0
    assert "A JDK is required" in result.stderr


def test_imaris_cmake_uses_selected_jdk_for_java_and_jni():
    """Keep CMake and the maintained server runtime on the same JDK.

    Inputs: tracked build recipes. Output: fails on provider-specific paths.
    """
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    assert '-DJAVA_HOME="${JAVA_BUILD_HOME}"' in script
    assert '-DJRE_HOME="${JAVA_BUILD_HOME}"' in script
    assert "/usr/lib/jvm/java-11-openjdk" not in script
    assert script.index('JAVA_BUILD_HOME="$(resolve_java_build_home)"') < script.index(
        'rm -rf "${BUILD_ROOT}"'
    )
    dockerfile = (REPO_ROOT / "docker" / "omero-server.Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "ENV JAVA_HOME=/opt/java/openjdk" in dockerfile
    assert (
        'ln -sfn /etc/pki/java/cacerts "${JAVA_HOME}/lib/security/cacerts"'
        in dockerfile
    )
    assert "--setopt=clean_requirements_on_remove=False" in dockerfile
    assert dockerfile.index('"${TEMURIN_JDK_SHA256}"') < dockerfile.index(
        'tar --extract --gzip --file "${archive}"'
    )


def _write_executable(path: Path, content: str = "#!/bin/sh\nexit 0\n") -> None:
    """Write the executable.

    Inputs: `path` (Path) path, `content` (str). Output: None.
    """
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_large_jar(path: Path) -> None:
    """Write the large jar.

    Inputs: `path` (Path) path. Output: None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(10_000_000)


def _write_sha256_manifest(jar_path: Path) -> None:
    """Write the sha256 manifest.

    Inputs: `jar_path` (Path). Output: None.
    """
    digest = subprocess.check_output(
        [SHA256SUM_BIN, str(jar_path)],
        text=True,
    ).split()[0]
    jar_path.with_suffix(jar_path.suffix + ".sha256").write_text(
        f"{digest}  bioformats_package.jar\n",
        encoding="utf-8",
    )


def _prepare_valid_install(tmp_path: Path) -> tuple[Path, Path]:
    """Prepare the valid install.

    Inputs: `tmp_path` (Path) temporary path fixture. Output: `tuple[Path, Path]`.
    """
    install_dir = tmp_path / "imarisconvert"
    wrapper_path = tmp_path / "bin" / "imarisconvert"
    wrapper_path.parent.mkdir(parents=True)
    install_dir.mkdir()

    (install_dir / ".version").write_text("1.0.0\n", encoding="utf-8")
    _write_executable(install_dir / "ImarisConvertBioformats")
    runtime_jar = install_dir / "bioformats" / "bioformats_package.jar"
    cache_jar = install_dir / "artifacts" / "bioformats" / "bioformats_package.jar"
    _write_large_jar(runtime_jar)
    cache_jar.parent.mkdir(parents=True)
    cache_jar.write_bytes(runtime_jar.read_bytes())
    _write_sha256_manifest(cache_jar)
    _write_executable(wrapper_path)
    return install_dir, wrapper_path


def _script_env(install_dir: Path, wrapper_path: Path) -> dict[str, str]:
    """Return the script environment.

    Inputs: `install_dir` (Path), `wrapper_path` (Path). Output: `dict[str, str]`.
    """
    runtime_jar = install_dir / "bioformats" / "bioformats_package.jar"
    if runtime_jar.is_file():
        bioformats_sha256 = (
            hashlib.sha256(  # DevSkim: ignore DS197836 -- test fixture file digest
                runtime_jar.read_bytes()
            ).hexdigest()
        )
    else:
        bioformats_sha256 = (
            "978093f2a4d0034f9581b19a5acd5a53"  # DevSkim: ignore DS173237 -- fixture digest
            "c56d7b04b703865cd533aa953c92b1c2"  # DevSkim: ignore DS173237 -- fixture digest
        )
    return {
        **os.environ,
        "BIOFORMATS_VERSION": "8.5.0",
        "BIOFORMATS_SHA256": bioformats_sha256,
        "IMARISCONVERT_INSTALL_DIR": str(install_dir),
        "IMARISCONVERT_WRAPPER_PATH": str(wrapper_path),
    }


def test_imarisconvert_startup_default_verifies_existing_install(tmp_path):
    """Verify imarisconvert startup default verifies existing install.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in imarisconvert startup default verifies existing install.
    """
    install_dir, wrapper_path = _prepare_valid_install(tmp_path)

    result = subprocess.run(
        [BASH_BIN, str(SCRIPT_PATH)],
        check=False,
        env=_script_env(install_dir, wrapper_path),
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "verified" in result.stdout


def test_imarisconvert_startup_ignores_entrypoint_arguments_in_verify_mode(tmp_path):
    """Verify imarisconvert startup ignores entrypoint arguments in verify mode.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in imarisconvert startup ignores entrypoint arguments in verify mode.
    """
    install_dir, wrapper_path = _prepare_valid_install(tmp_path)

    result = subprocess.run(
        [BASH_BIN, str(SCRIPT_PATH), "/startup/99-run.sh"],
        check=False,
        env=_script_env(install_dir, wrapper_path),
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "verified" in result.stdout


def test_imarisconvert_startup_fails_fast_when_runtime_artifacts_are_missing(tmp_path):
    """Confirm imarisconvert startup fails fast when runtime artifacts are missing exposes the expected failure.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in imarisconvert startup fails fast when runtime artifacts are missing.
    """
    install_dir, wrapper_path = _prepare_valid_install(tmp_path)
    (install_dir / "artifacts" / "bioformats" / "bioformats_package.jar").unlink()

    result = subprocess.run(
        [BASH_BIN, str(SCRIPT_PATH)],
        check=False,
        env=_script_env(install_dir, wrapper_path),
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "local artifact cache is missing or invalid" in result.stderr


def test_imarisconvert_build_time_mode_repairs_wrapper_and_cache_without_network(
    tmp_path,
):
    """Verify imarisconvert build time mode repairs wrapper and cache without network.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in imarisconvert build time mode repairs wrapper and cache without network.
    """
    install_dir, wrapper_path = _prepare_valid_install(tmp_path)
    wrapper_path.unlink()
    cache_dir = install_dir / "artifacts" / "bioformats"
    for path in cache_dir.iterdir():
        path.unlink()

    result = subprocess.run(
        [BASH_BIN, str(SCRIPT_PATH), "--install-build-time"],
        check=False,
        env=_script_env(install_dir, wrapper_path),
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert wrapper_path.exists()
    assert os.access(wrapper_path, os.X_OK)
    assert (cache_dir / "bioformats_package.jar").is_file()
    assert (cache_dir / "bioformats_package.jar.sha256").is_file()


def test_imarisconvert_download_uses_versioned_ome_artifactory_with_pinned_checksum():
    """Verify ImarisConvert build downloads Bio-Formats from OME Artifactory.

    Inputs: repository fixtures. Output: fails on regressions in Bio-Formats
    artifact source or repository-pinned checksum validation.
    """
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "downloads.openmicroscopy.org/bio-formats" not in script_text
    assert (
        "https://artifacts.openmicroscopy.org/artifactory/maven/ome/"
        "bioformats_package/${BIOFORMATS_VERSION}/${BIOFORMATS_ARTIFACT_NAME}"
        in script_text
    )
    assert (
        'BIOFORMATS_ARTIFACT_NAME="bioformats_package-${BIOFORMATS_VERSION}.jar"'
        in script_text
    )
    assert (
        ': "${BIOFORMATS_SHA256:?BIOFORMATS_SHA256 must be set in env/omeroserver.env}"'
        in script_text
    )
    assert "sha256_matches_pin" in script_text
    assert 'BIOFORMATS_SHA256_URL="${BIOFORMATS_URL}.sha256"' in script_text
    assert "curl -L --fail --retry 5 --retry-delay 3 --max-time 300" in script_text
    assert "Published Bio-Formats checksum does not match repository pin" in script_text
    assert "Bio-Formats jar checksum mismatch" in script_text


def test_imarisconvert_verify_rejects_unpinned_bioformats_digest(tmp_path):
    """Confirm runtime verification enforces the repository Bio-Formats pin.

    Inputs: pytest provides `tmp_path`. Output: asserts mismatched runtime jars
    are rejected against the repository-controlled Bio-Formats checksum pin.
    """
    install_dir, wrapper_path = _prepare_valid_install(tmp_path)
    env = _script_env(install_dir, wrapper_path)
    env["BIOFORMATS_SHA256"] = "a" * 64

    result = subprocess.run(
        [BASH_BIN, str(SCRIPT_PATH)],
        check=False,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "checksum does not match repository pin" in result.stderr


def test_imariswriter_clone_is_pinned_and_commit_verified():
    """Verify ImarisWriter supply-chain input is pinned and verified.

    Inputs: repository fixtures. Output: fails on mutable dependency regressions.
    """
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert (
        "IMARISWRITER_GIT_COMMIT="
        '"${IMARISWRITER_GIT_COMMIT:-b128e6e7d1a147261e9d5caf24ebc6b5c9c63779}"'
        in script_text
    )
    assert (
        'git clone --depth 1 --branch "${IMARISWRITER_GIT_REF}" '
        '"${IMARISWRITER_REPO_URL}" ImarisWriter' in script_text
    )
    assert 'actual_commit="$(git rev-parse HEAD)"' in script_text
    assert "ImarisWriter commit mismatch" in script_text
