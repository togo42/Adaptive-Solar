"""Frozen candidate evaluation preserves causality, missingness and true day lengths."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from zoneinfo import ZoneInfo

import pytest

from custom_components.adaptive_solar.archive_export import json_value
from custom_components.adaptive_solar.core.archive import canonical_bytes
from custom_components.adaptive_solar.core.support_evaluation import SCHEMA, evaluate_support, frozen_from_events
from scripts.analyze_learning_support import main
from tests.test_archive_replay import forecast_bundle
from tests.test_learning import EPOCH, synthetic_days


def frozen(*, trained=True):
    samples = synthetic_days(count=28) if trained else []
    target = synthetic_days(first=28, count=1)[0]
    return {"schema": SCHEMA, "timezone": "UTC", "as_of": (EPOCH + timedelta(days=30)).isoformat(),
            "fits": [{"id": "fit1", "fit_as_of": (EPOCH + timedelta(days=28)).isoformat(),
                      "output_caps_w": {"wr": 2000}, "fit_samples": json_value(samples)}],
            "tasks": [{"fit_id": "fit1", "issued_at": target.issued_at.isoformat(),
                       "start": target.start.isoformat(), "end": target.end.isoformat(),
                       "inverter_id": "wr", "baseline_w": target.baseline_w, "features": dict(target.features)}],
            "actuals": [{"inverter_id": "wr", "start": target.start.isoformat(), "end": target.end.isoformat(),
                         "observed_at": target.observed_at.isoformat(), "power_w": target.actual_w,
                         "qualified": True, "quality_source": "synthetic complete interval", "curtailed": False}]}


def test_three_arms_share_actuals_and_ood_falls_back_without_uncertainty():
    payload = frozen()
    task = payload["tasks"][0]
    task["baseline_w"] = task["features"]["baseline_w"] = 1900
    task["features"]["cloud_cover_pct"] = 100
    report = evaluate_support(payload)
    row = report["tasks"][0]
    assert row["support"]["supported"] is False
    assert row["predictions"]["residual"]["status"].startswith("residual")
    assert row["predictions"]["residual"]["power_w"] != 1900
    assert row["predictions"]["guarded_residual"]["power_w"] == 1900
    assert row["predictions"]["guarded_residual"]["lower_w"] is None
    assert report["evaluation"]["paired_intervals"] == 1
    assert report["statistical_acceptance"] == "not_evaluated"
    assert report["supports_activation"] is report["operational_use"] is False
    assert report["evaluation"]["energy_pairs"] == []
    assert report["scope"] == "residual_stage_before_power_nowcast"


@pytest.mark.parametrize("kind", ["absent", "unqualified", "future", "curtailed", "partial", "conflict"])
def test_missing_or_unqualified_actuals_cannot_create_scores(kind):
    payload = frozen(trained=False)
    actual = payload["actuals"][0]
    if kind == "absent":
        payload["actuals"] = []
    elif kind == "unqualified":
        actual["qualified"] = False
    elif kind == "future":
        actual["observed_at"] = (EPOCH + timedelta(days=31)).isoformat()
    elif kind == "curtailed":
        actual["curtailed"] = True
    elif kind == "partial":
        actual["end"] = (datetime.fromisoformat(actual["end"]) - timedelta(minutes=1)).isoformat()
    else:
        payload["actuals"].append({**actual, "power_w": actual["power_w"] + 10})
    report = evaluate_support(payload)
    assert report["evaluation"]["paired_intervals"] == 0
    assert all(value["overall"]["mae_w"] is None for value in report["evaluation"]["scores"].values())
    assert report["evaluation"]["energy_pairs"] == []


@pytest.mark.parametrize("change", ["fit_after_issue", "future_fit_label", "wrong_lead", "task_before_issue"])
def test_time_leakage_fails_before_scoring(change):
    payload = frozen()
    if change == "fit_after_issue":
        payload["fits"][0]["fit_as_of"] = (EPOCH + timedelta(days=29)).isoformat()
    elif change == "future_fit_label":
        payload["fits"][0]["fit_samples"][0]["observed_at"] = (EPOCH + timedelta(days=29)).isoformat()
    elif change == "wrong_lead":
        payload["tasks"][0]["features"]["lead_hours"] += 1
    else:
        payload["tasks"][0]["issued_at"] = payload["tasks"][0]["end"]
    with pytest.raises(ValueError):
        evaluate_support(payload)


def test_duplicates_do_not_multiply_tasks_or_evidence_and_conflicts_fail():
    payload = frozen(trained=False)
    original = evaluate_support(payload)
    payload["tasks"] *= 2
    payload["actuals"] *= 2
    payload["fits"] *= 2
    duplicated = evaluate_support(payload)
    for key in ("evaluation", "strata", "task_count", "actual_counts", "daily_wins"):
        assert duplicated[key] == original[key]
    payload["tasks"] = [payload["tasks"][0], deepcopy(payload["tasks"][0])]
    payload["tasks"][1]["baseline_w"] += 1
    with pytest.raises(ValueError, match="conflicting forecast"):
        evaluate_support(payload)


def test_late_forecast_receipt_is_diagnostic_only():
    payload = frozen(trained=False)
    payload["tasks"][0]["available_at"] = payload["tasks"][0]["end"]
    report = evaluate_support(payload)
    assert report["task_count"] == 1
    assert report["scoring_exclusions"] == {"not_prospective_at_receipt": 1}
    assert report["evaluation"]["paired_intervals"] == 0


@pytest.mark.parametrize("month,day,hours", [(3, 29, 23), (10, 25, 25)])
def test_daily_energy_requires_the_complete_real_dst_day(month, day, hours):
    zone = ZoneInfo("Europe/Berlin")
    start = datetime(2026, month, day, tzinfo=zone).astimezone(UTC)
    end = (datetime(2026, month, day, tzinfo=zone) + timedelta(days=1)).astimezone(UTC)
    issue = start - timedelta(hours=2)
    payload = frozen(trained=False)
    payload.update(timezone="Europe/Berlin", as_of=(end + timedelta(hours=1)).isoformat(), tasks=[], actuals=[])
    payload["fits"][0]["fit_as_of"] = issue.isoformat()
    for hour in range(hours):
        begin, stop = start + timedelta(hours=hour), start + timedelta(hours=hour + 1)
        features = {**synthetic_days(count=1)[0].features, "baseline_w": 1000, "lead_hours": hour + 2.5}
        payload["tasks"].append({"fit_id": "fit1", "issued_at": issue.isoformat(), "start": begin.isoformat(),
                                 "end": stop.isoformat(), "inverter_id": "wr", "baseline_w": 1000, "features": features})
        payload["actuals"].append({"start": begin.isoformat(), "end": stop.isoformat(), "inverter_id": "wr",
                                   "power_w": 900, "observed_at": (stop + timedelta(minutes=5)).isoformat(),
                                   "qualified": True, "quality_source": "synthetic complete DST hour"})
    report = evaluate_support(payload)
    assert report["evaluation"]["paired_intervals"] == hours
    energy = report["evaluation"]["energy_pairs"][0]
    assert energy["actual_kwh"] == pytest.approx(hours * .9)
    assert energy["forecasts_kwh"]["physics"] == hours
    payload["actuals"].pop(hours // 2)
    incomplete = evaluate_support(payload)
    assert incomplete["evaluation"]["energy_pairs"] == []


def test_declared_schedule_keeps_missing_forecast_tasks_visible():
    payload = frozen(trained=False)
    task = payload["tasks"][0]
    window = {"cutoff": task["issued_at"], **{k: task[k] for k in ("start", "end", "inverter_id")}}
    payload["schedule"] = [window, {**window, "start": task["end"],
                                     "end": (datetime.fromisoformat(task["end"]) + timedelta(hours=1)).isoformat()}]
    report = evaluate_support(payload)
    assert report["evaluation"]["expected_intervals"] == 2
    assert report["evaluation"]["paired_intervals"] == 1
    assert report["schedule_status"] == "caller_declared_not_independently_verified"
    assert sum(row["scheduled_tasks"] for row in report["strata"].values()) == 2
    assert report["strata"]["wr|unknown|6-24h"]["available_tasks"] == 0


def test_schedule_selects_same_origin_for_global_stratum_and_bounds():
    payload = frozen()
    target = synthetic_days(first=28, count=1)[2]
    first = payload["tasks"][0]
    first.update(start=target.start.isoformat(), end=target.end.isoformat(), baseline_w=target.baseline_w,
                 features=dict(target.features))
    payload["actuals"][0].update(start=target.start.isoformat(), end=target.end.isoformat(),
                                  power_w=target.actual_w, observed_at=target.observed_at.isoformat())
    second = deepcopy(first)
    second["issued_at"] = (datetime.fromisoformat(first["issued_at"]) + timedelta(hours=1)).isoformat()
    second["features"]["lead_hours"] -= 1
    second["features"]["cloud_cover_pct"] = 100  # Deliberately outside support.
    payload["tasks"].append(second)
    payload["schedule"] = [{"cutoff": first["issued_at"], **{key: first[key] for key in ("start", "end", "inverter_id")}}]
    report = evaluate_support(payload)
    assert report["task_count"] == 2
    assert report["evaluation"]["paired_intervals"] == 1
    assert len(report["strata"]) == 1
    stratum = next(iter(report["strata"].values()))
    assert stratum["scheduled_tasks"] == stratum["paired_tasks"] == 1
    assert stratum["guard_fallback_tasks"] == 0
    assert stratum["calibration"]["residual"]["paired_bounded_tasks"] == 1
    for arm in ("physics", "residual", "guarded_residual"):
        assert stratum["scores"][arm] == report["evaluation"]["scores"][arm]["overall"]
    payload["schedule"][0]["cutoff"] = second["issued_at"]
    newer = evaluate_support(payload)
    stratum = next(iter(newer["strata"].values()))
    assert stratum["guard_fallback_tasks"] == 1
    assert stratum["calibration"]["guarded_residual"]["paired_bounded_tasks"] == 0


def test_declared_schedule_cannot_split_native_feature_support():
    payload = frozen(trained=False)
    task = payload["tasks"][0]
    payload["schedule"] = [{"cutoff": task["issued_at"], "start": task["start"], "inverter_id": "wr",
                            "end": (datetime.fromisoformat(task["end"]) - timedelta(minutes=30)).isoformat()}]
    with pytest.raises(ValueError, match="complete exported target"):
        evaluate_support(payload)


def test_ghi_bounds_and_status_are_withheld_like_the_engine():
    from tests.test_learning_regimes import regimes

    _, ghi = regimes(count=28)
    _, targets = regimes(first=28, count=1)
    target = targets[0]
    payload = frozen()
    payload["fits"][0]["fit_samples"] = json_value(ghi)
    payload["tasks"] = [{"fit_id": "fit1", "issued_at": target.issued_at.isoformat(),
                         "start": target.start.isoformat(), "end": target.end.isoformat(),
                         "inverter_id": "wr", "baseline_w": target.baseline_w, "features": target.features}]
    report = evaluate_support(payload)
    for arm in ("residual", "guarded_residual"):
        prediction = report["tasks"][0]["predictions"][arm]
        assert prediction["lower_w"] is prediction["upper_w"] is None
        assert prediction["status"] != "residual_empirical_calibration"


def test_native_export_preserves_provenance_and_requires_original_dependencies(tmp_path):
    event, events, _ = forecast_bundle(tmp_path)
    as_of = event["received_at"]
    payload = frozen_from_events(events, [event["event_id"]], as_of=as_of)
    report = evaluate_support(payload)
    assert report["task_count"] > 0
    assert report["evaluation"]["paired_intervals"] == 0
    assert report["provenance"][0]["archived_software"] == event["payload"]["software"]
    assert report["provenance"][0]["exact_original_replay_acceptance"] == "not_evaluated"
    with pytest.raises(ValueError, match="missing"):
        frozen_from_events([event], [event["event_id"]], as_of=as_of)
    damaged = deepcopy(events)
    damaged[0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum"):
        frozen_from_events(damaged, [event["event_id"]], as_of=as_of)


@pytest.mark.parametrize("sources", [("a", "b"), ("a", None), (None, None)])
def test_native_identical_sites_cannot_merge_different_or_unknown_sources(tmp_path, sources):
    events, identifiers, receipts = [], [], []
    for index, source in enumerate(sources):
        event, rows, _ = forecast_bundle(tmp_path / str(index))
        events.extend({**row, "source": source} if source is not None else row for row in rows)
        identifiers.append(event["event_id"])
        receipts.append(event["received_at"])
    with pytest.raises(ValueError, match="different archive sources"):
        frozen_from_events(events, identifiers, as_of=max(receipts))


def test_cli_reads_frozen_input_and_never_overwrites_input_or_symlink(tmp_path, monkeypatch):
    source, output = tmp_path / "input.json", tmp_path / "report.json"
    source.write_text(json.dumps(frozen(trained=False)))
    before = source.read_bytes()
    monkeypatch.setattr("sys.argv", ["analyze_learning_support.py", "--input", str(source), "--output", str(output)])
    assert main() == 0
    report = json.loads(output.read_text())
    assert report["input_file_sha256"]["input"] == hashlib.sha256(before).hexdigest()
    assert report["analysis_script_sha256"]
    for bad_output in (source, tmp_path / "link.json"):
        if bad_output != source:
            bad_output.symlink_to(source)
        monkeypatch.setattr("sys.argv", ["analyze_learning_support.py", "--input", str(source), "--output", str(bad_output)])
        assert main() == 2
        assert source.read_bytes() == before


def test_cli_native_export_does_not_touch_input_directory(tmp_path, monkeypatch):
    event, events, _ = forecast_bundle(tmp_path)
    source, output = tmp_path / "events.json", tmp_path / "report.json"
    source.write_bytes(canonical_bytes(events))
    before = source.read_bytes()
    monkeypatch.setattr("sys.argv", ["analyze_learning_support.py", "--events-json", str(source), "--event-id", event["event_id"],
                                     "--as-of", event["received_at"], "--output", str(output)])
    assert main() == 0
    assert source.read_bytes() == before
    report = json.loads(output.read_text())
    assert report["actual_counts"] == {}
    assert report["provenance"][0]["event_id"] == event["event_id"]


@pytest.mark.parametrize("empty", [True, False])
def test_native_failed_attempt_never_reuses_older_success_at_later_cutoff(tmp_path, empty):
    """Keep an empty whole result, or one missing stage beside a healthy stage."""
    event, events, _ = forecast_bundle(tmp_path)
    site = event["payload"]["site"]
    second = {**site["inverters"][0], "id": "other"}
    site["inverters"].append(second)
    site["strings"].append({**site["strings"][0], "id": "other-string", "inverter_id": "other"})
    points = event["payload"]["result"]["points"]
    points.extend({**deepcopy(point), "inverter_id": "other"} for point in list(points))
    event["sha256"] = hashlib.sha256(canonical_bytes({k: v for k, v in event.items() if k != "sha256"})).hexdigest()
    later = deepcopy(event)
    later.update(event_id="later-missing-stage", sequence=event["sequence"] + 1,
                 received_at=(datetime.fromisoformat(event["received_at"]) + timedelta(minutes=1)).isoformat())
    later["payload"]["result"]["points"] = [] if empty else [p for p in later["payload"]["result"]["points"] if p["inverter_id"] == "other"]
    later["sha256"] = hashlib.sha256(canonical_bytes({k: v for k, v in later.items() if k != "sha256"})).hexdigest()
    events.append(later)
    target = next(p for p in points if p["inverter_id"] == "i" and p["start"] > later["received_at"])
    start, end = (datetime.fromisoformat(target[k]) for k in ("start", "end"))
    actuals = [{"start": target["start"], "end": target["end"], "inverter_id": stage, "power_w": target["baseline_w"],
                "observed_at": end.isoformat(), "qualified": True, "quality_source": "synthetic full interval"}
               for stage in ("i", "other")]
    schedule = [{"cutoff": receipt, "start": target["start"], "end": target["end"], "inverter_id": stage}
                for receipt in (event["received_at"], later["received_at"]) for stage in ("i", "other")]
    frozen_input = frozen_from_events(events, [event["event_id"], later["event_id"]],
                                      as_of=end.isoformat(), actuals=actuals, schedule=schedule)
    assert len(frozen_input["attempts"]) == 4
    report = evaluate_support(frozen_input)
    assert report["evaluation"]["expected_intervals"] == 4
    assert report["evaluation"]["paired_intervals"] == (2 if empty else 3)
    assert sum(row["scheduled_tasks"] for row in report["strata"].values()) == 4
    unknown = [s for s in report["strata"].values() if s["regime"] == "unknown"]
    assert sum(s["scheduled_tasks"] for s in unknown) == (2 if empty else 1)
    assert all(s["available_tasks"] == s["paired_tasks"] == 0 for s in unknown)
    assert all(s["calibration"]["residual"]["paired_bounded_tasks"] == 0 for s in unknown)


@pytest.mark.parametrize("change", [{"inverter_id": "unknown"}, {"available_at": "2999-01-01T00:00:00+00:00"}, {"extra": True}])
def test_attempt_inventory_requires_known_stage_and_honest_availability(change):
    payload = frozen(trained=False)
    task = payload["tasks"][0]
    payload["attempts"] = [{"issued_at": task["issued_at"], "available_at": task["issued_at"], "inverter_id": "wr", **change}]
    with pytest.raises(ValueError, match="attempt"):
        evaluate_support(payload)
