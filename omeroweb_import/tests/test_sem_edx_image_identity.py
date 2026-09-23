from types import SimpleNamespace

from omeroweb_import.views import core_functions as core


def test_import_ids_take_priority_over_names_and_survive_cache_reload(monkeypatch):
    """Resolve exact import IDs across name collisions and new connections.

    Inputs: connection doubles and stored import IDs. Output: target identity and
    lookup-count assertions before and after reconnection.
    """
    entries = {
        "first/image.tif": {"status": "imported", "imported_image_ids": [11]},
        "second/image.tif": {"status": "imported", "imported_image_ids": [22]},
    }
    queries = []
    monkeypatch.setattr(
        core, "_batch_find_images_by_name", lambda *args: queries.append(args) or {}
    )
    for connection_number in range(2):
        images = {
            image_id: SimpleNamespace(
                getName=lambda: "renamed.tif", connection=connection_number
            )
            for image_id in (11, 22)
        }
        fetched = []

        def get_object(kind, image_id):
            """Return wrappers belonging only to the active connection.

            Inputs: model name and image ID. Output: current connection's wrapper.
            """
            fetched.append((kind, image_id))
            return images.get(image_id)

        result = core._sem_edx_image_cache(
            SimpleNamespace(getObject=get_object), entries, entries, {}, None, None
        )
        assert result == {
            "first/image.tif": images[11],
            "second/image.tif": images[22],
        }
        assert fetched == [("Image", 11), ("Image", 22)]
    assert queries == []


def test_import_identity_rejects_missing_ambiguous_or_unimported_targets(monkeypatch):
    """Missing IDs and failed entries cannot fall back to an unrelated image.

    Inputs: failed, missing, duplicate and multi-image import records. Output:
    assertions that only unambiguous imported identities are selected.
    """
    images = {
        1: SimpleNamespace(getName=lambda: "image.tif"),
        2: SimpleNamespace(getName=lambda: "image.tif"),
        3: SimpleNamespace(getName=lambda: "other.tif"),
    }
    entries = {
        "": {},
        "failed/image.tif": {"status": "error"},
        "missing/image.tif": {"status": "imported", "imported_image_ids": [99]},
        "ambiguous/image.tif": {"status": "imported", "imported_image_ids": [1, 2]},
        "matched/image.tif": {"status": "imported", "imported_image_ids": [1, 3]},
        "deduplicated/renamed.tif": {
            "status": "imported",
            "imported_image_ids": [3, 3],
        },
    }
    fetched = []
    fallback_calls = []

    def get_object(_kind, image_id):
        """Count lookups to prove shared IDs are loaded only once.

        Inputs: model name and image ID. Output: known wrapper or None.
        """
        fetched.append(image_id)
        return images.get(image_id)

    monkeypatch.setattr(
        core,
        "_batch_find_images_by_name",
        lambda *args: fallback_calls.append(args) or {},
    )
    result = core._sem_edx_image_cache(
        SimpleNamespace(getObject=get_object), entries, entries, {}, None, None
    )
    assert result == {
        "matched/image.tif": images[1],
        "deduplicated/renamed.tif": images[3],
    }
    assert fetched == [99, 1, 2, 3]
    assert fallback_calls == []


def test_legacy_lookup_preserves_scope_and_rejects_duplicate_paths(monkeypatch):
    """Never widen a missing dataset lookup or guess between duplicate paths.

    Inputs: legacy records and dataset-scoped query doubles. Output: exact query
    scope and unambiguous relative-path mapping assertions.
    """
    entries = {
        "first/image.tif": {},
        "second/image.tif": {},
        "unmatched/image.tif": {},
        "orphan.tif": {},
    }
    scoped_image = object()
    orphan_image = object()
    queries = []

    def lookup(_conn, names, dataset_id):
        """Model one missing dataset and one actual orphan match.

        Inputs: connection, requested names and dataset ID. Output: scoped images.
        """
        queries.append((tuple(names), dataset_id))
        return (
            {"image.tif": scoped_image}
            if dataset_id == 22
            else {"orphan.tif": orphan_image}
            if dataset_id is None
            else {}
        )

    monkeypatch.setattr(core, "_batch_find_images_by_name", lookup)
    monkeypatch.setattr(
        core,
        "_dataset_name_for_path",
        lambda path, _orphan: path.split("/")[0],
    )
    result = core._sem_edx_image_cache(
        object(),
        entries,
        entries,
        {"first": 11, "second": 22, "unmatched": 33},
        None,
        None,
    )
    assert result == {"second/image.tif": scoped_image, "orphan.tif": orphan_image}
    assert queries == [
        (("image.tif",), 11),
        (("image.tif",), 22),
        (("image.tif",), 33),
        (("orphan.tif",), None),
    ]
    queries.clear()
    duplicates = {"first/image.tif": {}, "second/image.tif": {}}
    assert (
        core._sem_edx_image_cache(
            object(), duplicates, duplicates, {"Override": 22}, None, "Override"
        )
        == {}
    )
    assert queries == [(("image.tif",), 22)]


def test_legacy_batch_lookup_omits_ambiguous_matches_and_partial_failures(monkeypatch):
    """Distinct same-name images are ambiguous; repeated query rows are not.

    Inputs: duplicate rows, missing wrappers and an interrupted query. Output:
    assertions that ambiguity or partial results cannot select an arbitrary image.
    """
    monkeypatch.setattr(
        core.omero, "sys", SimpleNamespace(ParametersI=object), raising=False
    )
    monkeypatch.setattr(core, "_params_add_string_list", lambda *_args: None)
    monkeypatch.setattr(core, "_params_add_long", lambda *_args: None)
    names = {1: "same.tif", 2: "same.tif", 3: "unique.tif"}
    rows = [1, 1, 2, 3, 99]
    queries = []

    def find_all(query, _params, _options):
        """Include duplicate join rows and one missing wrapper.

        Inputs: query, parameters and service options. Output: selected model rows.
        """
        queries.append(query)
        return [
            SimpleNamespace(
                getId=lambda value=value: SimpleNamespace(getValue=lambda: value)
            )
            for value in rows
        ]

    wrappers = {
        image_id: SimpleNamespace(getName=lambda name=name: name)
        for image_id, name in names.items()
    }
    conn = SimpleNamespace(
        SERVICE_OPTS={},
        getQueryService=lambda: SimpleNamespace(findAllByQuery=find_all),
        getObject=lambda _kind, image_id: wrappers.get(image_id),
    )
    assert core._batch_find_images_by_name(conn, list(names.values())) == {
        "unique.tif": wrappers[3]
    }
    assert "i.datasetLinks IS EMPTY" in queries[-1]
    rows[:] = [1, 1]
    assert core._batch_find_images_by_name(conn, ["same.tif"], 11) == {
        "same.tif": wrappers[1]
    }
    assert "i.datasetLinks IS EMPTY" not in queries[-1]
    rows[:] = [3, 2]

    def fail_after_first(_kind, image_id):
        """A partial query cannot establish whether a name is unambiguous.

        Inputs: model name and image ID. Output: wrapper or a lookup exception.
        """
        if image_id == 2:
            raise RuntimeError("lookup failed")
        return wrappers[image_id]

    conn.getObject = fail_after_first
    assert core._batch_find_images_by_name(conn, ["unique.tif"], 11) == {}
