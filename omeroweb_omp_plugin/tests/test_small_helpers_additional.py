from __future__ import annotations

import inspect
import re
from types import SimpleNamespace

from django.test import RequestFactory

from omeroweb_omp_plugin.services import filename_utils, http_utils
from omeroweb_omp_plugin.views import save_keyvaluepairs_view


def test_filename_utils_cover_whitespace_and_separator_fallback_paths():
    """Verify filename utils cover whitespace and separator fallback paths.

    Inputs: none. Output: None.
    """
    no_pairs = [
        "alpha-A-01.tif",
        "beta-B-02.tif",
    ]

    assert filename_utils.extract_base_name("prefix sample-01.tif") == "sample-01"

    separator_regex = filename_utils.regex_for_separators(" -", filenames=no_pairs)
    assert r"\s" in separator_regex
    assert re.split(separator_regex, "alpha A-01") == ["alpha", "A", "01"]

    boundary_regex = filename_utils.regex_for_separators([], filenames=no_pairs)
    assert re.split(boundary_regex, "A12B") == ["A", "12", "B"]
    assert (
        filename_utils.suggest_separator_regex(["Alpha123"])
        == r"(?<=\D)(?=\d)|(?<=\d)(?=\D)"
    )


def test_http_utils_internal_response_helpers_cover_none_and_empty_payloads():
    """Verify HTTP utils internal response helpers cover none and empty payloads.

    Inputs: none. Output: None.
    """
    assert http_utils._extract_message_from_response(None) is None

    empty_payload_response = SimpleNamespace(
        json=lambda: {},
        text="ignored",
    )
    assert http_utils._extract_message_from_response(empty_payload_response) is None


def test_save_keyvaluepairs_ready_endpoint_returns_plain_response():
    """Verify save keyvaluepairs ready endpoint returns plain response.

    Inputs: none. Output: None.
    """
    response = inspect.unwrap(save_keyvaluepairs_view.save_keyvaluepairs)(
        RequestFactory().get("/omeroweb_omp_plugin/save-keyvaluepairs/")
    )

    assert response.status_code == 200
    assert response.content == b"Save endpoint ready"
