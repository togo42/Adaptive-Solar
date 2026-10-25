"""Read-only native Energy dashboard solar-forecast provider."""
from __future__ import annotations

from datetime import timedelta


async def async_get_solar_forecast(hass, config_entry_id):
    """Return native full UTC-hour Wh, retaining partial hours as gaps.

    Rest-of-day and quality entities retain the actual issue-time partial cell.
    A remaining 10-minute cell must not masquerade as a full hourly forecast.
    """
    entry = hass.config_entries.async_get_entry(config_entry_id)
    if entry is None or not getattr(entry, "runtime_data", None):
        return None
    coordinator = entry.runtime_data
    if not coordinator.last_update_success or coordinator.data is None:
        return None
    # One native config-entry forecast expresses one measurement boundary.
    # AC and DC source outputs can be summed by explicitly labelled sensors,
    # but a mixed-boundary sum cannot be an unqualified native Energy curve.
    if len({inv.output_type for inv in coordinator.site.inverters}) != 1:
        return None
    points = coordinator.data.points
    if not points:
        return None
    hour = min(point.start for point in points).replace(minute=0, second=0, microsecond=0)
    last = max(point.end for point in points)
    values = {}
    while hour + timedelta(hours=1) <= last:
        end = hour + timedelta(hours=1)
        energies = [coordinator.data.energy_kwh(hour, end, inv.id) for inv in coordinator.site.inverters]
        if all(value is not None for value in energies):
            values[hour.isoformat()] = sum(energies) * 1000
        hour = end
    return {"wh_hours": values} if values else None
