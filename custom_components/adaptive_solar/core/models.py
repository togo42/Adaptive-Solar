"""Validated, HA-independent data contracts. All interval ends are exclusive."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone as dt_timezone
from math import isfinite
from numbers import Real
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MEASUREMENT_BOUNDARIES = {"ac": "ac_inverter_output", "dc": "dc_charge_controller_output"}
MAX_FORECAST_DAYS = 7


def finite_number(value, name: str, minimum=None, maximum=None) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f"{name} outside permitted range")
    return value


def utc_time(value: datetime, name="time") -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(dt_timezone.utc)


def _identifier(value, name="id"):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a nonempty string without surrounding whitespace")


def _optional_entity(value):
    if value is not None:
        _identifier(value, "entity_id")
        if "." not in value:
            raise ValueError("entity_id must include a domain")


def _number_fields(obj, specs):
    for name, low, high in specs:
        object.__setattr__(obj, name, finite_number(getattr(obj, name), name, low, high))


def _interval(obj):
    object.__setattr__(obj, "start", utc_time(obj.start, "start"))
    object.__setattr__(obj, "end", utc_time(obj.end, "end"))
    if obj.end <= obj.start:
        raise ValueError("end must follow start")


def _features(values):
    if not isinstance(values, Mapping):
        raise ValueError("features must be a mapping")
    result = {}
    for key, value in values.items():
        _identifier(key, "feature name")
        result[key] = finite_number(value, key)
    return result



def midpoint_lead_hours(issued_at: datetime, start: datetime, end: datetime) -> float:
    """Shared forecast-mean lead reference for archive, training and prediction."""
    issued_at, start, end = utc_time(issued_at), utc_time(start), utc_time(end)
    if end <= start:
        raise ValueError("lead interval must have positive duration")
    return max(0.0, ((start + (end - start) / 2) - issued_at).total_seconds() / 3600)

@dataclass(frozen=True)
class HorizonPoint:
    azimuth_deg: float
    elevation_deg: float
    beam_transmission: float = 0.0

    def __post_init__(self):
        _number_fields(self, (("azimuth_deg", 0, 360), ("elevation_deg", 0, 90),
                              ("beam_transmission", 0, 1)))
        object.__setattr__(self, "azimuth_deg", self.azimuth_deg % 360)


@dataclass(frozen=True)
class StringConfig:
    id: str
    inverter_id: str
    peak_kw: float
    tilt_deg: float
    azimuth_deg: float
    loss_fraction: float = 0.14
    temperature_coefficient: float = -0.004
    horizon: tuple[HorizonPoint, ...] = ()

    def __post_init__(self):
        _identifier(self.id)
        _identifier(self.inverter_id, "inverter_id")
        _number_fields(self, (("peak_kw", 0.000001, 1e6), ("tilt_deg", 0, 180),
            ("azimuth_deg", 0, 360), ("loss_fraction", 0, 1),
            ("temperature_coefficient", -0.02, 0)))
        object.__setattr__(self, "azimuth_deg", self.azimuth_deg % 360)
        horizon = tuple(self.horizon)
        if any(not isinstance(p, HorizonPoint) for p in horizon):
            raise ValueError("horizon must contain HorizonPoint")
        if len({p.azimuth_deg for p in horizon}) != len(horizon):
            raise ValueError("duplicate horizon azimuth")
        object.__setattr__(self, "horizon", tuple(sorted(horizon, key=lambda p: p.azimuth_deg)))


@dataclass(frozen=True)
class InverterConfig:
    """One measured output stage; legacy naming/positions stay AC-compatible.

    max_output_kw is the canonical stage limit after validation. max_ac_kw is
    an AC-only alias and must never name a DC limit. AC efficiency defaults to
    its historical 0.96; a DC stage has no AC efficiency. DC-stage losses are
    explicit additional output losses, separate from each string's losses.
    """
    id: str
    max_ac_kw: float | None = None
    efficiency: float | None = None
    power_entity_id: str | None = None
    energy_entity_id: str | None = None
    curtailed_entity_id: str | None = None
    output_type: str = "ac"
    max_output_kw: float | None = None
    dc_loss_fraction: float = 0.0
    measurement_valid_entity_id: str | None = None

    def __post_init__(self):
        _identifier(self.id)
        if not isinstance(self.output_type, str) or self.output_type not in {"ac", "dc"}:
            raise ValueError("output_type must be ac or dc")
        loss = finite_number(self.dc_loss_fraction, "dc_loss_fraction", 0, 1)
        object.__setattr__(self, "dc_loss_fraction", loss)
        if self.output_type == "dc":
            if self.max_ac_kw is not None:
                raise ValueError("max_ac_kw is an AC-only alias; a DC stage requires max_output_kw")
            if self.efficiency is not None:
                raise ValueError("efficiency is AC-only; use dc_loss_fraction for explicit DC-stage losses")
            cap = finite_number(self.max_output_kw, "max_output_kw", 0.000001, 1e6)
        else:
            if loss != 0:
                raise ValueError("dc_loss_fraction only applies to a DC output stage")
            legacy = None if self.max_ac_kw is None else finite_number(self.max_ac_kw, "max_ac_kw", 0.000001, 1e6)
            canonical = None if self.max_output_kw is None else finite_number(self.max_output_kw, "max_output_kw", 0.000001, 1e6)
            if legacy is None and canonical is None:
                raise ValueError("an AC output stage requires max_output_kw or legacy max_ac_kw")
            if legacy is not None and canonical is not None and legacy != canonical:
                raise ValueError("max_ac_kw and max_output_kw conflict")
            cap = legacy if canonical is None else canonical
            object.__setattr__(self, "max_ac_kw", cap)
            object.__setattr__(self, "efficiency", finite_number(
                0.96 if self.efficiency is None else self.efficiency, "efficiency", 0.000001, 1))
        object.__setattr__(self, "max_output_kw", cap)
        for entity in (self.power_entity_id, self.energy_entity_id, self.curtailed_entity_id, self.measurement_valid_entity_id):
            _optional_entity(entity)
        if self.measurement_valid_entity_id is not None and not self.measurement_valid_entity_id.startswith("binary_sensor."):
            raise ValueError("measurement_valid_entity_id must be a binary_sensor")
        if self.measurement_valid_entity_id is not None and self.measurement_valid_entity_id == self.curtailed_entity_id:
            raise ValueError("measurement validity and curtailment require distinct signals")

    @property
    def output_cap_w(self) -> float:
        """Configured nominal model limit at the declared output boundary.

        A fixed DC limit is not a claim of voltage-independent charger power.
        Battery voltage, storage behavior and operational control are separate.
        """
        return self.max_output_kw * 1000

    @property
    def measurement_boundary(self) -> str:
        """Shared physical output label for API/sensor/capture provenance."""
        return MEASUREMENT_BOUNDARIES[self.output_type]

    def to_dict(self) -> dict:
        """Keep old AC JSON/fingerprints exact; DC has no misleading AC keys."""
        entities = {"power_entity_id": self.power_entity_id, "energy_entity_id": self.energy_entity_id,
                    "curtailed_entity_id": self.curtailed_entity_id}
        if self.measurement_valid_entity_id is not None:
            # Unset preserves every legacy AC/DC serialized byte and digest.
            entities["measurement_valid_entity_id"] = self.measurement_valid_entity_id
        if self.output_type == "ac":
            return {"id": self.id, "max_ac_kw": self.max_ac_kw, "efficiency": self.efficiency, **entities}
        return {"id": self.id, "output_type": "dc", "max_output_kw": self.max_output_kw,
                "dc_loss_fraction": self.dc_loss_fraction, **entities}


@dataclass(frozen=True)
class SiteConfig:
    latitude: float
    longitude: float
    timezone: str
    strings: tuple[StringConfig, ...]
    inverters: tuple[InverterConfig, ...]
    weather_models: tuple[str, ...] = ("best_match",)
    forecast_days: int = MAX_FORECAST_DAYS
    temperature_entity_id: str | None = None
    wind_entity_id: str | None = None
    irradiance_entity_id: str | None = None

    def __post_init__(self):
        _number_fields(self, (("latitude", -90, 90), ("longitude", -180, 180)))
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, TypeError, ValueError) as err:
            raise ValueError("unknown site timezone") from err
        for name, cls in (("strings", StringConfig), ("inverters", InverterConfig)):
            values = tuple(getattr(self, name))
            if not values or any(not isinstance(v, cls) for v in values):
                raise ValueError(f"{name} must contain {cls.__name__}")
            if len({v.id for v in values}) != len(values):
                raise ValueError(f"duplicate {name} id")
            object.__setattr__(self, name, values)
        ids = {v.id for v in self.inverters}
        if {s.inverter_id for s in self.strings} != ids:
            raise ValueError("every string needs a configured inverter and every inverter a string")
        meters = {}
        for inverter in self.inverters:
            for entity in (inverter.power_entity_id, inverter.energy_entity_id):
                if entity is None:
                    continue
                if entity in meters and meters[entity] != inverter.id:
                    raise ValueError("power/energy measurement entities cannot be shared across output stages")
                meters[entity] = inverter.id
        models = tuple(self.weather_models)
        if not models or len(set(models)) != len(models):
            raise ValueError("weather_models must be nonempty and unique")
        for model in models:
            _identifier(model, "weather model")
        object.__setattr__(self, "weather_models", models)
        if isinstance(self.forecast_days, bool) or not isinstance(self.forecast_days, int) or not 1 <= self.forecast_days <= MAX_FORECAST_DAYS:
            raise ValueError(f"forecast_days must be an integer from 1 to {MAX_FORECAST_DAYS}")
        _optional_entity(self.temperature_entity_id)
        _optional_entity(self.wind_entity_id)
        _optional_entity(self.irradiance_entity_id)

    @classmethod
    def from_dict(cls, data: dict) -> SiteConfig:
        values = dict(data)
        values["strings"] = tuple(StringConfig(**{**s, "horizon": tuple(HorizonPoint(**p) for p in s.get("horizon", ()))}) for s in values["strings"])
        values["inverters"] = tuple(InverterConfig(**v) for v in values["inverters"])
        return cls(**values)

    def to_dict(self) -> dict:
        # JSON roundtripping uses lists and primitive values exclusively.
        result = asdict(self)
        result["strings"] = [{**s, "horizon": list(s["horizon"])} for s in result["strings"]]
        result["inverters"] = [inverter.to_dict() for inverter in self.inverters]
        result["weather_models"] = list(result["weather_models"])
        return result


@dataclass(frozen=True)
class WeatherPoint:
    """Radiation means and representative ambient source-interval conditions.

    Source radiation describes [start,end). Open-Meteo temperature, wind and
    cloud use a linear midpoint approximation from both valid hourly instant
    endpoints, not measured or exact hourly means. Other callers must supply
    equivalently aligned representative conditions. Cropping and instantaneous
    geometry proxies retain these as constant source-condition approximations;
    new cell boundaries do not imply newly interpolated subhour meteorology.
    """

    start: datetime
    end: datetime
    ghi_w_m2: float
    dni_w_m2: float
    dhi_w_m2: float
    temperature_c: float
    wind_m_s: float
    cloud_cover_pct: float

    def __post_init__(self):
        _interval(self)
        _number_fields(self, (("ghi_w_m2", 0, 2500), ("dni_w_m2", 0, 2000),
            ("dhi_w_m2", 0, 2500), ("temperature_c", -100, 80),
            ("wind_m_s", 0, 150), ("cloud_cover_pct", 0, 100)))


@dataclass(frozen=True)
class WeatherForecast:
    model: str
    issued_at: datetime
    points: tuple[WeatherPoint, ...]

    def __post_init__(self):
        _identifier(self.model, "model")
        object.__setattr__(self, "issued_at", utc_time(self.issued_at, "issued_at"))
        points = tuple(self.points)
        if any(not isinstance(p, WeatherPoint) for p in points):
            raise ValueError("points must contain WeatherPoint")
        points = tuple(sorted(points, key=lambda p: p.start))
        if any(a.end > b.start for a, b in zip(points, points[1:])):
            raise ValueError("overlapping weather intervals")
        object.__setattr__(self, "points", points)


@dataclass(frozen=True)
class Observation:
    time: datetime
    inverter_id: str
    power_w: float | None = None
    temperature_c: float | None = None
    wind_m_s: float | None = None
    curtailed: bool = False
    ghi_w_m2: float | None = None

    def __post_init__(self):
        object.__setattr__(self, "time", utc_time(self.time))
        _identifier(self.inverter_id, "inverter_id")
        for name, low, high in (("power_w", 0, 1e9), ("temperature_c", -100, 80), ("wind_m_s", 0, 150), ("ghi_w_m2", 0, 1600)):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, finite_number(getattr(self, name), name, low, high))
        if not isinstance(self.curtailed, bool):
            raise ValueError("curtailed must be boolean")


@dataclass(frozen=True)
class TrainingSample:
    issued_at: datetime
    start: datetime
    end: datetime
    observed_at: datetime
    inverter_id: str
    baseline_w: float
    actual_w: float
    features: dict[str, float]
    curtailed: bool = False

    def __post_init__(self):
        _interval(self)
        object.__setattr__(self, "issued_at", utc_time(self.issued_at, "issued_at"))
        object.__setattr__(self, "observed_at", utc_time(self.observed_at, "observed_at"))
        _identifier(self.inverter_id, "inverter_id")
        _number_fields(self, (("baseline_w", 0, 1e9), ("actual_w", 0, 1e9)))
        object.__setattr__(self, "features", _features(self.features))
        if not isinstance(self.curtailed, bool):
            raise ValueError("curtailed must be boolean")


@dataclass(frozen=True)
class ForecastPoint:
    start: datetime
    end: datetime
    inverter_id: str
    baseline_w: float
    power_w: float
    lower_w: float | None = None
    upper_w: float | None = None
    features: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        _interval(self)
        _identifier(self.inverter_id, "inverter_id")
        _number_fields(self, (("baseline_w", 0, 1e9), ("power_w", 0, 1e9)))
        for name in ("lower_w", "upper_w"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, finite_number(getattr(self, name), name, 0, 1e9))
        if (self.lower_w is None) != (self.upper_w is None):
            raise ValueError("both uncertainty bounds must be supplied together")
        if self.lower_w is not None and not self.lower_w <= self.power_w <= self.upper_w:
            raise ValueError("uncertainty bounds must bracket power")
        object.__setattr__(self, "features", _features(self.features))


@dataclass(frozen=True)
class ForecastResult:
    issued_at: datetime
    points: tuple[ForecastPoint, ...]
    model_status: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "issued_at", utc_time(self.issued_at, "issued_at"))
        points = tuple(self.points)
        if any(not isinstance(p, ForecastPoint) for p in points):
            raise ValueError("points must contain ForecastPoint")
        points = tuple(sorted(points, key=lambda p: (p.start, p.inverter_id)))
        for inverter in {p.inverter_id for p in points}:
            own = [p for p in points if p.inverter_id == inverter]
            if any(a.end > b.start for a, b in zip(own, own[1:])):
                raise ValueError("overlapping forecast intervals for inverter")
        object.__setattr__(self, "points", points)
        object.__setattr__(self, "model_status", dict(self.model_status))

    def energy_kwh(self, start: datetime, end: datetime, inverter_id: str | None = None) -> float | None:
        """Integrate only complete coverage; UTC durations preserve 23/25-hour days."""
        start, end = utc_time(start, "start"), utc_time(end, "end")
        if end <= start:
            raise ValueError("end must follow start")
        ids = {inverter_id} if inverter_id is not None else {p.inverter_id for p in self.points}
        if not ids:
            return None
        energy = 0.0
        for inverter in ids:
            cursor = start
            for point in self.points:
                if point.inverter_id != inverter or point.end <= cursor or point.start >= end:
                    continue
                if point.start > cursor:
                    return None
                stop = min(point.end, end)
                energy += point.power_w * (stop - cursor).total_seconds() / 3_600_000
                cursor = stop
                if cursor == end:
                    break
            if cursor != end:
                return None
        return energy

    def power_at(self, time: datetime, inverter_id: str | None = None) -> float | None:
        """Return the interval mean at time, never extrapolating across a gap."""
        time = utc_time(time)
        ids = {inverter_id} if inverter_id is not None else {p.inverter_id for p in self.points}
        if not ids:
            return None
        values = []
        for inverter in ids:
            point = next((p for p in self.points if p.inverter_id == inverter and p.start <= time < p.end), None)
            if point is None:
                return None
            values.append(point.power_w)
        return sum(values)
