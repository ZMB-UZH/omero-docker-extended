from __future__ import annotations

from types import SimpleNamespace

from omeroweb_omp_plugin.constants import HASH_KEY
from omeroweb_omp_plugin.services import rate_limit
from omeroweb_omp_plugin.services.omero import annotation_service


class _Value:
    def __init__(self, value):
        self.val = value

    def getValue(self):
        return self.val


class _BadValue:
    def __init__(self, value):
        self.val = value

    def getValue(self):
        raise RuntimeError("bad wrapped value")


class _Params:
    def __init__(self):
        self.values = {}

    def add(self, key, value):
        self.values[key] = value


def test_annotation_service_covers_wrapped_values_and_query_failures(monkeypatch):
    monkeypatch.setattr(
        annotation_service,
        "get_env",
        lambda name, env_file=None: "shared-secret",
    )
    assert annotation_service.get_hash_secret() == "shared-secret"

    monkeypatch.setattr(annotation_service, "ParametersI", _Params)
    monkeypatch.setattr(annotation_service, "rlong", lambda value: value)
    monkeypatch.setattr(annotation_service, "rstring", lambda value: value)
    monkeypatch.setattr(annotation_service, "get_hash_secret", lambda: "")

    mapping = {"alpha": "1"}
    mapping[HASH_KEY] = annotation_service.compute_plugin_hash(mapping)

    class _NamedValue:
        def __init__(self, name, value):
            self.name = name
            self.value = value

    wrapped_ann = SimpleNamespace(
        getMapValue=lambda: [
            _NamedValue(_BadValue("alpha"), _BadValue("1")),
            _NamedValue(_BadValue(HASH_KEY), _BadValue(mapping[HASH_KEY])),
        ]
    )
    assert annotation_service.is_plugin_annotation(wrapped_ann) is True

    class _LookupFailureQS:
        def projection(self, hql, params, service_opts=None):
            raise RuntimeError("query failed")

    qs_backed_ann = SimpleNamespace(
        getMapValue=lambda: [],
        getId=lambda: (_ for _ in ()).throw(RuntimeError("missing id wrapper")),
        id=5,
    )
    assert (
        annotation_service.is_plugin_annotation(
            qs_backed_ann,
            qs=_LookupFailureQS(),
        )
        is False
    )

    class _UnreadableMapValue:
        def getValue(self):
            raise RuntimeError("map wrapper unavailable")

        def __iter__(self):
            raise RuntimeError("cannot iterate wrapped values")

    unreadable_ann = SimpleNamespace(getMapValue=lambda: _UnreadableMapValue())
    assert annotation_service.is_plugin_annotation(unreadable_ann) is False

    class _QueryService:
        def projection(self, hql, params, service_opts=None):
            if "where l.parent.id = :iid and a.ns = :ns" in hql:
                return [[_Value(1)], [_Value(2)]]
            if "join a.mapValue mv" in hql:
                aid = params.values["aid"]
                if aid == 1:
                    return [
                        (_Value("alpha"), _Value("1")),
                        (_Value(HASH_KEY), _Value(mapping[HASH_KEY])),
                        (_Value("lonely"),),
                        (None, _Value("ignored")),
                    ]
                raise RuntimeError("verification failed")
            raise AssertionError(f"Unexpected HQL: {hql}")

    conn = SimpleNamespace(
        SERVICE_OPTS=object(), getQueryService=lambda: _QueryService()
    )
    assert annotation_service.find_plugin_annotation_ids(
        conn,
        7,
        allow_legacy=False,
    ) == [1]

    broken_conn = SimpleNamespace(
        SERVICE_OPTS=object(),
        getQueryService=lambda: (_ for _ in ()).throw(RuntimeError("qs boom")),
    )
    assert annotation_service.find_plugin_annotation_ids(broken_conn, 7) == []

    raising_query_service = SimpleNamespace(
        projection=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    conn_with_raising_qs = SimpleNamespace(
        SERVICE_OPTS=object(),
        getQueryService=lambda: raising_query_service,
    )
    assert annotation_service.find_annotation_link_ids(conn_with_raising_qs, 9) == []
    assert annotation_service.find_map_annotation_ids(conn_with_raising_qs, 9) == []


def test_delete_existing_annotations_handles_sparse_annotations_and_cleanup_failures(
    monkeypatch,
):
    monkeypatch.setattr(annotation_service, "ParametersI", _Params)
    monkeypatch.setattr(annotation_service, "rlong", lambda value: value)
    monkeypatch.setattr(annotation_service, "get_hash_secret", lambda: "")

    def _get_id(obj):
        if getattr(obj, "explode_id", False):
            raise RuntimeError("id lookup failed")
        return getattr(obj, "id", None)

    monkeypatch.setattr(annotation_service, "get_id", _get_id)

    class _NsWrapper:
        def getValue(self):
            raise RuntimeError("namespace missing")

    plugin_cleanup_result = annotation_service.delete_existing_annotations(
        SimpleNamespace(
            getQueryService=lambda: None,
            getObject=lambda *_args: None,
        ),
        SimpleNamespace(deleteObject=lambda obj: None),
        SimpleNamespace(
            id=99,
            listAnnotations=lambda: [
                SimpleNamespace(id=1),
                SimpleNamespace(id=None, _obj=SimpleNamespace(getMapValue=lambda: [])),
                SimpleNamespace(
                    id=7,
                    _obj=SimpleNamespace(getMapValue=lambda: []),
                    getNs=lambda: _NsWrapper(),
                ),
                SimpleNamespace(
                    explode_id=True,
                    _obj=SimpleNamespace(getMapValue=lambda: []),
                ),
            ],
        ),
        var_names=[],
        mode="plugin",
    )
    assert plugin_cleanup_result == (0, 0, 0)

    link_calls = {}

    def _find_link_ids(_conn, annotation_id):
        link_calls[annotation_id] = link_calls.get(annotation_id, 0) + 1
        if annotation_id == 13:
            raise RuntimeError("link query failed")
        if annotation_id == 11:
            return [401, 402] if link_calls[annotation_id] == 1 else []
        if annotation_id == 12:
            return [501] if link_calls[annotation_id] == 1 else []
        if annotation_id == 14:
            return [701] if link_calls[annotation_id] == 1 else []
        return []

    monkeypatch.setattr(annotation_service, "find_annotation_link_ids", _find_link_ids)
    monkeypatch.setattr(
        annotation_service,
        "find_map_annotation_ids",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("map lookup failed")
        ),
    )

    class _LinkStub:
        def __init__(self):
            self.id = None

        def setId(self, value):
            if value == 402:
                raise RuntimeError("stub creation failed")
            self.id = value

    monkeypatch.setattr(annotation_service, "ImageAnnotationLinkI", _LinkStub)

    class _BrokenLenMapValue:
        def __bool__(self):
            return True

        def __len__(self):
            raise RuntimeError("cannot measure pairs")

    class _AnnotationQueryService:
        def projection(self, hql, params, service_opts=None):
            if "select a.id from MapAnnotation a where a.id = :aid" in hql:
                aid = params.values["aid"]
                if aid == 14:
                    raise RuntimeError("projection failed")
                return []
            raise AssertionError(f"Unexpected HQL: {hql}")

    deleted_objects = []
    update = SimpleNamespace(deleteObject=lambda obj: deleted_objects.append(obj))

    annotations = {
        11: SimpleNamespace(
            id=11, _obj=("annotation", 11), getMapValue=lambda: _BrokenLenMapValue()
        ),
        13: SimpleNamespace(id=13, _obj=("annotation", 13), getMapValue=lambda: [1]),
        14: SimpleNamespace(id=14, _obj=("annotation", 14), getMapValue=lambda: []),
    }

    class _Conn:
        SERVICE_OPTS = object()

        def getQueryService(self):
            return _AnnotationQueryService()

        def getObject(self, kind, obj_id):
            if kind == "ImageAnnotationLink":
                raise RuntimeError("link lookup unavailable")
            if kind == "MapAnnotation" and obj_id == 12:
                raise RuntimeError("annotation not reloadable")
            return annotations.get(obj_id)

    image = SimpleNamespace(
        id=55,
        listAnnotations=lambda: [
            SimpleNamespace(id=11, _obj=SimpleNamespace(getMapValue=lambda: [])),
            SimpleNamespace(id=12, _obj=SimpleNamespace(getMapValue=lambda: [])),
            SimpleNamespace(id=13, _obj=SimpleNamespace(getMapValue=lambda: [])),
            SimpleNamespace(id=14, _obj=SimpleNamespace(getMapValue=lambda: [])),
        ],
    )

    deleted_sets, deleted_pairs, attempted = (
        annotation_service.delete_existing_annotations(
            _Conn(),
            update,
            image,
            var_names=[],
            mode="all",
        )
    )

    assert (deleted_sets, deleted_pairs, attempted) == (2, 0, 4)
    assert any(isinstance(obj, _LinkStub) and obj.id == 401 for obj in deleted_objects)
    assert any(isinstance(obj, _LinkStub) and obj.id == 501 for obj in deleted_objects)


def test_rate_limit_covers_dummy_cache_cleanup_and_blocked_state(monkeypatch):
    current_time = [100.0]
    monkeypatch.setattr(rate_limit.time, "time", lambda: current_time[0])

    cache = rate_limit.InMemoryCache()
    cache._cleanup_interval = 10
    cache.set("expired", "value", timeout=1)
    current_time[0] = 120.0
    assert cache.get("missing") is None
    assert "expired" not in cache._store

    class _DummyCache:
        def __init__(self):
            self.deleted = []

        def get(self, key):
            return {"actions": "bad", "blocked_until": "bad"}

        def set(self, key, value, timeout=None):
            raise AssertionError(
                "django dummy cache backend should not be used directly"
            )

        def delete(self, key):
            self.deleted.append(key)

    dummy_cache = _DummyCache()
    memory_calls = []
    monkeypatch.setattr(rate_limit, "DummyCache", _DummyCache)
    monkeypatch.setattr(rate_limit, "cache", dummy_cache)
    monkeypatch.setattr(rate_limit._memory_cache, "get", lambda key: {"memory": key})
    monkeypatch.setattr(
        rate_limit._memory_cache,
        "set",
        lambda key, value, timeout=None: (
            memory_calls.append((key, value, timeout)) or True
        ),
    )
    monkeypatch.setattr(
        rate_limit._memory_cache,
        "delete",
        lambda key: memory_calls.append(("delete", key)) or True,
    )

    assert rate_limit._is_dummy_cache() is True
    assert rate_limit._cache_get("alpha") == {"memory": "alpha"}
    assert rate_limit._cache_set("alpha", {"value": 1}, timeout=5) is True
    assert rate_limit._cache_delete("alpha") is True
    assert memory_calls == [
        ("alpha", {"value": 1}, 5),
        ("delete", "alpha"),
    ]

    state = {}

    def _cache_get(_key):
        return {"actions": "bad", "blocked_until": 150.0}

    def _cache_set(key, value, timeout):
        state["value"] = value
        state["timeout"] = timeout
        return True

    monkeypatch.setattr(rate_limit, "_cache_get", _cache_get)
    monkeypatch.setattr(rate_limit, "_cache_set", _cache_set)
    request = SimpleNamespace(
        META={"REMOTE_ADDR": ""},
        user=SimpleNamespace(is_authenticated=False),
    )

    blocked, remaining = rate_limit.check_major_action_rate_limit(request)
    assert blocked is False
    assert remaining == 30.0
    assert state["value"] == {"actions": [], "blocked_until": 150.0}
    assert state["timeout"] == rate_limit._cache_timeout_seconds()
