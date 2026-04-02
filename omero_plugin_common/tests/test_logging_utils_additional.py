from __future__ import annotations

from omero_plugin_common import logging_utils


def test_logging_utils_cover_empty_url_parse_failures_and_exception_fallbacks(
    monkeypatch,
):
    assert logging_utils.sanitize_url_for_logging("") == ""

    monkeypatch.setattr(
        logging_utils,
        "urlsplit",
        lambda raw: (_ for _ in ()).throw(ValueError("bad url")),
    )
    assert logging_utils.sanitize_url_for_logging("line1\nline2") == "line1\\\\nline2"

    class _UnconstructableError(Exception):
        def __init__(self):
            super().__init__("original")

    try:
        raise _UnconstructableError()
    except _UnconstructableError as exc:
        exc_type, sanitized_exc, tb = logging_utils.sanitized_exc_info(exc)

    assert exc_type is RuntimeError
    assert "_UnconstructableError" in str(sanitized_exc)
    assert "original" in str(sanitized_exc)
    assert tb is not None


def test_summarize_process_output_reports_only_counts() -> None:
    summary = logging_utils.summarize_process_output("line1\nline2", "error")

    assert summary == ("stdout_lines=2 stderr_lines=1 stdout_chars=11 stderr_chars=5")
