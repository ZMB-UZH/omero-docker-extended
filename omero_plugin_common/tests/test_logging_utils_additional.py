from __future__ import annotations

from types import SimpleNamespace

from omero_plugin_common import logging_utils


class _UnconstructableError(Exception):
    """Test double for unconstructable error behavior in this module."""

    def __init__(self):
        """Create `_UnconstructableError` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        super().__init__("original")


def test_logging_utils_cover_empty_url_parse_failures_and_exception_fallbacks(
    monkeypatch,
):
    """Confirm logging utils cover empty URL parse failures and exception fallbacks exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when logging utils cover empty URL parse failures and exception fallbacks stops reporting the expected error.
    Raises: _UnconstructableError when validation or the called operation fails.
    """
    assert logging_utils.sanitize_url_for_logging("") == ""

    monkeypatch.setattr(
        logging_utils,
        "urlsplit",
        lambda raw: (_ for _ in ()).throw(ValueError("bad url")),
    )
    assert logging_utils.sanitize_url_for_logging("line1\nline2") == "line1\\\\nline2"

    def sanitized_info_for_test_exception():
        """Return the sanitized info for test exception.

        Inputs: none. Output: `sanitized_exc_info` result. Raises: _UnconstructableError
        when validation or the called operation fails.
        """
        try:
            raise _UnconstructableError()
        except _UnconstructableError as exc:
            return logging_utils.sanitized_exc_info(exc)

    exc_type, sanitized_exc, tb = sanitized_info_for_test_exception()
    assert exc_type is RuntimeError
    assert "_UnconstructableError" in str(sanitized_exc)
    assert "original" in str(sanitized_exc)
    assert tb is not None


def test_summarize_process_output_reports_only_counts() -> None:
    """Verify summarize process output reports only counts.

    Inputs: helper fakes. Output: fails on regressions in summarize process output reports only counts.
    """
    summary = logging_utils.summarize_process_output("line1\nline2", "error")

    assert summary == ("stdout_lines=2 stderr_lines=1 stdout_chars=11 stderr_chars=5")


def test_redacted_netloc_brackets_raw_ipv6_hosts() -> None:
    """Verify redacted netloc brackets raw ipv6 hosts.

    Inputs: helper fakes. Output: fails on regressions in redacted netloc brackets raw ipv6 hosts.
    """
    parsed = SimpleNamespace(
        hostname="2001:db8::1",
        port=None,
        username=None,
        password=None,
    )

    assert logging_utils._redacted_netloc(parsed) == "[2001:db8::1]"
