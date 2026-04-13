from __future__ import annotations

from omeroweb_tools.services import search_query_builder


def test_build_omero_fulltext_query_uses_prefix_matching_for_terms():
    assert search_query_builder.build_omero_fulltext_query("104") == "104*"
    assert search_query_builder.build_omero_fulltext_query("104 204") == "104* OR 204*"


def test_build_omero_fulltext_query_preserves_exact_phrases():
    assert (
        search_query_builder.build_omero_fulltext_query('"GFP H2B" 104')
        == '"GFP H2B" OR 104*'
    )


def test_build_postgres_prefix_tsquery_uses_prefix_and_phrase_operators():
    assert (
        search_query_builder.build_postgres_prefix_tsquery("104 204") == "104:* | 204:*"
    )
    assert (
        search_query_builder.build_postgres_prefix_tsquery('"GFP H2B" 104')
        == "GFP:* <-> H2B:* | 104:*"
    )


def test_build_query_helpers_ignore_non_search_punctuation():
    assert search_query_builder.build_omero_fulltext_query("___") == ""
    assert search_query_builder.build_postgres_prefix_tsquery("___") == ""
