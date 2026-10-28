"""Direct-beam shading table per output stage and solar azimuth/elevation bin.

Learns effective near-field direct-beam transmittance on clear hours from global
irradiance and stage output power without attenuating diffuse irradiance.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from copy import deepcopy
import math
from statistics import median
from typing import Any, Mapping

from .models import finite_number, utc_time


def _non_empty_id(value: Any, name: str = "inverter_id") -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value

AZIMUTH_BIN_DEG = 10
ELEVATION_BIN_DEG = 5
MIN_SHADE_SAMPLES = 5
MAX_SHADE_SAMPLES = 24
SHADE_MAX_AGE = timedelta(days=45)
MIN_SHADE_DAYS = 2
MAX_SHADE_DAILY_MAD = 0.15
MAX_SHADE_DAILY_DRIFT = 0.10
MIN_SHADE_ELEVATION_DEG = 10.0
MIN_SHADE_CLEAR_SKY_W_M2 = 50.0
MIN_SHADE_CLEARNESS_INDEX = 0.6
MIN_SHADE_BEAM_SHARE = 0.4
MIN_SHADE_BEAM_ABS_W = 30.0
MIN_SHADE_BEAM_CAP_FRACTION = 0.03
MAX_SHADE_CAP_FRACTION = 0.98
MAX_SHADE_PAIR_SECONDS = 300.0
SHADE_BASELINE_TOLERANCE = 0.10
BEAM_SHADE_STORE_KEY = "beam_shade_v1"
BEAM_SHADE_REJECTION_REASONS = (
    "low_elevation",
    "low_clearness",
    "stale_or_unpaired",
    "low_beam",
    "at_cap",
    "curtailed_or_invalid",
    "no_reference",
    "insufficient_samples",
)


def shade_bin(azimuth_deg: float | None, elevation_deg: float | None) -> tuple[int, int] | None:
    """Map apparent solar position to (azimuth_bin_deg, elevation_bin_deg)."""
    if (azimuth_deg is None or elevation_deg is None
            or isinstance(azimuth_deg, bool) or isinstance(elevation_deg, bool)
            or not isinstance(azimuth_deg, (int, float)) or not isinstance(elevation_deg, (int, float))):
        return None
    azimuth = float(azimuth_deg)
    elevation = float(elevation_deg)
    if not math.isfinite(azimuth) or not math.isfinite(elevation) or elevation < 0.0 or elevation >= 90.0:
        return None
    az_index = math.floor(azimuth / AZIMUTH_BIN_DEG) % (360 // AZIMUTH_BIN_DEG)
    el_index = min((90 // ELEVATION_BIN_DEG) - 1, max(0, math.floor(elevation / ELEVATION_BIN_DEG)))
    return az_index * AZIMUTH_BIN_DEG, el_index * ELEVATION_BIN_DEG


def feature_solar_angles(features: Mapping[str, Any]) -> tuple[float, float] | None:
    """Extract (azimuth_deg, elevation_deg) from forecast or training features."""
    el = features.get("sun_elevation_deg")
    if isinstance(el, bool) or not isinstance(el, (int, float)) or not math.isfinite(float(el)):
        return None
    az = features.get("sun_azimuth_deg")
    if az is not None:
        if isinstance(az, bool) or not isinstance(az, (int, float)) or not math.isfinite(float(az)):
            return None
        return float(az) % 360.0, float(el)
    az_sin = features.get("sun_azimuth_sin")
    az_cos = features.get("sun_azimuth_cos")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in (az_sin, az_cos)):
        return None
    if float(az_sin) == 0.0 and float(az_cos) == 0.0:
        return None
    return round(math.degrees(math.atan2(float(az_sin), float(az_cos))) % 360.0, 9) % 360.0, float(el)


def feature_shade_bin(features: Mapping[str, Any]) -> tuple[int, int] | None:
    """Resolve the solar shade bin from feature dict, or None if unavailable."""
    angles = feature_solar_angles(features)
    return None if angles is None else shade_bin(*angles)


def utc_quarter_hour(at: datetime) -> datetime:
    """Floor an aware timestamp to its 15-minute UTC boundary."""
    stamp = utc_time(at, "at")
    return stamp.replace(minute=(stamp.minute // 15) * 15, second=0, microsecond=0)


def compute_beam_shade_factor(measured_power_w: float, p0_w: float, p1_w: float) -> float:
    """Compute clipped direct-beam factor t = clip((P_messung - P0) / (P1 - P0), 0, 1)."""
    measured = finite_number(measured_power_w, "measured_power_w", 0)
    p0 = finite_number(p0_w, "p0_w", 0)
    p1 = finite_number(p1_w, "p1_w", 0)
    if p1 <= p0:
        raise ValueError("p1_w must exceed p0_w")
    return min(1.0, max(0.0, (measured - p0) / (p1 - p0)))


def shade_factors_compatible(factor_a: float, factor_b: float) -> bool:
    """Return True when two beam-shade factors belong to the same baseline phase.

    Unshaded baselines (1.0) and released shaded baselines (< 1.0) are never
    mixed. Released shaded baselines tolerate bounded median drift up to
    SHADE_BASELINE_TOLERANCE so noisy partial-shading measurements do not
    invalidate historical training or validation support.
    """
    if (
        isinstance(factor_a, bool)
        or isinstance(factor_b, bool)
        or not isinstance(factor_a, (int, float))
        or not isinstance(factor_b, (int, float))
    ):
        return False
    a = float(factor_a)
    b = float(factor_b)
    if not (math.isfinite(a) and math.isfinite(b) and 0.0 <= a <= 1.0 and 0.0 <= b <= 1.0):
        return False
    a_unshaded = a >= 1.0 - 1e-6
    b_unshaded = b >= 1.0 - 1e-6
    if a_unshaded or b_unshaded:
        return a_unshaded and b_unshaded
    return abs(a - b) <= SHADE_BASELINE_TOLERANCE + 1e-9


class BeamShadeTable:
    """Bounded per-stage azimuth/elevation ring buffer with median release."""

    def __init__(self) -> None:
        self._bins: dict[str, dict[tuple[int, int], dict[datetime, tuple[datetime, datetime, float]]]] = {}
        self._released: dict[str, dict[tuple[int, int], tuple[tuple[datetime, float], ...]]] = {}
        self._legacy_unqualified: dict = {}

    def copy(self) -> BeamShadeTable:
        clone = BeamShadeTable()
        clone._bins = {
            inverter_id: {window: dict(samples) for window, samples in windows.items() if samples}
            for inverter_id, windows in self._bins.items()
            if windows
        }
        clone._released = {key: dict(value) for key, value in self._released.items()}
        clone._legacy_unqualified = deepcopy(self._legacy_unqualified)
        return clone

    def record(self, inverter_id: str, azimuth_deg: float, elevation_deg: float,
               at: datetime, factor: float, *, as_of: datetime | None = None) -> bool:
        inverter_id = _non_empty_id(inverter_id, "inverter_id")
        if isinstance(factor, bool) or not isinstance(factor, (int, float)) or not math.isfinite(float(factor)):
            raise ValueError("shade factor must be a finite number")
        clipped = min(1.0, max(0.0, float(factor)))
        window = shade_bin(azimuth_deg, elevation_deg)
        if window is None:
            return False
        at = utc_time(at)
        as_of = utc_time(as_of) if as_of is not None else datetime.now(timezone.utc)
        if at > as_of or as_of - at > SHADE_MAX_AGE:
            return False
        quarter = utc_quarter_hour(at)
        samples = self._bins.setdefault(inverter_id, {}).setdefault(window, {})
        # Keep the first qualified report in a quarter immutable. Replacing it
        # with a later report would rewrite the evidence visible to an older
        # as_of; versioning every report would defeat the bounded sample table.
        if quarter in samples:
            return False
        samples[quarter] = at, as_of, clipped
        if len(samples) > MAX_SHADE_SAMPLES:
            for oldest in sorted(samples)[:len(samples) - MAX_SHADE_SAMPLES]:
                samples.pop(oldest, None)
        self._refresh_release(inverter_id, window, as_of)
        return True

    @staticmethod
    def _as_of(as_of):
        return datetime.now(timezone.utc) if as_of is None else utc_time(as_of, "as_of")

    def _eligible(self, inverter_id, window, as_of):
        return {observed: factor for observed, available, factor
                in self._bins.get(inverter_id, {}).get(window, {}).values()
                if as_of - SHADE_MAX_AGE <= observed <= as_of and available <= as_of}

    def _assessment(self, inverter_id, window, as_of):
        samples = self._eligible(inverter_id, window, as_of)
        daily = {}
        for stamp, factor in samples.items():
            daily.setdefault(stamp.date(), []).append(factor)
        medians = [float(median(values)) for _, values in sorted(daily.items())]
        center = float(median(medians)) if medians else 1.0
        mad = float(median(abs(value - center) for value in medians)) if medians else 0.0
        reason = ("insufficient_samples" if len(samples) < MIN_SHADE_SAMPLES else
                  "insufficient_days" if len(medians) < MIN_SHADE_DAYS else
                  "unstable_daily_transmittance" if mad > MAX_SHADE_DAILY_MAD else None)
        return samples, medians, center, mad, reason

    def _refresh_release(self, inverter_id, window, as_of):
        _, _, center, _, reason = self._assessment(inverter_id, window, as_of)
        if reason is not None:
            return
        releases = self._released.setdefault(inverter_id, {})
        history = releases.get(window, ())
        previous = history[-1] if history else None
        if previous is not None:
            stamp, old = previous
            if stamp > as_of:
                return
            if as_of - stamp <= SHADE_MAX_AGE:
                days = max(0, (as_of.date() - stamp.date()).days)
                bound = days * MAX_SHADE_DAILY_DRIFT
                limited = max(old - bound, min(old + bound, center))
                # Preserve the release clock when the value did not change;
                # repeated polling must not stop time-based adaptation.
                if limited == old:
                    return
                center = limited
        releases[window] = (*history, (as_of, center))[-64:]

    def bin_samples(self, inverter_id: str, azimuth_deg: float | None,
                    elevation_deg: float | None, *, as_of: datetime | None = None) -> tuple[float, ...]:
        window = shade_bin(azimuth_deg, elevation_deg)
        samples = self._eligible(inverter_id, window, self._as_of(as_of))
        return tuple(value for _, value in sorted(samples.items()))

    def transmittance(self, inverter_id: str, azimuth_deg: float | None,
                      elevation_deg: float | None, *, as_of: datetime | None = None) -> float:
        as_of = self._as_of(as_of)
        window = shade_bin(azimuth_deg, elevation_deg)
        _, _, center, _, reason = self._assessment(inverter_id, window, as_of)
        if reason is not None:
            return 1.0
        previous = self._release_as_of(inverter_id, window, as_of)
        return 1.0 if previous is None else previous[1]

    def _release_as_of(self, inverter_id, window, as_of):
        history = self._released.get(inverter_id, {}).get(window, ())
        return next((entry for entry in reversed(history) if entry[0] <= as_of), None)

    def filled_bins(self, inverter_id: str, *, as_of: datetime | None = None) -> int:
        as_of = self._as_of(as_of)
        return sum(self._assessment(inverter_id, window, as_of)[-1] is None
                   and self._release_as_of(inverter_id, window, as_of) is not None
                   for window in self._bins.get(inverter_id, {}))

    def status_for(self, inverter_id: str, azimuth_deg: float | None = None,
                   elevation_deg: float | None = None, *, as_of: datetime | None = None,
                   last_rejection: str | None = None) -> dict[str, Any]:
        as_of = self._as_of(as_of)
        window = shade_bin(azimuth_deg, elevation_deg)
        samples, days, center, mad, reason = self._assessment(inverter_id, window, as_of)
        raw_count = len(self._bins.get(inverter_id, {}).get(window, {}))
        if reason is None and self._release_as_of(inverter_id, window, as_of) is None:
            reason = "no_release_available_at_as_of"
        return {
            "azimuth_bin_deg": window[0] if window is not None else None,
            "elevation_bin_deg": window[1] if window is not None else None,
            "transmittance": self.transmittance(inverter_id, azimuth_deg, elevation_deg, as_of=as_of),
            "candidate_transmittance": center, "daily_mad": mad,
            "unqualified_legacy_samples": sum(len(entries) for entries in self._legacy_unqualified.get(inverter_id, {}).values()),
            "samples": len(samples), "days": len(days), "excluded_time_samples": raw_count - len(samples),
            "newest_sample_age_days": (as_of - max(samples)).total_seconds() / 86400 if samples else None,
            "max_age_days": SHADE_MAX_AGE.days, "release_reason": reason or "qualified",
            "released": reason is None, "filled_bins": self.filled_bins(inverter_id, as_of=as_of),
            "last_rejection": last_rejection,
        }

    def to_dict(self) -> dict[str, Any]:
        inverters: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for inverter_id, windows in sorted(self._bins.items()):
            serialized_windows: dict[str, list[dict[str, Any]]] = {}
            for (az_bin, el_bin), samples in sorted(windows.items()):
                if not samples:
                    continue
                serialized_windows[f"{az_bin}:{el_bin}"] = [
                    {"quarter_hour": quarter.isoformat(), "observed_at": observed.isoformat(),
                     "available_at": available.isoformat(), "factor": factor}
                    for quarter, (observed, available, factor) in sorted(samples.items())
                ]
            if serialized_windows:
                inverters[inverter_id] = serialized_windows
        released = {inverter: {f"{az}:{el}": [{"at": stamp.isoformat(), "factor": factor}
                                               for stamp, factor in history]
                               for (az, el), history in windows.items()}
                    for inverter, windows in self._released.items()}
        result = {"schema": 3, "inverters": inverters, "released": released}
        if self._legacy_unqualified:
            result["unqualified_legacy"] = deepcopy(self._legacy_unqualified)
        return result

    @classmethod
    def from_dict(cls, data: Any, *,
                  inverter_ids: set[str] | tuple[str, ...] | None = None) -> BeamShadeTable:
        table = cls()
        if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] not in (1, 2, 3):
            return table
        # Legacy quarters do not prove when the underlying observation or its
        # receipt existed. Reading them as quarter-start observations backdates
        # evidence. Accept the old format by starting this optional table cold.
        raw_inverters = data.get("inverters")
        if not isinstance(raw_inverters, dict):
            return table
        allowed_ids = set(inverter_ids) if inverter_ids is not None else None
        valid_az = {index * AZIMUTH_BIN_DEG for index in range(360 // AZIMUTH_BIN_DEG)}
        valid_el = {index * ELEVATION_BIN_DEG for index in range(90 // ELEVATION_BIN_DEG)}
        try:
            parsed: dict[str, dict[tuple[int, int], dict[datetime, tuple[datetime, datetime, float]]]] = {}
            for inverter_id, raw_windows in raw_inverters.items():
                inverter_id = _non_empty_id(inverter_id, "inverter_id")
                if allowed_ids is not None and inverter_id not in allowed_ids:
                    raise ValueError("unknown inverter_id in shade table")
                if not isinstance(raw_windows, dict):
                    raise ValueError("invalid shade windows")
                stage_windows: dict[tuple[int, int], dict[datetime, tuple[datetime, datetime, float]]] = {}
                for raw_key, raw_entries in raw_windows.items():
                    if not isinstance(raw_key, str) or ":" not in raw_key or not isinstance(raw_entries, list):
                        raise ValueError("invalid shade bin entry")
                    az_text, el_text = raw_key.split(":", 1)
                    if not (az_text.isdigit() and el_text.isdigit()):
                        raise ValueError("non-integer bin key")
                    az_bin, el_bin = int(az_text), int(el_text)
                    if az_bin not in valid_az or el_bin not in valid_el:
                        raise ValueError("out-of-range shade bin")
                    if len(raw_entries) > MAX_SHADE_SAMPLES:
                        raise ValueError("shade bin exceeds sample bound")
                    samples: dict[datetime, tuple[datetime, datetime, float]] = {}
                    for entry in raw_entries:
                        if not isinstance(entry, dict) or not isinstance(entry.get("quarter_hour"), str):
                            raise ValueError("invalid shade sample")
                        stamp = utc_time(datetime.fromisoformat(entry["quarter_hour"]), "quarter_hour")
                        if stamp != utc_quarter_hour(stamp) or stamp in samples:
                            raise ValueError("unaligned or duplicate shade quarter-hour")
                        factor = finite_number(entry.get("factor"), "factor", 0, 1)
                        if data["schema"] < 3:
                            table._legacy_unqualified.setdefault(inverter_id, {}).setdefault(raw_key, []).append(
                                {"quarter_hour": stamp.isoformat(), "factor": factor})
                            continue
                        observed = utc_time(datetime.fromisoformat(entry["observed_at"]))
                        available = utc_time(datetime.fromisoformat(entry["available_at"]))
                        if utc_quarter_hour(observed) != stamp or available < observed:
                            raise ValueError("invalid shade sample chronology")
                        samples[stamp] = observed, available, factor
                    if samples:
                        stage_windows[(az_bin, el_bin)] = dict(sorted(samples.items()))
                if stage_windows:
                    parsed[inverter_id] = stage_windows
            table._bins = parsed
            if data["schema"] < 3:
                return table
            if "unqualified_legacy" in data:
                legacy = cls.from_dict({"schema": 1, "inverters": data["unqualified_legacy"]}, inverter_ids=inverter_ids)
                table._legacy_unqualified = legacy._legacy_unqualified
            if data["schema"] == 3:
                raw_released = data.get("released", {})
                if not isinstance(raw_released, dict):
                    raise ValueError("invalid shade release state")
                for inverter, windows in raw_released.items():
                    if inverter not in parsed or not isinstance(windows, dict):
                        raise ValueError("release has no sample bins")
                    for key, history in windows.items():
                        if not isinstance(key, str):
                            raise ValueError("invalid release window key")
                        az, el = (int(value) for value in key.split(":"))
                        window = az, el
                        if window not in parsed[inverter] or not isinstance(history, list) or not 1 <= len(history) <= 64:
                            raise ValueError("invalid release window")
                        entries = []
                        for release in history:
                            if not isinstance(release, dict):
                                raise ValueError("invalid release event")
                            stamp = utc_time(datetime.fromisoformat(release["at"]))
                            factor = finite_number(release.get("factor"), "release factor", 0, 1)
                            if entries and stamp < entries[-1][0]:
                                raise ValueError("unordered shade release events")
                            entries.append((stamp, factor))
                        table._released.setdefault(inverter, {})[window] = tuple(entries)
        except (KeyError, TypeError, ValueError, OverflowError):
            return cls()
        return table
