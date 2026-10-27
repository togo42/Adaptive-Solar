"""Native power, daily energy and diagnostic forecast entities."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .core.models import MAX_FORECAST_DAYS, MEASUREMENT_BOUNDARIES

PARALLEL_UPDATES = 0
FORECAST_SCOPE = "available_pv_potential_without_operational_curtailment"
QUALITY_OPTIONS = ("complete", "mixed", "partial", "degraded", "physics", "curtailed")




async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    registry = er.async_get(hass)
    total_scope = _scope(coordinator.site, None)
    keys = {"power", "remaining", "quality", *(f"day_{day}" for day in range(MAX_FORECAST_DAYS))}
    legacy_total = any(row.platform == DOMAIN and row.unique_id in {
        f"{entry.entry_id}_{total_scope}_{key}" for key in keys
    } for row in er.async_entries_for_config_entry(registry, entry.entry_id))
    # New single-stage entries have no aggregate duplicates. Existing aggregate
    # IDs stay live as hidden aliases on the stage's device for old consumers.
    scopes = ([None] if len(coordinator.site.inverters) > 1 or legacy_total else [])
    scopes.extend(inv.id for inv in coordinator.site.inverters)
    entities = []
    for inverter_id in scopes:
        entities.extend([AdaptiveSolarSensor(coordinator, entry, inverter_id, "power"), AdaptiveSolarSensor(coordinator, entry, inverter_id, "remaining")])
        entities.extend(AdaptiveSolarSensor(coordinator, entry, inverter_id, "day", day) for day in range(MAX_FORECAST_DAYS))
        entities.append(AdaptiveSolarSensor(coordinator, entry, inverter_id, "quality"))
    _sync_registry(hass, entry, entities, keys)
    async_add_entities(entities)


def _scope(site, inverter_id):
    if inverter_id is not None:
        stage = next(inv for inv in site.inverters if inv.id == inverter_id)
        return f"dc_inverter_{inverter_id}" if stage.output_type == "dc" else f"inverter_{inverter_id}"
    types = {inv.output_type for inv in site.inverters}
    return "mixed_site" if len(types) > 1 else "dc_site" if types == {"dc"} else "site"


def _sync_registry(hass, entry, entities, keys):
    """Move compatible aggregate aliases without changing IDs or user choices.

    Only this platform's known sensor keys/scopes are managed. Removing an
    output stage removes that stage's registry rows; other integrations and
    unknown future sensor kinds are left alone. Recorder history is untouched.
    """
    registry, devices = er.async_get(hass), dr.async_get(hass)
    current = {}
    device_ids = set()
    for sensor in entities:
        device = devices.async_get_or_create(config_entry_id=entry.entry_id, **sensor.device_info)
        device_ids.add(device.id)
        current[sensor.unique_id] = (device.id, sensor.inverter_id is None)
    single = len(entry.runtime_data.site.inverters) == 1
    prefix = f"{entry.entry_id}_"
    for row in list(er.async_entries_for_config_entry(registry, entry.entry_id)):
        if row.platform != DOMAIN:
            continue
        if row.unique_id in current:
            device_id, aggregate = current[row.unique_id]
            changes = {"device_id": device_id} if row.device_id != device_id else {}
            if aggregate:
                if single and row.hidden_by is None:
                    changes["hidden_by"] = er.RegistryEntryHider.INTEGRATION
                elif not single and row.hidden_by is er.RegistryEntryHider.INTEGRATION:
                    changes["hidden_by"] = None
            if changes:
                registry.async_update_entity(row.entity_id, **changes)
            continue
        if not row.unique_id.startswith(prefix):
            continue
        suffix = row.unique_id[len(prefix):]
        scope = next((suffix[:-(len(key) + 1)] for key in keys if suffix.endswith("_" + key)), None)
        if scope in {"site", "dc_site", "mixed_site"} or scope and scope.startswith(("inverter_", "dc_inverter_")):
            registry.async_remove(row.entity_id)
    for device in list(dr.async_entries_for_config_entry(devices, entry.entry_id)):
        if (device.id not in device_ids and device.config_entries == {entry.entry_id}
                and device.identifiers and all(domain == DOMAIN and identifier.startswith(prefix)
                                              for domain, identifier in device.identifiers)
                and not er.async_entries_for_device(registry, device.id, include_disabled_entities=True)):
            devices.async_remove_device(device.id)


def day_bounds(now: datetime, timezone: str, offset: int) -> tuple[datetime, datetime]:
    """Return real local midnights, including 23/25-hour DST days."""
    zone = ZoneInfo(timezone)
    day = now.astimezone(zone).date() + timedelta(days=offset)
    return datetime.combine(day, time.min, zone).astimezone(UTC), datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC)


class AdaptiveSolarSensor(CoordinatorEntity, SensorEntity):
    """Forecast values stay unavailable when their full coverage is missing."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _unrecorded_attributes = frozenset({"forecast", "learning", "learning_horizon", "inputs", "model_status", "weather_errors", "weather_diagnostics", "resources", "training_intervals", "archive_points", "issued_at", "coverage_start", "coverage_end"})

    def __init__(self, coordinator, entry, inverter_id, kind, day=0):
        super().__init__(coordinator)
        self.inverter_id = inverter_id
        self.kind = kind
        self.day = day
        scope = _scope(coordinator.site, inverter_id)
        key = f"{kind}_{day}" if kind == "day" else kind
        self._attr_unique_id = f"{entry.entry_id}_{scope}_{key}"
        self._attr_translation_key = key
        device_inverter = coordinator.site.inverters[0].id if len(coordinator.site.inverters) == 1 else inverter_id
        device_scope = _scope(coordinator.site, device_inverter)
        device_types = {inv.output_type for inv in coordinator.site.inverters
                        if device_inverter is None or inv.id == device_inverter}
        prefix = "AC/DC " if len(device_types) > 1 else "DC " if device_types == {"dc"} else ""
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"{entry.entry_id}_{device_scope}")}, name=f"{NAME} {prefix}{device_inverter or 'Total'}", manufacturer=NAME, model="Adaptive PV forecast", entry_type=None)
        self._attr_entity_registry_visible_default = not (inverter_id is None and len(coordinator.site.inverters) == 1)
        if kind == "power":
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_native_unit_of_measurement = UnitOfPower.WATT
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_suggested_display_precision = 0
        elif kind in ("remaining", "day"):
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
            # A forecast changes in both directions. It is not a meter and must
            # never be exposed as total/total_increasing Recorder statistics.
            self._attr_suggested_display_precision = 2
        else:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = list(QUALITY_OPTIONS)
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_icon = "mdi:check-network-outline"

    @property
    def available(self):
        return super().available and self.native_value is not None

    @property
    def capability_attributes(self):
        # HA omits extra_state_attributes for unavailable entities. The static
        # physical scope must still label day/energy gaps and cold starts.
        return {**(super().capability_attributes or {}), "forecast_scope": FORECAST_SCOPE,
                "operational_curtailment_modelled": False, **self._measurement_metadata()}

    def _covered(self, start, end):
        result = self.coordinator.data
        if result is None:
            return None
        if self.inverter_id is not None:
            return result.energy_kwh(start, end, self.inverter_id)
        # Explicitly enumerate configured inverters. A result containing only
        # one inverter must never masquerade as a complete site total.
        values = [result.energy_kwh(start, end, inv.id) for inv in self.coordinator.site.inverters]
        return sum(values) if all(value is not None for value in values) else None

    def _inverters(self):
        return tuple(inv for inv in self.coordinator.site.inverters
                     if self.inverter_id is None or inv.id == self.inverter_id)

    def _measurement_metadata(self):
        types = sorted({inv.output_type for inv in self._inverters()})
        boundaries = [MEASUREMENT_BOUNDARIES[kind] for kind in types]
        site_types = {inv.output_type for inv in self.coordinator.site.inverters}
        return {"output_type": types[0] if len(types) == 1 else "mixed",
                "output_types": types, "measurement_boundaries": boundaries,
                "output_stage_boundaries": {stage.id: stage.measurement_boundary for stage in self._inverters()},
                "measurement_boundary": boundaries[0] if len(boundaries) == 1 else "mixed_output_generation_sum",
                "native_energy_eligible": len(site_types) == 1}

    def _curtailment_status(self):
        """Control status belongs to this entity's inverter scope only."""
        inputs = self.coordinator.input_quality
        statuses = [inputs.get(f"curtailment_{inv.id}", "unknown")
                    if inv.curtailed_entity_id else "not_configured" for inv in self._inverters()]
        if "active" in statuses:
            return "active"
        if any(status not in ("clear", "not_configured") for status in statuses):
            return "unknown"
        return "clear" if "clear" in statuses else "not_configured"

    def _model_application(self):
        """Summarize actual published statuses, independently of fitted regimes.

        The engine currently publishes a status union over its whole horizon,
        not a per-point trace. Never invent a day/lead assignment from it. Plain
        physics and physics_night accompany night/zero-baseline cells and do not
        cancel residual use in daylight. Explicit daytime fallback reasons do.
        """
        residual, fallback = False, False
        result = self.coordinator.data
        for inv in self._inverters():
            statuses = set(result.model_status.get(inv.id, "physics").split(";")) - {""}
            active = any(status.startswith("residual_") for status in statuses)
            residual |= active
            meaningful = any(point.inverter_id == inv.id and point.baseline_w > 0
                             and point.features.get("sun_elevation_deg", 1) > 0 for point in result.points)
            fallback |= (not active and meaningful) or any(
                (status.startswith(("physics_", "physics:")) or "rejected" in status)
                and status != "physics_night" for status in statuses)
        return "mixed" if residual and fallback else "residual" if residual else "physics"

    def _learning_horizon(self):
        """Expose validation support separately from actual horizon-wide use.

        An inactive opposite regime is evidence metadata, never a veto over
        residuals actually present in the published output. Supported ranges
        are internal validation support, not future accuracy guarantees.
        """
        result = self.coordinator.data
        own = {inv.id for inv in self._inverters()}
        points = [point for point in result.points if point.inverter_id in own]
        stages = {}
        for inverter_id in sorted(own):
            report = self.coordinator.learner_status.get(inverter_id, {})
            regimes = report.get("regimes", {"nwp": report})
            stages[inverter_id] = {
                "published_statuses": sorted(set(result.model_status.get(inverter_id, "physics").split(";")) - {""}),
                "validated_lead_support": {
                    name: {"state": regime.get("state", "unknown"), "lead_ranges": {
                        lead: {"min_hours": values["supported_lead_min_hours"],
                               "max_hours": values["supported_lead_max_hours"]}
                        for lead, values in regime.get("lead_bins", {}).items()
                        if values.get("state") == "active"
                        and "supported_lead_min_hours" in values and "supported_lead_max_hours" in values}}
                    for name, regime in regimes.items()},
            }
        return {"scope": "published_forecast_horizon", "application": self._model_application(),
                "start": min((point.start for point in points), default=None).isoformat() if points else None,
                "end": max((point.end for point in points), default=None).isoformat() if points else None,
                "support_evidence": "internal_chronological_validation_not_future_accuracy",
                "inverters": stages}

    def _quality(self, now):
        """Describe coverage and usable inputs, never an accuracy/confidence rank.

        An operational production limit does not change irradiance. Forecasts
        remain available PV potential; active/unknown limits block power-based
        nowcast in the engine and have an explicit status here.

        Coverage describes the remaining local day, degraded describes current
        configured observations/controls. An unavailable extra provider or a
        failed physics interval elsewhere is horizon-wide diagnostics only:
        unusable output today already makes coverage partial, while a valid
        remaining model may still supply complete output. Model application
        independently describes the explicitly labelled published horizon.
        """
        _, end = day_bounds(now, self.coordinator.site.timezone, 0)
        coverage = "complete" if self._covered(now, end) is not None else "partial"
        curtailment = self._curtailment_status()
        if curtailment == "active":
            return "curtailed", coverage
        if coverage == "partial":
            return "partial", coverage
        weather_diagnostics = getattr(self.coordinator.client, "diagnostics", {})
        resources = getattr(self.coordinator, "resource_diagnostics", {})
        if ((isinstance(weather_diagnostics, dict) and any(isinstance(values, dict)
                and values.get("cache_state") == "stale_if_error" for values in weather_diagnostics.values()))
                or (isinstance(resources, dict) and resources.get("fit_error"))):
            return "degraded", coverage
        inputs = self.coordinator.input_quality
        configured = [("temperature", self.coordinator.site.temperature_entity_id),
                      ("wind", self.coordinator.site.wind_entity_id),
                      ("irradiance", self.coordinator.site.irradiance_entity_id)]
        configured.extend((f"power_{inv.id}", inv.power_entity_id) for inv in self._inverters())
        configured.extend((f"measurement_valid_{inv.id}", inv.measurement_valid_entity_id) for inv in self._inverters())
        if curtailment == "unknown" or any(entity and inputs.get(key) != "valid" for key, entity in configured):
            return "degraded", coverage
        if self.coordinator.site.irradiance_entity_id:
            ghi_status = inputs.get("irradiance_nowcast", "ignored:no_observation")
            if not ghi_status.startswith("usable:") and ghi_status != "ignored:low_sun_or_clear_sky":
                return "degraded", coverage
        application = self._model_application()
        return "complete" if application == "residual" else application, coverage

    @property
    def native_value(self):
        result = self.coordinator.data
        if result is None:
            return None
        now = datetime.now(UTC)
        if self.kind == "quality":
            return self._quality(now)[0]
        if self.kind == "power":
            if self.inverter_id is not None:
                return result.power_at(now, self.inverter_id)
            values = [result.power_at(now, inv.id) for inv in self.coordinator.site.inverters]
            return sum(values) if all(value is not None for value in values) else None
        start, end = day_bounds(now, self.coordinator.site.timezone, self.day if self.kind == "day" else 0)
        if self.kind == "remaining":
            start = now
        if self.kind == "day" and self.day == 0:
            # A separate complete-day snapshot is frozen before local midnight.
            day = start.astimezone(ZoneInfo(self.coordinator.site.timezone)).date().isoformat()
            snapshot = self.coordinator.daily_snapshots.get(day)
            if snapshot is None:
                return None
            if self.inverter_id is not None:
                return snapshot["energies"].get(self.inverter_id)
            values = [snapshot["energies"].get(inv.id) for inv in self.coordinator.site.inverters]
            return sum(values) if all(value is not None for value in values) else None
        return self._covered(start, end)

    @property
    def extra_state_attributes(self):
        result = self.coordinator.data
        if result is None:
            return None
        curtailment = self._curtailment_status()
        attrs = {"issued_at": result.issued_at.isoformat(), "inverter_id": self.inverter_id or "total",
                 "forecast_scope": FORECAST_SCOPE, "operational_curtailment": curtailment,
                 "control_status_as_of": result.issued_at.isoformat(),
                 "operational_curtailment_modelled": False,
                 "power_nowcast_control": "blocked" if curtailment in ("active", "unknown") else "not_blocked",
                 **self._measurement_metadata()}
        if self.kind == "day" and self.day == 0:
            start, _ = day_bounds(datetime.now(UTC), self.coordinator.site.timezone, 0)
            attrs["forecast_cutoff"] = start.isoformat()
            day = start.astimezone(ZoneInfo(self.coordinator.site.timezone)).date().isoformat()
            snapshot = self.coordinator.daily_snapshots.get(day)
            attrs["issued_at"] = snapshot["issued_at"] if snapshot else None
            metadata = getattr(self.coordinator, "daily_snapshot_provenance", {})
            origin = metadata.get(day) if isinstance(metadata, dict) else None
            if origin is not None:
                attrs["forecast_provenance"] = origin
                attrs["forecast_configuration_changed"] = origin["config_fingerprint"] != self.coordinator._fingerprint
        if self.kind == "quality":
            now = datetime.now(UTC)
            weather_diagnostics = getattr(self.coordinator.client, "diagnostics", {})
            _, end = day_bounds(now, self.coordinator.site.timezone, 0)
            attrs.update({"coverage": self._quality(now)[1],
                          "coverage_scope": "remaining_local_day", "coverage_start": now.isoformat(),
                          "coverage_end": end.isoformat(), "learning_horizon": self._learning_horizon(),
                          "input_quality_scope": "current_issue_observations_and_controls",
                          "model_status_scope": "published_forecast_horizon",
                          "weather_errors_scope": "latest_provider_fetches_diagnostic_only",
                          "learning": self.coordinator.learner_status, "inputs": self.coordinator.input_quality,
                          "model_status": result.model_status, "weather_errors": self.coordinator.client.errors,
                          "weather_diagnostics": weather_diagnostics if isinstance(weather_diagnostics, dict) else {},
                          "resources": getattr(self.coordinator, "resource_diagnostics", {}),
                          "training_intervals": len(self.coordinator.intervals), "archive_points": len(self.coordinator.archive)})
            curve = []
            groups = {}
            for point in result.points:
                if self.inverter_id is None or point.inverter_id == self.inverter_id:
                    groups.setdefault((point.start, point.end), []).append(point)
            expected = {inv.id for inv in self.coordinator.site.inverters}
            for (start, end), points in sorted(groups.items()):
                if self.inverter_id is None and {point.inverter_id for point in points} != expected:
                    continue
                curve.append({"start": start.isoformat(), "end": end.isoformat(), "power_w": round(sum(point.power_w for point in points), 2), "energy_kwh": round(sum(point.power_w for point in points) * (end - start).total_seconds() / 3600000, 4), "lower_w": sum(point.lower_w for point in points) if all(point.lower_w is not None for point in points) else None, "upper_w": sum(point.upper_w for point in points) if all(point.upper_w is not None for point in points) else None})
            attrs["forecast"] = curve
        return attrs
