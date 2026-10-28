"""Real Home Assistant fixture support; all provider I/O is mocked in tests."""

from copy import deepcopy
from unittest.mock import patch

from homeassistant.helpers.storage import Store
import pytest

NATIVE_STORE_WRITE = Store._async_write_data

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir, hass_storage):
    """Isolate real Store writes from installed plugin fixtures and other runs."""
    memory_write = Store._async_write_data

    async def write(store, data):
        if store.key.startswith("adaptive_solar."):
            data = dict(data)
            if "data_func" in data:
                data["data"] = data.pop("data_func")()
            data = deepcopy(data)
            await NATIVE_STORE_WRITE(store, data)
        await memory_write(store, data)

    # Component reloads exercise real immutable Store envelopes. Keep the
    # plugin's memory map for unrelated HA stores and existing readback asserts.
    with patch.object(Store, "_async_write_data", write):
        yield hass_tmp_config_dir
