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
