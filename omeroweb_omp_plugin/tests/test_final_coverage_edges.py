from __future__ import annotations

import json
from types import SimpleNamespace

from django.http import HttpResponse
from django.test import RequestFactory

from omeroweb_omp_plugin.services.omero import annotation_service, image_service
from omeroweb_omp_plugin.views import ai_credentials_view, index_view


def _json_payload(response):
    return json.loads(response.content.decode("utf-8"))


def _unwrap_view(func):
    while hasattr(func, "__wrapped__"):
        func = func.__wrapped__
    return func


class _Value:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class _Image:
    def __init__(self, image_id, name):
        self._id = image_id
        self._name = name

    def getId(self):
        return _Value(self._id)

    def getName(self):
        return self._name


class _Dataset:
    def __init__(self, dataset_id, name, images):
        self._id = dataset_id
        self._name = name
        self._images = list(images)

    def getId(self):
        return _Value(self._id)

    def getName(self):
        return self._name

    def listChildren(self):
        return list(self._images)


class _Project:
    def __init__(self, datasets):
        self._datasets = list(datasets)

    def listChildren(self):
        return list(self._datasets)


class _ExplodingFormatImage:
    @property
    def getFileset(self):
        raise RuntimeError("format failure")

    @staticmethod
    def getId():
        return _Value(1)

    @staticmethod
    def getName():
        return "sample.tif"


def test_list_models_covers_claude_custom_and_empty_model_sets(monkeypatch):
    monkeypatch.setattr(ai_credentials_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(
        ai_credentials_view,
        "get_ai_credential",
        lambda username, provider: "test-key",
    )

    class _Response:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload

        def json(self):
            return self._payload

    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: _Response({"data": [{"id": "claude-3-5-sonnet-20240620"}]}),
    )
    claude = _unwrap_view(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "claude"}),
        conn=None,
    )
    assert _json_payload(claude)["supports_models"] is True
    assert _json_payload(claude)["default_model"] == "claude-3-5-sonnet-20240620"

    monkeypatch.setitem(
        ai_credentials_view._MODEL_ENDPOINTS,
        "custom",
        {
            "url": "https://api.example.test/models",
            "headers": lambda key: {},
        },
    )
    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: _Response({"objects": []}),
    )
    custom = _unwrap_view(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "custom"}),
        conn=None,
    )
    assert _json_payload(custom) == {
        "models": [],
        "default_model": None,
        "supports_models": False,
    }

    monkeypatch.setattr(
        ai_credentials_view.requests,
        "request",
        lambda **kwargs: _Response({"data": []}),
    )
    empty_claude = _unwrap_view(ai_credentials_view.list_models)(
        RequestFactory().get("/", data={"provider": "claude"}),
        conn=None,
    )
    assert _json_payload(empty_claude)["supports_models"] is False


def test_annotation_and_image_services_cover_remaining_nonfatal_edge_paths(
    monkeypatch,
):
    def _query_service():
        return object()

    class _NamedValueWithBrokenGetter:
        name = _Value("alpha")

        @staticmethod
        def getValue():
            raise RuntimeError("value unavailable")

    map_ann = SimpleNamespace(
        getMapValue=lambda: [_NamedValueWithBrokenGetter()],
        getId=lambda: _Value(7),
    )
    empty_ann = SimpleNamespace(
        getMapValue=lambda: [],
        getId=lambda: _Value(None),
    )
    assert annotation_service.is_plugin_annotation(map_ann) is False
    assert annotation_service.is_plugin_annotation(empty_ann) is False
    monkeypatch.setattr(
        annotation_service,
        "find_plugin_annotation_ids",
        lambda conn, image_id, allow_legacy=True: (_ for _ in ()).throw(
            RuntimeError("plugin scan failed")
        ),
    )

    deleted = annotation_service.delete_existing_annotations(
        SimpleNamespace(
            SERVICE_OPTS=object(),
            getQueryService=_query_service,
            getObject=lambda kind, obj_id: None,
        ),
        SimpleNamespace(deleteObject=lambda obj: None),
        SimpleNamespace(
            id=5,
            listAnnotations=lambda: [],
        ),
        mode="plugin",
        var_names=[],
    )
    assert deleted == (0, 0, 0)

    dataset = _Dataset(11, "Dataset", [_ExplodingFormatImage()])
    project = _Project([dataset])
    monkeypatch.setattr(image_service, "is_owned_by_user", lambda *_args: True)
    summaries = image_service.collect_dataset_summaries(
        SimpleNamespace(getObject=lambda object_type, project_id: project),
        "7",
        owner_id=1,
    )
    assert summaries == [
        {
            "id": "11",
            "name": "Dataset",
            "image_count": 1,
            "formats": "Unknown",
        }
    ]


def test_index_view_covers_remaining_group_helper_and_action_guard_edges(monkeypatch):
    class _Group:
        def __init__(self, permissions, member_count=1):
            self._permissions = permissions
            self._member_count = member_count

        def getDetails(self):
            return SimpleNamespace(getPermissions=lambda: self._permissions)

        def getPermissions(self):
            return self._permissions

        def getMemberCount(self):
            return self._member_count

        @staticmethod
        def getId():
            return _Value(1)

    blank_group = _Group(None, member_count=1)
    assert index_view._group_is_read_write(blank_group) is False
    assert index_view._group_is_read_annotate(blank_group) is False

    monkeypatch.setattr(index_view, "_iter_member_groups", lambda conn: [blank_group])
    monkeypatch.setattr(index_view, "_group_member_count", lambda conn, group: 1)
    assert index_view._has_collaboration_groups(SimpleNamespace()) is False

    broken_obj = SimpleNamespace(
        getDetails=lambda: (_ for _ in ()).throw(RuntimeError("details exploded"))
    )
    assert index_view._get_object_group(broken_obj) is None

    factory = RequestFactory()
    conn = SimpleNamespace()
    monkeypatch.setattr(index_view, "_current_user_id", lambda conn: 7)
    monkeypatch.setattr(
        index_view, "_collect_project_payload", lambda conn, user_id: {}
    )
    monkeypatch.setattr(
        index_view,
        "_get_accessible_project",
        lambda conn, project_id, user_id: (
            SimpleNamespace(getName=lambda: "Project"),
            "owned",
        ),
    )
    monkeypatch.setattr(
        index_view, "check_major_action_rate_limit", lambda *_args: (True, 0)
    )
    monkeypatch.setattr(index_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(index_view, "get_ai_credential", lambda *_args: "token")
    monkeypatch.setattr(
        index_view,
        "collect_images_by_selected_datasets",
        lambda *_args, **_kwargs: [
            (
                SimpleNamespace(getId=lambda: _Value(10)),
                [
                    SimpleNamespace(
                        getId=lambda: _Value(17), getName=lambda: "sample.tif"
                    )
                ],
            )
        ],
    )
    monkeypatch.setattr(
        index_view,
        "generate_ai_regex",
        lambda provider, api_key, filenames, model=None: {"regex": "_", "source": "ai"},
    )
    regex_ok = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={
                "action": "ai_regex",
                "project": "5",
                "selected_datasets": "10",
                "provider": "groq",
            },
        ),
        conn=conn,
    )
    assert _json_payload(regex_ok) == {"regex": "_", "source": "ai"}

    monkeypatch.setattr(
        index_view,
        "_get_accessible_project",
        lambda conn, project_id, user_id: (None, "owned"),
    )
    regex_missing_project = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={
                "action": "ai_regex",
                "project": "5",
                "selected_datasets": "10",
            },
        ),
        conn=conn,
    )
    assert regex_missing_project.status_code == 400

    monkeypatch.setattr(
        index_view,
        "_get_accessible_project",
        lambda conn, project_id, user_id: (
            SimpleNamespace(getName=lambda: "Project"),
            "owned",
        ),
    )
    regex_missing_datasets = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={"action": "ai_regex", "project": "5", "selected_datasets": "   "},
        ),
        conn=conn,
    )
    assert regex_missing_datasets.status_code == 400

    monkeypatch.setattr(
        index_view, "check_major_action_rate_limit", lambda *_args: (False, 15)
    )
    regex_rate_limited = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={"action": "ai_regex", "project": "5", "selected_datasets": "10"},
        ),
        conn=conn,
    )
    assert regex_rate_limited.status_code == 429

    monkeypatch.setattr(index_view, "_current_user_id", lambda conn: None)
    parse_missing_user = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": "10",
                "provider": "groq",
            },
        ),
        conn=conn,
    )
    assert parse_missing_user.status_code == 400

    monkeypatch.setattr(index_view, "_current_user_id", lambda conn: 7)
    parse_missing_project = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={
                "action": "ai_parse",
                "project": "",
                "selected_datasets": "10",
                "provider": "groq",
            },
        ),
        conn=conn,
    )
    assert parse_missing_project.status_code == 400

    parse_missing_datasets = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": "",
                "provider": "groq",
            },
        ),
        conn=conn,
    )
    assert parse_missing_datasets.status_code == 400

    parse_invalid_ids = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": " , ",
                "provider": "groq",
            },
        ),
        conn=conn,
    )
    assert parse_invalid_ids.status_code == 400

    monkeypatch.setattr(
        index_view, "check_major_action_rate_limit", lambda *_args: (True, 0)
    )
    monkeypatch.setattr(
        index_view,
        "collect_images_by_selected_datasets",
        lambda *_args, **_kwargs: [
            (
                SimpleNamespace(getId=lambda: _Value(10)),
                [
                    SimpleNamespace(
                        getName=lambda: (_ for _ in ()).throw(
                            RuntimeError("name failure")
                        ),
                        getId=lambda: _Value(17),
                    )
                ],
            )
        ],
    )
    parse_bad_image = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": "10",
                "provider": "groq",
            },
        ),
        conn=conn,
    )
    assert parse_bad_image.status_code == 400

    monkeypatch.setattr(
        index_view,
        "collect_images_by_selected_datasets",
        lambda *_args, **_kwargs: [
            (
                SimpleNamespace(getId=lambda: _Value(10)),
                [
                    SimpleNamespace(
                        getName=lambda: "sample.tif", getId=lambda: _Value(17)
                    )
                ],
            )
        ],
    )
    monkeypatch.setattr(index_view, "current_username", lambda *_args: "")
    parse_missing_username = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": "10",
                "provider": "groq",
            },
        ),
        conn=conn,
    )
    assert parse_missing_username.status_code == 400

    monkeypatch.setattr(index_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(
        index_view,
        "get_ai_credential",
        lambda *_args: (_ for _ in ()).throw(
            index_view.AiCredentialStoreError("store failed")
        ),
    )
    parse_store_error = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": "10",
                "provider": "groq",
            },
        ),
        conn=conn,
    )
    assert parse_store_error.status_code == 500

    monkeypatch.setattr(index_view, "get_ai_credential", lambda *_args: "")
    parse_missing_key = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": "10",
                "provider": "groq",
            },
        ),
        conn=conn,
    )
    assert parse_missing_key.status_code == 400

    rendered = {}
    monkeypatch.setattr(index_view, "reverse", lambda name: f"/{name}/")
    monkeypatch.setattr(index_view, "list_ai_provider_options", lambda: [])
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context: (
            rendered.update({"template": template, "context": context})
            or HttpResponse(json.dumps(rendered), content_type="application/json")
        ),
    )
    preview_missing_datasets = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={
                "project": "5",
                "selected_datasets": "",
                "separator_mode": "chars",
                "separator": "_",
            },
        ),
        conn=conn,
    )
    assert _json_payload(preview_missing_datasets)["context"]["error_message"] == (
        index_view.errors.datasets_required()
    )

    preview_bad_dataset_id = _unwrap_view(index_view.index)(
        factory.post(
            "/",
            data={
                "project": "5",
                "selected_datasets": "x",
                "separator_mode": "chars",
                "separator": "_",
            },
        ),
        conn=conn,
    )
    assert _json_payload(preview_bad_dataset_id)["context"]["error_message"] == (
        index_view.errors.datasets_required()
    )
