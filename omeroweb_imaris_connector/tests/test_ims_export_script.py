from __future__ import annotations

import hashlib
import importlib.util
import pathlib
import sys
import types


def _install_omero_stub() -> None:
    omero_module = types.ModuleType("omero")

    gateway_module = types.ModuleType("omero.gateway")
    gateway_module.BlitzGateway = type("BlitzGateway", (), {})

    rtypes_module = types.ModuleType("omero.rtypes")
    rtypes_module.rstring = lambda value: value

    scripts_module = types.ModuleType("omero.scripts")

    omero_module.rtypes = rtypes_module
    omero_module.scripts = scripts_module

    sys.modules["omero"] = omero_module
    sys.modules["omero.gateway"] = gateway_module
    sys.modules["omero.rtypes"] = rtypes_module
    sys.modules["omero.scripts"] = scripts_module


def _load_script_module():
    _install_omero_stub()
    module_name = "ims_export_script_under_test"
    sys.modules.pop(module_name, None)
    script_path = (
        pathlib.Path(__file__).resolve().parents[1] / "omero_scripts" / "IMS_Export.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_file(path: pathlib.Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _write_sha256(path: pathlib.Path, payload: bytes) -> None:
    digest = hashlib.sha256(payload).hexdigest()
    path.write_text(f"{digest}  bioformats_package.jar\n", encoding="ascii")


def test_ensure_bioformats_jar_seeds_cache_from_runtime(monkeypatch, tmp_path) -> None:
    module = _load_script_module()
    monkeypatch.setattr(module, "BIOFORMATS_MIN_SIZE_BYTES", 4)

    install_dir = tmp_path / "imarisconvert"
    runtime_jar = install_dir / "bioformats" / module.BIOFORMATS_JAR_NAME
    payload = b"trusted-runtime-jar"
    _write_file(runtime_jar, payload)

    resolved = module._ensure_bioformats_jar(str(install_dir))

    cache_jar = (
        install_dir / module.BIOFORMATS_ARTIFACTS_SUBDIR / module.BIOFORMATS_JAR_NAME
    )
    cache_sha = pathlib.Path(str(cache_jar) + ".sha256")
    assert resolved == str(runtime_jar)
    assert cache_jar.read_bytes() == payload
    assert cache_sha.exists()


def test_ensure_bioformats_jar_restores_runtime_from_cache(
    monkeypatch, tmp_path
) -> None:
    module = _load_script_module()
    monkeypatch.setattr(module, "BIOFORMATS_MIN_SIZE_BYTES", 4)

    install_dir = tmp_path / "imarisconvert"
    cache_jar = (
        install_dir / module.BIOFORMATS_ARTIFACTS_SUBDIR / module.BIOFORMATS_JAR_NAME
    )
    cache_sha = pathlib.Path(str(cache_jar) + ".sha256")
    payload = b"cached-runtime-jar"
    _write_file(cache_jar, payload)
    _write_sha256(cache_sha, payload)

    resolved = module._ensure_bioformats_jar(str(install_dir))

    runtime_jar = install_dir / "bioformats" / module.BIOFORMATS_JAR_NAME
    assert resolved == str(runtime_jar)
    assert runtime_jar.read_bytes() == payload


def test_ensure_bioformats_jar_replaces_invalid_runtime_from_cache(
    monkeypatch, tmp_path
) -> None:
    module = _load_script_module()
    monkeypatch.setattr(module, "BIOFORMATS_MIN_SIZE_BYTES", 4)

    install_dir = tmp_path / "imarisconvert"
    runtime_jar = install_dir / "bioformats" / module.BIOFORMATS_JAR_NAME
    cache_jar = (
        install_dir / module.BIOFORMATS_ARTIFACTS_SUBDIR / module.BIOFORMATS_JAR_NAME
    )
    cache_sha = pathlib.Path(str(cache_jar) + ".sha256")
    _write_file(runtime_jar, b"bad")
    payload = b"valid-cached-runtime-jar"
    _write_file(cache_jar, payload)
    _write_sha256(cache_sha, payload)

    resolved = module._ensure_bioformats_jar(str(install_dir))

    assert resolved == str(runtime_jar)
    assert runtime_jar.read_bytes() == payload


def test_ensure_bioformats_jar_returns_none_without_runtime_or_cache(
    monkeypatch, tmp_path
) -> None:
    module = _load_script_module()
    monkeypatch.setattr(module, "BIOFORMATS_MIN_SIZE_BYTES", 4)
    monkeypatch.setenv("BIOFORMATS_VERSION", "8.5.0")

    install_dir = tmp_path / "imarisconvert"

    assert module._ensure_bioformats_jar(str(install_dir)) is None
