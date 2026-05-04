from __future__ import annotations

import importlib.util
import runpy
import shutil
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_manage_script_module():
    """Load the manage script module.

    Inputs: none. Output: `module`.
    """
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
    """Return the server config.

    Inputs: `tmp_path` (Path) temporary path fixture. Output: `dict[str, str]`.
    """
    return {
        "omero.data.dir": str(tmp_path / "data"),
        "omero.managed.dir": str(tmp_path / "data" / "ManagedRepository"),
        "omero.fs.repo.path": "%group%/%user%/%year%-%month%-%day%/%time%",
        "omero.web.import.shared_tmp_path": str(tmp_path / "shared"),
    }


def _managed_repo_conn(managed_root: Path, *, proxies_shape: str = "mapping"):
    """Return the managed repo conn.

    Inputs: `managed_root` (Path), `proxies_shape` (str). Output: `bool`. Raises:
    ValueError when validation or the called operation fails.
    """

    class _RepoProxy:
        """Test double for repo proxy behavior in this module."""

        def __init__(self, root: Path):
            """Create `_RepoProxy` with `root`.

            Inputs: `root`. Output: None.
            """
            self.root = root
            self.make_dir_calls = []
            self.delete_calls = []
            self.registered_paths = set()

        def makeDir(self, path, parents):
            """Create the dir for `_RepoProxy`.

            Inputs: `path` path, `parents`. Output: None.
            """
            self.make_dir_calls.append((path, parents))
            target = self.root / path.strip("/")
            target.mkdir(parents=parents, exist_ok=True)
            current = self.root
            for part in target.relative_to(self.root).parts:
                current = current / part
                self.registered_paths.add(current.resolve(strict=False))

        def fileExists(self, path):
            """Return the file Exists for `_RepoProxy`.

            Inputs: `path` path. Output: `bool`.
            """
            target = (self.root / path.strip("/")).resolve(strict=False)
            return target in self.registered_paths

        def deletePaths(self, paths, recursively, force):
            """Delete the paths for `_RepoProxy`.

            Inputs: `paths`, `recursively`, `force`. Output: `str`.
            """
            self.delete_calls.append((list(paths), recursively, force))
            for raw_path in paths:
                target = (self.root / raw_path.strip("/")).resolve(strict=False)
                self.registered_paths = {
                    candidate
                    for candidate in self.registered_paths
                    if candidate != target and target not in candidate.parents
                }
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
            return "delete-handle"

    repo_proxy = _RepoProxy(managed_root)
    description = types.SimpleNamespace(
        path=types.SimpleNamespace(val=str(managed_root.parent)),
        name=types.SimpleNamespace(val=managed_root.name),
        hash=types.SimpleNamespace(val="managed-repo-hash"),
    )
    descriptions = [description]
    wait_calls = []
    if proxies_shape == "mapping":
        proxies = {"managed-repo-hash": repo_proxy}
    elif proxies_shape == "sequence":
        stale_description = types.SimpleNamespace(
            path=types.SimpleNamespace(val=str(managed_root.parent.parent)),
            name=types.SimpleNamespace(val="OMERO"),
            hash=types.SimpleNamespace(val="stale-root-hash"),
        )
        description = types.SimpleNamespace(
            path=types.SimpleNamespace(val=str(managed_root.parent)),
            name=types.SimpleNamespace(val=managed_root.name),
            hash=types.SimpleNamespace(val="managed-repo-hash"),
        )
        descriptions = [stale_description, description]
        proxies = [None, repo_proxy]
    else:
        raise ValueError(f"Unsupported proxies_shape: {proxies_shape}")

    conn = types.SimpleNamespace(
        c=types.SimpleNamespace(
            sf=types.SimpleNamespace(
                sharedResources=lambda: types.SimpleNamespace(
                    repositories=lambda: types.SimpleNamespace(
                        descriptions=descriptions,
                        proxies=proxies,
                    )
                )
            ),
            waitOnCmd=lambda handle, closehandle=True: wait_calls.append(
                (handle, closehandle)
            ),
        )
    )
    return conn, repo_proxy, wait_calls


def _register_repo_path(repo_proxy, managed_root: Path, target: Path) -> None:
    """Record the register repo path call on the test double for later assertions.

    Inputs: `repo_proxy`, `managed_root` (Path), `target` (Path). Output: None.
    """
    current = managed_root.resolve(strict=False)
    for part in target.resolve(strict=False).relative_to(managed_root).parts:
        current = (current / part).resolve(strict=False)
        repo_proxy.registered_paths.add(current)


def test_manage_script_config_and_runtime_helpers_cover_remaining_guards(
    monkeypatch,
    tmp_path: Path,
):
    """Verify the manage script config and runtime helpers cover remaining guards execution contract.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in manage script config and runtime helpers cover remaining guards integration.
    """
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
    """Check manage script path validation and template guards cover remaining edges renders the expected surface.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when manage script path validation and template guards cover remaining edges accepts unsafe input.
    """
    module = _load_manage_script_module()
    config = _server_config(tmp_path)

    with pytest.raises(ValueError, match="Invalid username"):
        module._validate_path_component("../escape", "username")

    empty_config = dict(config)
    empty_config["omero.fs.repo.path"] = ""
    with pytest.raises(RuntimeError, match="Missing required OMERO config value"):
        module._render_repo_template(
            empty_config, "users_private", "alice", datetime.now()
        )

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
    """Verify the manage script prefix suffix cleanup and symlink guards cover remaining paths execution contract.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions when manage script prefix suffix cleanup and symlink guards cover remaining paths accepts unsafe input.
    """
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
    monkeypatch.setattr(module, "_render_repo_template", lambda *args, **kwargs: [".."])
    with pytest.raises(RuntimeError, match="template escaped its root"):
        module._template_container_dir(
            config,
            "users_private",
            "alice",
            datetime.now(),
        )
    monkeypatch.setattr(module, "_render_repo_template", original_render_repo_template)

    prefix_dir = managed_root / "users_private" / "alice"
    prefix_dir.mkdir(parents=True)

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

    conn, repo_proxy, wait_calls = _managed_repo_conn(managed_root)
    staged_parent = prefix_dir / "2026-03-22" / "09-51-15"
    staged_parent.mkdir(parents=True)
    _register_repo_path(repo_proxy, managed_root, staged_parent)
    managed_dir = staged_parent / "delete-me.zarr"
    managed_dir.mkdir()
    _register_repo_path(repo_proxy, managed_root, managed_dir)
    cleaned = module._cleanup_zarr(
        conn,
        config,
        str(managed_dir),
        "users_private",
        "alice",
    )
    assert cleaned == managed_dir
    assert not managed_dir.exists()
    assert repo_proxy.delete_calls == [
        (["/users_private/alice/2026-03-22/09-51-15/delete-me.zarr/"], True, False)
    ]
    assert wait_calls == [("delete-handle", True)]


def test_manage_script_stage_permissions_allow_service_read_access(tmp_path: Path):
    """Verify the manage script stage permissions allow service read access execution contract.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in manage script stage permissions allow service read access integration.
    """
    module = _load_manage_script_module()
    config = _server_config(tmp_path)
    managed_root = tmp_path / "data" / "ManagedRepository"
    managed_root.mkdir(parents=True)
    prefix_dir = managed_root / "users_private" / "alice"
    prefix_dir.mkdir(parents=True)
    conn, repo_proxy, wait_calls = _managed_repo_conn(managed_root)
    _register_repo_path(repo_proxy, managed_root, prefix_dir)
    source = tmp_path / "shared" / "job-1" / "sample.zarr"
    nested_dir = source / "0"
    nested_dir.mkdir(parents=True)
    payload = nested_dir / "0"
    payload.write_text("pixels", encoding="utf-8")

    destination = module._stage_zarr(
        conn,
        config,
        str(source),
        "users_private",
        "alice",
    )

    assert repo_proxy.make_dir_calls == [
        (
            f"users_private/alice/{destination.parent.parent.name}/{destination.parent.name}/",
            True,
        ),
        (
            f"users_private/alice/{destination.parent.parent.name}/{destination.parent.name}/sample.zarr/",
            True,
        ),
    ]
    assert wait_calls == []
    assert (managed_root / "users_private").stat().st_mode & 0o777 == 0o711
    assert (managed_root / "users_private" / "alice").stat().st_mode & 0o777 == 0o711
    assert destination.parent.parent.stat().st_mode & 0o777 == 0o711
    assert destination.parent.stat().st_mode & 0o777 == 0o711
    assert destination.stat().st_mode & 0o777 == 0o755
    assert (destination / "0").stat().st_mode & 0o777 == 0o755
    assert (destination / "0" / "0").stat().st_mode & 0o777 == 0o644


def test_manage_script_resolves_sequence_style_repository_maps(tmp_path: Path):
    """Verify the manage script resolves sequence style repository maps execution contract.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in manage script resolves sequence style repository maps integration.
    """
    module = _load_manage_script_module()
    config = _server_config(tmp_path)
    managed_root = tmp_path / "data" / "ManagedRepository"
    managed_root.mkdir(parents=True)
    (managed_root / "users_private" / "alice").mkdir(parents=True)
    conn, repo_proxy, _wait_calls = _managed_repo_conn(
        managed_root, proxies_shape="sequence"
    )

    resolved_proxy = module._managed_repository_proxy(conn, config)

    assert resolved_proxy is repo_proxy


def test_manage_script_rejects_unregistered_existing_suffix_dirs(tmp_path: Path):
    """Confirm manage script rejects unregistered existing suffix dirs is rejected at the boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in manage script rejects unregistered existing suffix dirs integration.
    """
    module = _load_manage_script_module()
    config = _server_config(tmp_path)
    managed_root = tmp_path / "data" / "ManagedRepository"
    managed_root.mkdir(parents=True)
    prefix_dir = managed_root / "users_private" / "alice"
    prefix_dir.mkdir(parents=True)
    source = tmp_path / "shared" / "job-1" / "sample.zarr"
    (source / "0").mkdir(parents=True)
    (source / "0" / "0").write_text("pixels", encoding="utf-8")

    conn, repo_proxy, _wait_calls = _managed_repo_conn(managed_root)
    fixed_now = datetime(2026, 3, 22, 9, 51, 15)
    stale_suffix = prefix_dir / "2026-03-22"
    stale_suffix.mkdir(parents=True)
    _register_repo_path(repo_proxy, managed_root, prefix_dir)

    class _FixedDatetime:
        """Test double for fixed datetime behavior in this module."""

        @staticmethod
        def now():
            """Return `_FixedDatetime`'s fixed timestamp.

            Inputs: none. Output: `fixed_now`.
            """
            return fixed_now

    original_datetime = module.datetime
    module.datetime = _FixedDatetime
    try:
        with pytest.raises(RuntimeError, match="exists on disk but is not registered"):
            module._stage_zarr(
                conn,
                config,
                str(source),
                "users_private",
                "alice",
            )
    finally:
        module.datetime = original_datetime

    assert repo_proxy.make_dir_calls == []


def test_manage_script_stages_from_generic_template_without_user_anchor(
    tmp_path: Path,
):
    """Check manage script stages from generic template without user anchor renders the expected surface.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in manage script stages from generic template without user anchor integration.
    """
    module = _load_manage_script_module()
    config = _server_config(tmp_path)
    config["omero.fs.repo.path"] = "shared/%year%/%group%/%time%"
    managed_root = tmp_path / "data" / "ManagedRepository"
    managed_root.mkdir(parents=True)
    (tmp_path / "shared" / "job-1").mkdir(parents=True)
    source = tmp_path / "shared" / "job-1" / "sample.zarr"
    (source / "0").mkdir(parents=True)
    (source / "0" / "0").write_text("pixels", encoding="utf-8")

    conn, repo_proxy, _wait_calls = _managed_repo_conn(managed_root)
    fixed_now = datetime(2026, 3, 22, 9, 51, 15)

    class _FixedDatetime:
        """Test double for fixed datetime behavior in this module."""

        @staticmethod
        def now():
            """Return `_FixedDatetime`'s fixed timestamp.

            Inputs: none. Output: `fixed_now`.
            """
            return fixed_now

    original_datetime = module.datetime
    module.datetime = _FixedDatetime
    try:
        destination = module._stage_zarr(
            conn,
            config,
            str(source),
            "users_private",
            "alice",
        )
    finally:
        module.datetime = original_datetime

    assert destination == (
        managed_root / "shared" / "2026" / "users_private" / "09-51-15" / "sample.zarr"
    )
    assert repo_proxy.make_dir_calls == [
        ("shared/2026/users_private/09-51-15/", True),
        ("shared/2026/users_private/09-51-15/sample.zarr/", True),
    ]


def test_manage_script_cleanup_restricts_deletion_to_staged_leaf(
    tmp_path: Path,
):
    """Verify the manage script cleanup restricts deletion to staged leaf execution contract.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in manage script cleanup restricts deletion to staged leaf integration.
    """
    module = _load_manage_script_module()
    config = _server_config(tmp_path)
    config["omero.fs.repo.path"] = "shared/%year%/%group%/%time%"
    managed_root = tmp_path / "data" / "ManagedRepository"
    managed_root.mkdir(parents=True)
    staged_dir = (
        managed_root / "shared" / "2026" / "users_private" / "09-51-15" / "sample.zarr"
    )
    nested_dir = staged_dir / "0"
    nested_dir.mkdir(parents=True)

    conn, repo_proxy, _wait_calls = _managed_repo_conn(managed_root)
    _register_repo_path(repo_proxy, managed_root, staged_dir)

    with pytest.raises(
        RuntimeError, match="only supports staged .zarr directories directly"
    ):
        module._cleanup_zarr(
            conn,
            config,
            str(nested_dir),
            "users_private",
            "alice",
        )

    cleaned = module._cleanup_zarr(
        conn,
        config,
        str(staged_dir),
        "users_private",
        "alice",
    )
    assert cleaned == staged_dir
    assert not staged_dir.exists()
    assert repo_proxy.delete_calls == [
        (["/shared/2026/users_private/09-51-15/sample.zarr/"], True, False)
    ]


def test_manage_script_handles_prefix_not_directory_and_main_entrypoint(
    monkeypatch,
    tmp_path: Path,
):
    """Verify the manage script handles prefix not directory and main entrypoint execution contract.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in manage script handles prefix not directory and main entrypoint integration.
    """
    module = _load_manage_script_module()
    managed_root = tmp_path / "data" / "ManagedRepository"
    managed_root.mkdir(parents=True)
    blocking_file = managed_root / "users_private"
    blocking_file.write_text("not-a-directory", encoding="utf-8")

    with pytest.raises(RuntimeError, match="path is not a directory"):
        module._assert_no_unregistered_existing_dirs(
            object(),
            managed_root,
            managed_root / "users_private" / "alice",
        )

    output_calls = []

    class _Client:
        """Test double for client behavior in this module."""

        @staticmethod
        def getInputs(unwrap=True):
            """Return the inputs for `_Client`.

            Inputs: `unwrap`. Output: `dict`.
            """
            return {}

        @staticmethod
        def setOutput(key, value):
            """Set the output for `_Client`.

            Inputs: `key` lookup key, `value` input value. Output: None.
            """
            output_calls.append((key, value))

        @staticmethod
        def closeSession():
            """Close the session for `_Client`.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            output_calls.append(("closed", True))

    omero_module = types.ModuleType("omero")
    omero_module.scripts = types.SimpleNamespace(
        client=lambda *args, **kwargs: _Client(),
        String=lambda *args, **kwargs: None,
    )
    gateway_module = types.ModuleType("omero.gateway")
    gateway_module.BlitzGateway = lambda client_obj=None: object()
    rtypes_module = types.ModuleType("omero.rtypes")
    rtypes_module.rstring = lambda value: value

    original_modules = {
        name: sys.modules.get(name)
        for name in ("omero", "omero.gateway", "omero.rtypes")
    }
    sys.modules["omero"] = omero_module
    sys.modules["omero.gateway"] = gateway_module
    sys.modules["omero.rtypes"] = rtypes_module
    try:
        with pytest.raises(RuntimeError):
            runpy.run_path(
                str(
                    REPO_ROOT
                    / "omeroweb_import"
                    / "omero_scripts"
                    / "Manage_Zarr_ManagedRepository.py"
                ),
                run_name="__main__",
            )
    finally:
        for name, original in original_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    assert ("closed", True) in output_calls


def test_manage_script_repository_helper_edges_cover_proxy_and_cleanup_failures(
    tmp_path: Path,
):
    """Verify the manage script repository helper edges cover proxy and cleanup failures execution contract.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in manage script repository helper edges cover proxy and cleanup failures integration.
    """
    module = _load_manage_script_module()
    config = _server_config(tmp_path)
    managed_root = tmp_path / "data" / "ManagedRepository"
    managed_root.mkdir(parents=True)

    assert (
        module._repo_model_attr(types.SimpleNamespace(path="direct"), "path")
        == "direct"
    )
    assert module._repo_model_attr(types.SimpleNamespace(_path="fallback"), "path") == (
        "fallback"
    )
    assert module._repo_text(None) == ""
    assert module._repo_text(types.SimpleNamespace(_val=" wrapped ")) == "wrapped"
    assert module._repo_text(" raw ") == "raw"
    assert (
        module._repo_description_root(
            types.SimpleNamespace(
                path=types.SimpleNamespace(val=""),
                name=types.SimpleNamespace(val="leaf"),
            )
        )
        == "/leaf"
    )
    assert (
        module._repo_description_root(
            types.SimpleNamespace(
                path=types.SimpleNamespace(val="/data/root"),
                name=types.SimpleNamespace(val=""),
            )
        )
        == "/data/root"
    )

    with pytest.raises(RuntimeError, match="Missing OMERO connection"):
        module._managed_repository_proxy(None, config)

    broken_conn = types.SimpleNamespace(
        c=types.SimpleNamespace(
            sf=types.SimpleNamespace(
                sharedResources=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            )
        )
    )
    with pytest.raises(RuntimeError, match="managed-repository proxy"):
        module._managed_repository_proxy(broken_conn, config)

    unresolved_mapping_description_conn = types.SimpleNamespace(
        c=types.SimpleNamespace(
            sf=types.SimpleNamespace(
                sharedResources=lambda: types.SimpleNamespace(
                    repositories=lambda: types.SimpleNamespace(
                        descriptions=[
                            types.SimpleNamespace(
                                path=types.SimpleNamespace(
                                    val=str(managed_root.parent)
                                ),
                                name=types.SimpleNamespace(val=managed_root.name),
                                hash=types.SimpleNamespace(val="managed-repo-hash"),
                            )
                        ],
                        proxies={"other": object()},
                    )
                )
            )
        )
    )
    with pytest.raises(
        RuntimeError, match="Failed to resolve the managed-repository proxy"
    ):
        module._managed_repository_proxy(unresolved_mapping_description_conn, config)

    managed_proxy = object()
    managed_conn = types.SimpleNamespace(
        c=types.SimpleNamespace(
            sf=types.SimpleNamespace(
                sharedResources=lambda: types.SimpleNamespace(
                    repositories=lambda: types.SimpleNamespace(
                        descriptions=[],
                        proxies={"ManagedRepository": managed_proxy},
                    )
                )
            )
        )
    )
    assert module._managed_repository_proxy(managed_conn, config) is managed_proxy

    single_mapping_proxy = object()
    single_mapping_conn = types.SimpleNamespace(
        c=types.SimpleNamespace(
            sf=types.SimpleNamespace(
                sharedResources=lambda: types.SimpleNamespace(
                    repositories=lambda: types.SimpleNamespace(
                        descriptions=[],
                        proxies={"only": single_mapping_proxy},
                    )
                )
            )
        )
    )
    assert (
        module._managed_repository_proxy(single_mapping_conn, config)
        is single_mapping_proxy
    )

    single_sequence_proxy = object()
    single_sequence_conn = types.SimpleNamespace(
        c=types.SimpleNamespace(
            sf=types.SimpleNamespace(
                sharedResources=lambda: types.SimpleNamespace(
                    repositories=lambda: types.SimpleNamespace(
                        descriptions=[],
                        proxies=[single_sequence_proxy],
                    )
                )
            )
        )
    )
    assert (
        module._managed_repository_proxy(single_sequence_conn, config)
        is single_sequence_proxy
    )

    unresolved_conn = types.SimpleNamespace(
        c=types.SimpleNamespace(
            sf=types.SimpleNamespace(
                sharedResources=lambda: types.SimpleNamespace(
                    repositories=lambda: types.SimpleNamespace(
                        descriptions=[],
                        proxies={},
                    )
                )
            )
        )
    )
    with pytest.raises(
        RuntimeError, match="Failed to resolve the managed-repository proxy"
    ):
        module._managed_repository_proxy(unresolved_conn, config)

    target_dir = managed_root / "users_private" / "alice" / "2026-03-22" / "09-51-15"
    failing_proxy = types.SimpleNamespace(
        makeDir=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("mkdir boom")
        )
    )
    with pytest.raises(
        RuntimeError,
        match="Failed to create registered managed-repository directory",
    ):
        module._register_managed_directory(failing_proxy, managed_root, target_dir)

    failing_exists_proxy = types.SimpleNamespace(
        fileExists=lambda path: (_ for _ in ()).throw(RuntimeError("exists boom"))
    )
    with pytest.raises(
        RuntimeError,
        match="Failed to query managed-repository registration state",
    ):
        module._repository_directory_registered(
            failing_exists_proxy,
            managed_root,
            target_dir,
        )

    failing_wait_conn = types.SimpleNamespace(
        c=types.SimpleNamespace(
            waitOnCmd=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("wait boom")
            )
        )
    )
    deleting_proxy = types.SimpleNamespace(
        deletePaths=lambda *args, **kwargs: "delete-handle"
    )
    with pytest.raises(RuntimeError, match="Failed to delete managed-repository path"):
        module._delete_registered_managed_path(
            failing_wait_conn,
            deleting_proxy,
            managed_root,
            target_dir / "sample.zarr",
        )


def test_manage_script_relative_path_and_cleanup_root_guards_cover_remaining_edges(
    tmp_path: Path,
):
    """Verify the manage script relative path and cleanup root guards cover remaining edges execution contract.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when manage script relative path and cleanup root guards cover remaining edges accepts unsafe input.
    """
    module = _load_manage_script_module()
    config = _server_config(tmp_path)
    managed_root = tmp_path / "data" / "ManagedRepository"
    managed_root.mkdir(parents=True)
    (tmp_path / "shared").mkdir(parents=True)

    outside_target = tmp_path / "outside" / "sample.zarr"
    with pytest.raises(RuntimeError, match="Managed-repository path escaped its root"):
        module._repo_relative_path(managed_root, outside_target, directory=True)

    with pytest.raises(RuntimeError, match="relative path must not be empty"):
        module._repo_relative_path(managed_root, managed_root, directory=True)

    with pytest.raises(RuntimeError, match="outside the managed repository"):
        module._cleanup_zarr(
            object(),
            config,
            str(outside_target),
            "users_private",
            "alice",
        )

    missing_staged_dir = (
        managed_root
        / "users_private"
        / "alice"
        / "2026-03-22"
        / "09-51-15"
        / "sample.zarr"
    )
    assert (
        module._cleanup_zarr(
            object(),
            config,
            str(missing_staged_dir),
            "users_private",
            "alice",
        )
        == missing_staged_dir
    )


def test_manage_script_stage_and_cleanup_cover_remaining_registered_path_guards(
    tmp_path: Path,
):
    """Verify the manage script stage and cleanup cover remaining registered path guards execution contract.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when manage script stage and cleanup cover remaining registered path guards accepts unsafe input.
    """
    module = _load_manage_script_module()
    config = _server_config(tmp_path)
    managed_root = tmp_path / "data" / "ManagedRepository"
    managed_root.mkdir(parents=True)
    source = tmp_path / "shared" / "job-1" / "sample.zarr"
    (source / "0").mkdir(parents=True)
    (source / "0" / "0").write_text("pixels", encoding="utf-8")

    conn, repo_proxy, _wait_calls = _managed_repo_conn(managed_root)
    fixed_now = datetime(2026, 3, 22, 9, 51, 15)

    class _FixedDatetime:
        """Test double for fixed datetime behavior in this module."""

        @staticmethod
        def now():
            """Return `_FixedDatetime`'s fixed timestamp.

            Inputs: none. Output: `fixed_now`.
            """
            return fixed_now

    original_datetime = module.datetime
    original_prefix_directories = module._prefix_directories
    module.datetime = _FixedDatetime
    broken_prefix = managed_root / "broken-prefix"
    broken_prefix.write_text("not-a-directory", encoding="utf-8")
    module._prefix_directories = lambda managed_root, leaf_parent: [broken_prefix]
    try:
        with pytest.raises(RuntimeError, match="prefix path is not a directory"):
            module._stage_zarr(
                conn,
                config,
                str(source),
                "users_private",
                "alice",
            )
    finally:
        module.datetime = original_datetime
        module._prefix_directories = original_prefix_directories

    staged_dir = (
        managed_root
        / "users_private"
        / "alice"
        / "2026-03-22"
        / "09-51-15"
        / "sample.zarr"
    )
    unregistered_dir = (
        managed_root
        / "users_private"
        / "alice"
        / "2026-03-22"
        / "09-51-16"
        / "other.zarr"
    )
    unregistered_dir.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="only supports staged .zarr directories"):
        module._cleanup_zarr(
            conn,
            config,
            str(staged_dir.with_name("sample.txt")),
            "users_private",
            "alice",
        )

    with pytest.raises(
        RuntimeError, match="path exists on disk but is not registered in OMERO"
    ):
        module._cleanup_zarr(
            conn,
            config,
            str(unregistered_dir),
            "users_private",
            "alice",
        )

    _register_repo_path(repo_proxy, managed_root, staged_dir)
    shutil.rmtree(staged_dir)
    staged_dir.write_text("not-a-directory", encoding="utf-8")
    with pytest.raises(RuntimeError, match="path is not a directory"):
        module._cleanup_zarr(
            conn,
            config,
            str(staged_dir),
            "users_private",
            "alice",
        )

    staged_dir.unlink()
    nested_dir = staged_dir / "0"
    nested_dir.mkdir(parents=True)
    _register_repo_path(repo_proxy, managed_root, staged_dir)
    with pytest.raises(
        RuntimeError,
        match="directly under the configured managed-repository template",
    ):
        module._cleanup_zarr(
            conn,
            config,
            str(nested_dir),
            "users_private",
            "alice",
        )
