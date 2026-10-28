"""Behavioral chronological learning replay with original raw weather closure."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.adaptive_solar.archive_export import json_value, replay_events, software_provenance
from custom_components.adaptive_solar.core.archive import ArchiveJournal
from custom_components.adaptive_solar.core.engine import ForecastEngine
from custom_components.adaptive_solar.core.models import InverterConfig, Observation, SiteConfig, StringConfig
from custom_components.adaptive_solar.core.physics import clear_sky_ghi
from custom_components.adaptive_solar.core.shade_learning import ShadeLearningPolicy, evaluate_shade_step
from custom_components.adaptive_solar.core.shade_replay import ShadeCandidate, replay_shading
from custom_components.adaptive_solar.core.shading import BeamShadeTable
from custom_components.adaptive_solar.weather import parse_forecast
from tests.test_weather import payload as raw_weather

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def bundle(tmp_path, *, times=None, seed=None, blocked=False, future_ghi=False, weather_gap=False, state_padding=0):
    times = times or [NOW + timedelta(minutes=15 * i) for i in range(3)]
    site = SiteConfig(52.52, 13.41, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),),
                      (InverterConfig("i", 20, power_entity_id="sensor.power"),),
                      weather_models=("best_match",), irradiance_entity_id="sensor.ghi")
    journal = ArchiveJournal(tmp_path / "journal")
    table = seed.copy() if seed else BeamShadeTable()
    forecasts = []
    software = software_provenance()
    for sequence, now in enumerate(times, 1):
        now = now.astimezone(UTC)
        raw = raw_weather(start=now - timedelta(hours=1), count=5)
        if weather_gap:
            raw["hourly"]["shortwave_radiation"][2:] = [None] * 3
        weather = parse_forecast(raw, "best_match", now, site)
        receipt = journal.append("weather_response", {"model": "best_match", "status": "available", "raw_response": raw}, now)
        source_ghi = clear_sky_ghi(site, now) * .7
        ghi = None if future_ghi else source_ghi
        observations = (Observation(now, "i", power_w=1000),) + ((Observation(now, "i", ghi_w_m2=ghi),) if ghi is not None else ())
        stage_input = {"power_w": 1000., "power_time": now, "ghi_w_m2": ghi, "ghi_time": now if ghi is not None else None,
                       "curtailed_or_invalid": blocked}
        before = table.to_dict()
        decision = evaluate_shade_step(site, site.inverters[0], (weather,), now, observations, table, stage_input)
        snapshot = {}
        for entity_id, value, unit, role in (("sensor.power", 1000, "W", "power_i"),
                                            ("sensor.ghi", source_ghi, "W/m²", "irradiance")):
            snapshot[entity_id] = {"entity_id": entity_id, "state": str(value), "last_changed": now.isoformat(),
                                   "last_updated": now.isoformat(), "last_reported": now.isoformat(),
                                   "attributes": {"unit_of_measurement": unit},
                                   "quality": {role: {"status": "valid", "normalized_value": value}}}
            if future_ghi and role == "irradiance":
                snapshot[entity_id]["last_reported"] = (now + timedelta(minutes=1)).isoformat()
                snapshot[entity_id]["quality"][role] = {"status": "ignored:future", "normalized_value": None}
        learning = {"schema": 1, "session_id": "session-a", "step_sequence": sequence,
                    "previous_step_id": f"step-{sequence - 1}" if sequence > 1 else None,
                    "step_id": f"step-{sequence}", "evaluated_at": now,
                    "initial_state_source": "session_seed" if sequence == 1 else "previous_step",
                    "initial_state_scope": "unverified_preexisting_history",
                    "policy_version": ShadeLearningPolicy().version, "inputs": {"i": stage_input},
                    "decisions": {"i": decision}, "raw_state_snapshot": snapshot}
        payload = {"site": site.to_dict(), "weather": json_value((weather,)), "observations": json_value(observations),
                   "issued_at": now.isoformat(), "computed_at": now.isoformat(), "software": software,
                   "result": json_value(ForecastEngine(site, table).forecast((weather,), now, observations)),
                   "weather_receipt_ids": {"best_match": receipt["event_id"]}, "shade_learning": json_value(learning)}
        state = {"shading_before": before, "shading": table.to_dict(), "fit_samples": [], "fit_as_of": None}
        if state_padding:
            state["padding"] = "x" * state_padding
        import json

        for kind, value, received, identifier in replay_events(payload, state, now + timedelta(seconds=1)):
            row = journal.append(kind, json.loads(value), received, identifier)
            if kind == "forecast_issued":
                forecasts.append(row)
    rows = journal.page(limit=100)["events"]
    for event in [*forecasts, *rows]:
        event["source"] = "ha:test"
    return forecasts, rows


def strict_candidate():
    return ShadeCandidate("strict", "strict-v1", ShadeLearningPolicy(version="strict-v1", min_clearness_index=.8))


def test_continuous_replay_exact_decisions_and_independent_candidate_divergence(tmp_path):
    forecasts, rows = bundle(tmp_path)
    report = replay_shading(forecasts, rows, candidates=(strict_candidate(),))
    assert report["baseline"]["accepted"]
    assert all(row["baseline"]["decisions_match"] and row["baseline"]["state_match"] for row in report["steps"])
    assert any(row["baseline"]["decisions"]["i"]["accepted"] for row in report["steps"])
    assert all(not row["candidates"]["strict"]["decisions"]["i"]["accepted"] for row in report["steps"])
    assert report["steps"][-1]["candidates"]["strict"]["shading"] == {"schema": 1, "inverters": {}}
    assert report["accuracy_status"].startswith("unevaluated")
    assert report["residual_learning"] == "disabled_in_candidates"


def test_omitted_rejected_step_is_rejected_even_when_table_did_not_change(tmp_path):
    forecasts, rows = bundle(tmp_path, blocked=True)
    with pytest.raises(ValueError, match="step chain"):
        replay_shading([forecasts[0], forecasts[2]], rows)
    with pytest.raises(ValueError, match="step chain"):
        replay_shading(forecasts[1:], rows)


@pytest.mark.parametrize("mutation,error", [
    (lambda f: f[1].update(source="other"), "source"),
    (lambda f: f[1].update(generation="other"), "generation"),
    (lambda f: f[1]["payload"]["site"].update(latitude=1), "configuration"),
    (lambda f: f[1]["payload"]["software"].update(source_sha256="different"), "software"),
    (lambda f: f[1]["payload"]["shade_learning"].update(policy_version="unknown"), "policy"),
    (lambda f: f[1]["payload"]["shade_learning"].update(previous_step_id="missing"), "step chain"),
    (lambda f: f[1]["payload"]["shade_learning"].update(schema=True), "step chain"),
])
def test_session_identity_configuration_version_and_chain_are_strict(tmp_path, mutation, error):
    forecasts, rows = bundle(tmp_path)
    mutation(forecasts)
    with pytest.raises(ValueError, match=error):
        replay_shading(forecasts, rows)


def test_missing_original_weather_and_raw_measurements_fail_closed(tmp_path):
    forecasts, rows = bundle(tmp_path)
    with pytest.raises(ValueError, match="weather receipt"):
        replay_shading(forecasts, [row for row in rows if row["kind"] != "weather_response"])
    forecasts[0]["payload"]["shade_learning"]["raw_state_snapshot"].pop("sensor.power")
    with pytest.raises(ValueError, match="original raw"):
        replay_shading(forecasts, rows)


def test_future_observations_and_normalized_inputs_are_rejected(tmp_path):
    forecasts, rows = bundle(tmp_path)
    original = deepcopy(forecasts)
    forecasts[0]["payload"]["observations"][0]["time"] = (NOW + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="future observation"):
        replay_shading(forecasts, rows)
    forecasts = original
    forecasts[0]["payload"]["shade_learning"]["inputs"]["i"]["power_time"] = (NOW + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="raw source or cutoff"):
        replay_shading(forecasts, rows)


def test_future_seed_rejected_and_empty_candidate_does_not_inherit_old_seed(tmp_path):
    seed = BeamShadeTable()
    seed.record("i", 180, 30, NOW - timedelta(days=1), .3)
    forecasts, rows = bundle(tmp_path, seed=seed, blocked=True)
    report = replay_shading(forecasts, rows, initial_state="empty", candidates=(strict_candidate(),))
    assert report["baseline"]["accepted"]
    assert report["initial_state_scope"] == "observed_segment_only"
    assert report["steps"][0]["candidates"]["strict"]["shading"]["inverters"] == {}
    future = BeamShadeTable()
    future.record("i", 180, 30, NOW + timedelta(hours=1), .2)
    future_forecasts, future_rows = bundle(tmp_path / "future", seed=future)
    with pytest.raises(ValueError, match="future shade seed"):
        replay_shading(future_forecasts, future_rows)


@pytest.mark.parametrize("day", [(2026, 3, 29), (2026, 10, 25)])
def test_dst_transitions_keep_utc_step_chronology(tmp_path, day):
    start = datetime(*day, 0, 30, tzinfo=UTC)
    times = [(start + timedelta(minutes=30 * i)).astimezone(ZoneInfo("Europe/Berlin")) for i in range(5)]
    forecasts, rows = bundle(tmp_path, times=times)
    report = replay_shading(list(reversed(forecasts)), rows)
    assert report["baseline"]["accepted"]
    assert [datetime.fromisoformat(row["issued_at"]) for row in report["steps"]] == [t.astimezone(UTC) for t in times]


def test_multiple_sessions_require_explicit_choice_and_baseline_version_is_separate(tmp_path):
    forecasts, rows = bundle(tmp_path)
    other, other_rows = bundle(tmp_path / "other")
    for event in other:
        event["payload"]["shade_learning"]["session_id"] = "session-b"
    with pytest.raises(ValueError, match="multiple shade sessions"):
        replay_shading([*forecasts, *other], [*rows, *other_rows])
    report = replay_shading([*forecasts, *other], [*rows, *other_rows], session_id="session-a")
    assert len(report["steps"]) == 3
    for event in forecasts:
        event["payload"]["software"]["source_sha256"] = "old-code"
    report = replay_shading(forecasts, rows)
    assert not report["baseline"]["accepted"] and not report["baseline"]["software_match"]


def test_cli_uses_immutable_pin_and_writes_independent_policy_forecasts(tmp_path, monkeypatch):
    from custom_components.adaptive_solar.core.archive import ArchiveStore
    from scripts.capture_weather import flush_journal
    from scripts.replay_shading import main
    import json

    bundle(tmp_path)
    store = ArchiveStore(tmp_path / "archive")
    flush_journal(ArchiveJournal(tmp_path / "journal"), store, "ha:test")
    store.pin("shade-frozen")
    output = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["replay_shading.py", "--archive", str(tmp_path / "archive"),
                                     "--source", "ha:test", "--dataset", "shade-frozen", "--output", str(output),
                                     "--initial-state", "empty", "--candidate-min-clearness", ".8"])
    assert main() == 0
    records = [json.loads(line) for line in output.read_text().splitlines()]
    report = records.pop()
    assert report["record_type"] == "summary" and report["baseline"]["accepted"]
    assert set(report["candidate_versions"]) == {"shade_control", "clearness_candidate"}
    assert all(row["candidates"]["shade_control"]["result"]["points"] for row in records)
    assert report["dataset"] == "shade-frozen" and report["replay_script_sha256"]


def test_rejected_future_raw_report_is_preserved_without_admitting_it(tmp_path):
    forecasts, rows = bundle(tmp_path, future_ghi=True)
    report = replay_shading(forecasts, rows, candidates=(strict_candidate(),))
    assert report["baseline"]["accepted"]
    assert all(not row["baseline"]["decisions"]["i"]["accepted"] for row in report["steps"])
    assert all(row["baseline"]["decisions"]["i"]["input"]["ghi_time"] is None for row in report["steps"])


def test_missing_forecast_support_remains_unavailable_in_candidates(tmp_path):
    forecasts, rows = bundle(tmp_path, weather_gap=True)
    report = replay_shading(forecasts, rows, candidates=(strict_candidate(),))
    assert report["baseline"]["accepted"]
    assert all(not row["candidates"]["strict"]["result"].points for row in report["steps"])
    assert all(row["candidates"]["strict"]["support_status"].startswith("unavailable") for row in report["steps"])


def test_stream_consumes_one_step_at_a_time_and_finishes_with_summary(tmp_path):
    from custom_components.adaptive_solar.core.shade_replay import replay_shading_stream

    forecasts, rows = bundle(tmp_path)
    consumed = []

    def step_inputs():
        for event in forecasts:
            consumed.append(event["event_id"])
            yield event, rows

    stream = replay_shading_stream(step_inputs(), candidates=(strict_candidate(),))
    first = next(stream)
    assert first["record_type"] == "step" and len(consumed) == 1
    second = next(stream)
    assert second["step_sequence"] == 2 and len(consumed) == 2
    third = next(stream)
    assert third["step_sequence"] == 3 and len(consumed) == 3
    summary = next(stream)
    assert summary["record_type"] == "summary" and summary["baseline"]["accepted"]
    assert "steps" not in summary and summary["step_count"] == 3
    with pytest.raises(StopIteration):
        next(stream)


def test_cli_does_not_publish_partial_stream_after_later_missing_step(tmp_path, monkeypatch):
    from custom_components.adaptive_solar.core.archive import ArchiveStore
    from scripts.capture_weather import flush_journal
    from scripts import replay_shading as command

    bundle(tmp_path)
    store = ArchiveStore(tmp_path / "archive")
    flush_journal(ArchiveJournal(tmp_path / "journal"), store, "ha:test")
    store.pin("shade-frozen")
    original = command._dependencies

    def missing_step(*args):
        event, dependencies = original(*args)
        if event["payload"]["shade_learning"]["step_sequence"] == 3:
            event["payload"]["shade_learning"]["step_sequence"] = 4
        return event, dependencies

    monkeypatch.setattr(command, "_dependencies", missing_step)
    output = tmp_path / "report.jsonl"
    monkeypatch.setattr("sys.argv", ["replay_shading.py", "--archive", str(tmp_path / "archive"),
                                     "--source", "ha:test", "--dataset", "shade-frozen", "--output", str(output)])
    assert command.main() == 2
    assert not output.exists()
    assert not list(tmp_path.glob(".report.jsonl.*.tmp"))


@pytest.mark.parametrize("role", ["temperature", "wind"])
def test_all_configured_environment_sources_and_observation_closure_are_required(tmp_path, role):
    forecasts, rows = bundle(tmp_path)
    for event in forecasts:
        event["payload"]["site"][f"{role}_entity_id"] = f"sensor.{role}"
    with pytest.raises(ValueError, match="configured source"):
        replay_shading(forecasts, rows)
    first = forecasts[0]["payload"]
    unit, number, field = ("°C", 20, "temperature_c") if role == "temperature" else ("m/s", 2, "wind_m_s")
    first["shade_learning"]["raw_state_snapshot"][f"sensor.{role}"] = {
        "entity_id": f"sensor.{role}", "state": str(number), "last_reported": NOW.isoformat(),
        "last_changed": NOW.isoformat(), "last_updated": NOW.isoformat(), "attributes": {"unit_of_measurement": unit},
        "quality": {role: {"status": "valid", "normalized_value": number}}}
    first["observations"].append({"time": NOW.isoformat(), "inverter_id": "i", field: number + 1})
    with pytest.raises(ValueError, match="observation disagrees"):
        replay_shading(forecasts, rows)


async def test_native_capture_through_pinned_store_to_subprocess_streaming_cli(hass, tmp_path):
    import asyncio
    import json
    from pathlib import Path
    import sys
    from uuid import uuid4

    from freezegun import freeze_time
    from custom_components.adaptive_solar.core.archive import ArchiveStore
    from scripts.capture_weather import flush_journal
    from tests.test_shade_capture import configured

    hass.config.config_dir = str(tmp_path)
    instance = configured(hass)
    with freeze_time(NOW, real_asyncio=True):
        raw = raw_weather(start=NOW - timedelta(hours=1), count=6)
        weather = parse_forecast(raw, "best_match", NOW, instance.site)
        identifier = str(uuid4())
        instance.export.record("weather_response", {"model": "best_match", "status": "available", "raw_response": raw},
                               NOW, identifier)
        instance.client.receipt_ids = {"best_match": identifier}
        instance.client.async_forecasts.return_value = (weather,)
        instance.async_start_tracking()
        instance.async_commit_setup()
        for offset in (0, 15):
            with freeze_time(NOW + timedelta(minutes=offset), real_asyncio=True):
                hass.states.async_set("sensor.power", "1000", {"unit_of_measurement": "W"})
                hass.states.async_set("sensor.ghi", "600", {"unit_of_measurement": "W/m²"})
                hass.states.async_set("sensor.temp", "20", {"unit_of_measurement": "°C"})
                hass.states.async_set("sensor.wind", "3", {"unit_of_measurement": "m/s"})
                await instance._async_update_data()
        await instance.export.page()
        await instance.async_close()
    store = ArchiveStore(tmp_path / "store")
    await hass.async_add_executor_job(flush_journal, instance.export.journal, store, "ha:native")
    await hass.async_add_executor_job(store.pin, "native-frozen")
    output = tmp_path / "native-replay.jsonl"
    process = await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).parents[1] / "scripts/replay_shading.py"),
        "--archive", str(tmp_path / "store"), "--source", "ha:native", "--dataset", "native-frozen",
        "--output", str(output), "--initial-state", "empty", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, (stdout.decode(), stderr.decode())
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert [row["step_sequence"] for row in records[:-1]] == [1, 2]
    assert records[-1]["record_type"] == "summary" and records[-1]["baseline"]["accepted"]
    assert set(records[0]["candidates"]) == {"shade_control", "clearness_candidate"}


def test_compressed_state_is_bounded_by_declared_decoded_bytes_before_reconstruction(tmp_path, monkeypatch, capsys):
    from custom_components.adaptive_solar.core.archive import ArchiveStore
    from scripts.capture_weather import flush_journal
    from scripts.replay_shading import main

    bundle(tmp_path, state_padding=2 * 1024 * 1024)
    store = ArchiveStore(tmp_path / "archive")
    flush_journal(ArchiveJournal(tmp_path / "journal"), store, "ha:test")
    store.pin("shade-frozen")
    output = tmp_path / "report.jsonl"
    monkeypatch.setattr("sys.argv", ["replay_shading.py", "--archive", str(tmp_path / "archive"), "--source", "ha:test",
                                     "--dataset", "shade-frozen", "--output", str(output), "--max-decoded-mib", "1"])
    assert main() == 2
    assert "decompressed/serialized byte budget" in capsys.readouterr().err
    assert not output.exists()


def test_cli_publishes_only_after_scoped_pin_readers_close_successfully(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from custom_components.adaptive_solar.core.archive import ArchiveStore
    from scripts.capture_weather import flush_journal
    from scripts.replay_shading import main

    bundle(tmp_path)
    store = ArchiveStore(tmp_path / "archive")
    flush_journal(ArchiveJournal(tmp_path / "journal"), store, "ha:test")
    store.pin("shade-frozen")
    original = ArchiveStore.reference_reader

    @contextmanager
    def changed_pin(self, **kwargs):
        with original(self, **kwargs) as resolve:
            yield resolve
        raise ValueError("pin changed before publication")

    monkeypatch.setattr(ArchiveStore, "reference_reader", changed_pin)
    output = tmp_path / "report.jsonl"
    monkeypatch.setattr("sys.argv", ["replay_shading.py", "--archive", str(tmp_path / "archive"), "--source", "ha:test",
                                     "--dataset", "shade-frozen", "--output", str(output)])
    assert main() == 2
    assert not output.exists()
    assert not list(tmp_path.glob(".report.jsonl.*.tmp"))
