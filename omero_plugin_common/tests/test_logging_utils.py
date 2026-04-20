"""Tests for shared logging configuration helpers."""

import logging
import traceback

from omero_plugin_common import logging_utils


def test_configure_omero_gateway_logging_sets_info_level() -> None:
    logger = logging.getLogger("omero.gateway.utils")
    previous_level = logger.level
    previous_flag = logging_utils._OMERO_GATEWAY_LOGGING_CONFIGURED

    try:
        logger.setLevel(logging.NOTSET)
        logging_utils._OMERO_GATEWAY_LOGGING_CONFIGURED = False

        logging_utils.configure_omero_gateway_logging()

        assert logger.level == logging.INFO
        assert logging_utils._OMERO_GATEWAY_LOGGING_CONFIGURED is True
    finally:
        logger.setLevel(previous_level)
        logging_utils._OMERO_GATEWAY_LOGGING_CONFIGURED = previous_flag


def test_configure_omero_gateway_logging_is_idempotent() -> None:
    logger = logging.getLogger("omero.gateway.utils")
    previous_level = logger.level
    previous_flag = logging_utils._OMERO_GATEWAY_LOGGING_CONFIGURED

    try:
        logger.setLevel(logging.WARNING)
        logging_utils._OMERO_GATEWAY_LOGGING_CONFIGURED = True

        logging_utils.configure_omero_gateway_logging()

        assert logger.level == logging.WARNING
    finally:
        logger.setLevel(previous_level)
        logging_utils._OMERO_GATEWAY_LOGGING_CONFIGURED = previous_flag


def test_sanitize_log_value_escapes_newlines_and_carriage_returns() -> None:
    assert (
        logging_utils.sanitize_log_value("line1\nline2\rline3")
        == "line1\\\\nline2\\\\rline3"
    )


def test_sanitize_log_value_handles_non_string_values() -> None:
    assert logging_utils.sanitize_log_value(123) == "123"


def test_sanitize_url_for_logging_redacts_sensitive_query_values() -> None:
    sanitized = logging_utils.sanitize_url_for_logging(
        "https://example.org/api?token=secret&ok=value&session_key=abc123"
    )

    assert "token=%2A%2A%2A" in sanitized
    assert "session_key=%2A%2A%2A" in sanitized
    assert "ok=value" in sanitized
    assert "secret" not in sanitized
    assert "abc123" not in sanitized


def test_sanitize_url_for_logging_redacts_userinfo() -> None:
    sanitized = logging_utils.sanitize_url_for_logging(
        "https://alice:supersecret@example.org/path"
    )

    assert sanitized == "https://alice:***@example.org/path"


def test_sanitized_exc_info_escapes_exception_message() -> None:
    try:
        raise RuntimeError("secret\nline")
    except RuntimeError as exc:
        exc_type, sanitized_exc, tb = logging_utils.sanitized_exc_info(exc)

    assert exc_type is RuntimeError
    assert str(sanitized_exc) == "secret\\\\nline"
    assert tb is not None
    formatted = "".join(traceback.format_exception(exc_type, sanitized_exc, tb))
    assert "secret\\nline" in formatted
    assert "secret\nline" not in formatted
