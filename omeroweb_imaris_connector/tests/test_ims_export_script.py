from __future__ import annotations

import hashlib
import importlib.util
import pathlib
import runpy
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


def test_export_root_and_checksum_helpers_cover_fallback_cleanup_and_altsep(
    monkeypatch, tmp_path
) -> None:
    module = _load_script_module()
    printed = []

    monkeypatch.setattr(
        module,
        "get_env",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("missing env")),
    )
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: printed.append(args))

    assert module._get_export_root() == "/OMERO/ImarisExports"
    assert any(
        "Falling back to default" in " ".join(map(str, line)) for line in printed
    )

    monkeypatch.setattr(module.os, "altsep", "\\", raising=False)
    assert (
        module._safe_filename("  unsafe\\name  ", fallback="fallback") == "unsafe_name"
    )
    assert module._safe_filename("   ", fallback="fallback") == "fallback"

    checksum_path = tmp_path / "bioformats.sha256"
    real_replace = module.os.replace
    real_exists = module.os.path.exists
    tmp_checksum = pathlib.Path(str(checksum_path) + ".tmp")

    monkeypatch.setattr(
        module.os,
        "replace",
        lambda src, dst: (_ for _ in ()).throw(OSError("replace failed")),
    )
    monkeypatch.setattr(
        module.os.path,
        "exists",
        lambda path: str(path) == str(tmp_checksum) or real_exists(path),
    )
    monkeypatch.setattr(
        module.os,
        "remove",
        lambda path: (_ for _ in ()).throw(OSError("cleanup failed")),
    )

    assert module._write_expected_sha256(str(checksum_path), "b" * 64) is False

    monkeypatch.setattr(module.os, "replace", real_replace)
    monkeypatch.setattr(module.os.path, "exists", real_exists)
    monkeypatch.setattr(module.os.path, "exists", lambda path: True)
    monkeypatch.setattr(
        module.os.path,
        "getsize",
        lambda path: (_ for _ in ()).throw(OSError("size failed")),
    )
    assert module._is_valid_bioformats_jar(str(tmp_path / "missing.jar")) is False
    assert (
        module._safe_filename("\x00\x00", fallback="fallback-name") == "fallback-name"
    )


def test_run_conversion_returns_missing_original_file_error(tmp_path) -> None:
    module = _load_script_module()

    class _Conn:
        def getObject(self, object_type, image_id):
            return types.SimpleNamespace(getName=lambda: "demo.ome.tif")

    module.get_original_file_path = lambda conn, image: None
    assert module.run_conversion(_Conn(), 7, str(tmp_path)) == (
        False,
        "Could not get original file path",
        None,
    )
    assert module._safe_filename(None, fallback="") == ""


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


def test_copy_and_path_helpers_cover_error_and_exception_fallbacks(
    monkeypatch, tmp_path
) -> None:
    module = _load_script_module()
    source = tmp_path / "source.jar"
    source.write_text("payload", encoding="utf-8")
    destination = tmp_path / "nested" / "bioformats.jar"
    tmp_destination = pathlib.Path(str(destination) + ".tmp")
    real_exists = module.os.path.exists

    monkeypatch.setattr(
        module.shutil,
        "copyfile",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("copy failed")),
    )
    monkeypatch.setattr(
        module.os.path,
        "exists",
        lambda path: str(path) == str(tmp_destination) or real_exists(path),
    )
    monkeypatch.setattr(
        module.os,
        "remove",
        lambda path: (_ for _ in ()).throw(OSError("cleanup failed")),
    )

    assert (
        module._copy_bioformats_jar(
            str(source),
            str(destination),
            expected_sha256="a" * 64,
            file_mode=0o600,
            description="runtime jar",
        )
        is False
    )

    class _BadPhysicalSize:
        def getValue(self):
            raise RuntimeError("bad value")

    class _BadPrimaryPixels:
        def getPhysicalSizeX(self):
            return _BadPhysicalSize()

        def getPhysicalSizeY(self):
            return _BadPhysicalSize()

        def getPhysicalSizeZ(self):
            return _BadPhysicalSize()

    image = types.SimpleNamespace(getPrimaryPixels=lambda: _BadPrimaryPixels())
    assert module._get_voxel_size_from_image(image) == (1.0, 1.0, 1.0)

    broken_image = types.SimpleNamespace(
        getPrimaryPixels=lambda: (_ for _ in ()).throw(RuntimeError("pixels failed"))
    )
    assert module._get_voxel_size_from_image(broken_image) == (1.0, 1.0, 1.0)

    empty_fileset_image = types.SimpleNamespace(
        getFileset=lambda: types.SimpleNamespace(listFiles=lambda: [])
    )
    assert module.get_original_file_path(object(), empty_fileset_image) is None

    assert (
        module.get_original_file_path(
            object(),
            types.SimpleNamespace(
                getFileset=lambda: (_ for _ in ()).throw(RuntimeError("fileset failed"))
            ),
        )
        is None
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

    def fake_run(cmd, *, timeout, env, cwd, **_kwargs):
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


def test_convert_to_ims_and_run_conversion_cover_failure_paths(
    monkeypatch, tmp_path
) -> None:
    module = _load_script_module()
    install_dir = tmp_path / "install"
    real_bin = install_dir / "ImarisConvertBioformats"
    real_bin.parent.mkdir(parents=True, exist_ok=True)
    real_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    input_file = tmp_path / "input.ome.tif"
    input_file.write_text("data", encoding="utf-8")
    output_file = tmp_path / "output.ims"

    class _FixedDatetime:
        @staticmethod
        def utcnow():
            class _Now:
                def strftime(self, fmt):
                    return "20260331T120000Z"

            return _Now()

    monkeypatch.setattr(module, "datetime", _FixedDatetime)

    monkeypatch.setattr(module, "IMARISCONVERT_INSTALL_DIR", str(install_dir))
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    monkeypatch.setattr(module, "_ensure_bioformats_jar", lambda _install_dir: None)
    assert (
        module.convert_to_ims(
            types.SimpleNamespace(getName=lambda: "demo.ome.tif"),
            str(input_file),
            str(output_file),
        )
        is False
    )

    jar_path = tmp_path / "bioformats_package.jar"
    jar_path.write_text("jar", encoding="utf-8")
    monkeypatch.setattr(
        module, "_ensure_bioformats_jar", lambda _install_dir: str(jar_path)
    )
    monkeypatch.setattr(
        module, "_get_voxel_size_from_image", lambda image: (1.0, 2.0, 3.0)
    )
    monkeypatch.setenv("LD_LIBRARY_PATH", "/runtime/lib")
    monkeypatch.setenv("CLASSPATH", "/runtime/classes")

    calls = []

    def _failed_run(cmd, *, timeout, env, cwd, **_kwargs):
        calls.append({"env": env, "cwd": cwd})
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="bad", stderr="boom"
        )

    monkeypatch.setattr(module.subprocess, "run", _failed_run)
    assert (
        module.convert_to_ims(
            types.SimpleNamespace(getName=lambda: "demo.ome.tif"),
            str(input_file),
            str(output_file),
        )
        is False
    )
    assert calls[0]["env"]["LD_LIBRARY_PATH"].startswith("/runtime/lib:")
    assert calls[0]["env"]["CLASSPATH"].startswith(f"{jar_path}{module.os.pathsep}")

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("subprocess boom")),
    )
    assert (
        module.convert_to_ims(
            types.SimpleNamespace(getName=lambda: "demo.ome.tif"),
            str(input_file),
            str(output_file),
        )
        is False
    )

    image = types.SimpleNamespace(getName=lambda: "demo.ome.tif")
    conn = types.SimpleNamespace(getObject=lambda kind, image_id: image)
    missing_source = tmp_path / "missing.ome.tif"
    monkeypatch.setattr(
        module,
        "get_original_file_path",
        lambda current_conn, current_image: str(missing_source),
    )
    assert module.run_conversion(conn, 7, str(tmp_path)) == (
        False,
        f"Original file not found: {missing_source}",
        None,
    )

    source_file = tmp_path / "source.ome.tif"
    source_file.write_text("source", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "get_original_file_path",
        lambda current_conn, current_image: str(source_file),
    )
    monkeypatch.setattr(module, "convert_to_ims", lambda current_image, src, dst: False)
    assert module.run_conversion(conn, 7, str(tmp_path)) == (
        False,
        "Conversion to IMS failed",
        None,
    )


def test_run_script_sets_outputs_and_attaches_exported_file(
    monkeypatch, tmp_path
) -> None:
    module = _load_script_module()
    export_root = tmp_path / "exports"
    export_path = export_root / "image_7" / "demo.ims"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text("ims", encoding="utf-8")

    outputs = {}
    group_calls = []
    linked = []
    file_annotation = types.SimpleNamespace(_obj=object(), getId=lambda: 21)
    image = types.SimpleNamespace(
        getName=lambda: "demo.ome.tif",
        getDetails=lambda: types.SimpleNamespace(
            getGroup=lambda: types.SimpleNamespace(getId=lambda: 9)
        ),
        linkAnnotation=lambda annotation: linked.append(annotation),
    )
    conn = types.SimpleNamespace(
        SERVICE_OPTS=types.SimpleNamespace(
            setOmeroGroup=lambda value: group_calls.append(value)
        ),
        getObject=lambda kind, image_id: image,
        createFileAnnfromLocalFile=lambda path, mimetype, ns, desc: file_annotation,
    )

    class _Client:
        def getInputs(self, unwrap=True):
            assert unwrap is True
            return {"Image_ID": 7}

        def setOutput(self, key, value):
            outputs[key] = value

        def closeSession(self):
            outputs["closed"] = True

    client = _Client()
    monkeypatch.setattr(module, "_get_export_root", lambda: str(export_root))
    monkeypatch.setattr(module.os, "makedirs", lambda path, exist_ok=True: None)
    monkeypatch.setattr(
        module.scripts,
        "Long",
        lambda *args, **kwargs: ("Long", args, kwargs),
        raising=False,
    )
    monkeypatch.setattr(
        module.scripts, "client", lambda *args, **kwargs: client, raising=False
    )
    monkeypatch.setattr(module, "BlitzGateway", lambda client_obj=None: conn)
    monkeypatch.setattr(
        module,
        "run_conversion",
        lambda current_conn, image_id, current_root: (
            True,
            f"Successfully exported IMS: {export_path}",
            str(export_path),
        ),
    )
    monkeypatch.setattr(
        module.omero.rtypes, "robject", lambda value: value, raising=False
    )
    monkeypatch.setattr(
        module.omero.rtypes, "rlong", lambda value: value, raising=False
    )

    module.run_script()

    assert outputs["Message"] == f"Successfully exported IMS: {export_path}"
    assert outputs["File_Annotation"] is file_annotation._obj
    assert outputs["File_Annotation_Id"] == 21
    assert outputs["Export_Path"] == str(export_path)
    assert outputs["Export_Name"] == "demo.ims"
    assert outputs["closed"] is True
    assert group_calls == [-1, 9]
    assert linked == [file_annotation]


def test_run_script_survives_attachment_failure_and_reports_export_path(
    monkeypatch, tmp_path
) -> None:
    module = _load_script_module()
    export_root = tmp_path / "exports"
    export_path = export_root / "image_8" / "failed-demo.ims"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text("ims", encoding="utf-8")

    outputs = {}
    image = types.SimpleNamespace(
        getName=lambda: "demo.ome.tif",
        getDetails=lambda: types.SimpleNamespace(
            getGroup=lambda: types.SimpleNamespace(getId=lambda: 9)
        ),
    )
    conn = types.SimpleNamespace(
        SERVICE_OPTS=types.SimpleNamespace(setOmeroGroup=lambda value: None),
        getObject=lambda kind, image_id: image,
        createFileAnnfromLocalFile=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("attach failed")
        ),
    )

    class _Client:
        def getInputs(self, unwrap=True):
            return {"Image_ID": 8}

        def setOutput(self, key, value):
            outputs[key] = value

        def closeSession(self):
            outputs["closed"] = True

    monkeypatch.setattr(module, "_get_export_root", lambda: str(export_root))
    monkeypatch.setattr(module.os, "makedirs", lambda path, exist_ok=True: None)
    monkeypatch.setattr(
        module.scripts,
        "Long",
        lambda *args, **kwargs: ("Long", args, kwargs),
        raising=False,
    )
    monkeypatch.setattr(
        module.scripts, "client", lambda *args, **kwargs: _Client(), raising=False
    )
    monkeypatch.setattr(module, "BlitzGateway", lambda client_obj=None: conn)
    monkeypatch.setattr(
        module,
        "run_conversion",
        lambda current_conn, image_id, current_root: (
            True,
            f"Successfully exported IMS: {export_path}",
            str(export_path),
        ),
    )
    monkeypatch.setattr(module, "print", lambda *args, **kwargs: None, raising=False)

    module.run_script()

    assert outputs["Message"] == f"Successfully exported IMS: {export_path}"
    assert outputs["Export_Path"] == str(export_path)
    assert outputs["Export_Name"] == "failed-demo.ims"
    assert outputs["closed"] is True


def test_run_script_covers_missing_image_output_failure_and_top_level_errors(
    monkeypatch, tmp_path
) -> None:
    module = _load_script_module()
    export_root = tmp_path / "exports"
    export_path = export_root / "image_9" / "demo.ims"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text("ims", encoding="utf-8")

    output_calls = []

    class _Client:
        def getInputs(self, unwrap=True):
            return {"Image_ID": 9}

        def setOutput(self, key, value):
            output_calls.append((key, value))
            if key == "File_Annotation":
                raise RuntimeError("output failed")

        def closeSession(self):
            output_calls.append(("closed", True))

    client = _Client()
    file_annotation = types.SimpleNamespace(_obj=object(), getId=lambda: 99)
    image = types.SimpleNamespace(
        getName=lambda: "demo.ome.tif",
        getDetails=lambda: types.SimpleNamespace(
            getGroup=lambda: types.SimpleNamespace(getId=lambda: 9)
        ),
        linkAnnotation=lambda annotation: None,
    )
    conn = types.SimpleNamespace(
        SERVICE_OPTS=types.SimpleNamespace(setOmeroGroup=lambda value: None),
        getObject=lambda kind, image_id: image if image_id == 9 else None,
        createFileAnnfromLocalFile=lambda *args, **kwargs: file_annotation,
    )

    monkeypatch.setattr(module, "_get_export_root", lambda: str(export_root))
    monkeypatch.setattr(module.os, "makedirs", lambda path, exist_ok=True: None)
    monkeypatch.setattr(
        module.scripts, "client", lambda *args, **kwargs: client, raising=False
    )
    monkeypatch.setattr(
        module.scripts,
        "Long",
        lambda *args, **kwargs: ("Long", args, kwargs),
        raising=False,
    )
    monkeypatch.setattr(module, "BlitzGateway", lambda client_obj=None: conn)
    monkeypatch.setattr(
        module,
        "run_conversion",
        lambda current_conn, image_id, current_root: (
            True,
            f"Successfully exported IMS: {export_path}",
            str(export_path),
        ),
    )
    monkeypatch.setattr(
        module.omero.rtypes, "robject", lambda value: value, raising=False
    )
    monkeypatch.setattr(
        module.omero.rtypes, "rlong", lambda value: value, raising=False
    )

    module.run_script()

    assert ("Export_Path", str(export_path)) in output_calls
    assert ("Export_Name", "demo.ims") in output_calls
    assert ("File_Annotation_Id", 99) in output_calls
    assert ("closed", True) in output_calls

    missing_image_calls = []

    class _MissingImageClient:
        def getInputs(self, unwrap=True):
            return {"Image_ID": 10}

        def setOutput(self, key, value):
            missing_image_calls.append((key, value))

        def closeSession(self):
            missing_image_calls.append(("closed", True))

    monkeypatch.setattr(
        module.scripts,
        "client",
        lambda *args, **kwargs: _MissingImageClient(),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "BlitzGateway",
        lambda client_obj=None: types.SimpleNamespace(
            SERVICE_OPTS=types.SimpleNamespace(setOmeroGroup=lambda value: None),
            getObject=lambda kind, image_id: None,
        ),
    )

    module.run_script()

    assert ("Export_Path", str(export_path)) in missing_image_calls
    assert ("Export_Name", "demo.ims") in missing_image_calls
    assert ("closed", True) in missing_image_calls

    error_calls = []

    class _ExplodingClient:
        def setOutput(self, key, value):
            error_calls.append((key, value))

        def closeSession(self):
            error_calls.append(("closed", True))

    monkeypatch.setattr(
        module.scripts,
        "client",
        lambda *args, **kwargs: _ExplodingClient(),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "BlitzGateway",
        lambda client_obj=None: (_ for _ in ()).throw(RuntimeError("gateway failed")),
    )

    module.run_script()

    assert error_calls[0][0] == "Message"
    assert "Script error:" in error_calls[0][1]
    assert ("closed", True) in error_calls


def test_ims_export_script_main_entrypoint_executes_run_script() -> None:
    _install_omero_stub()

    output_calls = []

    class _Client:
        def getInputs(self, unwrap=True):
            raise RuntimeError("boom")

        def setOutput(self, key, value):
            output_calls.append((key, value))

        def closeSession(self):
            output_calls.append(("closed", True))

    sys.modules["omero"].scripts.client = lambda *args, **kwargs: _Client()
    sys.modules["omero"].scripts.Long = lambda *args, **kwargs: None

    runpy.run_path(
        str(
            pathlib.Path(__file__).resolve().parents[1]
            / "omero_scripts"
            / "IMS_Export.py"
        ),
        run_name="__main__",
    )

    assert output_calls[0][0] == "Message"
    assert ("closed", True) in output_calls
