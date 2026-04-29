from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "startup" / "51-install-imarisconvert.sh"
BASH_BIN = shutil.which("bash") or "/bin/bash"
SHA256SUM_BIN = shutil.which("sha256sum") or "/usr/bin/sha256sum"


def _write_executable(path: Path, content: str = "#!/bin/sh\nexit 0\n") -> None:
    """Handle write executable."""
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_large_jar(path: Path) -> None:
    """Handle write large jar."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(10_000_000)


def _write_sha256_manifest(jar_path: Path) -> None:
    """Handle write sha256 manifest."""
    digest = subprocess.check_output(
        [SHA256SUM_BIN, str(jar_path)],
        text=True,
    ).split()[0]
    jar_path.with_suffix(jar_path.suffix + ".sha256").write_text(
        f"{digest}  bioformats_package.jar\n",
        encoding="utf-8",
    )


def _prepare_valid_install(tmp_path: Path) -> tuple[Path, Path]:
    """Handle prepare valid install."""
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
    """Handle script env."""
    return {
        **os.environ,
        "BIOFORMATS_VERSION": "8.5.0",
        "IMARISCONVERT_INSTALL_DIR": str(install_dir),
        "IMARISCONVERT_WRAPPER_PATH": str(wrapper_path),
    }


def test_imarisconvert_startup_default_verifies_existing_install(tmp_path):
    """Verify test imarisconvert startup default verifies e behavior."""
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
    """Verify test imarisconvert startup ignores entrypoint behavior."""
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
    """Verify test imarisconvert startup fails fast when ru behavior."""
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
    """Verify test imarisconvert build time mode repairs wr behavior."""
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
