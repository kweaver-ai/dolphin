"""Root conftest.py — shared fixtures for all tests."""

import logging
import pytest

from dolphin.core import flags
from dolphin.core.logging.logger import SDK_LOGGER_NAME


@pytest.fixture(autouse=True)
def _isolate_log_handlers():
    """Temporarily remove file handlers during tests to avoid polluting dolphin.log."""
    logger = logging.getLogger(SDK_LOGGER_NAME)
    original_handlers = logger.handlers[:]
    logger.handlers = [h for h in logger.handlers if not isinstance(h, logging.FileHandler)]
    yield
    logger.handlers = original_handlers


@pytest.fixture
def disable_explore_v2():
    """Disable EXPLORE_BLOCK_V2 flag for the duration of the test."""
    with flags.override({flags.EXPLORE_BLOCK_V2: False}):
        yield


@pytest.fixture
def enable_explore_v2():
    """Enable EXPLORE_BLOCK_V2 flag for the duration of the test."""
    with flags.override({flags.EXPLORE_BLOCK_V2: True}):
        yield
