from __future__ import annotations

from omeroweb_tools.services import search_query_builder


def test_build_omero_fulltext_query_uses_prefix_matching_for_terms():
    """Verify build OMERO fulltext query uses prefix matching for terms.

    Inputs: none. Output: None.
    """
    assert search_query_builder.build_omero_fulltext_query("104") == "104*"
    assert search_query_builder.build_omero_fulltext_query("104 204") == "104* OR 204*"
    assert (
        search_query_builder.build_omero_fulltext_query("definitely-not-a-real-hit-xyz")
        == "definitely* OR not* OR real* OR hit* OR xyz*"
    )


def test_build_omero_fulltext_query_preserves_exact_phrases():
    """Verify build OMERO fulltext query preserves exact phrases.

    Inputs: none. Output: None.
    """
    assert (
        search_query_builder.build_omero_fulltext_query('"GFP H2B" 104')
        == '"GFP H2B" OR 104*'
    )


def test_build_postgres_prefix_tsquery_uses_prefix_and_phrase_operators():
    """Verify build postgres prefix tsquery uses prefix and phrase operators.

    Inputs: none. Output: None.
    """
    assert (
        search_query_builder.build_postgres_prefix_tsquery("104 204") == "104:* | 204:*"
    )
    assert (
        search_query_builder.build_postgres_prefix_tsquery('"GFP H2B" 104')
        == "GFP:* <-> H2B:* | 104:*"
    )
    assert (
        search_query_builder.build_postgres_prefix_tsquery(
            "definitely-not-a-real-hit-xyz"
        )
        == "definitely:* | not:* | real:* | hit:* | xyz:*"
    )


def test_build_query_helpers_ignore_non_search_punctuation():
    """Verify build query helpers ignore non search punctuation.

    Inputs: none. Output: None.
    """
    assert search_query_builder.build_omero_fulltext_query("___") == ""
    assert search_query_builder.build_postgres_prefix_tsquery("___") == ""
    assert search_query_builder.build_omero_fulltext_query("a") == ""
    assert search_query_builder.build_postgres_prefix_tsquery("a") == ""


def test_build_query_helpers_drop_single_numeric_fragments_from_decimals():
    """Verify build query helpers drop single numeric fragments from decimals.

    Inputs: none. Output: None.
    """
    assert (
        search_query_builder.build_postgres_prefix_tsquery("0.6240005493164062")
        == "6240005493164062:*"
    )
    assert (
        search_query_builder.build_omero_fulltext_query("0.6240005493164062")
        == "6240005493164062*"
    )
