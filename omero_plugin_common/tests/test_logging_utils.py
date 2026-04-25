"""Tests for shared logging configuration helpers."""

import logging
import traceback

from omero_plugin_common import logging_utils


def test_configure_omero_gateway_logging_sets_info_level() -> None:
    logger = logging.getLogger("omero.gateway.utils")
    previous_level = logger.level
    previous_flag = logging_utils._gateway_logging_configured()

    try:
        logger.setLevel(logging.NOTSET)
        logging_utils._set_gateway_logging_configured(False)

        logging_utils.configure_omero_gateway_logging()

        assert logger.level == logging.INFO
        assert logging_utils._gateway_logging_configured() is True
    finally:
        logger.setLevel(previous_level)
        logging_utils._set_gateway_logging_configured(previous_flag)


def test_configure_omero_gateway_logging_is_idempotent() -> None:
    logger = logging.getLogger("omero.gateway.utils")
    previous_level = logger.level
    previous_flag = logging_utils._gateway_logging_configured()

    try:
        logger.setLevel(logging.WARNING)
        logging_utils._set_gateway_logging_configured(True)

        logging_utils.configure_omero_gateway_logging()

        assert logger.level == logging.WARNING
    finally:
        logger.setLevel(previous_level)
        logging_utils._set_gateway_logging_configured(previous_flag)


def test_sanitize_log_value_escapes_newlines_and_carriage_returns() -> None:
    assert (
        logging_utils.sanitize_log_value("line1\nline2\rline3")
        == "line1\\\\nline2\\\\rline3"
    )


def test_sanitize_log_value_handles_non_string_values() -> None:
    assert logging_utils.sanitize_log_value(123) == "123"


def test_sanitize_log_value_handles_unprintable_values() -> None:
    class Unprintable:
        def __str__(self):
            raise RuntimeError("bad\nstring")

    assert (
        logging_utils.sanitize_log_value(Unprintable()) == "<unprintable Unprintable>"
    )
    assert (
        logging_utils.sanitize_url_for_logging(Unprintable())
        == "<unprintable Unprintable>"
    )
    assert "stdout_chars=25" in logging_utils.summarize_process_output(
        Unprintable(), None
    )


def test_sanitize_url_for_logging_redacts_sensitive_query_values() -> None:
    sanitized = logging_utils.sanitize_url_for_logging(
        "https://example.org/api?token=secret&ok=value&session_key=abc123&auth=key"
    )
    fragment_sanitized = logging_utils.sanitize_url_for_logging(
        "https://example.org/callback?ok=value#access_token=fragment-secret"
    )

    assert "token=REDACTED" in sanitized
    assert "session_key=REDACTED" in sanitized
    assert "auth=REDACTED" in sanitized
    assert "ok=value" in sanitized
    assert "secret" not in sanitized
    assert "abc123" not in sanitized
    assert "auth=key" not in sanitized
    assert fragment_sanitized == "https://example.org/callback?ok=value"
    assert "fragment-secret" not in fragment_sanitized


def test_sanitize_url_for_logging_redacts_userinfo() -> None:
    sanitized = logging_utils.sanitize_url_for_logging(
        "https://alice:supersecret@example.org/path"
    )

    assert sanitized == "https://alice:***@example.org/path"


def test_sanitize_url_for_logging_redacts_userinfo_with_invalid_port() -> None:
    sanitized = logging_utils.sanitize_url_for_logging(
        "https://alice:supersecret@example.org:bad-port/path"
    )

    assert sanitized == "https://alice:***@example.org/path"
    assert "supersecret" not in sanitized


def test_sanitize_url_for_logging_redacts_userinfo_when_username_is_malformed() -> None:
    sanitized = logging_utils.sanitize_url_for_logging(
        "https://bad\ud800:supersecret@example.org/path?token=secret"
    )

    assert sanitized == "https://REDACTED:***@example.org/path?token=REDACTED"
    assert "supersecret" not in sanitized
    assert "secret" not in sanitized
    assert "\ud800" not in sanitized


def test_sanitized_exc_info_escapes_exception_message() -> None:
    def sanitized_info_for_test_exception():
        try:
            raise RuntimeError("secret\nline")
        except RuntimeError as exc:
            return logging_utils.sanitized_exc_info(exc)

    exc_type, sanitized_exc, tb = sanitized_info_for_test_exception()
    assert exc_type is RuntimeError
    assert str(sanitized_exc) == "secret\\\\nline"
    assert tb is not None
    formatted = "".join(traceback.format_exception(exc_type, sanitized_exc, tb))
    assert str(sanitized_exc) in formatted
    assert "secret\nline" not in formatted
