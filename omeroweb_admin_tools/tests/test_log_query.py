from __future__ import annotations

import pytest

from omeroweb_admin_tools.services.log_query import build_loki_query


def test_build_loki_query_requires_containers() -> None:
    with pytest.raises(ValueError):
        build_loki_query([])


def test_build_loki_query_builds_regex() -> None:
    query = build_loki_query(["omeroserver", "omeroweb"])
    assert query == '{container=~"omeroserver|omeroweb"}'
