from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_manage_script_module():
    omero_module = types.ModuleType("omero")
    omero_module.scripts = types.SimpleNamespace(client=lambda *args, **kwargs: None)

    gateway_module = types.ModuleType("omero.gateway")
    gateway_module.BlitzGateway = object

    rtypes_module = types.ModuleType("omero.rtypes")
    rtypes_module.rstring = lambda value: value

    module_path = (
        REPO_ROOT
        / "omeroweb_import"
        / "omero_scripts"
        / "Manage_Zarr_ManagedRepository.py"
    )
    spec = importlib.util.spec_from_file_location(
        "manage_zarr_managed_repository_coverage_module",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    original_modules = {
        name: sys.modules.get(name)
        for name in ("omero", "omero.gateway", "omero.rtypes")
    }
    sys.modules["omero"] = omero_module
    sys.modules["omero.gateway"] = gateway_module
    sys.modules["omero.rtypes"] = rtypes_module
    try:
        spec.loader.exec_module(module)
    finally:
        for name, original in original_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module


def _server_config(tmp_path: Path) -> dict[str, str]:
    return {
        "omero.data.dir": str(tmp_path / "data"),
        "omero.managed.dir": str(tmp_path / "data" / "ManagedRepository"),
        "omero.fs.repo.path": "%group%/%user%/%year%-%month%-%day%/%time%",
        "omero.web.import.shared_tmp_path": str(tmp_path / "shared"),
    }


def test_manage_script_config_and_runtime_helpers_cover_remaining_guards(
    monkeypatch,
    tmp_path: Path,
):
    module = _load_manage_script_module()

    with pytest.raises(RuntimeError, match="Missing OMERO connection"):
        module._load_server_config(None)

    failing_conn = types.SimpleNamespace(
        c=types.SimpleNamespace(
            sf=types.SimpleNamespace(
                getConfigService=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            )
        )
    )
    with pytest.raises(RuntimeError, match="Failed to access the OMERO config service"):
        module._load_server_config(failing_conn)

    none_conn = types.SimpleNamespace(
        c=types.SimpleNamespace(sf=types.SimpleNamespace(getConfigService=lambda: None))
    )
    with pytest.raises(RuntimeError, match="config service is unavailable"):
        module._load_server_config(none_conn)

    bad_value_conn = types.SimpleNamespace(
        c=types.SimpleNamespace(
            sf=types.SimpleNamespace(
                getConfigService=lambda: types.SimpleNamespace(
                    getConfigValue=lambda key: (_ for _ in ()).throw(
                        RuntimeError(f"cannot read {key}")
                    )
                )
            )
        )
    )
    with pytest.raises(RuntimeError, match="Failed to read OMERO config value"):
        module._load_server_config(bad_value_conn)

    monkeypatch.delenv("OMERODIR", raising=False)
    with pytest.raises(RuntimeError, match="OMERODIR is not set"):
        module._runtime_state_path()

    omerodir = tmp_path / "OMERO.server"
    state_dir = omerodir / "var"
    state_dir.mkdir(parents=True)
    (state_dir / "managed-zarr-runtime.env").write_text(
        "\n# comment only\ninvalid-line\nomero.web.import.shared_tmp_path=/shared\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OMERODIR", str(omerodir))
    assert module._load_runtime_state_value("omero.web.import.shared_tmp_path") == (
        "/shared"
    )


def test_manage_script_path_validation_and_template_guards_cover_remaining_edges(
    tmp_path: Path,
):
    module = _load_manage_script_module()
    config = _server_config(tmp_path)

    with pytest.raises(ValueError, match="Invalid username"):
        module._validate_path_component("../escape", "username")

    empty_config = dict(config)
    empty_config["omero.fs.repo.path"] = ""
    with pytest.raises(RuntimeError, match="Missing required OMERO config value"):
        module._render_repo_template(empty_config, "users_private", "alice", datetime.now())

    slash_only_config = dict(config)
    slash_only_config["omero.fs.repo.path"] = "/"
    with pytest.raises(RuntimeError, match="must not be empty"):
        module._render_repo_template(
            slash_only_config,
            "users_private",
            "alice",
            datetime.now(),
        )

    unresolved_config = dict(config)
    unresolved_config["omero.fs.repo.path"] = "%group%/prefix%user"
    with pytest.raises(RuntimeError, match="unresolved token syntax"):
        module._render_repo_template(
            unresolved_config,
            "users_private",
            "alice",
            datetime.now(),
        )

    with pytest.raises(RuntimeError, match="Managed repository root does not exist"):
        module._managed_repository_root(config)

    (tmp_path / "data" / "ManagedRepository").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="Shared temp root does not exist"):
        module._shared_tmp_root(config)

    (tmp_path / "shared").mkdir(parents=True)
    file_source = tmp_path / "shared" / "sample.zarr"
    file_source.write_text("not a directory", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not a directory"):
        module._validate_source_path(config, str(file_source))


def test_manage_script_prefix_suffix_cleanup_and_symlink_guards_cover_remaining_paths(
    monkeypatch,
    tmp_path: Path,
):
    module = _load_manage_script_module()
    config = _server_config(tmp_path)
    managed_root = tmp_path / "data" / "ManagedRepository"
    managed_root.mkdir(parents=True)
    (tmp_path / "shared").mkdir(parents=True)

    source_target = tmp_path / "source-target"
    source_target.mkdir()
    symlink_root = tmp_path / "linked-source"
    symlink_root.symlink_to(source_target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="Symlinked directories are not allowed"):
        module._reject_symlinks(symlink_root)

    original_render_repo_template = module._render_repo_template
    monkeypatch.setattr(module, "_render_repo_template", lambda *args, **kwargs: ([".."], []))
    with pytest.raises(RuntimeError, match="prefix escaped its root"):
        module._user_prefix_dir(
            config,
            "users_private",
            "alice",
            datetime.now(),
            create_missing=True,
        )
    monkeypatch.setattr(module, "_render_repo_template", original_render_repo_template)

    with pytest.raises(RuntimeError, match="must be created by OMERO.server first"):
        module._user_prefix_dir(
            config,
            "users_private",
            "alice",
            datetime.now(),
            create_missing=False,
        )

    prefix_dir = managed_root / "users_private" / "alice"
    prefix_dir.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="target escaped its root"):
        module._ensure_suffix_dir(managed_root, tmp_path / "outside", ["escape"])

    existing_plain = prefix_dir / "sample"
    existing_plain.mkdir()
    candidate = module._allocate_destination_dir(prefix_dir, "sample")
    assert candidate.name.startswith("sample__")
    assert "." not in candidate.name

    existing_zarr = prefix_dir / "sample.ome.zarr"
    existing_zarr.mkdir()
    zarr_candidate = module._allocate_destination_dir(prefix_dir, "sample.ome.zarr")
    assert zarr_candidate.name.startswith("sample__")
    assert zarr_candidate.name.endswith(".ome.zarr")

    managed_file = prefix_dir / "delete-me.zarr"
    managed_file.write_text("payload", encoding="utf-8")
    cleaned = module._cleanup_zarr(
        config,
        str(managed_file),
        "users_private",
        "alice",
    )
    assert cleaned == managed_file
    assert not managed_file.exists()
