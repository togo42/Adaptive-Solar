"""Optional raw-diagnostic sampling; never meter processing or learned labels."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import math
from zoneinfo import ZoneInfo

from .core.models import utc_time

CONF_SOURCE_REPORT_PROFILE = "archive_source_report_profile"
FULL = "full"
NIGHT_SPARSE = "night_sparse_v1"
PROFILES = (FULL, NIGHT_SPARSE)
HEARTBEAT_SECONDS = 3600
DAY_EDGE_MINUTES = 90
MAX_TRACKED_ENTITIES = 256


@dataclass(frozen=True)
class NightPlan:
    start: datetime
    end: datetime
    windows: tuple[tuple[datetime, datetime], ...]


def calculate_night_plan(site, now):
    """Blocking SPA work, called only in HA's executor, at most once/local day.

    A missing rise/set pair on any of the three days means full export.
    Adjacent dates cover sites far from their civil timezone's solar longitude.
    """
    import pandas as pd
    import pvlib

    zone = ZoneInfo(site.timezone)
    day = utc_time(now).astimezone(zone).date()
    dates = [day + timedelta(days=offset) for offset in (-1, 0, 1)]
    times = pd.DatetimeIndex([datetime.combine(date, time(12), zone) for date in dates])
    events = pvlib.solarposition.sun_rise_set_transit_spa(times, site.latitude, site.longitude)
    if pd.isna(events.iloc[1].sunrise) or pd.isna(events.iloc[1].sunset):
        return None
    start = utc_time(datetime.combine(day, time(), zone))
    end = utc_time(datetime.combine(day + timedelta(days=1), time(), zone))
    margin = timedelta(minutes=DAY_EDGE_MINUTES)
    blocked = []
    for _, row in events.iterrows():
        if pd.isna(row.sunrise) or pd.isna(row.sunset):
            return None
        rise, setting = utc_time(row.sunrise.to_pydatetime(warn=False)), utc_time(row.sunset.to_pydatetime(warn=False))
        if rise >= setting:
            return None
        left, right = max(start, rise - margin), min(end, setting + margin)
        if left < right:
            blocked.append((left, right))
    cursor, windows = start, []
    for left, right in sorted(blocked):
        if left > cursor:
            windows.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < end:
        windows.append((cursor, end))
    return NightPlan(start, end, tuple(windows))


class SourceReportPolicy:
    """Bounded event-loop state; only real retained reports act as heartbeats."""

    def __init__(self, profile=FULL):
        self.profile = profile if profile in PROFILES else FULL
        self.attempted_day = None
        self.plan = None
        self.marker_ready = False
        self.skipped_reports = 0
        self._previous = {}

    def prepare(self, day, plan):
        self.attempted_day, self.plan, self.marker_ready = day, plan, False

    def marker(self):
        return {"schema": 1, "profile": self.profile,
                "scope": "raw_source_report_diagnostics_only_not_measurement_or_learning",
                "detail": "selected_unchanged_night_repeats_omitted_not_complete_report_cadence",
                "heartbeat_seconds": HEARTBEAT_SECONDS, "day_edge_minutes": DAY_EDGE_MINUTES,
                "measurement_and_control_reports": "full", "qualified_intervals": "full",
                "solar_definition": "SPA rise/set with90min full-detail margin; missing/polar=>full",
                "valid_from": self.plan.start.isoformat() if self.plan else None,
                "valid_to": self.plan.end.isoformat() if self.plan else None,
                "night_windows": [[a.isoformat(), b.isoformat()] for a, b in self.plan.windows] if self.plan else [],
                "fallback_full": self.plan is None}

    def status(self):
        return {"profile": self.profile, "ready": self.marker_ready and self.plan is not None,
                "heartbeat_seconds": HEARTBEAT_SECONDS, "day_edge_minutes": DAY_EDGE_MINUTES,
                "skipped_reports_since_restart": self.skipped_reports,
                "tracked_entities": len(self._previous),
                "window_valid_from": self.plan.start.isoformat() if self.plan else None,
                "window_valid_to": self.plan.end.isoformat() if self.plan else None,
                "scope": "diagnostics_only_native_measurement_and_learning_unchanged"}

    def _retain(self, payload):
        # A nonnumeric/invalid/nonzero transition must also preserve its recovery.
        self._previous.pop(payload.get("entity_id"), None)
        return True

    def keep(self, payload, roles, received):
        if self.profile == FULL:
            return True
        kinds = set(roles.values())
        if not kinds or kinds & {"energy", "control", "validity"}:
            return self._retain(payload)
        units = {"power": {"W", "kW", "MW"}, "temperature": {"°C", "°F", "K"},
                 "irradiance": {"W/m²", "W/m2", "kW/m²"},
                 "wind": {"m/s", "km/h", "mph", "kn"}}
        state, attrs = payload.get("state"), payload.get("attributes", {})
        if (isinstance(state, bool) or not kinds <= units.keys() or attrs.get("restored")
                or any(attrs.get("unit_of_measurement") not in units[kind] for kind in kinds)):
            return self._retain(payload)
        try:
            number = float(state)
            reported = payload["last_reported"]
            reported = datetime.fromisoformat(reported) if isinstance(reported, str) else reported
            age = (utc_time(received) - utc_time(reported)).total_seconds()
            if (not math.isfinite(number) or not 0 <= age <= (300 if "irradiance" in kinds else 900)
                    or ("power" in kinds and number != 0) or (number < 0 and "temperature" not in kinds)):
                return self._retain(payload)
            unit = attrs["unit_of_measurement"]
            if "temperature" in kinds:
                celsius = (number - 32) * 5 / 9 if unit == "°F" else number - 273.15 if unit == "K" else number
                if not -100 <= celsius <= 70:
                    return self._retain(payload)
            if "wind" in kinds and number * {"m/s": 1, "km/h": 1 / 3.6, "mph": 0.44704, "kn": 0.514444444}[unit] > 150:
                return self._retain(payload)
            if "irradiance" in kinds and number * (1000 if unit == "kW/m²" else 1) > 1600:
                return self._retain(payload)
        except (ValueError, TypeError, KeyError, OverflowError):
            return self._retain(payload)
        entity = payload["entity_id"]
        if entity not in self._previous and len(self._previous) >= MAX_TRACKED_ENTITIES:
            return self._retain(payload)
        fingerprint = (state, attrs.get("unit_of_measurement"), attrs.get("state_class"), attrs.get("restored"))
        night = bool(self.marker_ready and self.plan is not None and self.plan.start <= received < self.plan.end
                     and any(a <= received < b for a, b in self.plan.windows))
        previous = self._previous.get(entity)
        keep = (not night or previous is None or previous[0] != fingerprint or not previous[2]
                or not 0 <= (received - previous[1]).total_seconds() < HEARTBEAT_SECONDS)
        if keep:
            self._previous[entity] = fingerprint, received, night
        else:
            self.skipped_reports += 1
        return keep
