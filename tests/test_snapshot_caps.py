"""Original physical caps bind day totals and cells across both DST days."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig
from custom_components.adaptive_solar.snapshots import provenance, validate_snapshot
from tests.storage_helpers import seed_store


def original(kind, day):
    config = SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),),
                        (InverterConfig("i", max_output_kw=5, output_type=kind),))
    local = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(config.timezone))
    start, end = local.astimezone(UTC), (local + timedelta(days=1)).astimezone(UTC)
    hours = int((end - start).total_seconds() / 3600)
    snapshot = {"issued_at": (start - timedelta(hours=1)).isoformat(), "energies": {"i": 5 * hours},
                "forecast": {"i": [{"start": (start + timedelta(hours=i)).isoformat(),
                                       "end": (start + timedelta(hours=i + 1)).isoformat(), "energy_kwh": 5.0}
                                      for i in range(hours)]}}
    return config, start, hours, snapshot


@pytest.mark.parametrize("day,hours", [("2026-03-29", 23), ("2026-06-01", 24), ("2026-10-25", 25)])
@pytest.mark.parametrize("kind", ["ac", "dc"])
def test_original_cap_is_hard_for_daily_energy_and_each_cell(day, hours, kind):
    config, _, actual_hours, snapshot = original(kind, day)
    assert actual_hours == hours
    clean, _ = validate_snapshot(day, snapshot, provenance(config), config)
    assert clean == snapshot

    over_day = deepcopy(snapshot)
    over_day["energies"]["i"] *= 1.01
    with pytest.raises(ValueError, match="invalid day-start energy"):
        validate_snapshot(day, over_day, provenance(config), config)
    over_cell = deepcopy(snapshot)
    over_cell["forecast"]["i"][0]["energy_kwh"] += .01
    over_cell["forecast"]["i"][1]["energy_kwh"] -= .01
    # Daily sum is still exactly the hard limit: the cell bound is independent.
    with pytest.raises(ValueError, match="invalid day-start curve"):
        validate_snapshot(day, over_cell, provenance(config), config)
    legacy, _ = validate_snapshot(day, over_cell, provenance(config), config, strict_curve=False)
    assert legacy == {key: value for key, value in snapshot.items() if key != "forecast"}

    rounded = deepcopy(snapshot)
    rounded["energies"]["i"] += 1e-13
    rounded["forecast"]["i"][0]["energy_kwh"] += 1e-13
    validate_snapshot(day, rounded, provenance(config), config)
    # An original higher cap may survive a later physical reconfiguration.
    lower = replace(config, inverters=(replace(config.inverters[0], max_ac_kw=None, max_output_kw=4),))
    validate_snapshot(day, snapshot, provenance(config), lower)


@pytest.mark.parametrize("day", ["2026-03-29", "2026-06-01", "2026-10-25"])
@pytest.mark.parametrize("kind", ["ac", "dc"])
async def test_native_import_rejects_overcap_before_writing_and_roundtrips_exact_cap(hass, day, kind):
    config, start, _, snapshot = original(kind, day)
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    with freeze_time(start + timedelta(hours=2), real_asyncio=True):
        await coordinator.async_restore()
        coordinator.async_commit_setup()
        over = deepcopy(snapshot)
        over["energies"]["i"] *= 1.01
        with pytest.raises(ValueError, match="invalid day-start energy"):
            await coordinator.async_restore_day_start(day, over, config)
        assert not coordinator.daily_snapshots and not coordinator._pending_day_start_imports
        assert not Path(coordinator._store.path).exists()
        over["energies"]["i"] = 10**1000
        with pytest.raises(ValueError, match="invalid day-start energy"):
            await coordinator.async_restore_day_start(day, over, config)
        assert not Path(coordinator._store.path).exists()
        over = deepcopy(snapshot)
        over["forecast"]["i"][0]["energy_kwh"] += .01
        over["forecast"]["i"][1]["energy_kwh"] -= .01
        with pytest.raises(ValueError, match="invalid day-start curve"):
            await coordinator.async_restore_day_start(day, over, config)
        assert not Path(coordinator._store.path).exists()
        await coordinator.async_restore_day_start(day, snapshot, config)
        assert coordinator.daily_snapshots[day] == snapshot
        await coordinator.async_close()
        restored = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
        await restored.async_restore()
        assert restored.daily_snapshots[day] == snapshot
        await restored.async_close()


@pytest.mark.parametrize("invalid", ["overcap", "huge_energy", "huge_cap"])
async def test_native_load_preserves_overcap_store_read_only(hass, invalid):
    day = "2026-10-25"
    config, start, _, snapshot = original("ac", day)
    entry = MockConfigEntry(domain="adaptive_solar", data={"site": config.to_dict()})
    entry.add_to_hass(hass)
    coordinator = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
    with freeze_time(start + timedelta(hours=2), real_asyncio=True):
        await coordinator.async_restore()
        stored = coordinator._stored()
        snapshot["energies"]["i"] = 10**1000 if invalid == "huge_energy" else snapshot["energies"]["i"] * 1.1
        stored["daily_snapshots"] = {day: {key: value for key, value in snapshot.items() if key != "forecast"}}
        stored["daily_snapshot_provenance"] = {day: provenance(config)}
        if invalid == "huge_cap":
            stored["daily_snapshot_provenance"][day]["output_caps_kw"]["i"] = 10**1000
        if invalid == "overcap":
            await coordinator._store.async_save(stored)
        else:
            # HA's writer already refuses integers outside its JSON range.
            # A foreign/corrupt existing file must still remain read-only.
            seed_store(coordinator._store, stored)
        before = Path(coordinator._store.path).read_bytes()
        await coordinator.async_close()
        restored = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
        await restored.async_restore()
        assert not restored._store_writable and not restored.daily_snapshots
        restored.async_commit_setup()
        await restored.async_close()
        assert Path(coordinator._store.path).read_bytes() == before


@pytest.mark.parametrize("field", ["daily", "hourly", "cap"])
def test_snapshot_huge_integer_is_a_validation_error(field):
    config, _, _, snapshot = original("ac", "2026-06-01")
    metadata = provenance(config)
    if field == "daily":
        snapshot["energies"]["i"] = 10**1000
    elif field == "hourly":
        snapshot["forecast"]["i"][0]["energy_kwh"] = 10**1000
    else:
        metadata["output_caps_kw"]["i"] = 10**1000
    with pytest.raises(ValueError, match="invalid day-start"):
        validate_snapshot("2026-06-01", snapshot, metadata, config)
