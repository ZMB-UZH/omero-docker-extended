from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

import pytest
from django.http import Http404
from django.test import RequestFactory

from omeroweb_omp_plugin.services import core, http_utils
from omeroweb_omp_plugin.services.omero import annotation_service
from omeroweb_omp_plugin.services.parsing import filename_parser
from omeroweb_omp_plugin.views import help_view, user_settings_view


def _json_payload(response):
    """Handle JSON payload."""
    return json.loads(response.content.decode("utf-8"))


def test_http_utils_cover_response_and_stream_fallback_paths():
    """Verify test HTTP utils cover response and stream fal behavior."""
    nested_response = SimpleNamespace(
        json=lambda: {"message": {"message": "nested detail"}},
        text="ignored",
    )
    plain_response = SimpleNamespace(
        json=lambda: {"error": "plain detail"},
        text="ignored",
    )
    string_response = SimpleNamespace(
        json=lambda: "  raw detail  ",
        text="ignored",
    )
    text_fallback = SimpleNamespace(
        json=lambda: (_ for _ in ()).throw(ValueError("bad json")),
        text="  text fallback  ",
    )

    class _UnreadableBody:
        """Represent unreadable body."""

        @staticmethod
        def read():
            """Return read."""
            raise RuntimeError("unreadable")

    assert http_utils.extract_error_details(
        SimpleNamespace(response=nested_response)
    ) == ("nested detail")
    assert http_utils.extract_error_details(plain_response) == "plain detail"
    assert http_utils.extract_error_details(string_response) == "raw detail"
    assert http_utils.extract_error_details(text_fallback) == "text fallback"
    assert http_utils.extract_error_details(_UnreadableBody()) is None


def test_core_wrapper_and_filename_parser_paths_follow_runtime_contracts(
    monkeypatch,
):
    """Verify test core wrapper and filename parser paths f behavior."""
    monkeypatch.setattr(
        annotation_service,
        "canonicalize_mapping",
        lambda mapping: f"canonical:{mapping['id']}",
    )
    monkeypatch.setattr(
        annotation_service,
        "is_plugin_annotation",
        lambda annotation: annotation == "ann",
    )
    monkeypatch.setattr(
        annotation_service,
        "find_plugin_annotation_ids",
        lambda conn, image_id, allow_legacy=True: [image_id, allow_legacy],
    )
    monkeypatch.setattr(
        annotation_service,
        "find_annotation_link_ids",
        lambda conn, annotation_ids: ["links", annotation_ids],
    )
    monkeypatch.setattr(
        annotation_service,
        "find_map_annotation_ids",
        lambda conn, image_id: [image_id, "map"],
    )
    monkeypatch.setattr(
        annotation_service,
        "delete_existing_annotations",
        lambda conn, image_id, **kwargs: (image_id, kwargs),
    )

    assert core._canonicalize_mapping({"id": 3}) == "canonical:3"
    assert core.is_plugin_annotation("ann") is True
    assert core.find_plugin_annotation_ids(object(), 7, allow_legacy=False) == [
        7,
        False,
    ]
    assert core.find_annotation_link_ids(object(), [1, 2]) == ["links", [1, 2]]
    assert core.find_map_annotation_ids(object(), 9) == [9, "map"]
    assert core.delete_existing_annotations(
        object(),
        11,
        annotation_ids=[1],
        link_ids=[2],
        allow_legacy=False,
    ) == (
        11,
        {"annotation_ids": [1], "link_ids": [2], "allow_legacy": False},
    )

    assert filename_parser.parse_filename("prefix [sample-A].ome.tif", "_") == [
        "sample-A"
    ]
    assert filename_parser.parse_filename("folder sample_A-01.tif", "[-_]") == [
        "sample",
        "A",
        "01",
    ]
    assert filename_parser.parse_filename("sample_A.ome.tif", "_") == [
        "sample",
        "A.ome",
    ]
    assert filename_parser.parse_filename("sample_A-01.ome.tif", "[-_]+") == [
        "sample",
        "A",
        "01.ome",
    ]

    with pytest.raises(ValueError, match="Invalid separator regex"):
        filename_parser.parse_filename("sample.ome.tif", 7)

    with pytest.raises(ValueError, match="Invalid separator regex"):
        filename_parser.parse_filename("sample.ome.tif", "x" * 129)

    with pytest.raises(ValueError, match="Invalid separator regex"):
        filename_parser.parse_filename("sample.ome.tif", r"(?=_)")

    with pytest.raises(ValueError, match="Invalid separator regex"):
        filename_parser.parse_filename("sample.ome.tif", "a.*")

    assert core._normalize_annotation_ids([1, "2", "bad", None, 2, 1]) == [1, 2]


def test_core_delete_existing_annotations_supports_runtime_positional_signature(
    monkeypatch,
):
    """Verify test core delete existing annotations support behavior."""
    captured = {}

    def fake_delete(conn, update, img, var_names, mode):
        """Handle fake delete."""
        captured["args"] = (conn, update, img, var_names, mode)
        return (1, 2, 3)

    monkeypatch.setattr(annotation_service, "delete_existing_annotations", fake_delete)

    result = core.delete_existing_annotations(
        "conn",
        "update",
        "img",
        ["var_a"],
        "plugin",
    )

    assert result == (1, 2, 3)
    assert captured["args"] == ("conn", "update", "img", ["var_a"], "plugin")


def test_core_delete_existing_annotations_falls_back_to_id_based_deletion(
    monkeypatch,
):
    """Verify test core delete existing annotations falls b behavior."""
    deleted = []

    class _Stub:
        """Test double for stub."""

        def setId(self, value):
            """Store set identifier."""
            self.id = value

    class _Update:
        """Represent update."""

        @staticmethod
        def deleteObject(obj):
            """Handle delete object."""
            deleted.append(obj.id)

    class _Conn:
        """Represent conn."""

        @staticmethod
        def getObject(*_args):
            """Return get object."""
            return None

        @staticmethod
        def getUpdateService():
            """Return get update service."""
            return _Update()

        @staticmethod
        def deleteObjects(kind, object_ids, wait=True):
            """Handle delete objects."""
            deleted.extend((kind, object_id, wait) for object_id in object_ids)

    def fake_delete(conn, update, img, var_names, mode):
        """Handle fake delete."""
        raise AssertionError("legacy id-based fallback should handle this path")

    monkeypatch.setattr(annotation_service, "delete_existing_annotations", fake_delete)
    monkeypatch.setattr(
        annotation_service,
        "find_plugin_annotation_ids",
        lambda *_args, **_kwargs: [7, 8],
    )
    monkeypatch.setattr(
        annotation_service,
        "find_annotation_link_ids",
        lambda _conn, annotation_id: [annotation_id + 100],
    )
    monkeypatch.setattr(core, "MapAnnotationI", _Stub)
    monkeypatch.setattr(core, "ImageAnnotationLinkI", _Stub)
    monkeypatch.setattr(core, "rlong", lambda value: value)

    result = core.delete_existing_annotations(_Conn(), 11, allow_legacy=False)

    assert result == (2, 2, 2)
    assert deleted == [
        107,
        108,
        ("Annotation", 7, True),
        ("Annotation", 8, True),
    ]


def test_help_page_and_user_settings_views_cover_success_and_error_paths(
    monkeypatch,
):
    """Verify test help page and user settings views cover behavior."""
    factory = RequestFactory()

    response = inspect.unwrap(help_view.help_page)(factory.get("/help"))
    assert response.status_code == 200
    assert response["Content-Type"] == "text/markdown"
    response.close()

    monkeypatch.setattr(help_view.Path, "exists", lambda self: False)
    with pytest.raises(Http404):
        inspect.unwrap(help_view.help_page)(factory.get("/help"))

    assert (
        inspect.unwrap(user_settings_view.save_settings)(
            factory.get("/settings"),
            conn=object(),
        ).status_code
        == 405
    )

    post_request = factory.post("/settings", data={})
    monkeypatch.setattr(user_settings_view, "current_username", lambda *_args: "")
    missing_username = inspect.unwrap(user_settings_view.save_settings)(
        post_request,
        conn=object(),
    )
    assert missing_username.status_code == 400

    monkeypatch.setattr(user_settings_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(
        user_settings_view, "load_request_data", lambda request: {"settings": []}
    )
    invalid_payload = inspect.unwrap(user_settings_view.save_settings)(
        post_request,
        conn=object(),
    )
    assert invalid_payload.status_code == 400

    saved = {}
    monkeypatch.setattr(
        user_settings_view,
        "load_request_data",
        lambda request: {"settings": {"chunk_size": 5}},
    )
    monkeypatch.setattr(
        user_settings_view,
        "save_user_settings",
        lambda username, payload: saved.update(
            {"username": username, "payload": payload}
        ),
    )
    success = inspect.unwrap(user_settings_view.save_settings)(
        post_request, conn=object()
    )
    assert success.status_code == 200
    assert _json_payload(success)["success"] is True
    assert saved == {"username": "alice", "payload": {"chunk_size": 5}}

    monkeypatch.setattr(
        user_settings_view,
        "save_user_settings",
        lambda username, payload: (_ for _ in ()).throw(
            user_settings_view.UserSettingsStoreError("store failed")
        ),
    )
    store_failure = inspect.unwrap(user_settings_view.save_settings)(
        post_request,
        conn=object(),
    )
    assert store_failure.status_code == 500
    assert (
        _json_payload(store_failure)["error"]
        == user_settings_view.errors.user_settings_save_failed()
    )

    monkeypatch.setattr(
        user_settings_view,
        "load_request_data",
        lambda request: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    unexpected = inspect.unwrap(user_settings_view.save_settings)(
        post_request,
        conn=object(),
    )
    assert unexpected.status_code == 500
    assert (
        _json_payload(unexpected)["error"]
        == user_settings_view.errors.unexpected_error()
    )


def test_core_delete_helpers_cover_signature_and_argument_validation_edges(
    monkeypatch,
):
    """Verify test core delete helpers cover signature and behavior."""
    monkeypatch.setattr(
        core.inspect,
        "signature",
        lambda fn: (_ for _ in ()).throw(TypeError("bad signature")),
    )
    assert core._supports_legacy_annotation_kwargs() is False

    with pytest.raises(TypeError, match="exactly one image_id"):
        core.delete_existing_annotations(object(), 1, 2, annotation_ids=[1])

    with pytest.raises(TypeError, match="delete_existing_annotations expects either"):
        core.delete_existing_annotations(object(), "update", "img", "names")

    deleted = []

    class _Stub:
        """Test double for stub."""

        def setId(self, value):
            """Store set identifier."""
            self.id = value

    class _Update:
        """Represent update."""

        @staticmethod
        def deleteObject(obj):
            """Handle delete object."""
            deleted.append(obj)

    class _Conn:
        """Represent conn."""

        @staticmethod
        def getObject(object_type, object_id):
            """Return get object."""
            if object_type == "ImageAnnotationLink":
                raise RuntimeError("lookup failed")
            return SimpleNamespace(_obj=("annotation", object_id))

        @staticmethod
        def getUpdateService():
            """Return get update service."""
            return _Update()

        @staticmethod
        def deleteObjects(kind, object_ids, wait=True):
            """Handle delete objects."""
            deleted.extend((kind, object_id, wait) for object_id in object_ids)

    monkeypatch.setattr(core, "MapAnnotationI", _Stub)
    monkeypatch.setattr(core, "ImageAnnotationLinkI", _Stub)
    monkeypatch.setattr(core, "rlong", lambda value: value)

    result = core._delete_existing_annotations_by_ids(
        _Conn(),
        11,
        annotation_ids=[7],
        link_ids=[101],
    )

    assert result == (1, 1, 1)
    assert isinstance(deleted[0], _Stub)
    assert deleted[0].id == 101
    assert deleted[1] == ("Annotation", 7, True)

    class _ConnWithLoadedLink:
        """Represent conn with loaded link."""

        @staticmethod
        def getObject(object_type, object_id):
            """Return get object."""
            assert object_type == "ImageAnnotationLink"
            return SimpleNamespace(_obj=("loaded-link", object_id))

    deleted.clear()
    assert (
        core._delete_object_by_id(
            _ConnWithLoadedLink(),
            _Update(),
            "ImageAnnotationLink",
            _Stub,
            202,
        )
        is True
    )
    assert deleted == [("loaded-link", 202)]
