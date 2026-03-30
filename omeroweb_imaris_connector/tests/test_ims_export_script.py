from __future__ import annotations

import hashlib
import importlib.util
import pathlib
import subprocess
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


def test_safe_filename_and_checksum_helpers_cover_edge_cases(tmp_path) -> None:
    module = _load_script_module()
    checksum_path = tmp_path / "bioformats.sha256"

    assert module._safe_filename(None) == "image"
    assert module._safe_filename("../unsafe\x00name?.ims") == ".._unsafename_.ims"
    assert len(module._safe_filename("x" * 250)) == 200

    checksum_path.write_text("not-a-checksum\n", encoding="ascii")
    assert module._read_expected_sha256(str(checksum_path)) is None

    assert module._write_expected_sha256(str(checksum_path), "a" * 64) is True
    assert module._read_expected_sha256(str(checksum_path)) == "a" * 64


def test_copy_and_validate_bioformats_jar_cover_integrity_paths(
    monkeypatch, tmp_path
) -> None:
    module = _load_script_module()
    monkeypatch.setattr(module, "BIOFORMATS_MIN_SIZE_BYTES", 4)

    source = tmp_path / "source.jar"
    destination = tmp_path / "nested" / "bioformats.jar"
    payload = b"trusted-jar-payload"
    _write_file(source, payload)
    expected_sha = hashlib.sha256(payload).hexdigest()

    assert (
        module._copy_bioformats_jar(
            str(source),
            str(destination),
            expected_sha256=expected_sha,
            file_mode=0o600,
            description="runtime jar",
        )
        is True
    )
    assert destination.read_bytes() == payload
    assert module._is_valid_bioformats_jar(
        str(destination), expected_sha256=expected_sha
    )
    assert not module._is_valid_bioformats_jar(
        str(destination), expected_sha256="b" * 64
    )

    bad_source = tmp_path / "bad.jar"
    _write_file(bad_source, b"bad-data")
    assert (
        module._copy_bioformats_jar(
            str(bad_source),
            str(tmp_path / "broken" / "bioformats.jar"),
            expected_sha256=expected_sha,
            file_mode=0o600,
            description="broken jar",
        )
        is False
    )


def test_voxel_size_and_original_file_path_helpers_cover_safe_fallbacks() -> None:
    module = _load_script_module()

    class _PhysicalSize:
        def __init__(self, value):
            self._value = value

        def getValue(self):
            return self._value

    class _PrimaryPixels:
        def __init__(self, x, y, z):
            self._x = x
            self._y = y
            self._z = z

        def getPhysicalSizeX(self):
            return self._x

        def getPhysicalSizeY(self):
            return self._y

        def getPhysicalSizeZ(self):
            return self._z

    image = types.SimpleNamespace(
        getPrimaryPixels=lambda: _PrimaryPixels(
            _PhysicalSize(0), _PhysicalSize(-1), _PhysicalSize(None)
        )
    )
    assert module._get_voxel_size_from_image(image) == (1.0, 1.0, 1.0)

    managed_file = types.SimpleNamespace(
        getPath=lambda: "user/demo",
        getName=lambda: "sample.ome.tif",
    )
    fileset = types.SimpleNamespace(listFiles=lambda: [managed_file])
    image = types.SimpleNamespace(getFileset=lambda: fileset)
    assert (
        module.get_original_file_path(object(), image)
        == "/OMERO/ManagedRepository/user/demo/sample.ome.tif"
    )
    assert (
        module.get_original_file_path(
            object(), types.SimpleNamespace(getFileset=lambda: None)
        )
        is None
    )


def test_convert_to_ims_uses_resolved_binary_runtime_env_and_output(
    monkeypatch, tmp_path
) -> None:
    module = _load_script_module()
    install_dir = tmp_path / "install"
    real_bin = install_dir / "bin" / "ImarisConvertBioformats"
    real_bin.parent.mkdir(parents=True, exist_ok=True)
    real_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    wrapper = tmp_path / "bin" / "imarisconvert"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    jar_path = tmp_path / "bioformats_package.jar"
    jar_path.write_text("jar", encoding="utf-8")
    input_file = tmp_path / "input.ome.tif"
    input_file.write_text("data", encoding="utf-8")
    output_file = tmp_path / "output.ims"

    monkeypatch.setattr(module, "IMARISCONVERT_INSTALL_DIR", str(install_dir))
    monkeypatch.setattr(module.shutil, "which", lambda name: str(wrapper))
    monkeypatch.setattr(module.os.path, "realpath", lambda path: str(real_bin))
    monkeypatch.setattr(
        module, "_ensure_bioformats_jar", lambda _install_dir: str(jar_path)
    )
    monkeypatch.setattr(
        module, "_get_voxel_size_from_image", lambda image: (0.5, 0.5, 1.5)
    )

    captured = {}

    def fake_run(cmd, capture_output, text, timeout, env, cwd):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        captured["env"] = env
        captured["cwd"] = cwd
        output_file.write_text("ims", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="ok", stderr=""
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.convert_to_ims(
        types.SimpleNamespace(getName=lambda: "demo.ome.tif"),
        str(input_file),
        str(output_file),
    )

    assert result is True
    assert captured["cmd"][:4] == [str(real_bin), "-i", str(input_file), "-o"]
    assert captured["timeout"] == module.DEFAULT_TIMEOUT_SECONDS
    assert captured["cwd"] == str(real_bin.parent)
    assert str(install_dir) in captured["env"]["LD_LIBRARY_PATH"]
    assert captured["env"]["CLASSPATH"] == str(jar_path)


def test_convert_and_run_conversion_cover_missing_runtime_and_success_paths(
    monkeypatch, tmp_path
) -> None:
    module = _load_script_module()
    monkeypatch.setattr(module, "IMARISCONVERT_INSTALL_DIR", str(tmp_path / "missing"))
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    assert (
        module.convert_to_ims(
            types.SimpleNamespace(getName=lambda: "demo.ome.tif"),
            "input.ome.tif",
            "output.ims",
        )
        is False
    )

    image = types.SimpleNamespace(getName=lambda: "unsafe/name?.ome.tif")
    conn = types.SimpleNamespace(getObject=lambda kind, image_id: image)
    source_file = tmp_path / "source.ome.tif"
    source_file.write_text("source", encoding="utf-8")
    monkeypatch.setattr(
        module, "get_original_file_path", lambda conn, image: str(source_file)
    )
    monkeypatch.setattr(module, "convert_to_ims", lambda image, src, dst: True)

    class _FixedDatetime:
        @staticmethod
        def utcnow():
            class _Now:
                def strftime(self, fmt):
                    return "20260330T120000Z"

            return _Now()

    monkeypatch.setattr(module, "datetime", _FixedDatetime)

    ok, message, export_path = module.run_conversion(conn, 7, str(tmp_path / "exports"))

    assert ok is True
    assert export_path is not None
    assert export_path.endswith("unsafe_name_.ome.tif_20260330T120000Z.ims")
    assert message == f"Successfully exported IMS: {export_path}"

    missing_conn = types.SimpleNamespace(getObject=lambda kind, image_id: None)
    assert module.run_conversion(missing_conn, 8, str(tmp_path))[0] is False
