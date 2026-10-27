"""Actual repeated archive selection must preserve usable cross-cell issues."""
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.adaptive_solar.const import MAX_ARCHIVE_ROWS
from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator, EnergyIntervalTracker, join_training
from custom_components.adaptive_solar.core.learning import LEAD_BIN_NAMES, feature_regime, lead_bin, _target_hours, _weights
from custom_components.adaptive_solar.core.models import ForecastPoint, ForecastResult, InverterConfig, SiteConfig, StringConfig, midpoint_lead_hours

TARGET = datetime(2026, 6, 8, 10, tzinfo=UTC)


class ArchiveHarness:
    """Run the actual selector and live meter coalescer without persistence I/O."""

    _archive_result = AdaptiveSolarCoordinator._archive_result
    _append_interval = AdaptiveSolarCoordinator._append_interval

    def __init__(self, stages):
        self.site = SiteConfig(52, 13, "UTC",
            tuple(StringConfig(f"s{i}", f"i{i}", 5, 30, 180) for i in range(stages)),
            tuple(InverterConfig(f"i{i}", 5) for i in range(stages)), forecast_days=7)
        self.archive, self.intervals = [], []
        self.daily_snapshots, self.daily_snapshot_provenance = {}, {}
        self._interval_latest = {}
        self._measurement_part_count = self._history_revision = 0

    def _archive_comparison(self, result):
        """Separate optional comparison I/O is irrelevant to training selection."""


@pytest.mark.parametrize("stages", [1, 4, 7])
@pytest.mark.parametrize("near_target_ghi", [False, True])
def test_repeated_five_minute_archives_preserve_nwp_and_ghi_endpoint_labels(stages, near_target_ghi):
    instance, raw = ArchiveHarness(stages), []
    issue = TARGET - timedelta(days=6)
    while issue <= TARGET + timedelta(hours=3):
        points = []
        for offset in range(4):
            start = TARGET + timedelta(hours=offset)
            if issue > start:
                continue
            ghi = bool(near_target_ghi and start - issue < timedelta(minutes=90))
            baseline = 2000 + offset * 100
            features = {"baseline_w": baseline, "sun_elevation_deg": 45,
                "lead_hours": midpoint_lead_hours(issue, start, start + timedelta(hours=1)),
                "ghi_regime": float(ghi), "ghi_nowcast_gain": 1.1 if ghi else 1.0,
                "ghi_observation_age_seconds": 1.0 if ghi else 0.0, "beam_shade_factor": 1.0}
            point = ForecastPoint(start, start + timedelta(hours=1), "i0", baseline, baseline, features=features)
            points.append(point)
            raw.append({"issued_at": issue.isoformat(), "start": point.start.isoformat(),
                        "end": point.end.isoformat(), "inverter_id": "i0", "baseline_w": baseline,
                        "power_w": baseline, "features": features})
        instance._archive_result(ForecastResult(issue, tuple(points)))
        issue += timedelta(minutes=5)
    tracker = EnergyIntervalTracker()
    start = TARGET + timedelta(minutes=2)
    tracker.record("i0", start, 0, True, 5000)
    measured = []
    for index in range(1, 37):
        end = start + timedelta(minutes=index * 5)
        interval = tracker.record("i0", end, index / 12, True, 5000)
        measured.append(interval)
        instance._append_interval(interval)
    cutoff = start + timedelta(hours=3)
    unbounded = join_training(raw, measured, as_of=cutoff)
    bounded = join_training(instance.archive, instance.intervals, as_of=cutoff)
    def counts(samples):
        return Counter((feature_regime(row.features), LEAD_BIN_NAMES[lead_bin(row.features["lead_hours"])])
                       for row in samples)
    expected, accepted = counts(unbounded), counts(bounded)
    assert set(accepted) == set(expected)
    assert all(accepted["nwp", bucket] >= 3 for bucket in LEAD_BIN_NAMES)
    if near_target_ghi:
        assert accepted["ghi", "0-6h"] >= 3
    assert _target_hours(bounded) == 3
    assert sum(_weights(bounded)) == pytest.approx(10800)
    # Kept samples must be genuine original issues and numerical integrals.
    originals = {(row.start, row.end, row.issued_at, feature_regime(row.features)): row for row in unbounded}
    for row in bounded:
        original = originals[row.start, row.end, row.issued_at, feature_regime(row.features)]
        assert row.actual_w == pytest.approx(original.actual_w)
        assert row.baseline_w == pytest.approx(original.baseline_w)
    assert len(instance.archive) <= 4 * (12 if stages >= 7 else 24)


@pytest.mark.parametrize("stages,paired_slots", [(1, 2), (4, 2), (7, 1)])
def test_pair_origin_budget_leaves_room_for_28_long_summer_days_and_future_targets(stages, paired_slots):
    # Each source cell belongs to at most two neighbor pairs. Five NWP bins
    # plus the bounded near-term GHI bin use the same hard global row budget.
    rows_per_cell = 2 * paired_slots * 6
    target_cells = stages * 16 * (28 + 6)
    assert rows_per_cell * target_cells <= MAX_ARCHIVE_ROWS
