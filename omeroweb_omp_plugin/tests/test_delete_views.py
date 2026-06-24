from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

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
        self.update_service = object()

    @staticmethod
    def getUser():
        """Return the fake user.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(getName=lambda: "alice")

    def getUpdateService(self):
        """Return the fake update service.

        Inputs: none. Output: `self.update_service`.
        """
        return self.update_service


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
        "require_destructive_project_access",
        lambda current_conn, project_id: (True, None),
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

    monkeypatch.setattr(
        delete_all_view,
        "delete_existing_annotations",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("delete failed")),
    )
    failed_chunk = inspect.unwrap(delete_all_view.delete_all_keyvaluepairs)(
        factory.post("/omp/delete-all/"),
        conn=conn,
    )
    assert _payload(failed_chunk) == {
        "ok": True,
        "deleted_count": 0,
        "errors": [
            {
                "ids": [1],
                "error": delete_all_view.error_messages.unable_delete_annotations(),
            },
            {
                "ids": [2],
                "error": delete_all_view.error_messages.unable_delete_annotations(),
            },
            {
                "ids": [3],
                "error": delete_all_view.error_messages.unable_delete_annotations(),
            },
        ],
    }

    monkeypatch.setattr(
        delete_all_view,
        "collect_images_in_project",
        lambda current_conn, project_id: images[:2],
    )
    monkeypatch.setattr(
        delete_all_view,
        "delete_existing_annotations",
        lambda *_args: (1, 2, 1),
    )
    monkeypatch.setattr(
        delete_all_view,
        "find_map_annotation_ids",
        lambda current_conn, image_id: [99] if int(image_id) == 1 else [],
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
                "ids": [1],
                "error": delete_all_view.error_messages.map_annotations_still_present(),
                "remaining": [99],
            }
        ],
    }

    monkeypatch.setattr(
        delete_all_view,
        "collect_images_in_project",
        lambda current_conn, project_id: (_ for _ in ()).throw(
            RuntimeError("project unavailable")
        ),
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


def test_delete_all_rejects_project_without_write_access(monkeypatch):
    """Verify delete-all rejects projects without destructive write access.

    Inputs: pytest provides `monkeypatch`. Output: fails on authorization regressions.
    """
    conn = _Conn()
    factory = RequestFactory()
    monkeypatch.setattr(
        delete_all_view,
        "load_json_body",
        lambda request: (_delete_request_payload("5", AUTH_VALUE), None),
    )
    monkeypatch.setattr(
        delete_all_view,
        "validate_user_password",
        lambda current_conn, password: (True, None),
    )
    monkeypatch.setattr(
        delete_all_view,
        "require_destructive_project_access",
        lambda current_conn, project_id: (
            False,
            delete_all_view.error_messages.project_write_access_required(),
        ),
    )
    monkeypatch.setattr(
        delete_all_view,
        "collect_images_in_project",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("images must not be collected without write access")
        ),
    )

    response = inspect.unwrap(delete_all_view.delete_all_keyvaluepairs)(
        factory.post("/omp/delete-all/"),
        conn=conn,
    )

    assert response.status_code == 403
    assert _payload(response) == {
        "error": delete_all_view.error_messages.project_write_access_required()
    }


def test_delete_plugin_view_covers_validation_and_empty_project_paths(monkeypatch):
    """Check delete plugin view covers validation and empty project paths cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in delete plugin view covers validation and empty project paths.
    """
    assert not hasattr(delete_plugin_view, "_run_omero_delete")

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
        "require_destructive_project_access",
        lambda current_conn, project_id: (
            False,
            delete_plugin_view.error_messages.project_write_access_required(),
        ),
    )
    monkeypatch.setattr(
        delete_plugin_view,
        "collect_images_in_project",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("images must not be collected without write access")
        ),
    )
    forbidden = inspect.unwrap(delete_plugin_view.delete_plugin_keyvaluepairs)(
        factory.post("/omp/delete-plugin/"),
        conn=conn,
    )
    assert forbidden.status_code == 403
    assert _payload(forbidden) == {
        "error": delete_plugin_view.error_messages.project_write_access_required()
    }

    monkeypatch.setattr(
        delete_plugin_view,
        "require_destructive_project_access",
        lambda current_conn, project_id: (True, None),
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
        "collect_images_in_project",
        lambda current_conn, project_id: (_ for _ in ()).throw(
            RuntimeError("project unavailable")
        ),
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


def test_delete_plugin_view_covers_gateway_failures_residue_and_success(monkeypatch):
    """Verify delete plugin view covers gateway failures residue and success.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in gateway deletion handling.
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
        "check_major_action_rate_limit",
        lambda request, current_conn: (True, 0),
    )
    monkeypatch.setattr(
        delete_plugin_view,
        "require_destructive_project_access",
        lambda current_conn, project_id: (True, None),
    )
    monkeypatch.setattr(delete_plugin_view, "get_id", lambda obj: obj.id)

    images = [SimpleNamespace(id=value) for value in range(1, 6)]
    monkeypatch.setattr(
        delete_plugin_view,
        "collect_images_in_project",
        lambda current_conn, project_id: images,
    )

    plugin_lookup_counts = {}

    def _plugin_annotation_ids(_conn, image_id):
        """Return fake OMP plugin annotation IDs for delete-view tests.

        Inputs: `_conn`, `image_id` OMERO image ID. Output: ID value. Raises:
        RuntimeError when validation or the called operation fails.
        """
        if image_id == 1:
            raise RuntimeError("lookup failed")
        plugin_lookup_counts[image_id] = plugin_lookup_counts.get(image_id, 0) + 1
        if image_id == 4 and plugin_lookup_counts[image_id] > 1:
            return [104]
        if image_id == 5 and plugin_lookup_counts[image_id] > 1:
            return []
        return {
            2: [],
            3: [103],
            4: [104],
            5: [105],
        }[image_id]

    def _delete_existing_annotations(_conn, _update, img, _var_names, mode):
        """Delete fake plugin annotations using OMERO gateway helpers.

        Inputs: fake gateway arguments. Output: deletion helper tuple.
        Raises: RuntimeError when validation or the called operation fails.
        """
        assert mode == "plugin"
        if img.id == 3:
            raise RuntimeError("gateway delete failed")
        if img.id == 4:
            return 0, 0, 1
        if img.id == 5:
            return 1, 2, 1
        return 0, 0, 0

    monkeypatch.setattr(
        delete_plugin_view,
        "find_plugin_annotation_ids",
        _plugin_annotation_ids,
    )
    monkeypatch.setattr(
        delete_plugin_view,
        "delete_existing_annotations",
        _delete_existing_annotations,
    )

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
                "error": delete_plugin_view.error_messages.unexpected_error(),
            },
            {
                "image": 4,
                "annotations_remaining": [104],
                "error": delete_plugin_view.error_messages.annotation_still_exists(),
            },
        ],
    }
