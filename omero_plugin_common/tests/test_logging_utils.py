"""Tests for shared logging configuration helpers."""

import logging

from omero_plugin_common import logging_utils


def test_configure_omero_gateway_logging_sets_info_level() -> None:
    logger = logging.getLogger("omero.gateway.utils")
    previous_level = logger.level
    previous_flag = logging_utils._LOGGER_CONFIGURED

    try:
        logger.setLevel(logging.NOTSET)
        logging_utils._LOGGER_CONFIGURED = False

        logging_utils.configure_omero_gateway_logging()

        assert logger.level == logging.INFO
        assert logging_utils._LOGGER_CONFIGURED is True
    finally:
        logger.setLevel(previous_level)
        logging_utils._LOGGER_CONFIGURED = previous_flag


def test_configure_omero_gateway_logging_is_idempotent() -> None:
    logger = logging.getLogger("omero.gateway.utils")
    previous_level = logger.level
    previous_flag = logging_utils._LOGGER_CONFIGURED

    try:
        logger.setLevel(logging.WARNING)
        logging_utils._LOGGER_CONFIGURED = True

        logging_utils.configure_omero_gateway_logging()

        assert logger.level == logging.WARNING
    finally:
        logger.setLevel(previous_level)
        logging_utils._LOGGER_CONFIGURED = previous_flag


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
