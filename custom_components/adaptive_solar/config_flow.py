"""Native UI setup and a complete edit flow for site, inverters and strings."""
from __future__ import annotations

from copy import deepcopy
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import probatio as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_SITE, DOMAIN, NAME
from .core.models import MAX_FORECAST_DAYS, HorizonPoint, InverterConfig, SiteConfig, StringConfig

MODELS = ["best_match", "icon_seamless", "icon_global", "icon_eu", "icon_d2", "ecmwf_ifs025", "gfs_seamless"]


def number(minimum, maximum, step=0.1, unit=None):
    config = {"min": minimum, "max": maximum, "step": step if step >= 0.001 else "any", "mode": "box"}
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def entity(device_class):
    return selector.EntitySelector({"filter": [{"domain": "sensor", "device_class": device_class}]})


def field(schema, key, default, validation, required=True):
    marker = vol.Required if required else vol.Optional
    if not required and default is not None:
        schema[marker(key, description={"suggested_value": default})] = validation
    else:
        schema[marker(key, default=default) if default is not None else marker(key)] = validation


class _Editor:
    """Shared multi-step editor, preserving stable user-selected equipment IDs."""

    _site: dict
    _pending_inverters: list
    _pending_strings: list
    _edit_inverter: dict | None = None
    _edit_string: dict | None = None

    def _initialize(self, previous=None):
        previous = deepcopy(previous or {})
        self._site = previous
        self._pending_inverters = list(previous.get("inverters", []))
        self._pending_strings = list(previous.get("strings", []))
        self._site["inverters"] = []
        self._site["strings"] = []
        self._edit_inverter = None
        self._edit_string = None

    async def async_step_site(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                ZoneInfo(user_input["timezone"])
                if not user_input["weather_models"]:
                    raise ValueError("no weather models")
                self._site.pop("temperature_entity_id", None)
                self._site.pop("wind_entity_id", None)
                self._site.pop("irradiance_entity_id", None)
                self._site.update(user_input)
                self._site["forecast_days"] = int(user_input["forecast_days"])
                return await self.async_step_inverter()
            except (ZoneInfoNotFoundError, ValueError):
                errors["timezone"] = "invalid_timezone"
        schema = {}
        defaults = self._site
        field(schema, "latitude", defaults.get("latitude", self.hass.config.latitude), number(-90, 90, 0.000001, "°"))
        field(schema, "longitude", defaults.get("longitude", self.hass.config.longitude), number(-180, 180, 0.000001, "°"))
        field(schema, "timezone", defaults.get("timezone", self.hass.config.time_zone), selector.TextSelector())
        field(schema, "weather_models", defaults.get("weather_models", ["best_match"]), selector.SelectSelector({"options": MODELS, "multiple": True, "custom_value": True}))
        field(schema, "forecast_days", defaults.get("forecast_days", MAX_FORECAST_DAYS), number(1, MAX_FORECAST_DAYS, 1))
        field(schema, "temperature_entity_id", defaults.get("temperature_entity_id"), entity("temperature"), False)
        field(schema, "wind_entity_id", defaults.get("wind_entity_id"), entity("wind_speed"), False)
        field(schema, "irradiance_entity_id", defaults.get("irradiance_entity_id"), entity("irradiance"), False)
        return self.async_show_form(step_id="site", data_schema=vol.Schema(schema), errors=errors)

    def _validate_output_bindings(self, inverter):
        values = [value for value in (inverter.power_entity_id, inverter.energy_entity_id) if value]
        assigned = {row.get(key) for row in self._site["inverters"] for key in ("power_entity_id", "energy_entity_id") if row.get(key)}
        if len(values) != len(set(values)) or assigned.intersection(values):
            raise ValueError("a meter belongs to one physical output stage")

    async def async_step_inverter(self, user_input=None):
        errors = {}
        if self._edit_inverter is None:
            self._edit_inverter = self._pending_inverters.pop(0) if self._pending_inverters else {}
        if user_input is None and self._edit_inverter.get("output_type", "ac") == "dc":
            return await self.async_step_dc_inverter()
        if user_input is not None:
            if user_input.get("output_type", "ac") == "dc" and not user_input.get("remove"):
                # Changing the physical boundary requires fresh sensor choices.
                # Existing AC meter references never silently become DC labels.
                self._edit_inverter = {"id": user_input["id"], "output_type": "dc", "_flow_add_another": user_input.get("add_another", False)}
                return await self.async_step_dc_inverter()
            values = {key: value for key, value in user_input.items() if key not in ("add_another", "remove") and value not in (None, "")}
            try:
                if not user_input.get("remove"):
                    inv = InverterConfig(**values)
                    self._validate_output_bindings(inv)
                    if inv.id in [row["id"] for row in self._site["inverters"]]:
                        raise ValueError("duplicate")
                    self._site["inverters"].append(inv.to_dict())
                self._edit_inverter = None
                if self._pending_inverters or user_input.get("add_another"):
                    return await self.async_step_inverter()
                if not self._site["inverters"]:
                    errors["base"] = "at_least_one_inverter"
                else:
                    return await self.async_step_string()
            except (TypeError, ValueError):
                errors["base"] = "invalid_inverter"
        current = self._edit_inverter or {}
        schema = {}
        field(schema, "id", current.get("id", f"inverter_{len(self._site['inverters']) + 1}"), selector.TextSelector())
        field(schema, "output_type", "ac", selector.SelectSelector({"options": ["ac", "dc"], "translation_key": "output_type"}))
        field(schema, "max_ac_kw", current.get("max_ac_kw", 5), number(0.001, 1000, 0.001, "kW"))
        field(schema, "efficiency", current.get("efficiency", 0.96), number(0.01, 1, 0.001))
        field(schema, "power_entity_id", current.get("power_entity_id"), entity("power"), False)
        field(schema, "energy_entity_id", current.get("energy_entity_id"), entity("energy"), False)
        field(schema, "curtailed_entity_id", current.get("curtailed_entity_id"), selector.EntitySelector({"filter": [{"domain": "binary_sensor"}, {"domain": "input_boolean"}]}), False)
        field(schema, "add_another", current.get("_flow_add_another", False), selector.BooleanSelector())
        field(schema, "remove", False, selector.BooleanSelector())
        return self.async_show_form(step_id="inverter", data_schema=vol.Schema(schema), errors=errors)

    async def async_step_dc_inverter(self, user_input=None):
        """Configure a measured DC charge-controller output, without AC fields."""
        errors = {}
        if user_input is not None:
            if user_input.get("output_type", "dc") == "ac" and not user_input.get("remove"):
                self._edit_inverter = {"id": user_input["id"], "_flow_add_another": user_input.get("add_another", False)}
                return await self.async_step_inverter()
            values = {key: value for key, value in user_input.items()
                      if key not in ("add_another", "remove") and value not in (None, "")}
            try:
                if not user_input.get("remove"):
                    inv = InverterConfig(**{**values, "output_type": "dc"})
                    self._validate_output_bindings(inv)
                    if inv.id in [row["id"] for row in self._site["inverters"]]:
                        raise ValueError("duplicate")
                    self._site["inverters"].append(inv.to_dict())
                self._edit_inverter = None
                if self._pending_inverters or user_input.get("add_another"):
                    return await self.async_step_inverter()
                if not self._site["inverters"]:
                    errors["base"] = "at_least_one_inverter"
                else:
                    return await self.async_step_string()
            except (TypeError, ValueError):
                errors["base"] = "invalid_inverter"
        current = self._edit_inverter or {}
        schema = {}
        field(schema, "id", current.get("id", f"controller_{len(self._site['inverters']) + 1}"), selector.TextSelector())
        field(schema, "output_type", "dc", selector.SelectSelector({"options": ["ac", "dc"], "translation_key": "output_type"}))
        field(schema, "max_output_kw", current.get("max_output_kw", 5), number(0.001, 1000, 0.001, "kW"))
        field(schema, "dc_loss_fraction", current.get("dc_loss_fraction", 0), number(0, 0.99, 0.001))
        field(schema, "power_entity_id", current.get("power_entity_id"), entity("power"), False)
        field(schema, "energy_entity_id", current.get("energy_entity_id"), entity("energy"), False)
        field(schema, "curtailed_entity_id", current.get("curtailed_entity_id"), selector.EntitySelector({"filter": [{"domain": "binary_sensor"}, {"domain": "input_boolean"}]}), False)
        field(schema, "add_another", current.get("_flow_add_another", False), selector.BooleanSelector())
        field(schema, "remove", False, selector.BooleanSelector())
        return self.async_show_form(step_id="dc_inverter", data_schema=vol.Schema(schema), errors=errors)

    async def async_step_string(self, user_input=None):
        errors = {}
        if self._edit_string is None:
            self._edit_string = self._pending_strings.pop(0) if self._pending_strings else {}
        if user_input is not None:
            values = {key: value for key, value in user_input.items() if key not in ("add_another", "remove")}
            try:
                if not user_input.get("remove"):
                    horizon = values.get("horizon", [])
                    if isinstance(horizon, str):
                        horizon = json.loads(horizon)
                    values["horizon"] = horizon
                    parsed = {**values, "horizon": tuple(HorizonPoint(**point) for point in horizon)}
                    string = StringConfig(**parsed)
                    if string.id in [row["id"] for row in self._site["strings"]] or string.inverter_id not in [row["id"] for row in self._site["inverters"]]:
                        raise ValueError("duplicate or missing inverter")
                    self._site["strings"].append(values)
                self._edit_string = None
                if self._pending_strings or user_input.get("add_another"):
                    return await self.async_step_string()
                try:
                    return self._finish()
                except ValueError:
                    if not user_input.get("remove"):
                        self._site["strings"].pop()
                    self._edit_string = values
                    raise
            except (TypeError, ValueError, KeyError):
                errors["base"] = "invalid_string"
        current = self._edit_string or {}
        inverter_ids = [row["id"] for row in self._site["inverters"]]
        schema = {}
        field(schema, "id", current.get("id", f"string_{len(self._site['strings']) + 1}"), selector.TextSelector())
        field(schema, "inverter_id", current.get("inverter_id") if current.get("inverter_id") in inverter_ids else inverter_ids[0], selector.SelectSelector({"options": inverter_ids}))
        field(schema, "peak_kw", current.get("peak_kw", 5), number(0.001, 1000, 0.001, "kWp"))
        field(schema, "tilt_deg", current.get("tilt_deg", 30), number(0, 90, 0.1, "°"))
        field(schema, "azimuth_deg", current.get("azimuth_deg", 180), number(0, 359.9, 0.1, "°"))
        field(schema, "loss_fraction", current.get("loss_fraction", 0.14), number(0, 0.99, 0.001))
        field(schema, "temperature_coefficient", current.get("temperature_coefficient", -0.004), number(-0.02, 0, 0.0001, "1/°C"))
        field(schema, "horizon", current.get("horizon", []), selector.ObjectSelector({
            "multiple": True,
            "label_field": "azimuth_deg",
            "fields": {
                "azimuth_deg": {"label": "Azimuth (° N=0)", "required": True, "selector": number(0, 359.9, 0.1)},
                "elevation_deg": {"label": "Elevation (°)", "required": True, "selector": number(0, 90, 0.1)},
                "beam_transmission": {"label": "Transmission (0–1)", "required": False, "default": 0, "selector": number(0, 1, 0.01)},
            },
        }))
        field(schema, "add_another", False, selector.BooleanSelector())
        field(schema, "remove", False, selector.BooleanSelector())
        return self.async_show_form(step_id="string", data_schema=vol.Schema(schema), errors=errors)


class AdaptiveSolarConfigFlow(_Editor, config_entries.ConfigFlow, domain=DOMAIN):
    """Create a site without a YAML or JSON configuration file."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        self._initialize()
        return await self.async_step_site(user_input)

    def _finish(self):
        site = SiteConfig.from_dict(self._site)
        return self.async_create_entry(title=NAME, data={CONF_SITE: site.to_dict()})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AdaptiveSolarOptionsFlow()


class AdaptiveSolarOptionsFlow(_Editor, config_entries.OptionsFlow):
    """Revisit existing equipment and add or remove it during the same flow."""

    async def async_step_init(self, user_input=None):
        self._initialize(self.config_entry.options.get(CONF_SITE, self.config_entry.data[CONF_SITE]))
        return await self.async_step_site(user_input)

    def _finish(self):
        site = SiteConfig.from_dict(self._site)
        return self.async_create_entry(title="", data={CONF_SITE: site.to_dict()})
