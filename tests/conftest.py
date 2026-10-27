"""Real Home Assistant fixture support; all provider I/O is mocked in tests."""

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir):
    """Isolate real Store writes from installed plugin fixtures and other runs."""
    return hass_tmp_config_dir
