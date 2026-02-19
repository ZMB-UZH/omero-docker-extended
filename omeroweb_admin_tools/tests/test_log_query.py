from __future__ import annotations

import pytest

from omeroweb_admin_tools.services.log_query import (
    LogEntry,
    _build_internal_file_query,
    _cap_entries_per_container,
    _strip_message_prefix,
    build_loki_query,
)


def test_build_loki_query_requires_containers() -> None:
    with pytest.raises(ValueError):
        build_loki_query([])


def test_build_loki_query_builds_regex() -> None:
    query = build_loki_query(["omeroserver", "omeroweb"])
    assert query == '{compose_service=~"^(omeroserver|omeroweb)$"}'


def test_strip_message_prefix_removes_timestamp_and_level() -> None:
    message = "2026-02-02 14:52:58,266 INFO [omero.util] Started server"
    assert _strip_message_prefix(message) == "[omero.util] Started server"


def test_cap_entries_per_container_keeps_most_recent() -> None:
    entries = [
        LogEntry(
            timestamp="2026-02-02T14:52:58+00:00",
            container="omeroserver",
            level="info",
            message="one",
        ),
        LogEntry(
            timestamp="2026-02-02T14:52:59+00:00",
            container="omeroserver",
            level="info",
            message="two",
        ),
        LogEntry(
            timestamp="2026-02-02T14:52:00+00:00",
            container="omeroweb",
            level="info",
            message="other",
        ),
    ]

    capped = _cap_entries_per_container(entries, 1)
    assert {entry.message for entry in capped} == {"two", "other"}


def test_build_internal_file_query_uses_filepath_label() -> None:
    query = _build_internal_file_query("omeroserver_internal", "Blitz-0.log")
    assert (
        query
        == '{compose_service="omeroserver", log_type="internal", filepath=~"(^|.*/)Blitz\\-0\\.log$"}'
    )


def test_build_internal_file_query_handles_filename_label() -> None:
    query = _build_internal_file_query(
        "omeroserver_internal", "Blitz-0.log", "filename"
    )
    assert (
        query
        == '{compose_service="omeroserver", log_type="internal", filename=~"(^|.*/)Blitz\\-0\\.log$"}'
    )


def test_cap_entries_per_container_does_not_apply_global_cap() -> None:
    entries = [
        LogEntry(
            timestamp="2026-02-02T14:52:58+00:00",
            container="a",
            level="info",
            message="1",
        ),
        LogEntry(
            timestamp="2026-02-02T14:52:59+00:00",
            container="a",
            level="info",
            message="2",
        ),
        LogEntry(
            timestamp="2026-02-02T14:53:00+00:00",
            container="b",
            level="info",
            message="3",
        ),
    ]
    capped = _cap_entries_per_container(entries, 2)
    assert len(capped) == 3
