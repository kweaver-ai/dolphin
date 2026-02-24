"""Root conftest.py — shared fixtures for all tests."""

import pytest

from dolphin.core import flags


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
