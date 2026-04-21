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
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class _ErrorBody:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload


def test_extract_error_details_prefers_nested_messages_and_plaintext():
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
    monkeypatch.setattr(annotation_service, "get_hash_secret", lambda: "secret")
    monkeypatch.setattr(
        annotation_service,
        "compute_plugin_hash",
        lambda mapping: f"hash:{mapping['name']}",
    )

    assert core._get_hash_secret() == "secret"
    assert core.compute_plugin_hash({"name": "demo"}) == "hash:demo"


def test_filename_helpers_detect_label_value_pairs_and_protect_scientific_hyphens():
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
    current_time = [1000.0]
    state = {}

    def fake_get(key):
        return state.get(key)

    def fake_set(key, value, timeout):
        state[key] = value
        state["timeout"] = timeout
        return True

    def fake_delete(key):
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
        raise RuntimeError("cache boom")

    monkeypatch.setattr(rate_limit, "_cache_get", failing_cache)

    allowed, remaining = rate_limit.check_major_action_rate_limit(request)

    assert allowed is False
    assert remaining == rate_limit.MAJOR_ACTION_BLOCK_SECONDS
    assert "cache boom" in rate_limit.get_rate_limit_status(request)["error"]

    monkeypatch.setattr(
        rate_limit,
        "_cache_delete",
        lambda key: (_ for _ in ()).throw(RuntimeError("delete boom")),
    )
    assert rate_limit.reset_rate_limit(request) is False


class _FakeParameters:
    def __init__(self):
        self.values = {}

    def add(self, key, value):
        self.values[key] = value


class _NamedValue:
    def __init__(self, name, value):
        self.name = _Value(name)
        self.value = _Value(value)


class _MapAnnotation:
    def __init__(self, ann_id, mapping, *, ns=MAP_NS):
        self.id = ann_id
        self._mapping = dict(mapping)
        self._ns = ns
        self._obj = self

    def getId(self):
        return _Value(self.id)

    def getMapValue(self):
        return [_NamedValue(key, value) for key, value in self._mapping.items()]

    def getNs(self):
        return _Value(self._ns)


def _plugin_mapping(secret=None, **extra):
    original = annotation_service.get_hash_secret
    try:
        annotation_service.get_hash_secret = lambda: secret
        mapping = dict(extra)
        mapping[HASH_KEY] = annotation_service.compute_plugin_hash(mapping)
        return mapping
    finally:
        annotation_service.get_hash_secret = original


def test_annotation_hash_helpers_detect_preloaded_and_database_fallback(monkeypatch):
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
        @staticmethod
        def projection(hql, params, service_opts=None):
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
                return [] if aid in deleted_annotation_ids else [[_Value(aid + 1000)]]
            if "join a.mapValue mv" in hql and "where l.parent.id = :iid" in hql:
                return [[_Value(1)], [_Value(4)]]
            if "select a.id from MapAnnotation a where a.id = :aid" in hql:
                aid = params.values["aid"].getValue()
                return [] if aid in deleted_annotation_ids else [[_Value(aid)]]
            raise AssertionError(f"Unexpected HQL: {hql}")

    class _FakeUpdateService:
        def __init__(self):
            self.deleted = []

        def deleteObject(self, obj):
            self.deleted.append(obj)
            if isinstance(obj, tuple) and obj[0] == "link":
                deleted_link_ids.add(obj[1])
                deleted_annotation_ids.add(obj[1] - 1000)
            elif isinstance(obj, _MapAnnotation):
                deleted_annotation_ids.add(obj.id)

    ann1 = _MapAnnotation(1, plugin_mapping)
    ann2 = _MapAnnotation(2, legacy_mapping, ns="other-ns")
    ann3 = _MapAnnotation(3, bad_mapping)
    annotations = {1: ann1, 2: ann2, 3: ann3}
    update = _FakeUpdateService()
    conn = SimpleNamespace(
        SERVICE_OPTS=object(),
        getQueryService=lambda: _FakeQueryService(),
        getObject=lambda kind, obj_id: (
            SimpleNamespace(_obj=("link", obj_id))
            if kind == "ImageAnnotationLink"
            else annotations.get(obj_id)
        ),
    )
    image = SimpleNamespace(
        id=55,
        listAnnotations=lambda: [ann1, ann2, ann3],
    )

    assert annotation_service.find_plugin_annotation_ids(conn, 55) == [1, 2]
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

    assert (deleted_sets, deleted_pairs, attempted) == (2, 3, 2)
    assert ("link", 1001) in update.deleted
    assert 1001 in deleted_link_ids


def test_annotation_helpers_cover_tuple_pairs_and_link_stub_cleanup(monkeypatch):
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

    deleted_link_ids = set()
    deleted_annotation_ids = set()

    class _LinkStub:
        def setId(self, value):
            self.link_id = value.getValue() if hasattr(value, "getValue") else value

    class _QueryService:
        @staticmethod
        def projection(hql, params, service_opts=None):
            if "where l.child.id = :aid" in hql:
                aid = params.values["aid"].getValue()
                return [] if aid in deleted_annotation_ids else [[_Value(401)]]
            if "select a.id from MapAnnotation a where a.id = :aid" in hql:
                aid = params.values["aid"].getValue()
                return [] if aid in deleted_annotation_ids else [[_Value(aid)]]
            if "where l.parent.id = :iid" in hql:
                return [[_Value(7)]]
            raise AssertionError(f"Unexpected HQL: {hql}")

    class _UpdateService:
        def __init__(self):
            self.deleted = []

        def deleteObject(self, obj):
            self.deleted.append(obj)
            if isinstance(obj, _LinkStub):
                deleted_link_ids.add(obj.link_id)
                deleted_annotation_ids.add(7)
            elif getattr(obj, "id", None) == 7:
                deleted_annotation_ids.add(7)

    ann = _MapAnnotation(7, {"alpha": "1"})
    update = _UpdateService()
    conn = SimpleNamespace(
        SERVICE_OPTS=object(),
        getQueryService=lambda: _QueryService(),
        getObject=lambda kind, obj_id: (
            None
            if kind == "ImageAnnotationLink"
            else (None if obj_id in deleted_annotation_ids else ann)
        ),
    )
    monkeypatch.setattr(annotation_service, "ImageAnnotationLinkI", _LinkStub)
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
    assert deleted_link_ids == {401}


def test_annotation_query_helpers_cover_invalid_inputs_and_legacy_controls(monkeypatch):
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
        @staticmethod
        def projection(hql, params, service_opts=None):
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
        getQueryService=lambda: _QueryService(),
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
        @staticmethod
        def projection(hql, params, service_opts=None):
            if "where l.child.id = :aid" in hql:
                aid = params.values["aid"].getValue()
                return [[_Value(link_id)] for link_id in lingering_links.get(aid, [])]
            if "select a.id from MapAnnotation a where a.id = :aid" in hql:
                return [[_Value(params.values["aid"].getValue())]]
            raise AssertionError(f"Unexpected HQL: {hql}")

    class _UpdateService:
        @staticmethod
        def deleteObject(obj):
            deleted.append(obj)

    conn = SimpleNamespace(
        SERVICE_OPTS=object(),
        getQueryService=lambda: _QueryService(),
        getObject=lambda kind, obj_id: (
            None
            if kind == "ImageAnnotationLink"
            else (ann if kind == "MapAnnotation" and obj_id == 7 else None)
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
    assert len(deleted) == 1


class _FakeOriginalFile:
    def __init__(self):
        self._id = _Value(501)
        self.name = None
        self.path = None
        self.size = None
        self.mimetype = None

    def setName(self, value):
        self.name = value

    def setPath(self, value):
        self.path = value

    def setSize(self, value):
        self.size = value

    def setMimetype(self, value):
        self.mimetype = value

    def getId(self):
        return self._id


class _FakeFileAnnotation:
    def __init__(self):
        self.ns = None
        self.file = None

    def setNs(self, value):
        self.ns = value

    def setFile(self, value):
        self.file = value


class _FakeImageAnnotationLink:
    def __init__(self):
        self.parent = None
        self.child = None

    def setParent(self, value):
        self.parent = value

    def setChild(self, value):
        self.child = value


class _FakeRawFileStore:
    def __init__(self):
        self.file_id = None
        self.buffer = b""
        self.saved = False
        self.closed = False

    def setFileId(self, value):
        self.file_id = value

    def write(self, data, offset, length):
        self.buffer = data[offset : offset + length]

    def save(self):
        self.saved = True

    def close(self):
        self.closed = True


class _FakeUpdateServiceForMetadata:
    def __init__(self):
        self.saved = []

    def saveAndReturnObject(self, obj):
        self.saved.append(obj)
        return obj


class _FakeImageForMetadata:
    def __init__(self, raw_store):
        self._raw_store = raw_store
        self._update = _FakeUpdateServiceForMetadata()
        self._conn = SimpleNamespace(
            getUpdateService=lambda: self._update,
            c=SimpleNamespace(sf=SimpleNamespace(createRawFileStore=lambda: raw_store)),
        )
        self._obj = "image-obj"

    @staticmethod
    def getId():
        return 99

    @staticmethod
    def getAcquisitionDate():
        return _Value("2026-03-20T09:10:11")

    @staticmethod
    def getObjectiveSettings():
        return SimpleNamespace(
            getID=lambda: _Value(7),
            getCorrectionCollar=lambda: _Value(0.17),
        )

    @staticmethod
    def getChannels():
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
        return [
            SimpleNamespace(
                getID=lambda: _Value(3),
                getBinning=lambda: _Value("2x2"),
                getGain=lambda: _Value(4.5),
            )
        ]

    @staticmethod
    def loadOriginalMetadata():
        return (
            1,
            [("Exposure", "100ms"), ("LongNote", "X" * 260)],
            [("Series", "A")],
        )


def test_extract_acquisition_metadata_collects_searchable_fields_and_attaches_long_values(
    monkeypatch,
):
    raw_store = _FakeRawFileStore()
    image = _FakeImageForMetadata(raw_store)

    monkeypatch.setattr(metadata_service, "OriginalFileI", _FakeOriginalFile)
    monkeypatch.setattr(metadata_service, "FileAnnotationI", _FakeFileAnnotation)
    monkeypatch.setattr(
        metadata_service, "ImageAnnotationLinkI", _FakeImageAnnotationLink
    )
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
    assert raw_store.closed is True


def test_image_collection_helpers_cover_fetch_fallbacks_and_format_detection(
    monkeypatch,
):
    class _Image:
        def __init__(self, image_id, name, fileset=None):
            self.id = image_id
            self._name = name
            self._fileset = fileset

        def getId(self):
            return _Value(self.id)

        def getName(self):
            return _Value(self._name)

        def getFileset(self):
            return self._fileset

    class _Dataset:
        def __init__(self, dataset_id, name, images, owner_id=7):
            self.id = dataset_id
            self.owner_id = owner_id
            self._name = name
            self._images = list(images)

        def getId(self):
            return _Value(self.id)

        def getName(self):
            return _Value(self._name)

        def listChildren(self):
            return list(self._images)

    class _Project:
        def __init__(self, datasets):
            self._datasets = list(datasets)

        def listChildren(self):
            return list(self._datasets)

    class _OriginalFile:
        def __init__(self, *, fmt=None, name=None):
            self._fmt = fmt
            self._name = name

        def getFormat(self):
            return _Value(self._fmt) if self._fmt is not None else None

        def getName(self):
            return _Value(self._name)

    class _UsedFile:
        def __init__(self, original_file):
            self._original_file = original_file

        def getOriginalFile(self):
            return self._original_file

    class _Fileset:
        def __init__(self, used_files):
            self._used_files = list(used_files)

        def copyUsedFiles(self):
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
        @staticmethod
        def getObjects(object_type, ids=None, obj_ids=None):
            assert object_type == "Image"
            if ids is not None:
                raise TypeError("legacy backend")
            raise RuntimeError("bulk lookup failed")

        @staticmethod
        def getObject(object_type, image_id):
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
    class _ImageWithFallbacks:
        def __init__(self):
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
            return 101

        @staticmethod
        def getAcquisitionDate():
            return "2026-03-21T10:11:12"

        @staticmethod
        def getObjectiveSettings():
            return SimpleNamespace(
                getID=lambda: "OBJ-7",
                getCorrectionCollar=lambda: 0.20,
            )

        @staticmethod
        def getChannels():
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
    class _BrokenImage:
        @staticmethod
        def getId():
            return 202

        @staticmethod
        def getAcquisitionDate():
            raise RuntimeError("date failed")

        @staticmethod
        def getObjectiveSettings():
            raise RuntimeError("objective failed")

        @staticmethod
        def getChannels():
            raise RuntimeError("channels failed")

        @staticmethod
        def getDetectorSettings():
            raise RuntimeError("detectors failed")

        @staticmethod
        def loadOriginalMetadata():
            raise RuntimeError("metadata failed")

    assert metadata_service.extract_acquisition_metadata(_BrokenImage()) == {}


class _FakeOriginalFileRef:
    def __init__(self, name, fmt):
        self._name = name
        self._fmt = fmt

    def getFormat(self):
        return _Value(self._fmt) if self._fmt is not None else None

    def getName(self):
        return _Value(self._name)


class _FakeUsedFile:
    def __init__(self, original_file):
        self._original_file = original_file

    def getOriginalFile(self):
        return self._original_file


class _FakeFileset:
    def __init__(self, used_files):
        self._used_files = used_files

    def copyUsedFiles(self):
        return list(self._used_files)


class _FakeImage:
    def __init__(self, image_id, name, fileset=None):
        self.id = image_id
        self._name = name
        self._fileset = fileset

    def getFileset(self):
        return self._fileset

    def getName(self):
        return _Value(self._name)


class _FakeDataset:
    def __init__(self, dataset_id, name, owner_id, images):
        self.id = dataset_id
        self.owner_id = owner_id
        self._name = name
        self._images = list(images)

    def listChildren(self):
        return list(self._images)

    def getName(self):
        return _Value(self._name)


class _FakeProject:
    def __init__(self, datasets):
        self._datasets = list(datasets)

    def listChildren(self):
        return list(self._datasets)


def test_image_service_collectors_and_format_detection(monkeypatch):
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
        @staticmethod
        def getObjects(kind, ids=None, obj_ids=None):
            if ids is not None:
                raise TypeError("legacy gateway")
            if obj_ids is not None:
                raise RuntimeError("bulk fetch unavailable")
            return []

        @staticmethod
        def getObject(kind, object_id):
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
