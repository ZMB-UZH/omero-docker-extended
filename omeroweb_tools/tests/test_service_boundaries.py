from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from omeroweb_tools.services import acquisition_metadata as metadata
from omeroweb_tools.services import enhanced_search_service as service


class _DbConn:
    """Test double for database conn behavior in this module."""

    def __enter__(self):
        """Enter `_DbConn`'s context-managed fake resource.

        Inputs: none. Output: `self`.
        """
        return self

    def __exit__(self, exc_type, exc, tb):
        """Exit `_DbConn`'s context-managed fake resource.

        Inputs: `exc_type`, `exc`, `tb`. Output: bool.
        """
        return False


def _db_connect():
    """Return the db connect.

    Inputs: none. Output: `_DbConn` result.
    """
    return _DbConn()


def test_runtime_wrappers_query_helpers_and_user_settings_boundaries(monkeypatch):
    """Verify runtime wrappers query helpers and user settings boundaries.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in runtime wrappers query helpers and user settings boundaries.
    """
    runtime = SimpleNamespace(max_results=25, schema_version=4, sync_stale_seconds=600)
    celery = SimpleNamespace(enabled=True)

    def _runtime_config():
        """Return the runtime configuration.

        Inputs: none. Output: `runtime`.
        """
        return runtime

    def _celery_config():
        """Return the celery config.

        Inputs: none. Output: `celery`.
        """
        return celery

    monkeypatch.setattr(service, "build_enhanced_search_config", _runtime_config)
    monkeypatch.setattr(service, "build_enhanced_search_celery_config", _celery_config)

    assert service.runtime_config() is runtime
    assert service.runtime_celery_config() is celery
    assert service._default_scope_label("group", 7) == "Group 7"
    assert service.user_scope(7, "").label == service.USER_SCOPE_LABEL
    assert service.scope_from_key("user:not-an-int") is None
    assert service._parse_date("2026-04-12", end_of_day=True).hour == 23
    with pytest.raises(ValueError):
        service._parse_date("not-a-date")
    query = service.SearchQuery(
        query_text="lsm",
        acquisition_date_from=datetime(2026, 4, 12, tzinfo=timezone.utc),
        acquisition_date_to=datetime(2026, 4, 13, tzinfo=timezone.utc),
        page=2,
    )
    assert query.to_payload() == {
        "query_text": "lsm",
        "indexed_scope": service.SEARCH_SCOPE_ALL_INDEXED,
        "page": 2,
        "acquisition_date_from": "2026-04-12",
        "acquisition_date_to": "2026-04-13",
    }
    assert query.with_page(0).page == 1
    assert service._query_filters(query) == {
        "acquisition_date_from": datetime(2026, 4, 12, tzinfo=timezone.utc),
        "acquisition_date_to": datetime(2026, 4, 13, tzinfo=timezone.utc),
    }
    assert service._empty_search_payload(page=2, page_size=9) == {
        "results": [],
        "page": 2,
        "page_size": 9,
        "total_count": 0,
        "has_previous": False,
        "has_next": False,
    }
    assert tuple(option["value"] for option in service.search_scope_options()) == (
        service.SEARCH_SCOPE_OMERO_BUILTIN,
        service.SEARCH_SCOPE_ACQUISITION_METADATA,
        service.SEARCH_SCOPE_ALL_INDEXED,
    )
    assert service.default_user_settings() == {
        "acquisition_metadata_enabled": False,
        "collapsed_sections": [],
    }
    assert (
        service.acquisition_index_status_message(True)
        == "Universal metadata indexing is enabled for your user account. "
        "All images you own will be indexed automatically in the background."
    )
    assert (
        service.acquisition_index_status_message(False)
        == "Universal metadata indexing is disabled for your user account."
    )
    assert (
        service.acquisition_index_disabled_detail_message()
        == "Universal metadata indexing is disabled."
    )
    assert (
        service._normalized_sync_detail_message(
            "Universal metadata indexing is disabled for your user account. "
            "No indexed image metadata is stored for your user account."
        )
        == "Universal metadata indexing is disabled."
    )
    assert (
        service.user_settings_load_error_message()
        == "Could not retrieve user setting. Database is not accessible."
    )
    assert (
        service.user_settings_save_error_message()
        == "Could not save user setting. Database is not accessible."
    )
    assert service._coerce_bool("yes") is True
    assert service._coerce_bool("off") is False
    assert service._coerce_bool(3) is True
    assert service._normalized_user_settings(
        {"acquisition_metadata_enabled": "yes"}
    ) == {"acquisition_metadata_enabled": True, "collapsed_sections": []}
    assert service._normalized_user_settings(
        {
            "acquisition_metadata_enabled": True,
            "collapsed_sections": [
                "saved-queries",
                "unknown-section",
                "metadata-index",
            ],
        }
    ) == {
        "acquisition_metadata_enabled": True,
        "collapsed_sections": ["metadata-index", "saved-queries"],
    }
    assert service.user_settings("") == {
        "acquisition_metadata_enabled": False,
        "collapsed_sections": [],
    }

    monkeypatch.setattr(service, "db_connect", _db_connect)

    def _load_user_settings_row(conn, username, defaults=None):
        """Load the user settings row.

        Inputs: `conn` OMERO gateway connection, `username` username, `defaults`.
        Output: `dict`.
        """
        assert isinstance(conn, _DbConn)
        assert username == "alice"
        assert defaults == service.default_user_settings()
        return {"acquisition_metadata_enabled": "true"}

    monkeypatch.setattr(service, "load_user_settings_row", _load_user_settings_row)
    assert service.user_settings("alice") == {
        "acquisition_metadata_enabled": True,
        "collapsed_sections": [],
    }


def test_scope_state_sync_state_lookup_and_current_user_resolution(monkeypatch):
    """Verify scope state sync state lookup and current user resolution.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in scope state sync state lookup and current user resolution.
    """
    recorded = {}
    monkeypatch.setattr(service, "db_connect", _db_connect)
    monkeypatch.setattr(
        service,
        "ensure_sync_state_rows",
        lambda conn, scopes, schema_version: recorded.update(
            {"scopes": scopes, "schema_version": schema_version}
        ),
    )
    monkeypatch.setattr(
        service,
        "list_sync_states",
        lambda conn: [{"scope_type": "user", "scope_id": 7, "status": "running"}],
    )

    def _runtime_config():
        """Return the runtime configuration.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(schema_version=3)

    monkeypatch.setattr(service, "runtime_config", _runtime_config)
    scope = service.user_scope(7, "alice")

    ensured = service.ensure_scope_state((scope,))
    merged = service.current_sync_states((scope,))

    assert ensured == [{"scope_type": "user", "scope_id": 7, "status": "running"}]
    assert recorded == {
        "scopes": [scope.to_dict()],
        "schema_version": 3,
    }
    assert merged == [
        {
            "scope_type": "user",
            "scope_id": 7,
            "scope_key": "user:7",
            "scope_label": "Your universal metadata index",
            "status": "running",
            "requested_by": "",
            "indexed_image_count": 0,
            "current_message": "",
            "last_error": "",
            "last_started_at": None,
            "last_finished_at": None,
            "last_successful_at": None,
            "updated_at": None,
        }
    ]
    assert service.ensure_scope_state(()) == []

    class _WrappedId:
        """Test double for wrapped identifier behavior in this module."""

        @staticmethod
        def getValue():
            """Return `_WrappedId`'s fake OMERO value.

            Inputs: none. Output: 21.
            """
            return 21

    class _User:
        """Test double for user behavior in this module."""

        @staticmethod
        def getId():
            """Return `_User`'s fake OMERO identifier.

            Inputs: none. Output: `_WrappedId` result.
            """
            return _WrappedId()

    assert service._current_user_id(SimpleNamespace(getUser=_User)) == 21
    assert service._current_user_id(SimpleNamespace(getUser=lambda: None)) is None
    assert (
        service._current_user_id(
            SimpleNamespace(getUser=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        )
        is None
    )
    assert service.current_user_scope(object(), "") is None
    monkeypatch.setattr(service, "_current_user_id", lambda conn: 21)
    assert service.current_user_scope(object(), "alice") == service.EnhancedSearchScope(
        service.USER_SCOPE_TYPE,
        21,
        service.USER_SCOPE_LABEL,
    )
    monkeypatch.setattr(service, "current_user_scope", lambda conn, username: None)
    assert service.sync_states_for_user(object(), "alice") == []


def test_parse_search_query_sync_state_and_disabled_scope_guard_paths(monkeypatch):
    """Verify parse search query sync state and disabled scope guard paths.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in parse search query sync state and disabled scope guard paths.
    """
    assert service._parse_date(None) is None
    assert service._parse_date("   ") is None
    converted = service._parse_date("2026-04-12T10:15:00+02:00")
    assert converted.tzinfo == timezone.utc

    query, errors = service.parse_search_query(
        {
            "page": "-5",
            "acquisition_date_from": "bad",
            "acquisition_date_to": "still-bad",
        }
    )

    assert query.page == 1
    assert "Invalid acquisition start date." in errors
    assert "Invalid acquisition end date." in errors
    assert service._sync_state_needs_refresh(None) is True
    assert (
        service._sync_state_needs_refresh({"status": "running", "updated_at": None})
        is True
    )
    assert service.ensure_user_index_sync(object(), "alice")[0] == []
    monkeypatch.setattr(
        service,
        "current_user_scope",
        lambda conn, username: service.EnhancedSearchScope(
            "user", 7, service.USER_SCOPE_LABEL
        ),
    )
    monkeypatch.setattr(
        service,
        "current_sync_states",
        lambda scopes: [{"scope_key": "user:7", "status": "idle"}],
    )
    assert service.ensure_user_index_sync(
        object(),
        "alice",
        settings_payload={"acquisition_metadata_enabled": False},
    ) == ([{"scope_key": "user:7", "status": "idle"}], False, "")
    monkeypatch.setattr(
        service,
        "current_sync_states",
        lambda scopes: [{"scope_key": "user:7", "status": "idle"}],
    )
    assert service.sync_states_for_user(object(), "alice") == [
        {"scope_key": "user:7", "status": "idle"}
    ]


def test_visible_group_ids_range_math_and_row_merging_boundaries(monkeypatch):
    """Verify visible group IDs range math and row merging boundaries.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in visible group IDs range math and row merging boundaries.
    """
    monkeypatch.setattr(service, "_current_user_id", lambda conn: 9)
    monkeypatch.setattr(service, "get_id", lambda obj: obj)
    conn = SimpleNamespace(
        getAdminService=lambda: SimpleNamespace(
            containedGroups=lambda user_id: [5, "bad", 5, None]
        )
    )
    assert service._visible_group_ids(conn) == [5]
    monkeypatch.setattr(service, "_current_user_id", lambda conn: None)
    assert service._visible_group_ids(conn) == []
    monkeypatch.setattr(service, "_current_user_id", lambda conn: 9)
    assert (
        service._visible_group_ids(
            SimpleNamespace(
                getAdminService=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            )
        )
        == []
    )

    monkeypatch.setattr(service, "rtime", lambda milliseconds: ("rtime", milliseconds))
    search_range = service._omero_search_created_range(
        service.SearchQuery(
            acquisition_date_from=datetime(2026, 4, 12, tzinfo=timezone.utc),
            acquisition_date_to=datetime(2026, 4, 13, tzinfo=timezone.utc),
        )
    )
    assert search_range[0][0] == "rtime"
    assert service._omero_search_created_range(service.SearchQuery()) is None
    assert service._normalized_sort_datetime("bad") is None
    assert service._merge_indexed_sources(
        ["Universal metadata index"],
        ["OMERO index", "Other source"],
    ) == ["OMERO index", "Universal metadata index", "Other source"]

    acquisition_rows = [
        {
            "image_id": 3,
            "image_name": "",
            "dataset_name": "",
            "acquisition_date": datetime(2026, 4, 12, tzinfo=timezone.utc),
        }
    ]
    omero_rows = [
        {
            "image_id": 3,
            "image_name": "img-3",
            "dataset_name": "Dataset A",
            "indexed_sources": ["OMERO index"],
            "acquisition_date": datetime(2026, 4, 12, tzinfo=timezone.utc),
        },
        {
            "image_id": 1,
            "image_name": "img-1",
            "dataset_name": "",
            "indexed_sources": ["OMERO index"],
            "acquisition_date": None,
        },
    ]

    merged = service._merge_result_rows(acquisition_rows, omero_rows)

    assert [row["image_id"] for row in merged] == [3, 1]
    assert merged[0]["indexed_sources"] == [
        "OMERO index",
        "Universal metadata index",
    ]
    assert merged[0]["image_name"] == "img-3"
    assert merged[0]["dataset_name"] == "Dataset A"


def test_builtin_search_helper_paths_and_result_row_conversion(monkeypatch):
    """Verify builtin search helper paths and result row conversion result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in builtin search helper paths and result row conversion.
    Raises: RuntimeError when validation or the called operation fails.
    """
    monkeypatch.setattr(
        service,
        "_document_for_image",
        lambda image, schema_version: (
            {"image_id": 17, "image_name": "img-17"},
            [],
            [],
        ),
    )

    def _runtime_config():
        """Return the runtime configuration.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(schema_version=5, max_results=3)

    monkeypatch.setattr(service, "runtime_config", _runtime_config)
    assert service._result_row_from_image(object()) == {
        "image_id": 17,
        "image_name": "img-17",
    }

    class _BrokenDatasetHit:
        """Test double for broken dataset hit behavior in this module."""

        OMERO_CLASS = "Dataset"

        @staticmethod
        def listChildren():
            """Return `_BrokenDatasetHit`'s fake child listing.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("boom")

    class _UnknownHit:
        """Test double for unknown hit behavior in this module."""

        OMERO_CLASS = "Plate"

    assert service._images_from_builtin_search_hit(_BrokenDatasetHit()) == []
    assert service._images_from_builtin_search_hit(_UnknownHit()) == []

    assert (
        service._search_omero_builtin_rows(
            object(),
            service.SearchQuery(query_text=""),
        )
        == []
    )
    monkeypatch.setattr(service, "build_omero_fulltext_query", lambda query_text: "")
    assert (
        service._search_omero_builtin_rows(
            object(),
            service.SearchQuery(query_text="lsm"),
        )
        == []
    )

    search_calls = []
    fake_image = SimpleNamespace(_id=17)
    monkeypatch.setattr(
        service, "build_omero_fulltext_query", lambda query_text: "lsm:*"
    )
    monkeypatch.setattr(
        service,
        "_result_row_from_image",
        lambda image: {"image_id": 17, "image_name": "img-17"},
    )
    monkeypatch.setattr(
        service, "_images_from_builtin_search_hit", lambda hit: [fake_image]
    )
    monkeypatch.setattr(service, "get_id", lambda obj: getattr(obj, "_id", obj))

    class _SearchConn:
        """Test double for search conn behavior in this module."""

        def __init__(self):
            """Create `_SearchConn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.calls = 0

        def searchObjects(self, object_types, fulltext_query, **kwargs):
            """Return the search Objects for `_SearchConn`.

            Inputs: `object_types`, `fulltext_query`, `**kwargs` keyword arguments.
            Output: `list`. Raises: RuntimeError when validation or external operations
            fail.
            """
            search_calls.append(kwargs["searchGroup"])
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("all-groups unavailable")
            if self.calls == 2:
                return [SimpleNamespace()]
            return []

    rows = service._search_omero_builtin_rows(
        _SearchConn(),
        service.SearchQuery(query_text="lsm"),
    )

    assert rows == [
        {"image_id": 17, "image_name": "img-17", "indexed_sources": ["OMERO index"]}
    ]
    assert search_calls[:2] == ["-1", None]
    assert service._accessible_images_by_id(object(), []) == {}

    retry_calls = []

    class _AlwaysFailSearchConn:
        """Test double for always fail search conn behavior in this module."""

        def __init__(self):
            """Create `_AlwaysFailSearchConn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.calls = 0

        @staticmethod
        def searchObjects(object_types, fulltext_query, **kwargs):
            """Record the search objects call on `_AlwaysFailSearchConn` for later assertions.

            Inputs: `object_types`, `fulltext_query`, `**kwargs` keyword arguments.
            Output: None. Raises: RuntimeError when validation or external operations
            fail.
            """
            retry_calls.append(kwargs["searchGroup"])
            raise RuntimeError("still failing")

    assert (
        service._search_omero_builtin_rows(
            _AlwaysFailSearchConn(),
            service.SearchQuery(query_text="lsm"),
        )
        == []
    )
    assert retry_calls == ["-1", None]

    paged_calls = []
    dense_hits = []
    for index in range(100):
        if index == 0:
            dense_hits.append(SimpleNamespace(images=[SimpleNamespace(_id=None)]))
        elif index == 1:
            dense_hits.append(SimpleNamespace(images=[SimpleNamespace(_id="bad")]))
        elif index == 2:
            dense_hits.append(SimpleNamespace(images=[SimpleNamespace(_id=17)]))
        elif index == 3:
            dense_hits.append(SimpleNamespace(images=[SimpleNamespace(_id=17)]))
        else:
            dense_hits.append(SimpleNamespace(images=[]))

    monkeypatch.setattr(
        service, "_images_from_builtin_search_hit", lambda hit: hit.images
    )

    class _PagedSearchConn:
        """Test double for paged search conn behavior in this module."""

        def __init__(self):
            """Create `_PagedSearchConn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.calls = 0

        def searchObjects(self, object_types, fulltext_query, **kwargs):
            """Return the search Objects for `_PagedSearchConn`.

            Inputs: `object_types`, `fulltext_query`, `**kwargs` keyword arguments.
            Output: `list`.
            """
            paged_calls.append(kwargs["page"])
            self.calls += 1
            if self.calls == 1:
                return dense_hits
            return []

    paged_rows = service._search_omero_builtin_rows(
        _PagedSearchConn(),
        service.SearchQuery(query_text="lsm"),
    )
    assert paged_rows == [
        {"image_id": 17, "image_name": "img-17", "indexed_sources": ["OMERO index"]}
    ]
    assert paged_calls == [0, 1]


def test_image_helpers_owner_context_and_document_conversion(monkeypatch):
    """Verify image helpers owner context and document conversion.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image helpers owner context and document conversion.
    RuntimeError when validation or the called operation fails.
    """

    class _ImageHit:
        """Test double for image hit behavior in this module."""

        OMERO_CLASS = "Image"

    class _DatasetHit:
        """Test double for dataset hit behavior in this module."""

        OMERO_CLASS = "Dataset"

        @staticmethod
        def listChildren():
            """Return `_DatasetHit`'s fake child listing.

            Inputs: none. Output: list.
            """
            return ["image-a"]

    class _ProjectHit:
        """Test double for project hit behavior in this module."""

        OMERO_CLASS = "Project"

        @staticmethod
        def listChildren():
            """Return `_ProjectHit`'s fake child listing.

            Inputs: none. Output: list.
            """
            return [SimpleNamespace(listChildren=lambda: ["image-b"])]

    class _BrokenProjectHit:
        """Test double for broken project hit behavior in this module."""

        OMERO_CLASS = "Project"

        @staticmethod
        def listChildren():
            """Return `_BrokenProjectHit`'s fake child listing.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("boom")

    image_hit = _ImageHit()
    assert service._images_from_builtin_search_hit(image_hit) == [image_hit]
    assert service._images_from_builtin_search_hit(_DatasetHit()) == ["image-a"]
    assert service._images_from_builtin_search_hit(_ProjectHit()) == ["image-b"]
    assert service._images_from_builtin_search_hit(_BrokenProjectHit()) == []

    monkeypatch.setattr(service, "get_id", lambda obj: getattr(obj, "_id", obj))
    monkeypatch.setattr(
        service,
        "get_text",
        lambda value: value.getValue() if hasattr(value, "getValue") else value,
    )
    fallback_images = [SimpleNamespace(_id=17)]
    fallback_conn = SimpleNamespace(
        getObjects=lambda model, ids=None, obj_ids=None: (
            (_ for _ in ()).throw(TypeError("use obj_ids"))
            if ids is not None
            else fallback_images
        )
    )
    assert service._accessible_images_by_id(fallback_conn, [17]) == {
        17: fallback_images[0]
    }
    assert (
        service._accessible_images_by_id(
            SimpleNamespace(
                getObjects=lambda *args, **kwargs: (_ for _ in ()).throw(
                    RuntimeError("boom")
                )
            ),
            [17],
        )
        == {}
    )

    group = SimpleNamespace(
        getName=lambda: "Research",
        getDetails=lambda: SimpleNamespace(
            getPermissions=lambda: SimpleNamespace(isGroupRead=lambda: True)
        ),
    )
    assert service._group_context(group) == ("Research", True)
    assert service._group_context(None) == ("", False)
    broken_group = SimpleNamespace(
        getName=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        getDetails=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert service._group_context(broken_group) == ("", False)

    owner = SimpleNamespace(
        getName=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        getOmeName=lambda: "alice",
        getFirstName=lambda: "Alice",
        _id=9,
    )
    image = SimpleNamespace(getOwner=lambda: owner)
    assert service._owner_name(image) == "alice"
    owner_with_only_id = SimpleNamespace(
        getName=lambda: "",
        getOmeName=lambda: "",
        getFirstName=lambda: "",
        _id=11,
    )
    assert (
        service._owner_name(SimpleNamespace(getOwner=lambda: owner_with_only_id))
        == "11"
    )
    assert service._owner_name(SimpleNamespace(getOwner=lambda: None)) == ""
    assert (
        service._owner_name(
            SimpleNamespace(
                getOwner=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            )
        )
        == ""
    )
    assert (
        service._owner_name(SimpleNamespace(getOwner=lambda: SimpleNamespace(_id=12)))
        == "12"
    )

    image_a = SimpleNamespace(_id=None)
    image_b = SimpleNamespace(_id="bad")
    image_c = SimpleNamespace(_id=3)
    image_dup = SimpleNamespace(_id=7)
    image_dup_again = SimpleNamespace(_id=7)
    original_images_for_scope = service._images_for_scope
    monkeypatch.setattr(
        service,
        "_images_for_scope",
        lambda admin_conn, scope: [
            image_a,
            image_b,
            image_c,
            image_dup,
            image_dup_again,
        ],
    )
    scope = service.EnhancedSearchScope("user", 9, service.USER_SCOPE_LABEL)
    assert [image._id for image in service._scope_image_rows(object(), scope)] == [3, 7]
    monkeypatch.setattr(service, "_images_for_scope", original_images_for_scope)
    assert (
        service._images_for_scope(
            SimpleNamespace(
                getObjects=lambda *args, **kwargs: (_ for _ in ()).throw(
                    RuntimeError("boom")
                )
            ),
            scope,
        )
        == []
    )

    search_document = metadata.SearchDocument(
        acquisition_date=datetime(2026, 4, 12, tzinfo=timezone.utc),
        instrument_manufacturer="Zeiss",
        instrument_model="LSM 980",
        objective_model="Plan-Apochromat",
        objective_magnification=63.0,
        objective_na=1.4,
        detector_model="Airyscan 2",
        detector_binning="2x2",
        detector_gain=1.5,
        pixel_size_x_um=0.108,
        pixel_size_y_um=0.108,
        z_step_um=0.4,
        search_document="Zeiss LSM 980 GFP",
        channel_summary="GFP / Ex 488 nm / Em 525 nm",
        channels=(
            metadata.SearchChannel(
                channel_index=0,
                label="GFP",
                excitation_nm=488.0,
                emission_nm=525.0,
            ),
        ),
        attributes=(
            metadata.SearchAttribute(
                attribute_key="laser_line_nm",
                attribute_text="488 nm",
                attribute_numeric=488.0,
            ),
        ),
    )
    monkeypatch.setattr(
        service,
        "extract_search_document",
        lambda image: (
            search_document,
            {
                "dataset_id": 101,
                "dataset_name": "Dataset A",
                "project_id": 201,
                "project_name": "Project A",
            },
        ),
    )
    monkeypatch.setattr(service, "get_owner_id", lambda image: 9)
    details = SimpleNamespace(getGroup=lambda: SimpleNamespace(_id=5, **group.__dict__))
    image_for_document = SimpleNamespace(
        _id=17,
        getDetails=lambda: details,
        getName=lambda: "img-17",
        getOwner=lambda: owner,
    )
    row, channels, attributes = service._document_for_image(image_for_document, 3)
    assert row["image_id"] == 17
    assert row["group_id"] == 5
    assert row["owner_id"] == 9
    assert row["dataset_id"] == 101
    assert channels == [
        {
            "channel_index": 0,
            "label": "GFP",
            "excitation_nm": 488.0,
            "emission_nm": 525.0,
        }
    ]
    assert attributes == [
        {
            "attribute_key": "laser_line_nm",
            "attribute_text": "488 nm",
            "attribute_numeric": 488.0,
        }
    ]
    broken_image = SimpleNamespace(
        _id=19,
        getDetails=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        getName=lambda: "img-19",
        getOwner=lambda: owner,
    )
    broken_row, _channels, _attributes = service._document_for_image(broken_image, 3)
    assert broken_row["group_id"] == 0


def test_search_skips_inaccessible_images_and_handles_current_name_errors(monkeypatch):
    """Verify search skips inaccessible images and handles current name errors.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in search skips inaccessible images and handles current name errors.
    """

    def _runtime_config():
        """Return the runtime configuration.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(max_results=50)

    monkeypatch.setattr(service, "runtime_config", _runtime_config)
    monkeypatch.setattr(
        service,
        "_merge_result_rows",
        lambda acquisition_rows, omero_rows: [
            {"image_id": 7, "image_name": "stored-7"},
            {"image_id": 8, "image_name": "stored-8"},
        ],
    )
    monkeypatch.setattr(service, "db_connect", _db_connect)
    monkeypatch.setattr(service, "search_index_rows", lambda *args, **kwargs: ([], 0))
    monkeypatch.setattr(service, "_visible_group_ids", lambda conn: [5])
    monkeypatch.setattr(service, "_current_user_id", lambda conn: 9)
    monkeypatch.setattr(service, "_search_omero_builtin_rows", lambda conn, query: [])
    monkeypatch.setattr(
        service,
        "_accessible_images_by_id",
        lambda conn, image_ids: {
            8: SimpleNamespace(
                getName=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            )
        },
    )
    monkeypatch.setattr(
        service, "reverse", lambda name, args=(): f"/{name}/{'/'.join(map(str, args))}"
    )

    payload = service.search(
        object(),
        service.SearchQuery(
            query_text="lsm",
            indexed_scope=service.SEARCH_SCOPE_ALL_INDEXED,
        ),
        acquisition_metadata_enabled=True,
    )

    assert payload["results"] == [
        {
            "image_id": 8,
            "image_name": "stored-8",
            "image_url": "/webindex/?show=image-8",
            "thumbnail_url": "/render_thumbnail/8",
            "dataset_url": "",
            "project_url": "",
        }
    ]


def test_root_connection_covers_missing_password_failed_connect_and_cleanup(
    monkeypatch,
):
    """Check that root connection covers missing password failed connect and cleanup keeps sensitive data out of output.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in root connection covers missing password failed connect and cleanup.
    RuntimeError when validation or the called operation fails.
    """
    monkeypatch.delenv("ROOTPASS", raising=False)
    with (
        pytest.raises(RuntimeError, match="ROOTPASS is missing"),
        service._root_connection(),
    ):
        pass

    monkeypatch.setenv("ROOTPASS", "root-auth-value")
    monkeypatch.setattr(
        service,
        "get_env",
        lambda name, env_file=None: {"OMEROHOST": "host.example", "OMERO_PORT": "4064"}[
            name
        ],
    )
    monkeypatch.setattr(service, "get_bool_env", lambda name, env_file=None: False)

    class _FailingGateway:
        """Test double for failing gateway behavior in this module."""

        def __init__(self, *args, **kwargs):
            """Create `_FailingGateway` with its default state.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def connect():
            """Open the connection for `_FailingGateway`.

            Inputs: none. Output: bool.
            """
            return False

    monkeypatch.setattr(service, "BlitzGateway", _FailingGateway)
    with (
        pytest.raises(RuntimeError, match="Failed to connect as root"),
        service._root_connection(),
    ):
        pass

    closed = []

    class _WorkingGateway:
        """Test double for working gateway behavior in this module."""

        def __init__(self, *args, **kwargs):
            """Create `_WorkingGateway` with its default state.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.SERVICE_OPTS = SimpleNamespace(
                setOmeroGroup=lambda value: (_ for _ in ()).throw(RuntimeError("boom"))
            )

        @staticmethod
        def connect():
            """Open the connection for `_WorkingGateway`.

            Inputs: none. Output: bool.
            """
            return True

        @staticmethod
        def close():
            """Close `_WorkingGateway`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            closed.append(True)
            raise RuntimeError("close boom")

    monkeypatch.setattr(service, "BlitzGateway", _WorkingGateway)
    with service._root_connection() as conn:
        assert conn.connect() is True
    assert closed == [True]


def test_sync_scope_request_dispatch_and_saved_query_wrappers(monkeypatch):
    """Verify sync scope request dispatch and saved query wrappers.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in sync scope request dispatch and saved query wrappers.
    Raises: RuntimeError when validation or the called operation fails.
    """
    scope = service.EnhancedSearchScope("user", 9, service.USER_SCOPE_LABEL)
    original_process_sync_batch = service._process_sync_batch
    original_scope_from_key = service.scope_from_key
    sync_events = []
    db_context = _DbConn()

    def _runtime_config():
        """Return the runtime configuration.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(batch_size=2, schema_version=5)

    monkeypatch.setattr(service, "runtime_config", _runtime_config)

    @contextmanager
    def _root_connection():
        """Return the root connection.

        Inputs: none. Output: iterator of yielded items.
        """
        yield object()

    monkeypatch.setattr(service, "_root_connection", _root_connection)
    monkeypatch.setattr(service, "_scope_image_rows", lambda admin_conn, scope: [])

    def _db_context_connect():
        """DB context connect.

        Inputs: none. Output: `db_context`.
        """
        return db_context

    monkeypatch.setattr(service, "db_connect", _db_context_connect)
    monkeypatch.setattr(
        service,
        "prune_scope_membership",
        lambda conn, scope_type, scope_id, run_token: (
            sync_events.append(("prune_scope", scope_type, scope_id, run_token)) or 2
        ),
    )
    monkeypatch.setattr(
        service,
        "prune_orphan_documents",
        lambda conn: sync_events.append(("prune_orphans",)) or 1,
    )
    monkeypatch.setattr(
        service,
        "mark_sync_complete",
        lambda conn, scope_type, scope_id, **kwargs: sync_events.append(
            ("complete", scope_type, scope_id, kwargs)
        ),
    )
    sync_run_a = "sync-run-a"
    service._SYNC_THREADS[scope.scope_key] = object()
    assert service._sync_scope(scope, sync_run_a) == {
        "status": "idle",
        "indexed_image_count": 0,
    }
    assert sync_events[0] == ("prune_scope", "user", 9, sync_run_a)
    assert scope.scope_key not in service._SYNC_THREADS

    error_calls = []

    class _FailingRootConnection:
        """Test double for failing root connection behavior in this module."""

        def __enter__(self):
            """Enter `_FailingRootConnection`'s context-managed fake resource.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            raise RuntimeError("boom")

        def __exit__(self, exc_type, exc, tb):
            """Exit `_FailingRootConnection`'s context-managed fake resource.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    monkeypatch.setattr(service, "_root_connection", _FailingRootConnection)
    monkeypatch.setattr(
        service,
        "mark_sync_error",
        lambda conn, scope_type, scope_id, **kwargs: error_calls.append(
            (scope_type, scope_id, kwargs)
        ),
    )
    sync_run_b = "sync-run-b"
    service._SYNC_THREADS[scope.scope_key] = object()
    with pytest.raises(RuntimeError, match="boom"):
        service._sync_scope(scope, sync_run_b)
    assert error_calls[0][0:2] == ("user", 9)
    assert scope.scope_key not in service._SYNC_THREADS

    invalid_run_marker = "sync-run-bad"
    with pytest.raises(RuntimeError, match="Selected search scope is not valid."):
        service.run_scope_sync_task("bad-scope", invalid_run_marker)

    processed = []

    @contextmanager
    def _working_root_connection():
        """Return the working root connection.

        Inputs: none. Output: iterator of yielded items.
        """
        yield object()

    monkeypatch.setattr(service, "_root_connection", _working_root_connection)
    monkeypatch.setattr(
        service,
        "_scope_image_rows",
        lambda admin_conn, scope: [
            SimpleNamespace(_id=1),
            SimpleNamespace(_id=2),
            SimpleNamespace(_id=3),
        ],
    )
    monkeypatch.setattr(
        service,
        "_process_sync_batch",
        lambda scope, run_token, images, processed_count, schema_version: (
            processed.append([image._id for image in images])
            or (processed_count + len(images))
        ),
    )
    sync_run_c = "sync-run-c"
    service._SYNC_THREADS[scope.scope_key] = object()
    assert service._sync_scope(scope, sync_run_c) == {
        "status": "idle",
        "indexed_image_count": 3,
    }
    assert processed == [[1, 2], [3]]

    monkeypatch.setattr(
        service,
        "_process_sync_batch",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            service.ScopeSyncCancelledError("cancelled")
        ),
    )
    sync_run_d = "sync-run-d"
    service._SYNC_THREADS[scope.scope_key] = object()
    assert service._sync_scope(scope, sync_run_d) == {
        "status": "idle",
        "indexed_image_count": 0,
        "cancelled": True,
    }
    monkeypatch.setattr(service, "_process_sync_batch", original_process_sync_batch)

    monkeypatch.setattr(
        service,
        "_document_for_image",
        lambda image, schema_version: (
            {"image_id": image._id},
            [{"channel_index": image._id}],
            [{"attribute_key": f"key-{image._id}"}],
        ),
    )
    upserts = []
    monkeypatch.setattr(
        service,
        "sync_run_is_active",
        lambda conn, scope_type, scope_id, run_token: True,
    )
    monkeypatch.setattr(
        service,
        "upsert_search_document",
        lambda conn, **kwargs: upserts.append(kwargs),
    )
    monkeypatch.setattr(
        service,
        "update_sync_progress",
        lambda conn, scope_type, scope_id, **kwargs: upserts.append(
            {"progress": kwargs}
        ),
    )
    sync_run_e = "sync-run-e"
    processed_count = service._process_sync_batch(
        scope,
        sync_run_e,
        [SimpleNamespace(_id=7), SimpleNamespace(_id=8)],
        0,
        5,
    )
    assert processed_count == 2
    assert upserts[-1]["progress"]["last_cursor_image_id"] == 8

    monkeypatch.setattr(service, "scope_from_key", lambda scope_key: scope)
    monkeypatch.setattr(
        service, "_sync_scope", lambda scope_obj, run_token: {"ok": True}
    )
    sync_run_f = "sync-run-f"
    assert service.run_scope_sync_task("user:9", sync_run_f) == {"ok": True}
    monkeypatch.setattr(service, "scope_from_key", original_scope_from_key)

    started = []

    class _FakeThread:
        """Test double for fake thread."""

        def __init__(self, target, args, daemon, name):
            """Create `_FakeThread` with `target`, `args`, `daemon`, and `name`.

            Inputs: `target`, `args`, `daemon`, `name`. Output: None.
            """
            started.append(
                {
                    "target": target,
                    "args": args,
                    "daemon": daemon,
                    "name": name,
                }
            )

        @staticmethod
        def start():
            """Start `_FakeThread`'s fake operation.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            started.append("started")

    monkeypatch.setattr(service.threading, "Thread", _FakeThread)
    thread_run_a = "thread-run-a"
    service._start_threaded_sync(scope, thread_run_a)
    assert started[0]["args"] == ("user:9", thread_run_a)
    assert started[0]["daemon"] is True
    assert started[1] == "started"

    assert service.request_scope_sync("bad-scope", "alice") == (
        False,
        "Selected search scope is not valid.",
    )

    monkeypatch.setattr(service, "db_connect", _db_connect)

    def _runtime_config():
        """Return the runtime configuration.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(schema_version=5, sync_stale_seconds=600)

    monkeypatch.setattr(service, "runtime_config", _runtime_config)
    monkeypatch.setattr(service, "try_start_scope_sync", lambda *args, **kwargs: False)
    assert service.request_scope_sync("user:9", "alice") == (
        False,
        "Indexing is already running for this scope.",
    )
    monkeypatch.setattr(
        service,
        "try_start_scope_sync",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            service.EnhancedSearchStoreError("store unavailable")
        ),
    )
    assert service.request_scope_sync("user:9", "alice") == (
        False,
        "Could not schedule enhanced-search indexing.",
    )

    assert service.saved_queries("") == []
    monkeypatch.setattr(
        service, "list_saved_queries", lambda conn, username: [{"id": 1}]
    )
    assert service.saved_queries("alice") == [{"id": 1}]
    saved = []
    monkeypatch.setattr(
        service,
        "save_saved_query",
        lambda conn, username, query_name, query_payload: saved.append(
            (username, query_name, query_payload)
        ),
    )
    service.save_query("alice", "My query", {"query_text": "lsm"})
    monkeypatch.setattr(
        service,
        "delete_saved_query",
        lambda conn, username, query_id: username == "alice" and query_id == 3,
    )
    assert service.remove_saved_query("alice", 3) is True
    assert saved == [("alice", "My query", {"query_text": "lsm"})]
    monkeypatch.setattr(
        service,
        "get_bool_env",
        lambda name, env_file=None: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert service._admin_secure_flag() is True
