from __future__ import annotations

import inspect
import json
import subprocess
from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from omeroweb_omp_plugin.views import delete_all_view, delete_plugin_view

EMPTY_TEXT = str()
AUTH_VALUE = "".join(["fixture", "-", "credential"])


def _payload(response):
    """Return the payload.

    Inputs: `response` response object. Output: `loads` result.
    """
    return json.loads(response.content.decode("utf-8"))


def _delete_request_payload(project_id, password_value):
    """Delete the request payload.

    Inputs: `project_id` OMERO project ID, `password_value`. Output: `dict`.
    """
    return {"project_id": project_id, "password": password_value}


class _Conn:
    """Test double for conn behavior in this module."""

    def __init__(self):
        """Create `_Conn` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self.getObject = lambda kind, object_id: None

    @staticmethod
    def getUser():
        """Return the fake user.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(getName=lambda: "alice")


def test_delete_all_view_covers_validation_chunk_failures_and_top_level_errors(
    monkeypatch,
):
    """Check delete all view covers validation chunk failures and top level errors cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in delete all view covers validation chunk failures and top level errors.
    """
    conn = _Conn()
    factory = RequestFactory()

    wrong_method = inspect.unwrap(delete_all_view.delete_all_keyvaluepairs)(
        factory.get("/omp/delete-all/"),
        conn=conn,
    )
    assert wrong_method.status_code == 400

    monkeypatch.setattr(delete_all_view, "load_json_body", lambda request: ({}, "bad"))
    invalid_json = inspect.unwrap(delete_all_view.delete_all_keyvaluepairs)(
        factory.post("/omp/delete-all/"),
        conn=conn,
    )
    assert (
        _payload(invalid_json)["error"]
        == delete_all_view.error_messages.invalid_json_body()
    )

    monkeypatch.setattr(
        delete_all_view,
        "load_json_body",
        lambda request: (_delete_request_payload(EMPTY_TEXT, EMPTY_TEXT), None),
    )
    missing_project = inspect.unwrap(delete_all_view.delete_all_keyvaluepairs)(
        factory.post("/omp/delete-all/"),
        conn=conn,
    )
    assert (
        _payload(missing_project)["error"]
        == delete_all_view.error_messages.missing_project_id()
    )

    monkeypatch.setattr(
        delete_all_view,
        "load_json_body",
        lambda request: (_delete_request_payload("5", EMPTY_TEXT), None),
    )
    missing_password = inspect.unwrap(delete_all_view.delete_all_keyvaluepairs)(
        factory.post("/omp/delete-all/"),
        conn=conn,
    )
    assert (
        _payload(missing_password)["error"]
        == delete_all_view.error_messages.missing_password()
    )

    monkeypatch.setattr(
        delete_all_view,
        "load_json_body",
        lambda request: (_delete_request_payload("5", AUTH_VALUE), None),
    )
    monkeypatch.setattr(
        delete_all_view,
        "validate_user_password",
        lambda current_conn, password: (False, "bad"),
    )
    auth_failed = inspect.unwrap(delete_all_view.delete_all_keyvaluepairs)(
        factory.post("/omp/delete-all/"),
        conn=conn,
    )
    assert _payload(auth_failed) == {
        "ok": False,
        "error": delete_all_view.error_messages.omero_web_login_failed(),
    }

    monkeypatch.setattr(
        delete_all_view,
        "validate_user_password",
        lambda current_conn, password: (True, None),
    )
    monkeypatch.setattr(
        delete_all_view,
        "build_omero_cli_base_command",
        lambda current_conn: ["omero", "-u", "alice"],
    )
    monkeypatch.setattr(
        delete_all_view,
        "collect_images_in_project",
        lambda current_conn, project_id: [],
    )
    no_images = inspect.unwrap(delete_all_view.delete_all_keyvaluepairs)(
        factory.post("/omp/delete-all/"),
        conn=conn,
    )
    assert _payload(no_images) == {
        "ok": True,
        "deleted_count": 0,
        "errors": [],
        "note": delete_all_view.error_messages.no_images_found(),
    }

    images = [SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)]
    monkeypatch.setattr(
        delete_all_view,
        "collect_images_in_project",
        lambda current_conn, project_id: images,
    )
    monkeypatch.setattr(delete_all_view, "get_id", lambda obj: obj.id)
    monkeypatch.setattr(
        delete_all_view,
        "check_major_action_rate_limit",
        lambda request, current_conn: (False, 9),
    )
    rate_limited = inspect.unwrap(delete_all_view.delete_all_keyvaluepairs)(
        factory.post("/omp/delete-all/"),
        conn=conn,
    )
    assert rate_limited.status_code == 429

    monkeypatch.setattr(
        delete_all_view,
        "check_major_action_rate_limit",
        lambda request, current_conn: (True, 0),
    )

    cli_results = {
        "Image/Annotation:1,2,3": subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="delete failed",
        ),
        "Image/Annotation:1,2": subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="deleted",
            stderr="",
        ),
    }

    def _run(cmd, **kwargs):
        """Return the fake subprocess result for cmd and kwargs.

        Inputs: `cmd`, `**kwargs`. Output: `cli_results[cmd[4]]`.
        """
        return cli_results[cmd[4]]

    monkeypatch.setattr(delete_all_view.subprocess, "run", _run)
    failed_chunk = inspect.unwrap(delete_all_view.delete_all_keyvaluepairs)(
        factory.post("/omp/delete-all/"),
        conn=conn,
    )
    assert _payload(failed_chunk) == {
        "ok": True,
        "deleted_count": 0,
        "errors": [
            {
                "ids": ["1", "2", "3"],
                "error": delete_all_view.error_messages.unable_delete_annotations(),
            }
        ],
    }

    monkeypatch.setattr(
        delete_all_view,
        "collect_images_in_project",
        lambda current_conn, project_id: images[:2],
    )
    monkeypatch.setattr(
        delete_all_view,
        "find_map_annotation_ids",
        lambda current_conn, image_id: [99] if str(image_id) == "1" else [],
    )
    partial = inspect.unwrap(delete_all_view.delete_all_keyvaluepairs)(
        factory.post("/omp/delete-all/"),
        conn=conn,
    )
    assert _payload(partial) == {
        "ok": True,
        "deleted_count": 1,
        "errors": [
            {
                "ids": ["1"],
                "error": delete_all_view.error_messages.map_annotations_still_present(),
                "remaining": [99],
            }
        ],
    }

    monkeypatch.setattr(
        delete_all_view,
        "build_omero_cli_base_command",
        lambda current_conn: (_ for _ in ()).throw(RuntimeError("cli unavailable")),
    )
    top_level_error = inspect.unwrap(delete_all_view.delete_all_keyvaluepairs)(
        factory.post("/omp/delete-all/"),
        conn=conn,
    )
    assert top_level_error.status_code == 500
    assert (
        _payload(top_level_error)["error"]
        == delete_all_view.error_messages.unexpected_error()
    )


def test_delete_plugin_view_covers_validation_and_empty_project_paths(monkeypatch):
    """Check delete plugin view covers validation and empty project paths cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in delete plugin view covers validation and empty project paths.
    """
    with pytest.raises(ValueError, match="Invalid annotation id"):
        delete_plugin_view._validated_delete_object_id(0, "annotation id")
    with pytest.raises(ValueError, match="Unsupported OMERO delete target"):
        delete_plugin_view._run_omero_delete(["omero"], "Dataset", 1)

    conn = _Conn()
    factory = RequestFactory()

    wrong_method = inspect.unwrap(delete_plugin_view.delete_plugin_keyvaluepairs)(
        factory.get("/omp/delete-plugin/"),
        conn=conn,
    )
    assert wrong_method.status_code == 400

    monkeypatch.setattr(
        delete_plugin_view, "load_json_body", lambda request: ({}, "bad")
    )
    invalid_json = inspect.unwrap(delete_plugin_view.delete_plugin_keyvaluepairs)(
        factory.post("/omp/delete-plugin/"),
        conn=conn,
    )
    assert (
        _payload(invalid_json)["error"]
        == delete_plugin_view.error_messages.invalid_json_body()
    )

    monkeypatch.setattr(
        delete_plugin_view,
        "load_json_body",
        lambda request: (_delete_request_payload(EMPTY_TEXT, AUTH_VALUE), None),
    )
    missing_project = inspect.unwrap(delete_plugin_view.delete_plugin_keyvaluepairs)(
        factory.post("/omp/delete-plugin/"),
        conn=conn,
    )
    assert (
        _payload(missing_project)["error"]
        == delete_plugin_view.error_messages.missing_project_id()
    )

    monkeypatch.setattr(
        delete_plugin_view,
        "load_json_body",
        lambda request: (_delete_request_payload("5", EMPTY_TEXT), None),
    )
    missing_password = inspect.unwrap(delete_plugin_view.delete_plugin_keyvaluepairs)(
        factory.post("/omp/delete-plugin/"),
        conn=conn,
    )
    assert (
        _payload(missing_password)["error"]
        == delete_plugin_view.error_messages.missing_password()
    )

    monkeypatch.setattr(
        delete_plugin_view,
        "load_json_body",
        lambda request: (_delete_request_payload("5", AUTH_VALUE), None),
    )
    monkeypatch.setattr(
        delete_plugin_view,
        "validate_user_password",
        lambda current_conn, password: (False, "bad"),
    )
    auth_failed = inspect.unwrap(delete_plugin_view.delete_plugin_keyvaluepairs)(
        factory.post("/omp/delete-plugin/"),
        conn=conn,
    )
    assert _payload(auth_failed) == {
        "ok": False,
        "error": delete_plugin_view.error_messages.omero_web_login_failed(),
    }

    monkeypatch.setattr(
        delete_plugin_view,
        "validate_user_password",
        lambda current_conn, password: (True, None),
    )
    monkeypatch.setattr(
        delete_plugin_view,
        "build_omero_cli_base_command",
        lambda current_conn: ["omero", "-u", "alice"],
    )
    monkeypatch.setattr(
        delete_plugin_view,
        "collect_images_in_project",
        lambda current_conn, project_id: [],
    )
    no_images = inspect.unwrap(delete_plugin_view.delete_plugin_keyvaluepairs)(
        factory.post("/omp/delete-plugin/"),
        conn=conn,
    )
    assert _payload(no_images) == {
        "ok": True,
        "deleted_images": 0,
        "deleted_annotations": 0,
        "errors": [],
    }

    monkeypatch.setattr(
        delete_plugin_view,
        "collect_images_in_project",
        lambda current_conn, project_id: [SimpleNamespace(id=1)],
    )
    monkeypatch.setattr(delete_plugin_view, "get_id", lambda obj: obj.id)
    monkeypatch.setattr(
        delete_plugin_view,
        "check_major_action_rate_limit",
        lambda request, current_conn: (False, 12),
    )
    rate_limited = inspect.unwrap(delete_plugin_view.delete_plugin_keyvaluepairs)(
        factory.post("/omp/delete-plugin/"),
        conn=conn,
    )
    assert rate_limited.status_code == 429

    monkeypatch.setattr(
        delete_plugin_view,
        "check_major_action_rate_limit",
        lambda request, current_conn: (True, 0),
    )
    monkeypatch.setattr(
        delete_plugin_view,
        "build_omero_cli_base_command",
        lambda current_conn: (_ for _ in ()).throw(RuntimeError("cli unavailable")),
    )
    top_level_error = inspect.unwrap(delete_plugin_view.delete_plugin_keyvaluepairs)(
        factory.post("/omp/delete-plugin/"),
        conn=conn,
    )
    assert top_level_error.status_code == 500
    assert (
        _payload(top_level_error)["error"]
        == delete_plugin_view.error_messages.unexpected_error()
    )


def test_delete_plugin_view_covers_cli_failures_link_residue_and_success(monkeypatch):
    """Verify the delete plugin view covers CLI failures link residue and success execution contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in delete plugin view covers CLI failures link residue and success.
    Raises: RuntimeError when validation or the called operation fails.
    """
    conn = _Conn()
    factory = RequestFactory()

    monkeypatch.setattr(
        delete_plugin_view,
        "load_json_body",
        lambda request: (_delete_request_payload("5", AUTH_VALUE), None),
    )
    monkeypatch.setattr(
        delete_plugin_view,
        "validate_user_password",
        lambda current_conn, password: (True, None),
    )
    monkeypatch.setattr(
        delete_plugin_view,
        "build_omero_cli_base_command",
        lambda current_conn: ["omero", "-u", "alice"],
    )
    monkeypatch.setattr(
        delete_plugin_view,
        "check_major_action_rate_limit",
        lambda request, current_conn: (True, 0),
    )
    monkeypatch.setattr(delete_plugin_view, "get_id", lambda obj: obj.id)

    images = [SimpleNamespace(id=value) for value in range(1, 8)]
    monkeypatch.setattr(
        delete_plugin_view,
        "collect_images_in_project",
        lambda current_conn, project_id: images,
    )

    def _plugin_annotation_ids(_conn, image_id):
        """Return fake OMP plugin annotation IDs for delete-view tests.

        Inputs: `_conn`, `image_id` OMERO image ID. Output: ID value. Raises:
        RuntimeError when validation or the called operation fails.
        """
        if image_id == 1:
            raise RuntimeError("lookup failed")
        return {
            2: [],
            3: [103],
            4: [104],
            5: [105],
            6: [106],
            7: [107],
        }[image_id]

    link_lookup = {
        103: [[1103], [1103]],
        104: [[], []],
        105: [[], []],
        106: [[], []],
        107: "boom",
    }

    def _find_link_ids(_conn, annotation_id, image_id=None):
        """Find the link IDs.

        Inputs: `_conn`, `annotation_id` OMERO annotation ID, optional `image_id`.
        Output: `list`. Raises: RuntimeError when validation or the called operation
        fails.
        """
        assert image_id in {3, 4, 5, 6, 7}
        state = link_lookup[annotation_id]
        if state == "boom":
            raise RuntimeError("link lookup failed")
        values = state.pop(0)
        return list(values)

    delete_results = {
        "ImageAnnotationLink:1103": subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="link delete failed",
        ),
        "Annotation:104": subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="annotation delete failed",
        ),
        "Annotation:105": subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="deleted annotation",
            stderr="",
        ),
        "Annotation:106": subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="deleted annotation",
            stderr="",
        ),
    }

    def _run(cmd, **kwargs):
        """Return the fake subprocess result for cmd and kwargs.

        Inputs: `cmd`, `**kwargs`. Output: `delete_results[cmd[4]]`.
        """
        return delete_results[cmd[4]]

    annotation_lookup = {
        105: object(),
        106: None,
    }
    conn.getObject = lambda kind, object_id: (
        annotation_lookup.get(object_id) if kind == "MapAnnotation" else None
    )

    monkeypatch.setattr(
        delete_plugin_view,
        "find_plugin_annotation_ids",
        _plugin_annotation_ids,
    )
    monkeypatch.setattr(
        delete_plugin_view,
        "find_annotation_link_ids",
        _find_link_ids,
    )
    monkeypatch.setattr(delete_plugin_view.subprocess, "run", _run)

    response = inspect.unwrap(delete_plugin_view.delete_plugin_keyvaluepairs)(
        factory.post("/omp/delete-plugin/"),
        conn=conn,
    )

    assert _payload(response) == {
        "ok": True,
        "deleted_images": 1,
        "deleted_annotations": 1,
        "errors": [
            {
                "image": 1,
                "error": delete_plugin_view.error_messages.unexpected_error(),
            },
            {
                "image": 3,
                "annotation": 103,
                "link": 1103,
                "error": delete_plugin_view.error_messages.unable_delete_plugin_annotations(),
            },
            {
                "image": 3,
                "annotation": 103,
                "links_remaining": [1103],
                "error": delete_plugin_view.error_messages.annotation_links_still_exist(),
            },
            {
                "image": 4,
                "annotation": 104,
                "error": delete_plugin_view.error_messages.unable_delete_plugin_annotations(),
            },
            {
                "image": 5,
                "annotation": 105,
                "error": delete_plugin_view.error_messages.annotation_still_exists(),
            },
            {
                "image": 7,
                "annotation": 107,
                "error": delete_plugin_view.error_messages.unexpected_error(),
            },
        ],
    }
