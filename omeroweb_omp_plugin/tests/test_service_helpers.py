from __future__ import annotations

import json
import re
from types import SimpleNamespace

from omeroweb_omp_plugin.constants import HASH_KEY, HASH_PREFIX, MAP_NS
from omeroweb_omp_plugin.services import core, filename_utils, http_utils, rate_limit
from omeroweb_omp_plugin.services.omero import (
    annotation_service,
    image_service,
    metadata_service,
)


class _Value:
    """Test double for value behavior in this module."""

    def __init__(self, value):
        """Create `_Value` with `value`.

        Inputs: `value`. Output: None.
        """
        self._raw_value = value

    def getValue(self):
        """Return `_Value`'s fake OMERO value.

        Inputs: none. Output: `self._raw_value`.
        """
        return self._raw_value


class _ErrorBody:
    """Test double for error body behavior in this module."""

    def __init__(self, payload):
        """Create `_ErrorBody` with `payload`.

        Inputs: `payload`. Output: None.
        """
        self._payload = payload

    def read(self):
        """Read data from the resource.

        Inputs: none. Output: `self._payload`.
        """
        return self._payload


def test_extract_error_details_prefers_nested_messages_and_plaintext():
    """Confirm extract error details prefers nested messages and plaintext exposes the expected failure.

    Inputs: OMP service fakes. Output: fails on regressions when extract error details prefers nested messages and plaintext stops reporting the expected error.
    """
    nested = _ErrorBody(
        json.dumps({"error": {"message": "staging failed"}}).encode("utf-8")
    )
    plain = _ErrorBody(b"permission denied\n")
    empty = _ErrorBody(b"")

    assert http_utils.extract_error_details(nested) == "staging failed"
    assert http_utils.extract_error_details(plain) == "permission denied"
    assert http_utils.extract_error_details(empty) is None
    assert http_utils.extract_error_details(None) is None


def test_core_reexports_follow_live_annotation_service_bindings(monkeypatch):
    """Verify core reexports follow live annotation service bindings.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in core reexports follow live annotation service bindings.
    """
    monkeypatch.setattr(annotation_service, "get_hash_secret", lambda: "secret")
    monkeypatch.setattr(
        annotation_service,
        "compute_plugin_hash",
        lambda mapping: f"hash:{mapping['name']}",
    )

    assert core._get_hash_secret() == "secret"
    assert core.compute_plugin_hash({"name": "demo"}) == "hash:demo"


def test_filename_helpers_detect_label_value_pairs_and_protect_scientific_hyphens():
    """Verify filename helpers detect label value pairs and protect scientific hyphens.

    Inputs: OMP service fakes. Output: fails on regressions in filename helpers detect label value pairs and protect scientific hyphens.
    """
    filenames = [
        "experiment-ch-01-pos-02.tif",
        "experiment-ch-02-pos-03.tif",
        "experiment-ch-03-pos-04.tif",
    ]

    has_pairs, labels = filename_utils.detect_label_value_pairs(filenames)
    regex = filename_utils.regex_for_separators("-", filenames=filenames)

    assert (
        filename_utils.extract_base_name("prefix [sample-name].ome.tif")
        == "sample-name"
    )
    assert has_pairs is True
    assert labels == {"ch", "pos"}
    assert "ch" in filename_utils.build_hyphen_protection_pattern(labels)
    assert re.split(regex, "experiment-ch-01-pos-02") == ["experiment", "01", "02"]
    assert re.split(filename_utils.regex_for_separators("-"), "DMSO-d6-control") == [
        "DMSO-d6",
        "control",
    ]
    assert "-" in filename_utils.suggest_separator_regex(filenames)


def test_in_memory_cache_expires_entries_and_supports_delete_clear(monkeypatch):
    """Check in memory cache expires entries and supports delete clear cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in in memory cache expires entries and supports delete clear.
    """
    current_time = [100.0]
    cache = rate_limit.InMemoryCache()
    monkeypatch.setattr(rate_limit.time, "time", lambda: current_time[0])

    cache.set("alpha", "value", timeout=5)
    assert cache.get("alpha") == "value"

    current_time[0] = 106.0
    assert cache.get("alpha") is None

    cache.set("beta", 2, timeout=10)
    deleted = cache.delete("beta")
    assert deleted is True
    assert cache.get("beta") is None

    cache.set("gamma", 3, timeout=10)
    cache.clear()
    assert cache.get("gamma") is None


def test_rate_limit_uses_shared_counter_and_reports_block_status(monkeypatch):
    """Verify rate limit uses shared counter and reports block status.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in rate limit uses shared counter and reports block status.
    """
    current_time = [1000.0]
    state = {}

    def fake_get(key):
        """Simulate get so the surrounding test controls that dependency.

        Inputs: `key` lookup key. Output: `get` result.
        """
        return state.get(key)

    def fake_set(key, value, timeout):
        """Simulate set so the surrounding test controls that dependency.

        Inputs: `key` lookup key, `value` input value, `timeout` timeout seconds.
        Output: `bool`.
        """
        state[key] = value
        state["timeout"] = timeout
        return True

    def fake_delete(key):
        """Simulate delete so the surrounding test controls that dependency.

        Inputs: `key` lookup key. Output: `bool`.
        """
        state.pop(key, None)
        return True

    request = SimpleNamespace(
        META={"REMOTE_ADDR": "127.0.0.1"},
        user=SimpleNamespace(is_authenticated=False),
    )
    conn = SimpleNamespace(
        getUser=lambda: SimpleNamespace(getName=lambda: "omero-user"),
    )

    monkeypatch.setattr(rate_limit, "_cache_get", fake_get)
    monkeypatch.setattr(rate_limit, "_cache_set", fake_set)
    monkeypatch.setattr(rate_limit, "_cache_delete", fake_delete)
    monkeypatch.setattr(rate_limit.time, "time", lambda: current_time[0])

    assert (
        rate_limit._get_user_key(request, conn=conn)
        == "omp_rate_limit:omero:omero-user"
    )
    assert "minute" in rate_limit.build_rate_limit_message(61)
    assert "second" in rate_limit.build_rate_limit_message(12)

    for _ in range(rate_limit.MAJOR_ACTION_LIMIT):
        allowed, remaining = rate_limit.check_major_action_rate_limit(
            request, conn=conn
        )
        assert allowed is True
        assert remaining is None

    blocked, remaining = rate_limit.check_major_action_rate_limit(request, conn=conn)
    assert blocked is False
    assert remaining == rate_limit.MAJOR_ACTION_BLOCK_SECONDS
    assert state["timeout"] == rate_limit._cache_timeout_seconds()

    status = rate_limit.get_rate_limit_status(request, conn=conn)
    assert status["is_blocked"] is True
    assert status["actions_count"] == rate_limit.MAJOR_ACTION_LIMIT + 1

    assert rate_limit.reset_rate_limit(request, conn=conn) is True
    assert state == {"timeout": rate_limit._cache_timeout_seconds()}


def test_rate_limit_handles_django_ip_fallbacks_and_cache_failures(monkeypatch):
    """Verify rate limit handles django ip fallbacks and cache failures.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in rate limit handles django ip fallbacks and cache failures.
    when validation or the called operation fails.
    """
    request = SimpleNamespace(
        META={
            "HTTP_X_FORWARDED_FOR": "10.0.0.5, 10.0.0.6",
            "HTTP_X_REAL_IP": "10.0.0.7",
        },
        user=SimpleNamespace(is_authenticated=True, username="django-user", id=12),
    )
    failing_conn = SimpleNamespace(
        getUser=lambda: (_ for _ in ()).throw(RuntimeError("omero unavailable"))
    )

    assert (
        rate_limit._get_user_key(request, conn=failing_conn)
        == "omp_rate_limit:django:django-user"
    )

    request.user = SimpleNamespace(is_authenticated=False)
    assert rate_limit._get_user_key(request, conn=None) == "omp_rate_limit:ip:10.0.0.5"

    monkeypatch.setattr(rate_limit.time, "time", lambda: 100.0)
    monkeypatch.setattr(
        rate_limit,
        "_cache_get",
        lambda key: {"actions": "bad", "blocked_until": "bad"},
    )

    status = rate_limit.get_rate_limit_status(request)

    assert status["actions_count"] == 0
    assert status["remaining_actions"] == rate_limit.MAJOR_ACTION_LIMIT
    assert status["is_blocked"] is False

    def failing_cache(*_args, **_kwargs):
        """Record the failing cache call on the test double for later assertions.

        Inputs: `*_args`, `**_kwargs`. Output: None. Raises: RuntimeError when validation or the called operation fails.
        """
        raise RuntimeError("cache boom")

    monkeypatch.setattr(rate_limit, "_cache_get", failing_cache)

    allowed, remaining = rate_limit.check_major_action_rate_limit(request)

    assert allowed is False
    assert remaining == rate_limit.MAJOR_ACTION_BLOCK_SECONDS
    rate_status = rate_limit.get_rate_limit_status(request)
    assert rate_status["error"] == rate_limit.errors.unexpected_error()
    assert "cache boom" not in rate_status["error"]

    monkeypatch.setattr(
        rate_limit,
        "_cache_delete",
        lambda key: (_ for _ in ()).throw(RuntimeError("delete boom")),
    )
    assert rate_limit.reset_rate_limit(request) is False


class _FakeParameters:
    """Test double for fake parameters."""

    def __init__(self):
        """Create `_FakeParameters` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self.values = {}

    def add(self, key, value):
        """Add the add for `_FakeParameters`.

        Inputs: `key` lookup key, `value` input value. Output: None.
        """
        self.values[key] = value


class _NamedValue:
    """Test double for named value behavior in this module."""

    def __init__(self, name, value):
        """Create `_NamedValue` with `name` and `value`.

        Inputs: `name`, `value`. Output: None.
        """
        self.name = _Value(name)
        self.value = _Value(value)


class _MapAnnotation:
    """Test double for map annotation behavior in this module."""

    def __init__(self, ann_id, mapping, *, ns=MAP_NS):
        """Create `_MapAnnotation` with `ann_id` and `mapping`.

        Inputs: `ann_id`, `mapping`, `ns`. Output: None.
        """
        self.id = ann_id
        self._mapping = dict(mapping)
        self._ns = ns
        self._obj = self

    def getId(self):
        """Return `_MapAnnotation`'s fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self.id)

    def getMapValue(self):
        """Return the fake map payload used by this test double.

        Inputs: none. Output: get map value result.
        """
        return [_NamedValue(key, value) for key, value in self._mapping.items()]

    def getNs(self):
        """Return the ns for `_MapAnnotation`.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self._ns)


def _plugin_mapping(secret=None, **extra):
    """Return the plugin mapping.

    Inputs: `secret`, `**extra`. Output: `mapping`.
    """
    original = annotation_service.get_hash_secret
    try:
        annotation_service.get_hash_secret = lambda: secret
        mapping = dict(extra)
        mapping[HASH_KEY] = annotation_service.compute_plugin_hash(mapping)
        return mapping
    finally:
        annotation_service.get_hash_secret = original


def test_annotation_hash_helpers_detect_preloaded_and_database_fallback(monkeypatch):
    """Verify annotation hash helpers detect preloaded and database fallback.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in annotation hash helpers detect preloaded and database fallback.
    """
    monkeypatch.setattr(annotation_service, "ParametersI", _FakeParameters)
    monkeypatch.setattr(annotation_service, "rlong", _Value)
    monkeypatch.setattr(annotation_service, "get_hash_secret", lambda: "shared-secret")

    mapping = _plugin_mapping("shared-secret", alpha="1", beta=None)
    ann = _MapAnnotation(7, mapping)

    assert (
        HASH_KEY
        not in json.loads(annotation_service.canonicalize_mapping(mapping))["data"]
    )
    assert annotation_service.compute_plugin_hash(mapping).startswith(HASH_PREFIX)
    assert annotation_service.is_plugin_annotation(ann) is True

    fallback_ann = SimpleNamespace(
        getMapValue=lambda: [],
        getId=lambda: _Value(9),
    )
    fallback_qs = SimpleNamespace(
        projection=lambda hql, params, service_opts=None: [
            (_Value("alpha"), _Value("1")),
            (
                _Value(HASH_KEY),
                _Value(_plugin_mapping("shared-secret", alpha="1")[HASH_KEY]),
            ),
        ]
    )
    assert annotation_service.is_plugin_annotation(fallback_ann, qs=fallback_qs) is True


def test_annotation_queries_and_plugin_delete_mode(monkeypatch):
    """Check annotation queries and plugin delete mode cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in annotation queries and plugin delete mode.
    AssertionError when validation or the called operation fails.
    """
    monkeypatch.setattr(annotation_service, "ParametersI", _FakeParameters)
    monkeypatch.setattr(annotation_service, "rlong", _Value)
    monkeypatch.setattr(annotation_service, "rstring", _Value)
    monkeypatch.setattr(annotation_service, "get_hash_secret", lambda: "shared-secret")
    monkeypatch.setattr(
        annotation_service, "get_id", lambda obj: getattr(obj, "id", None)
    )

    plugin_mapping = _plugin_mapping("shared-secret", alpha="1")
    legacy_mapping = {"legacy": "yes"}
    bad_mapping = {HASH_KEY: f"{HASH_PREFIX}bad"}
    deleted_annotation_ids = set()
    deleted_link_ids = set()

    class _FakeQueryService:
        """Test double for fake query service."""

        @staticmethod
        def projection(hql, params, service_opts=None):
            """Return the projection for `_FakeQueryService`.

            Inputs: `hql`, `params` SQL parameters, `service_opts`. Output: `list`.
            Raises: AssertionError when validation or the called operation fails.
            """
            if "where l.parent.id = :iid and a.ns = :ns" in hql:
                return [[_Value(1)], [_Value(2)], [_Value(3)]]
            if "join a.mapValue mv" in hql and "where a.id = :aid" in hql:
                aid = params.values["aid"].getValue()
                rows_by_id = {
                    1: [
                        (_Value("alpha"), _Value("1")),
                        (_Value(HASH_KEY), _Value(plugin_mapping[HASH_KEY])),
                    ],
                    2: [(_Value("legacy"), _Value("yes"))],
                    3: [(_Value(HASH_KEY), _Value(bad_mapping[HASH_KEY]))],
                }
                return rows_by_id.get(aid, [])
            if "where l.child.id = :aid" in hql:
                aid = params.values["aid"].getValue()
                link_id = aid + 1000
                if aid in deleted_annotation_ids or link_id in deleted_link_ids:
                    return []
                return [[_Value(link_id)]]
            if "join a.mapValue mv" in hql and "where l.parent.id = :iid" in hql:
                return [[_Value(1)], [_Value(4)]]
            if "select a.id from MapAnnotation a where a.id = :aid" in hql:
                aid = params.values["aid"].getValue()
                return [] if aid in deleted_annotation_ids else [[_Value(aid)]]
            raise AssertionError(f"Unexpected HQL: {hql}")

    class _FakeUpdateService:
        """Test double for fake update service."""

        def __init__(self):
            """Create `_FakeUpdateService` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.deleted = []

        def deleteObject(self, obj):
            """Delete the object for `_FakeUpdateService`.

            Inputs: `obj`. Output: None.
            """
            self.deleted.append(obj)
            if isinstance(obj, tuple) and len(obj) == 2 and obj[0] == "link":
                deleted_link_ids.add(obj[1])

    ann1 = _MapAnnotation(1, plugin_mapping)
    ann2 = _MapAnnotation(2, legacy_mapping, ns="other-ns")
    ann3 = _MapAnnotation(3, bad_mapping)
    annotations = {1: ann1, 2: ann2, 3: ann3}
    update = _FakeUpdateService()
    conn = SimpleNamespace(
        SERVICE_OPTS=object(),
        getQueryService=_FakeQueryService,
        getObject=lambda kind, obj_id: (
            SimpleNamespace(_obj=("link", obj_id))
            if kind == "ImageAnnotationLink"
            else annotations.get(obj_id)
        ),
        deleteObjects=lambda kind, object_ids, wait=True: [
            deleted_annotation_ids.add(object_id) for object_id in object_ids
        ],
    )
    image = SimpleNamespace(
        id=55,
        listAnnotations=lambda: [ann1, ann2, ann3],
    )

    assert annotation_service.find_plugin_annotation_ids(conn, 55) == [1]
    assert annotation_service.find_plugin_annotation_ids(
        conn, 55, allow_legacy=True
    ) == [1, 2]
    assert annotation_service.find_annotation_link_ids(conn, 1) == [1001]
    assert annotation_service.find_map_annotation_ids(conn, 55) == [1, 4]

    deleted_sets, deleted_pairs, attempted = (
        annotation_service.delete_existing_annotations(
            conn,
            update,
            image,
            var_names=["alpha"],
            mode="plugin",
        )
    )

    assert (deleted_sets, deleted_pairs, attempted) == (1, 2, 1)
    assert update.deleted == [("link", 1001)]
    assert 1 in deleted_annotation_ids
    assert 1002 not in deleted_link_ids


def test_annotation_helpers_cover_tuple_pairs_and_link_stub_cleanup(monkeypatch):
    """Check annotation helpers cover tuple pairs and link stub cleanup cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in annotation helpers cover tuple pairs and link stub cleanup.
    Raises: AssertionError when validation or the called operation fails.
    """
    monkeypatch.setattr(annotation_service, "ParametersI", _FakeParameters)
    monkeypatch.setattr(annotation_service, "rlong", _Value)
    monkeypatch.setattr(annotation_service, "get_hash_secret", lambda: "shared-secret")

    tuple_mapping = _plugin_mapping("shared-secret", alpha="1")
    tuple_ann = SimpleNamespace(
        getMapValue=lambda: [
            ("alpha", "1"),
            (HASH_KEY, tuple_mapping[HASH_KEY]),
        ],
        getId=lambda: _Value(5),
    )

    assert annotation_service.is_plugin_annotation(tuple_ann) is True
    assert annotation_service.delete_existing_annotations(
        SimpleNamespace(getQueryService=lambda: None),
        SimpleNamespace(deleteObject=lambda obj: None),
        SimpleNamespace(
            listAnnotations=lambda: (_ for _ in ()).throw(RuntimeError("missing"))
        ),
        var_names=[],
        mode="all",
    ) == (0, 0, 0)

    deleted_annotation_ids = set()
    deleted_link_ids = set()

    class _QueryService:
        """Test double for query service behavior in this module."""

        @staticmethod
        def projection(hql, params, service_opts=None):
            """Return the projection for `_QueryService`.

            Inputs: `hql`, `params` SQL parameters, `service_opts`. Output: projection
            Raises: AssertionError when validation or the called operation fails.
            """
            if "where l.child.id = :aid" in hql:
                aid = params.values["aid"].getValue()
                if aid in deleted_annotation_ids or 401 in deleted_link_ids:
                    return []
                return [[_Value(401)]]
            if "select a.id from MapAnnotation a where a.id = :aid" in hql:
                aid = params.values["aid"].getValue()
                return [] if aid in deleted_annotation_ids else [[_Value(aid)]]
            if "where l.parent.id = :iid" in hql:
                return [[_Value(7)]]
            raise AssertionError(f"Unexpected HQL: {hql}")

    class _UpdateService:
        """Test double for update service behavior in this module."""

        def __init__(self):
            """Create `_UpdateService` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.deleted = []

        def deleteObject(self, obj):
            """Delete the object for `_UpdateService`.

            Inputs: `obj`. Output: None.
            """
            self.deleted.append(obj)

    ann = _MapAnnotation(7, {"alpha": "1"})
    update = _UpdateService()
    conn = SimpleNamespace(
        SERVICE_OPTS=object(),
        getQueryService=_QueryService,
        getObject=lambda kind, obj_id: (
            None
            if kind == "ImageAnnotationLink"
            else (None if obj_id in deleted_annotation_ids else ann)
        ),
        deleteObjects=lambda kind, object_ids, wait=True: [
            (
                deleted_link_ids.add(object_id)
                if kind == "ImageAnnotationLink"
                else deleted_annotation_ids.add(object_id)
            )
            for object_id in object_ids
        ],
    )
    monkeypatch.setattr(
        annotation_service,
        "find_map_annotation_ids",
        lambda current_conn, image_id: [7],
    )
    monkeypatch.setattr(
        annotation_service, "get_id", lambda obj: getattr(obj, "id", None)
    )

    deleted_sets, deleted_pairs, attempted = (
        annotation_service.delete_existing_annotations(
            conn,
            update,
            SimpleNamespace(id=33, listAnnotations=lambda: [ann]),
            var_names=[],
            mode="all",
        )
    )

    assert (deleted_sets, deleted_pairs, attempted) == (1, 1, 1)
    assert update.deleted == []
    assert deleted_annotation_ids == {7}
    assert deleted_link_ids == {401}


def test_annotation_query_helpers_cover_invalid_inputs_and_legacy_controls(monkeypatch):
    """Verify annotation query helpers cover invalid inputs and legacy controls.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in annotation query helpers cover invalid inputs and legacy controls.
    AssertionError, RuntimeError when validation or the called operation fails.
    """
    monkeypatch.setattr(annotation_service, "ParametersI", _FakeParameters)
    monkeypatch.setattr(annotation_service, "rlong", _Value)
    monkeypatch.setattr(annotation_service, "rstring", _Value)
    monkeypatch.setattr(annotation_service, "get_hash_secret", lambda: "")

    plugin_mapping = _plugin_mapping("", alpha="1")
    broken_ann = SimpleNamespace(
        getMapValue=lambda: [
            SimpleNamespace(
                getName=lambda: (_ for _ in ()).throw(RuntimeError("name failed")),
                getValue=lambda: "ignored",
            ),
            ("alpha", "1"),
            (HASH_KEY, plugin_mapping[HASH_KEY]),
        ],
        getId=lambda: _Value(9),
    )
    invalid_marker_ann = _MapAnnotation(10, {"alpha": "1", HASH_KEY: "not-plugin"})

    class _QueryService:
        """Test double for query service behavior in this module."""

        @staticmethod
        def projection(hql, params, service_opts=None):
            """Return the projection for `_QueryService`.

            Inputs: `hql`, `params` SQL parameters, `service_opts`. Output: `list`.
            Raises: AssertionError, RuntimeError when validation or external operations
            fail.
            """
            if "where l.parent.id = :iid and a.ns = :ns" in hql:
                return [[_Value(4)], [_Value(5)]]
            if "join a.mapValue mv" in hql and "where a.id = :aid" in hql:
                aid = params.values["aid"].getValue()
                if aid == 4:
                    return [(_Value("legacy"), _Value("1"))]
                if aid == 5:
                    raise RuntimeError("lookup failed")
            raise AssertionError(f"Unexpected HQL: {hql}")

    conn = SimpleNamespace(
        SERVICE_OPTS=object(),
        getQueryService=_QueryService,
    )

    assert annotation_service.is_plugin_annotation(broken_ann) is True
    assert annotation_service.is_plugin_annotation(invalid_marker_ann) is False
    assert annotation_service.find_plugin_annotation_ids(conn, "not-an-id") == []
    assert annotation_service.find_annotation_link_ids(conn, "bad-id") == []
    assert annotation_service.find_map_annotation_ids(conn, "bad-id") == []
    assert (
        annotation_service.find_plugin_annotation_ids(conn, 12, allow_legacy=False)
        == []
    )


def test_annotation_delete_paths_cover_keep_mode_link_residue_and_missing_annotations(
    monkeypatch,
):
    """Check annotation delete paths cover keep mode link residue and missing annotations cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in annotation delete paths cover keep mode link residue and missing annotations.
    Raises: AssertionError when validation or the called operation fails.
    """
    monkeypatch.setattr(annotation_service, "ParametersI", _FakeParameters)
    monkeypatch.setattr(annotation_service, "rlong", _Value)
    monkeypatch.setattr(annotation_service, "get_hash_secret", lambda: "shared-secret")
    monkeypatch.setattr(
        annotation_service, "get_id", lambda obj: getattr(obj, "id", None)
    )
    monkeypatch.setattr(
        annotation_service,
        "find_plugin_annotation_ids",
        lambda current_conn, image_id, allow_legacy=True: [7],
    )

    assert annotation_service.delete_existing_annotations(
        SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), [], "keep"
    ) == (0, 0, 0)

    plugin_mapping = _plugin_mapping("shared-secret", alpha="1")
    ann = _MapAnnotation(7, plugin_mapping)
    lingering_links = {7: [1007]}
    deleted = []

    class _QueryService:
        """Test double for query service behavior in this module."""

        @staticmethod
        def projection(hql, params, service_opts=None):
            """Return the projection for `_QueryService`.

            Inputs: `hql`, `params` SQL parameters, `service_opts`. Output: projection
            Raises: AssertionError when validation or the called operation fails.
            """
            if "where l.child.id = :aid" in hql:
                aid = params.values["aid"].getValue()
                return [[_Value(link_id)] for link_id in lingering_links.get(aid, [])]
            if "select a.id from MapAnnotation a where a.id = :aid" in hql:
                return [[_Value(params.values["aid"].getValue())]]
            raise AssertionError(f"Unexpected HQL: {hql}")

    class _UpdateService:
        """Test double for update service behavior in this module."""

        @staticmethod
        def deleteObject(obj):
            """Delete the object for `_UpdateService`.

            Inputs: `obj`. Output: None.
            """
            deleted.append(obj)

    conn = SimpleNamespace(
        SERVICE_OPTS=object(),
        getQueryService=_QueryService,
        getObject=lambda kind, obj_id: (
            None
            if kind == "ImageAnnotationLink"
            else (ann if kind == "MapAnnotation" and obj_id == 7 else None)
        ),
        deleteObjects=lambda kind, object_ids, wait=True: deleted.append(
            (kind, tuple(object_ids), wait)
        ),
    )
    image = SimpleNamespace(id=55, listAnnotations=lambda: [ann])

    deleted_sets, deleted_pairs, attempted = (
        annotation_service.delete_existing_annotations(
            conn,
            _UpdateService(),
            image,
            var_names=["alpha"],
            mode="plugin",
        )
    )

    assert (deleted_sets, deleted_pairs, attempted) == (0, 0, 1)
    assert deleted == [("ImageAnnotationLink", (1007,), True)]


class _FakeOriginalFile:
    """Test double for fake original file."""

    def __init__(self):
        """Create `_FakeOriginalFile` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self._id = _Value(501)
        self.name = None
        self.path = None
        self.size = None
        self.mimetype = None

    def setName(self, value):
        """Set the name for `_FakeOriginalFile`.

        Inputs: `value` input value. Output: None.
        """
        self.name = value

    def setPath(self, value):
        """Set the path for `_FakeOriginalFile`.

        Inputs: `value` input value. Output: None.
        """
        self.path = value

    def setSize(self, value):
        """Set the size for `_FakeOriginalFile`.

        Inputs: `value` input value. Output: None.
        """
        self.size = value

    def setMimetype(self, value):
        """Set the mimetype for `_FakeOriginalFile`.

        Inputs: `value` input value. Output: None.
        """
        self.mimetype = value

    def getId(self):
        """Return `_FakeOriginalFile`'s fake OMERO identifier.

        Inputs: none. Output: `self._id`.
        """
        return self._id


class _FakeFileAnnotation:
    """Test double for fake file annotation."""

    def __init__(self):
        """Create `_FakeFileAnnotation` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self.ns = None
        self.file = None

    def setNs(self, value):
        """Set the ns for `_FakeFileAnnotation`.

        Inputs: `value` input value. Output: None.
        """
        self.ns = value

    def setFile(self, value):
        """Set the file for `_FakeFileAnnotation`.

        Inputs: `value` input value. Output: None.
        """
        self.file = value


class _FakeImageAnnotationLink:
    """Test double for fake image annotation link."""

    def __init__(self):
        """Create `_FakeImageAnnotationLink` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self.parent = None
        self.child = None

    def setParent(self, value):
        """Set the parent for `_FakeImageAnnotationLink`.

        Inputs: `value` input value. Output: None.
        """
        self.parent = value

    def setChild(self, value):
        """Set the child for `_FakeImageAnnotationLink`.

        Inputs: `value` input value. Output: None.
        """
        self.child = value


class _FakeImageRef:
    """Test double for fake image ref."""

    def __init__(self, image_id, loaded):
        """Create `_FakeImageRef` with `image_id` and `loaded`.

        Inputs: `image_id`, `loaded`. Output: None.
        """
        self.image_id = image_id
        self.loaded = loaded


class _FakeRawFileStore:
    """Test double for fake raw file store."""

    def __init__(self):
        """Create `_FakeRawFileStore` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self.file_id = None
        self.buffer = b""
        self.saved = False
        self.closed = False

    def setFileId(self, value):
        """Set the file ID for `_FakeRawFileStore`.

        Inputs: `value` input value. Output: None.
        """
        self.file_id = value

    def write(self, data, offset, length):
        """Write data to the resource.

        Inputs: `data`, `offset`, `length`. Output: None.
        """
        self.buffer = data[offset : offset + length]

    def save(self):
        """Persist `_FakeRawFileStore`'s fake object state.

        Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
        """
        self.saved = True

    def close(self):
        """Close `_FakeRawFileStore`'s fake resource handle.

        Inputs: caller provides no extra arguments. Output: records the fake side effect.
        """
        self.closed = True


class _FakeUpdateServiceForMetadata:
    """Test double for fake update service for metadata."""

    def __init__(self):
        """Create `_FakeUpdateServiceForMetadata` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self.saved = []

    def saveAndReturnObject(self, obj):
        """Return the fake saved OMERO object from OMP service-helper tests.

        Inputs: `obj`. Output: `obj`.
        """
        self.saved.append(obj)
        return obj


class _FakeImageForMetadata:
    """Test double for fake image for metadata."""

    def __init__(self, raw_store):
        """Create `_FakeImageForMetadata` with `raw_store`.

        Inputs: `raw_store`. Output: None.
        """
        self._raw_store = raw_store
        self._update = _FakeUpdateServiceForMetadata()
        self._conn = SimpleNamespace(
            getUpdateService=lambda: self._update,
            c=SimpleNamespace(sf=SimpleNamespace(createRawFileStore=lambda: raw_store)),
        )
        self._obj = "image-obj"

    @staticmethod
    def getId():
        """Return `_FakeImageForMetadata`'s fake OMERO identifier.

        Inputs: none. Output: 99.
        """
        return 99

    @staticmethod
    def getAcquisitionDate():
        """Return `_FakeImageForMetadata`'s fake acquisition date.

        Inputs: none. Output: `_Value` result.
        """
        return _Value("2026-03-20T09:10:11")

    @staticmethod
    def getObjectiveSettings():
        """Return `_FakeImageForMetadata`'s fake objective settings.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(
            getID=lambda: _Value(7),
            getCorrectionCollar=lambda: _Value(0.17),
        )

    @staticmethod
    def getChannels():
        """Return the channels for `_FakeImageForMetadata`.

        Inputs: none. Output: `list`.
        """
        return [
            SimpleNamespace(
                getIndex=lambda: 0,
                getLabel=lambda: "DAPI",
                getEmissionWave=lambda: _Value(450),
                getExcitationWave=lambda: _Value(405),
            )
        ]

    @staticmethod
    def getDetectorSettings():
        """Return `_FakeImageForMetadata`'s fake detector settings.

        Inputs: none. Output: list.
        """
        return [
            SimpleNamespace(
                getID=lambda: _Value(3),
                getBinning=lambda: _Value("2x2"),
                getGain=lambda: _Value(4.5),
            )
        ]

    @staticmethod
    def loadOriginalMetadata():
        """Return `_FakeImageForMetadata`'s fake original-metadata payload.

        Inputs: none. Output: tuple.
        """
        return (
            1,
            [("Exposure", "100ms"), ("LongNote", "X" * 260)],
            [("Series", "A")],
        )


def test_extract_acquisition_metadata_collects_searchable_fields_and_attaches_long_values(
    monkeypatch,
):
    """Verify extract acquisition metadata collects searchable fields and attaches long values.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in extract acquisition metadata collects searchable fields and attaches long values.
    """
    raw_store = _FakeRawFileStore()
    image = _FakeImageForMetadata(raw_store)

    monkeypatch.setattr(metadata_service, "OriginalFileI", _FakeOriginalFile)
    monkeypatch.setattr(metadata_service, "FileAnnotationI", _FakeFileAnnotation)
    monkeypatch.setattr(
        metadata_service, "ImageAnnotationLinkI", _FakeImageAnnotationLink
    )
    monkeypatch.setattr(metadata_service, "ImageI", _FakeImageRef)
    monkeypatch.setattr(metadata_service, "rstring", lambda value: value)
    monkeypatch.setattr(metadata_service, "rlong", lambda value: value)

    cleaned = metadata_service.extract_acquisition_metadata(image)

    assert cleaned["acquisition_date"] == "2026-03-20T09:10:11"
    assert cleaned["objective_id"] == "7"
    assert cleaned["channel_0_label"] == "DAPI"
    assert cleaned["detector_3_gain"] == "4.5"
    assert cleaned["BF_Exposure"] == "100ms"
    assert cleaned["BF_Series"] == "A"
    assert cleaned["BF_LongNote"].startswith("[LONG_VALUE_STORED_IN_FILEANNOTATION")
    assert cleaned["full_metadata_file"] == "FileAnnotation:501"
    assert b"LongNote = " in raw_store.buffer
    assert raw_store.saved is True
    assert image._update.saved[-1].parent.image_id == 99
    assert image._update.saved[-1].parent.loaded is False
    assert raw_store.closed is True


def test_image_collection_helpers_cover_fetch_fallbacks_and_format_detection(
    monkeypatch,
):
    """Verify image collection helpers cover fetch fallbacks and format detection.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image collection helpers cover fetch fallbacks and format detection.
    RuntimeError, TypeError when validation or the called operation fails.
    """

    class _Image:
        """Test double for image behavior in this module."""

        def __init__(self, image_id, name, fileset=None):
            """Create `_Image` with `image_id`, `name`, and `fileset`.

            Inputs: `image_id`, `name`, `fileset`. Output: None.
            """
            self.id = image_id
            self._name = name
            self._fileset = fileset

        def getId(self):
            """Return `_Image`'s fake OMERO identifier.

            Inputs: none. Output: `_Value` result.
            """
            return _Value(self.id)

        def getName(self):
            """Return `_Image`'s fake object name.

            Inputs: none. Output: `_Value` result.
            """
            return _Value(self._name)

        def getFileset(self):
            """Return the fileset for `_Image`.

            Inputs: none. Output: `_fileset`.
            """
            return self._fileset

    class _Dataset:
        """Test double for dataset behavior in this module."""

        def __init__(self, dataset_id, name, images, owner_id=7):
            """Create `_Dataset` with `dataset_id`, `name`, `images`, and `owner_id`.

            Inputs: `dataset_id`, `name`, `images`, `owner_id`. Output: None.
            """
            self.id = dataset_id
            self.owner_id = owner_id
            self._name = name
            self._images = list(images)

        def getId(self):
            """Return `_Dataset`'s fake OMERO identifier.

            Inputs: none. Output: `_Value` result.
            """
            return _Value(self.id)

        def getName(self):
            """Return `_Dataset`'s fake object name.

            Inputs: none. Output: `_Value` result.
            """
            return _Value(self._name)

        def listChildren(self):
            """Return `_Dataset`'s fake child listing.

            Inputs: none. Output: `list` result.
            """
            return list(self._images)

    class _Project:
        """Test double for project behavior in this module."""

        def __init__(self, datasets):
            """Create `_Project` with `datasets`.

            Inputs: `datasets`. Output: None.
            """
            self._datasets = list(datasets)

        def listChildren(self):
            """Return `_Project`'s fake child listing.

            Inputs: none. Output: `list` result.
            """
            return list(self._datasets)

    class _OriginalFile:
        """Test double for original file behavior in this module."""

        def __init__(self, *, fmt=None, name=None):
            """Create `_OriginalFile` with its default state.

            Inputs: `fmt`, `name`. Output: None.
            """
            self._fmt = fmt
            self._name = name

        def getFormat(self):
            """Return the format for `_OriginalFile`.

            Inputs: none. Output: get format result.
            """
            return _Value(self._fmt) if self._fmt is not None else None

        def getName(self):
            """Return `_OriginalFile`'s fake object name.

            Inputs: none. Output: `_Value` result.
            """
            return _Value(self._name)

    class _UsedFile:
        """Test double for used file behavior in this module."""

        def __init__(self, original_file):
            """Create `_UsedFile` with `original_file`.

            Inputs: `original_file`. Output: None.
            """
            self._original_file = original_file

        def getOriginalFile(self):
            """Return `_UsedFile`'s fake original file.

            Inputs: none. Output: `self._original_file`.
            """
            return self._original_file

    class _Fileset:
        """Test double for fileset behavior in this module."""

        def __init__(self, used_files):
            """Create `_Fileset` with `used_files`.

            Inputs: `used_files`. Output: None.
            """
            self._used_files = list(used_files)

        def copyUsedFiles(self):
            """Copy the used Files for `_Fileset`.

            Inputs: none. Output: `list`.
            """
            return list(self._used_files)

    monkeypatch.setattr(
        image_service,
        "get_id",
        lambda obj: (
            obj.getId().getValue()
            if hasattr(obj, "getId")
            else getattr(obj, "id", None)
        ),
    )
    monkeypatch.setattr(
        image_service,
        "get_text",
        lambda value: value.getValue() if hasattr(value, "getValue") else str(value),
    )
    monkeypatch.setattr(
        image_service,
        "is_owned_by_user",
        lambda obj, owner_id: (
            owner_id is None or getattr(obj, "owner_id", None) == owner_id
        ),
    )

    image_one = _Image(1, "a.png")
    image_two = _Image(2, "b.png")
    fetched = {1: image_one, 2: image_two}

    class _FetchConn:
        """Test double for fetch conn behavior in this module."""

        @staticmethod
        def getObjects(object_type, ids=None, obj_ids=None):
            """Return the objects for `_FetchConn`.

            Inputs: `object_type`, `ids`, `obj_ids`. Output: None. Raises: RuntimeError,
            TypeError when validation or the called operation fails.
            """
            assert object_type == "Image"
            if ids is not None:
                raise TypeError("legacy backend")
            raise RuntimeError("bulk lookup failed")

        @staticmethod
        def getObject(object_type, image_id):
            """Return the object for `_FetchConn`.

            Inputs: `object_type`, `image_id` OMERO image ID. Output: `get` result.
            """
            assert object_type == "Image"
            return fetched.get(image_id)

    image_map = image_service.fetch_images_by_ids(_FetchConn(), [1, 2, 3])
    assert image_map == {1: image_one, 2: image_two}

    ds_all = _Dataset(
        1,
        "Dataset All",
        [_Image(3, "c.tif"), _Image(1, "a.tif"), _Image(2, "b.tif")],
    )
    ds_selected = _Dataset(2, "Dataset Selected", [_Image(4, "d.tif")])
    ds_skipped = _Dataset("bad", "Dataset Skipped", [_Image(5, "e.tif")])
    project = _Project([ds_all, ds_selected, ds_skipped])
    conn = SimpleNamespace(getObject=lambda object_type, object_id: project)

    dataset_rows = image_service.collect_images_by_dataset_sorted(
        conn, 1, limit=2, owner_id=7
    )
    assert [img.id for img in dataset_rows[0][1]] == [1, 2]

    selected_rows = image_service.collect_images_by_selected_datasets(
        conn, 1, ["bad", 2], owner_id=7
    )
    assert selected_rows == [(ds_selected, ds_selected.listChildren())]

    format_images = [
        _Image(
            6,
            "metadata-source.bin",
            _Fileset([_UsedFile(_OriginalFile(fmt="czi", name="source.bin"))]),
        ),
        _Image(
            7,
            "sample.ome.tiff",
            _Fileset(
                [_UsedFile(_OriginalFile(fmt="Directory", name="sample.ome.tiff"))]
            ),
        ),
        _Image(8, "preview.png"),
    ]
    format_dataset = _Dataset(9, "Formats", format_images)
    format_project = _Project([format_dataset])
    format_conn = SimpleNamespace(
        getObject=lambda object_type, object_id: format_project
    )

    summaries = image_service.collect_dataset_summaries(format_conn, 1, owner_id=7)

    assert summaries == [
        {
            "id": "9",
            "name": "Formats",
            "image_count": 3,
            "formats": "OME-TIFF, PNG, Zeiss CZI",
        }
    ]


def test_extract_acquisition_metadata_handles_direct_values_and_partial_failures():
    """Verify extract acquisition metadata handles direct values and partial failures.

    Inputs: OMP service fakes. Output: fails on regressions in extract acquisition metadata handles direct values and partial failures.
    """

    class _ImageWithFallbacks:
        """Test double for image with fallbacks behavior in this module."""

        def __init__(self):
            """Create `_ImageWithFallbacks` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self._raw_store = _FakeRawFileStore()
            self._update = _FakeUpdateServiceForMetadata()
            self._conn = SimpleNamespace(
                getUpdateService=lambda: self._update,
                c=SimpleNamespace(
                    sf=SimpleNamespace(createRawFileStore=lambda: self._raw_store)
                ),
            )
            self._obj = "image-obj"

        @staticmethod
        def getId():
            """Return `_ImageWithFallbacks`'s fake OMERO identifier.

            Inputs: none. Output: 101.
            """
            return 101

        @staticmethod
        def getAcquisitionDate():
            """Return `_ImageWithFallbacks`'s fake acquisition date.

            Inputs: none. Output: '2026-03-21T10:11:12'.
            """
            return "2026-03-21T10:11:12"

        @staticmethod
        def getObjectiveSettings():
            """Return `_ImageWithFallbacks`'s fake objective settings.

            Inputs: none. Output: `SimpleNamespace` result.
            """
            return SimpleNamespace(
                getID=lambda: "OBJ-7",
                getCorrectionCollar=lambda: 0.20,
            )

        @staticmethod
        def getChannels():
            """Return the channels for `_ImageWithFallbacks`.

            Inputs: none. Output: `list`.
            """
            return [
                SimpleNamespace(
                    getIndex=lambda: (_ for _ in ()).throw(RuntimeError("no index")),
                    getLabel=lambda: "DNA",
                    getEmissionWave=lambda: "525",
                    getExcitationWave=lambda: (_ for _ in ()).throw(
                        RuntimeError("missing excitation")
                    ),
                ),
                SimpleNamespace(
                    getIndex=lambda: 1,
                    getLabel=lambda: (_ for _ in ()).throw(RuntimeError("bad label")),
                    getEmissionWave=lambda: None,
                    getExcitationWave=lambda: "405",
                ),
            ]

        @staticmethod
        def getDetectorSettings():
            """Return `_ImageWithFallbacks`'s fake detector settings.

            Inputs: none. Output: list.
            """
            return [
                SimpleNamespace(
                    getID=lambda: (_ for _ in ()).throw(
                        RuntimeError("bad detector id")
                    ),
                    getBinning=lambda: "1x1",
                    getGain=lambda: None,
                )
            ]

        @staticmethod
        def loadOriginalMetadata():
            """Return `_ImageWithFallbacks`'s fake original-metadata payload.

            Inputs: none. Output: tuple.
            """
            return (
                1,
                [("Exposure", 100), ("OnlyKey",), None],
                [("Series", "B"), ("Comment", "ok")],
            )

    cleaned = metadata_service.extract_acquisition_metadata(_ImageWithFallbacks())

    assert cleaned == {
        "acquisition_date": "2026-03-21T10:11:12",
        "objective_id": "OBJ-7",
        "objective_collar": "0.2",
        "channel_unknown_label": "DNA",
        "channel_unknown_emission": "525",
        "channel_1_excitation": "405",
        "detector_unknown_binning": "1x1",
        "BF_Exposure": "100",
        "BF_Series": "B",
        "BF_Comment": "ok",
    }


def test_extract_acquisition_metadata_returns_empty_when_sections_raise():
    """Confirm extract acquisition metadata returns empty when sections raise exposes the expected failure.

    Inputs: OMP service fakes. Output: fails on regressions in extract acquisition metadata returns empty when sections raise.
    """

    class _BrokenImage:
        """Test double for broken image behavior in this module."""

        @staticmethod
        def getId():
            """Return `_BrokenImage`'s fake OMERO identifier.

            Inputs: none. Output: 202.
            """
            return 202

        @staticmethod
        def getAcquisitionDate():
            """Return `_BrokenImage`'s fake acquisition date.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("date failed")

        @staticmethod
        def getObjectiveSettings():
            """Return `_BrokenImage`'s fake objective settings.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("objective failed")

        @staticmethod
        def getChannels():
            """Return the channels for `_BrokenImage`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("channels failed")

        @staticmethod
        def getDetectorSettings():
            """Return `_BrokenImage`'s fake detector settings.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("detectors failed")

        @staticmethod
        def loadOriginalMetadata():
            """Return `_BrokenImage`'s fake original-metadata payload.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("metadata failed")

    assert metadata_service.extract_acquisition_metadata(_BrokenImage()) == {}


class _FakeOriginalFileRef:
    """Test double for fake original file ref."""

    def __init__(self, name, fmt):
        """Create `_FakeOriginalFileRef` with `name` and `fmt`.

        Inputs: `name`, `fmt`. Output: None.
        """
        self._name = name
        self._fmt = fmt

    def getFormat(self):
        """Return the format for `_FakeOriginalFileRef`.

        Inputs: none. Output: get format result.
        """
        return _Value(self._fmt) if self._fmt is not None else None

    def getName(self):
        """Return `_FakeOriginalFileRef`'s fake object name.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self._name)


class _FakeUsedFile:
    """Test double for fake used file."""

    def __init__(self, original_file):
        """Create `_FakeUsedFile` with `original_file`.

        Inputs: `original_file`. Output: None.
        """
        self._original_file = original_file

    def getOriginalFile(self):
        """Return `_FakeUsedFile`'s fake original file.

        Inputs: none. Output: `self._original_file`.
        """
        return self._original_file


class _FakeFileset:
    """Test double for fake fileset."""

    def __init__(self, used_files):
        """Create `_FakeFileset` with `used_files`.

        Inputs: `used_files`. Output: None.
        """
        self._used_files = used_files

    def copyUsedFiles(self):
        """Copy the used Files for `_FakeFileset`.

        Inputs: none. Output: `list`.
        """
        return list(self._used_files)


class _FakeImage:
    """Test double for fake image."""

    def __init__(self, image_id, name, fileset=None):
        """Create `_FakeImage` with `image_id`, `name`, and `fileset`.

        Inputs: `image_id`, `name`, `fileset`. Output: None.
        """
        self.id = image_id
        self._name = name
        self._fileset = fileset

    def getFileset(self):
        """Return the fileset for `_FakeImage`.

        Inputs: none. Output: `_fileset`.
        """
        return self._fileset

    def getName(self):
        """Return `_FakeImage`'s fake object name.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self._name)


class _FakeDataset:
    """Test double for fake dataset."""

    def __init__(self, dataset_id, name, owner_id, images):
        """Create `_FakeDataset` with `dataset_id`, `name`, `owner_id`, and `images`.

        Inputs: `dataset_id`, `name`, `owner_id`, `images`. Output: None.
        """
        self.id = dataset_id
        self.owner_id = owner_id
        self._name = name
        self._images = list(images)

    def listChildren(self):
        """Return `_FakeDataset`'s fake child listing.

        Inputs: none. Output: `list` result.
        """
        return list(self._images)

    def getName(self):
        """Return `_FakeDataset`'s fake object name.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self._name)


class _FakeProject:
    """Test double for fake project."""

    def __init__(self, datasets):
        """Create `_FakeProject` with `datasets`.

        Inputs: `datasets`. Output: None.
        """
        self._datasets = list(datasets)

    def listChildren(self):
        """Return `_FakeProject`'s fake child listing.

        Inputs: none. Output: `list` result.
        """
        return list(self._datasets)


def test_image_service_collectors_and_format_detection(monkeypatch):
    """Verify image service collectors and format detection.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image service collectors and format detection.
    RuntimeError, TypeError when validation or the called operation fails.
    """
    monkeypatch.setattr(image_service, "get_id", lambda obj: getattr(obj, "id", None))
    monkeypatch.setattr(
        image_service,
        "get_text",
        lambda value: value.getValue() if hasattr(value, "getValue") else str(value),
    )
    monkeypatch.setattr(
        image_service,
        "is_owned_by_user",
        lambda obj, owner_id: (
            owner_id is None or getattr(obj, "owner_id", None) == owner_id
        ),
    )

    czi_fileset = _FakeFileset(
        [_FakeUsedFile(_FakeOriginalFileRef("sample.czi", "CZI"))]
    )
    ome_tiff_fileset = _FakeFileset(
        [_FakeUsedFile(_FakeOriginalFileRef("plate.ome.tiff", None))]
    )
    images = {
        1: _FakeImage(1, "b.ome.tif", ome_tiff_fileset),
        2: _FakeImage(2, "a.czi", czi_fileset),
        3: _FakeImage(3, "unknown", None),
    }
    ds1 = _FakeDataset(11, "Dataset A", 7, [images[2], images[1]])
    ds2 = _FakeDataset(12, "Dataset B", 7, [images[3]])
    ds_other_owner = _FakeDataset(13, "Dataset C", 99, [images[1]])
    project = _FakeProject([ds1, ds2, ds_other_owner])

    class _FakeConn:
        """Test double for fake conn."""

        @staticmethod
        def getObjects(kind, ids=None, obj_ids=None):
            """Return the objects for `_FakeConn`.

            Inputs: `kind`, `ids`, `obj_ids`. Output: `list`. Raises: RuntimeError,
            TypeError when validation or the called operation fails.
            """
            if ids is not None:
                raise TypeError("legacy gateway")
            if obj_ids is not None:
                raise RuntimeError("bulk fetch unavailable")
            return []

        @staticmethod
        def getObject(kind, object_id):
            """Return the object for `_FakeConn`.

            Inputs: `kind`, `object_id`. Output: `get` result.
            """
            if kind == "Project":
                return project if object_id == 77 else None
            return images.get(object_id)

    conn = _FakeConn()

    fetched = image_service.fetch_images_by_ids(conn, [1, 3, 99])
    dataset_sorted = image_service.collect_images_by_dataset_sorted(
        conn, 77, limit=2, owner_id=7
    )
    selected = image_service.collect_images_by_selected_datasets(
        conn, 77, {"12", "99"}, limit=5, owner_id=7
    )
    summaries = image_service.collect_dataset_summaries(conn, 77, owner_id=7)
    project_images = image_service.collect_images_in_project(conn, 77, limit=2)

    assert sorted(fetched) == [1, 3]
    assert [img.id for img in dataset_sorted[0][1]] == [1, 2]
    assert len(dataset_sorted) == 1
    assert [(ds.id, [img.id for img in imgs]) for ds, imgs in selected] == [(12, [3])]
    assert summaries == [
        {
            "id": "11",
            "name": "Dataset A",
            "image_count": 2,
            "formats": "OME-TIFF, Zeiss CZI",
        },
        {"id": "12", "name": "Dataset B", "image_count": 1, "formats": "Unknown"},
    ]
    assert [img.id for img in project_images] == [2, 1]
