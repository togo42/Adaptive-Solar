"""Bounded original-report history for the optional normalized power candidate."""
from __future__ import annotations

from datetime import timedelta

from .models import utc_time


class PowerObservationHistory:
    """Retain reports read at refresh, without manufacturing a measurement.

    No interpolation or persistence. Missing/invalid power or a changed validity
    phase discards the stage's preceding cohort before any new report is added.
    The caller supplies phase identity from independently monitored boundaries.
    """

    def __init__(self, minutes: int, max_reports: int = 128):
        self.window = timedelta(minutes=minutes)
        self.max_reports = max_reports
        self._rows = {}
        self._phases = {}

    def update(self, observations, now, phases):
        now = utc_time(now)
        incoming = tuple(observations)
        for stage, phase in phases.items():
            own = [obs for obs in incoming if obs.inverter_id == stage]
            valid = any(obs.power_w is not None and not obs.curtailed for obs in own) and not any(obs.curtailed for obs in own)
            if not valid or self._phases.get(stage) != phase:
                self._rows.pop(stage, None)
            self._phases[stage] = phase
            if not valid:
                continue
            rows = self._rows.setdefault(stage, {})
            for obs in own:
                if now - self.window <= obs.time <= now:
                    # Distinct environmental reports at the same instant are
                    # retained; a repeat of a power report replaces that report.
                    kind = tuple(name for name in ("power_w", "temperature_c", "wind_m_s", "ghi_w_m2") if getattr(obs, name) is not None)
                    rows[obs.time, kind] = obs
            rows = {key: obs for key, obs in rows.items() if now - self.window <= obs.time <= now}
            self._rows[stage] = dict(sorted(rows.items(), key=lambda item: item[0], reverse=True)[:self.max_reports])
        # Current invalidity/control decisions remain visible to the engine;
        # only valid original history is added, exact duplicate objects omitted.
        result = list(incoming)
        for rows in self._rows.values():
            for obs in rows.values():
                if obs not in result:
                    result.append(obs)
        return tuple(result)
