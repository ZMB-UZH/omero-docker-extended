from __future__ import annotations

import types

from omeroweb_import.views import core_functions


class _Params:
    """Test double for params behavior in this module."""

    def __init__(self):
        """Create `_Params` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self.values = {}

    def add(self, key, value):
        """Add the add for `_Params`.

        Inputs: `key` lookup key, `value` input value. Output: None.
        """
        self.values[key] = value

    def addId(self, value):
        """Add the ID for `_Params`.

        Inputs: `value` input value. Output: None.
        """
        self.values["id"] = value


class _ServiceOpts:
    """Test double for service opts behavior in this module."""

    def __init__(self):
        """Create `_ServiceOpts` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self.group = None

    def setOmeroGroup(self, value):
        """Set the OMERO Group for `_ServiceOpts`.

        Inputs: `value` input value. Output: None.
        """
        self.group = value


class _ProjectionValue:
    """Test double for projection value behavior in this module."""

    def __init__(self, value):
        """Create `_ProjectionValue` with `value`.

        Inputs: `value`. Output: None.
        """
        self.val = value


class _RenderImage:
    """Test double for render image behavior in this module."""

    def __init__(
        self,
        image_id,
        *,
        sizes=(1, 1, 1, 1, 1),
        external_info=True,
        thumbnail_behavior="bytes",
    ):
        """Create `_RenderImage` with `image_id`.

        Inputs: `image_id`, `sizes`, `external_info`, `thumbnail_behavior`. Output:
        None.

        None.
        """
        self.id = image_id
        self._sizes = sizes
        external = object() if external_info else None
        self._obj = types.SimpleNamespace(
            details=types.SimpleNamespace(externalInfo=external)
        )
        self._thumbnail_behavior = thumbnail_behavior

    def getSizeX(self):
        """Return `_RenderImage`'s fake SizeX value.

        Inputs: none. Output: `self._sizes[0]`.
        """
        return self._sizes[0]

    def getSizeY(self):
        """Return `_RenderImage`'s fake SizeY value.

        Inputs: none. Output: `self._sizes[1]`.
        """
        return self._sizes[1]

    def getSizeZ(self):
        """Return `_RenderImage`'s fake SizeZ value.

        Inputs: none. Output: `self._sizes[2]`.
        """
        return self._sizes[2]

    def getSizeC(self):
        """Return `_RenderImage`'s fake channel count.

        Inputs: none. Output: `self._sizes[3]`.
        """
        return self._sizes[3]

    def getSizeT(self):
        """Return `_RenderImage`'s fake timepoint count.

        Inputs: none. Output: `self._sizes[4]`.
        """
        return self._sizes[4]

    def getThumbnail(self, size=None, direct=None):
        """Return the thumbnail for `_RenderImage`.

        Inputs: `size`, `direct`. Output: get thumbnail result. Raises: RuntimeError
        when validation or the called operation fails.
        """
        if self._thumbnail_behavior == "raise":
            raise RuntimeError("thumbnail failed")
        if self._thumbnail_behavior == "empty":
            return b""
        return b"thumbnail-bytes"


def test_verify_import_via_api_covers_missing_prerequisites_and_query_failures(
    monkeypatch,
) -> None:
    """Verify verify import via API covers missing prerequisites and query failures.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in verify import via API covers missing prerequisites and query failures.
    """
    monkeypatch.setattr(
        core_functions,
        "_params_add_string",
        lambda params, key, value: params.add(key, value),
    )
    monkeypatch.setattr(
        core_functions.omero,
        "sys",
        types.SimpleNamespace(ParametersI=_Params),
        raising=False,
    )

    assert (
        core_functions._verify_import_via_api(
            "",
            "omeroserver",
            4064,
            7,
            "image.ome.tif",
            "image.ome.tif",
        )
        == []
    )

    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: None
    )
    assert (
        core_functions._verify_import_via_api(
            "alice",
            "omeroserver",
            4064,
            7,
            "image.ome.tif",
            "image.ome.tif",
        )
        == []
    )

    state = {"admin_closed": False, "conn_closed": False}
    conn = types.SimpleNamespace(
        SERVICE_OPTS=_ServiceOpts(),
        getQueryService=lambda: types.SimpleNamespace(
            projection=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("boom")
            )
        ),
        close=lambda: state.__setitem__("conn_closed", True),
    )
    admin_conn = types.SimpleNamespace(
        suConn=lambda username: conn,
        close=lambda: state.__setitem__("admin_closed", True),
    )
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )

    assert (
        core_functions._verify_import_via_api(
            "alice",
            "omeroserver",
            4064,
            7,
            "image.ome.tif",
            "image.ome.tif",
        )
        == []
    )
    assert state == {"admin_closed": True, "conn_closed": True}

    admin_conn = types.SimpleNamespace(suConn=lambda username: None, close=lambda: None)
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )
    assert (
        core_functions._verify_import_via_api(
            "alice",
            "omeroserver",
            4064,
            7,
            "image.ome.tif",
            "image.ome.tif",
        )
        == []
    )

    conn = types.SimpleNamespace(
        SERVICE_OPTS=_ServiceOpts(),
        getQueryService=lambda: types.SimpleNamespace(
            projection=lambda *args, **kwargs: []
        ),
        close=lambda: None,
    )
    admin_conn = types.SimpleNamespace(suConn=lambda username: conn, close=lambda: None)
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )
    assert (
        core_functions._verify_import_via_api(
            "alice",
            "omeroserver",
            4064,
            7,
            None,
            None,
        )
        == []
    )


def test_verify_zarr_import_via_api_and_cleanup_imported_images_cover_edge_cases(
    monkeypatch,
) -> None:
    """Check verify Zarr import via API and cleanup imported images cover edge cases cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in verify Zarr import via API and cleanup imported images cover edge cases.
    """
    monkeypatch.setattr(
        core_functions.omero,
        "sys",
        types.SimpleNamespace(ParametersI=_Params),
        raising=False,
    )
    monkeypatch.setattr(
        core_functions.omero,
        "rtypes",
        types.SimpleNamespace(rstring=lambda value: value),
        raising=False,
    )

    assert (
        core_functions._verify_zarr_import_via_api(
            "",
            "omeroserver",
            4064,
            "imported.zarr",
            "image.zarr",
        )
        == []
    )

    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: None
    )
    assert (
        core_functions._verify_zarr_import_via_api(
            "alice",
            "omeroserver",
            4064,
            "imported.zarr",
            "image.zarr",
            expected_lsid="/managed/root/image.zarr",
        )
        == []
    )

    admin_conn = types.SimpleNamespace(suConn=lambda username: None, close=lambda: None)
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )
    assert (
        core_functions._verify_zarr_import_via_api(
            "alice",
            "omeroserver",
            4064,
            "imported.zarr",
            "image.zarr",
            expected_lsid="/managed/root/image.zarr",
        )
        == []
    )

    empty_conn = types.SimpleNamespace(
        SERVICE_OPTS=_ServiceOpts(),
        getQueryService=lambda: types.SimpleNamespace(
            projection=lambda *args, **kwargs: []
        ),
        close=lambda: None,
    )
    admin_conn = types.SimpleNamespace(
        suConn=lambda username: empty_conn, close=lambda: None
    )
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )
    assert (
        core_functions._verify_zarr_import_via_api(
            "alice",
            "omeroserver",
            4064,
            "imported.zarr",
            "image.zarr",
            expected_lsid_prefix="/managed/root/image.zarr",
        )
        == []
    )

    delete_state = {"opened": 0, "closed": False}
    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: None,
    )
    core_functions._cleanup_imported_images("omeroserver", 4064, ["bad-id"])
    core_functions._cleanup_imported_images("omeroserver", 4064, ["10"])

    failing_admin = types.SimpleNamespace(
        SERVICE_OPTS=_ServiceOpts(),
        deleteObjects=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("delete failed")
        ),
        close=lambda: delete_state.__setitem__("closed", True),
    )
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: failing_admin
    )
    core_functions._cleanup_imported_images("omeroserver", 4064, ["10", "bad", "11"])
    assert delete_state["closed"] is True


def test_verify_imported_zarr_images_renderable_reports_remaining_failures(
    monkeypatch,
) -> None:
    """Verify verify imported Zarr images renderable reports remaining failures.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in verify imported Zarr images renderable reports remaining failures.
    """
    assert core_functions._verify_imported_zarr_images_renderable(
        "",
        "omeroserver",
        4064,
        ["1"],
    ) == (
        False,
        ["Missing importing username for post-import render verification."],
    )
    assert core_functions._verify_imported_zarr_images_renderable(
        "alice",
        "omeroserver",
        4064,
        [],
    ) == (
        False,
        ["No imported Image IDs were available for render verification."],
    )

    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: None
    )
    assert core_functions._verify_imported_zarr_images_renderable(
        "alice",
        "omeroserver",
        4064,
        ["1"],
    ) == (
        False,
        ["Failed to open an admin connection for render verification."],
    )

    admin_conn = types.SimpleNamespace(suConn=lambda username: None, close=lambda: None)
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )
    assert core_functions._verify_imported_zarr_images_renderable(
        "alice",
        "omeroserver",
        4064,
        ["1"],
    ) == (
        False,
        ["Failed to open the importing user's session for render verification."],
    )

    failures = {
        1: RuntimeError("lookup exploded"),
        2: None,
        3: _RenderImage(3, sizes=(0, 1, 1, 1, 1)),
        4: _RenderImage(4, external_info=False),
        5: _RenderImage(5),
        6: _RenderImage(6, thumbnail_behavior="raise"),
        7: _RenderImage(7, thumbnail_behavior="empty"),
    }
    state = {"conn_closed": False, "admin_closed": False}

    def _get_object(_kind, image_id):
        """Return the object.

        Inputs: `_kind`, `image_id` OMERO image ID. Output: get object result. Raises:
        payload when validation or the called operation fails.
        """
        payload = failures[image_id]
        if isinstance(payload, Exception):
            raise payload
        return payload

    conn = types.SimpleNamespace(
        SERVICE_OPTS=_ServiceOpts(),
        getObject=_get_object,
        close=lambda: state.__setitem__("conn_closed", True),
    )
    admin_conn = types.SimpleNamespace(
        suConn=lambda username: conn,
        close=lambda: state.__setitem__("admin_closed", True),
    )
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )
    monkeypatch.setattr(
        core_functions,
        "_query_image_external_info",
        lambda conn, image_id: (
            ("/managed/root/other.zarr", "Image")
            if image_id == 5
            else ("/managed/root/image.zarr", "Image")
        ),
    )

    ok, errors = core_functions._verify_imported_zarr_images_renderable(
        "alice",
        "omeroserver",
        4064,
        ["1", "2", "3", "4", "5", "6", "7"],
        expected_lsid="/managed/root/image.zarr",
        group_name="users_private",
    )

    assert ok is False
    assert any("lookup failed" in error for error in errors)
    assert any("could not be loaded after import" in error for error in errors)
    assert any("invalid dimensions" in error for error in errors)
    assert any("missing externalInfo" in error for error in errors)
    assert any("unexpected externalInfo.lsid" in error for error in errors)
    assert any("thumbnail 96x96 failed" in error for error in errors)
    assert any("thumbnail 96x96 returned no data" in error for error in errors)
    assert conn.SERVICE_OPTS.group == "users_private"
    assert state == {"conn_closed": True, "admin_closed": True}


def test_run_zarr_managed_repo_script_and_cleanup_helpers_cover_error_paths(
    monkeypatch,
    tmp_path,
) -> None:
    """Confirm run Zarr managed repo script and cleanup helpers cover error paths exposes the expected failure.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions when run Zarr managed repo script and cleanup helpers cover error paths stops reporting the expected error.
    """
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: None
    )
    assert core_functions._run_zarr_managed_repo_script(
        "stage",
        "omeroserver",
        4064,
        username="alice",
        group_name="users_private",
    ) == (
        False,
        {},
        "Unable to open an admin OMERO session for managed-repository Zarr staging.",
    )

    admin_conn = types.SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )
    monkeypatch.setattr(
        core_functions, "_find_script_id_by_name", lambda *args, **kwargs: None
    )
    assert core_functions._run_zarr_managed_repo_script(
        "stage",
        "omeroserver",
        4064,
        username="alice",
        group_name="users_private",
    ) == (
        False,
        {},
        f"OMERO script not found: {core_functions.ZARR_MANAGED_REPO_SCRIPT_NAME}",
    )

    monkeypatch.setattr(
        core_functions, "_find_script_id_by_name", lambda *args, **kwargs: 17
    )
    monkeypatch.setattr(core_functions, "_get_root_password", lambda: "")
    ok, outputs, message = core_functions._run_zarr_managed_repo_script(
        "stage",
        "omeroserver",
        4064,
        username="alice",
        group_name="users_private",
    )
    assert ok is False
    assert outputs == {}
    assert "ROOTPASS is missing" in message

    monkeypatch.setattr(core_functions, "_get_root_password", lambda: "secret")
    monkeypatch.setattr(core_functions, "_build_cli_env", lambda: {})
    monkeypatch.setattr(core_functions, "_get_import_timeout_seconds", lambda: 60)
    monkeypatch.setattr(core_functions, "_get_script_start_timeout_seconds", lambda: 0)
    monkeypatch.setattr(core_functions, "_get_script_start_retry_seconds", lambda: 0)
    monkeypatch.setattr(
        core_functions.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            core_functions.subprocess.TimeoutExpired(cmd="omero", timeout=60)
        ),
    )
    ok, outputs, message = core_functions._run_zarr_managed_repo_script(
        "stage",
        "omeroserver",
        4064,
        username="alice",
        group_name="users_private",
    )
    assert ok is False
    assert outputs == {}
    assert "timed out" in message

    monkeypatch.setattr(
        core_functions.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cli exploded")),
    )
    ok, outputs, message = core_functions._run_zarr_managed_repo_script(
        "stage",
        "omeroserver",
        4064,
        username="alice",
        group_name="users_private",
    )
    assert ok is False
    assert outputs == {}
    assert message == "cli exploded"

    monkeypatch.setattr(
        core_functions,
        "_run_zarr_managed_repo_script",
        lambda *args, **kwargs: (False, {}, "cleanup failed"),
    )
    core_functions._cleanup_managed_zarr_path(
        "omeroserver",
        4064,
        username="alice",
        group_name="users_private",
        managed_path=tmp_path / "managed.zarr",
    )
