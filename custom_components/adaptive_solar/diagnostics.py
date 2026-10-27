"""Diagnostics without site coordinates, configured entity IDs or raw history."""

from .core.models import MEASUREMENT_BOUNDARIES


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    weather_diagnostics = getattr(coordinator.client, "diagnostics", {})
    output_types = {inv.output_type for inv in coordinator.site.inverters}
    return {
        "forecast_issued_at": coordinator.data.issued_at.isoformat() if coordinator.data else None,
        "last_update_success": coordinator.last_update_success,
        "strings": len(coordinator.site.strings),
        "inverters": len(coordinator.site.inverters),
        "output_stages": {kind: sum(inv.output_type == kind for inv in coordinator.site.inverters) for kind in sorted(output_types)},
        "site_measurement_boundary": "mixed_output_generation_sum" if len(output_types) > 1 else MEASUREMENT_BOUNDARIES[next(iter(output_types))],
        "native_energy_eligible": len(output_types) == 1,
        "weather_models": list(coordinator.site.weather_models),
        "weather_errors": dict(coordinator.client.errors),
        "weather_diagnostics": weather_diagnostics if isinstance(weather_diagnostics, dict) else {},
        "learning": coordinator.learner_status,
        "archived_forecast_points": len(coordinator.archive),
        "measured_energy_intervals": len(coordinator.intervals),
    }
