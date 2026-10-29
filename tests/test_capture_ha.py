"""Private prospective capture: mocked HA WS, strict scopes, no live HA calls."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from freezegun import freeze_time
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/capture_ha.py"
spec = importlib.util.spec_from_file_location("capture_ha_under_test", SCRIPT)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)
T = datetime(2026, 10, 25, 0, tzinfo=timezone.utc)
TOKEN = "TEST_SECRET_NEVER_PERSIST_THIS"


def mapping(entries=("first", "second")):
    return capture.parse_mapping({"mappings": [{"inverter_id": "roof", "source": "helios", "entry_ids": list(entries)}]})


def snapshot(values=None):
    return {"wh_hours": values if values is not None else {T.isoformat(): 100.0, (T + timedelta(hours=2)).isoformat(): 0.0}}


@pytest.mark.parametrize("offset", [0, 330, 345, -210, 570, .5])
def test_collector_joins_equivalent_utc_hours_across_offset_representations(offset):
    original = {"wh_hours": {T.astimezone(timezone(timedelta(minutes=offset))).isoformat(): 100.25}}
    inputs = {"first": original, "second": {"wh_hours": {T.isoformat(): 200.75}}}
    result = capture.build_capture(inputs, mapping(), T)
    group, = result["groups"]
    assert group["status"] == "available" and len(group["records"]) == 1
    assert group["records"][0]["start"] == T.isoformat()
    assert group["records"][0]["end"] == (T + timedelta(hours=1)).isoformat()
    assert group["records"][0]["energy_wh"] == 301
    assert result["snapshots"] == inputs


@pytest.mark.parametrize("offset", [330, 345, -210, 570, .5])
def test_collector_rejects_local_whole_hour_off_the_utc_grid(offset):
    stamp = datetime(2026, 6, 1, 15, tzinfo=timezone(timedelta(minutes=offset))).isoformat()
    with pytest.raises(capture.CaptureError):
        capture._hours({"wh_hours": {stamp: 100}})


def test_collector_rejects_duplicate_absolute_hour_in_different_offsets():
    with pytest.raises(capture.CaptureError):
        capture._hours({"wh_hours": {T.isoformat(): 100,
                       T.astimezone(timezone(timedelta(minutes=345))).isoformat(): 200}})


class FakeWS:
    def __init__(self, result, states=None, *, auth_ok=True, fail_request=False, block=False):
        self.responses = [{"type": "auth_required", "ha_version": "2026.10.3"},
                          {"type": "auth_ok" if auth_ok else "auth_invalid", "message": TOKEN},
                          {"id": 1, "type": "result", "success": not fail_request, "result": result},
                          {"id": 2, "type": "result", "success": True, "result": states}]
        self.sent = []
        self.block = block

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def receive_json(self):
        if self.block:
            await asyncio.Future()
        expected = self.sent[-1].get("id") if self.sent and "id" in self.sent[-1] else None
        if expected == 2 and self.responses[0].get("id") == 1:
            self.responses.pop(0)
        return self.responses.pop(0)

    async def send_json(self, value):
        self.sent.append(value)


class FakeSession:
    def __init__(self, ws):
        self.ws = ws
        self.calls = []

    def ws_connect(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.ws


def test_hour_sums_require_complete_identical_keys_and_preserve_gaps():
    result = {"first": snapshot(), "second": snapshot(), "unrequested_private": snapshot()}
    captured = capture.build_capture(result, mapping(), T)
    assert set(captured["snapshots"]) == {"first", "second"}
    group = captured["groups"][0]
    assert group["status"] == "available"
    assert len(group["records"]) == 2  # Missing middle hour is never inserted.
    assert group["records"][0]["power_w"] == 200
    assert group["records"][0]["energy_wh"] == 200
    assert group["records"][1]["power_w"] == 0  # An explicit zero survives.
    assert all(row["issued_at"] == T.isoformat() for row in group["records"])
    assert captured["snapshots"]["first"] == result["first"]


@pytest.mark.parametrize("result,status", [
    ({"first": snapshot()}, "missing_entries"),
    ({"first": snapshot(), "second": snapshot({})}, "incompatible_hours"),
    ({"first": snapshot(), "second": {"wh_hours": {T.isoformat(): True}}}, "invalid_entries"),
    ({"first": snapshot(), "second": {"wh_hours": {"2026-10-25T01:00:00": 10}}}, "invalid_entries"),
    ({"first": snapshot(), "second": {"wh_hours": {T.isoformat(): -1}}}, "invalid_entries"),
    ({"first": snapshot(), "second": {"watts": {T.isoformat(): 100}}}, "invalid_entries"),
    ({"first": snapshot({}), "second": snapshot({})}, "empty_forecast"),
])
def test_missing_or_malformed_contributions_never_become_partial_sum(result, status):
    group = capture.build_capture(result, mapping(), T)["groups"][0]
    assert group["status"] == status
    assert group["records"] == []


def test_repeated_dst_hour_is_two_real_utc_intervals():
    hours = {"2026-10-25T02:00:00+02:00": 100, "2026-10-25T02:00:00+01:00": 200}
    group = capture.build_capture({"first": snapshot(hours)}, mapping(("first",)), T)["groups"][0]
    assert [row["power_w"] for row in group["records"]] == [100, 200]
    assert group["records"][0]["end"] == group["records"][1]["start"]


@pytest.mark.parametrize("rows", [
    [{"inverter_id": "roof", "source": "unknown", "entry_ids": ["a"]}],
    [{"inverter_id": "roof", "source": "helios", "entry_ids": ["a", "a"]}],
    [{"inverter_id": "a", "source": "helios", "entry_ids": ["shared"]}, {"inverter_id": "b", "source": "helios", "entry_ids": ["shared"]}],
    [{"inverter_id": "roof", "source": "helios", "quality_entity_id": "sensor.quality"}],
    [{"inverter_id": "roof", "source": "adaptive", "entry_ids": ["a"], "quality_entity_id": "sensor.quality"}],
])
def test_invalid_mapping_and_invented_disaggregation_rejected(rows):
    with pytest.raises(capture.CaptureError):
        capture.parse_mapping({"mappings": rows})


async def test_one_energy_request_all_ids_local_scope_filter_and_receipt_clock(tmp_path, capsys):
    ws = FakeWS({"first": snapshot(), "second": snapshot(), "unrequested": {"wh_hours": {}}})
    client = FakeSession(ws)
    before = datetime.now(timezone.utc)
    captured = await capture.capture_forecasts("https://ha.example.invalid", TOKEN, mapping(), session=client)
    after = datetime.now(timezone.utc)
    assert before <= datetime.fromisoformat(captured["retrieved_at"]) <= after
    assert ws.sent == [{"type": "auth", "access_token": TOKEN}, {"id": 1, "type": "energy/solar_forecast"}]
    assert len(client.calls) == 1
    assert client.calls[0][0] == "wss://ha.example.invalid/api/websocket"
    output = tmp_path / "capture.jsonl"
    capture.append_capture(output, captured)
    text = output.read_text()
    assert TOKEN not in text and "ha.example.invalid" not in text and "unrequested" not in text
    assert capsys.readouterr().out == ""
    assert capsys.readouterr().err == ""


def quality_state(entity="sensor.roof_quality", forecast=None):
    return {"entity_id": entity, "state": "complete", "last_updated": T.isoformat(),
            "attributes": {"other_private_attribute": "must not persist", "forecast": forecast if forecast is not None else [
                {"start": T.isoformat(), "end": (T + timedelta(minutes=30)).isoformat(),
                 "power_w": 1234.56, "energy_kwh": 0.6173, "lower_w": None, "upper_w": None}]}}


async def test_per_inverter_quality_curve_uses_get_states_without_disaggregation():
    config = capture.parse_mapping({"mappings": [
        {"inverter_id": "roof", "source": "helios", "entry_ids": ["first"]},
        {"inverter_id": "roof", "source": "adaptive", "quality_entity_id": "sensor.roof_quality"}]})
    ws = FakeWS({"first": snapshot()}, [quality_state(), quality_state("sensor.foreign")])
    captured = await capture.capture_forecasts("http://ha.example.invalid", TOKEN, config, session=FakeSession(ws))
    assert ws.sent[-2:] == [{"id": 1, "type": "energy/solar_forecast"}, {"id": 2, "type": "get_states"}]
    assert set(captured["entity_snapshots"]) == {"sensor.roof_quality"}
    assert "other_private_attribute" not in json.dumps(captured)
    group = next(row for row in captured["groups"] if row["source"] == "adaptive")
    assert group["status"] == "available"
    record = group["records"][0]
    assert record["power_w"] == 1234.56
    assert record["energy_wh"] == pytest.approx(617.3)
    assert datetime.fromisoformat(record["end"]) - datetime.fromisoformat(record["start"]) == timedelta(minutes=30)


async def test_quality_only_capture_skips_energy_request():
    config = capture.parse_mapping({"mappings": [{"inverter_id": "roof", "source": "adaptive", "quality_entity_id": "sensor.roof_quality"}]})
    ws = FakeWS({}, [quality_state()])
    captured = await capture.capture_forecasts("http://ha.example.invalid", TOKEN, config, session=FakeSession(ws))
    assert ws.sent[-1] == {"id": 2, "type": "get_states"}
    assert len(ws.sent) == 2
    assert captured["commands"] == ["get_states"]
    assert captured["issued_at"] == captured["retrieved_at"]


@pytest.mark.parametrize("states,status", [([], "missing_entity"),
    ([{**quality_state(), "state": "unavailable"}], "unavailable_entity"),
    ([quality_state(forecast=[{"start": T.isoformat(), "end": (T + timedelta(hours=1)).isoformat(), "power_w": 1000, "energy_kwh": 2}])], "invalid_entity")])
def test_quality_missing_unavailable_and_inconsistent_energy_have_no_records(states, status):
    config = capture.parse_mapping({"mappings": [{"inverter_id": "roof", "source": "adaptive", "quality_entity_id": "sensor.roof_quality"}]})
    groups, _ = capture.quality_groups(states, config, T)
    assert groups[0]["status"] == status
    assert groups[0]["records"] == []


@pytest.mark.parametrize("options", [{"auth_ok": False}, {"fail_request": True}, {"block": True}])
async def test_auth_errors_and_timeout_are_sanitized_and_never_append(tmp_path, capsys, options):
    ws = FakeWS({"first": snapshot()}, **options)
    with pytest.raises(capture.CaptureError) as error:
        await capture.capture_forecasts("http://private-ha.invalid", TOKEN, mapping(("first",)), timeout=0.02, session=FakeSession(ws))
    assert TOKEN not in str(error.value)
    assert "private-ha" not in str(error.value)
    assert not list(tmp_path.iterdir())
    assert capsys.readouterr().out == ""


async def test_reflected_secret_in_selected_snapshot_is_never_persisted():
    ws = FakeWS({"first": {"wh_hours": {TOKEN: 100}}})
    with pytest.raises(capture.CaptureError, match="private connection"):
        await capture.capture_forecasts("http://ha.example.invalid", TOKEN, mapping(("first",)), session=FakeSession(ws))


def test_append_preserves_replays_exclusive_lock_and_partial_prior_record(tmp_path):
    output = tmp_path / "private.jsonl"
    payload = capture.build_capture({"first": snapshot()}, mapping(("first",)), T)
    capture.append_capture(output, payload)
    capture.append_capture(output, payload)
    assert len(output.read_text().splitlines()) == 2
    assert output.stat().st_mode & 0o777 == 0o600
    original = output.read_bytes()
    with output.open("ab") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(capture.CaptureError, match="locked"):
            capture.append_capture(output, payload)
    assert output.read_bytes() == original
    output.write_bytes(b'{"unfinished":')
    with pytest.raises(capture.CaptureError, match="incomplete"):
        capture.append_capture(output, payload)
    assert output.read_bytes() == b'{"unfinished":'


def test_cli_missing_token_and_outside_private_scope_fail_without_secret_logs(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "data").mkdir()
    shutil.copyfile(SCRIPT, root / "scripts/capture_ha.py")
    shutil.copyfile(SCRIPT.with_name("replay_paths.py"), root / "scripts/replay_paths.py")
    config = root / "data/map.json"
    config.write_text(json.dumps({"mappings": list(mapping(("first",)))}))
    env = {**os.environ, "HA_URL": "https://private-ha.invalid"}
    env.pop("HA_TOKEN", None)
    output = root / "data/capture.jsonl"
    run = subprocess.run([sys.executable, str(root / "scripts/capture_ha.py"), "--config", str(config), "--output", str(output)],
                         env=env, capture_output=True, text=True, timeout=10)
    assert run.returncode == 2
    assert "HA_TOKEN is required" in run.stderr
    assert "private-ha" not in run.stderr and not output.exists()
    run = subprocess.run([sys.executable, str(root / "scripts/capture_ha.py"), "--config", str(config), "--output", str(root / "public.jsonl")],
                         env={**env, "HA_TOKEN": TOKEN}, capture_output=True, text=True, timeout=10)
    assert run.returncode == 2
    assert "inside ignored data/" in run.stderr
    assert TOKEN not in run.stderr + run.stdout


def test_unavailable_groups_keep_own_real_receipt_without_records():
    energy = capture.build_capture({}, mapping(("missing",)), T)["groups"][0]
    assert energy["records"] == []
    assert energy["issued_at"] == energy["retrieved_at"] == T.isoformat()
    config = capture.parse_mapping({"mappings": [{"inverter_id": "roof", "source": "adaptive", "quality_entity_id": "sensor.roof_quality"}]})
    quality = capture.quality_groups([], config, T + timedelta(seconds=1))[0][0]
    assert quality["records"] == []
    assert quality["issued_at"] == quality["retrieved_at"] == (T + timedelta(seconds=1)).isoformat()


def wh_state(entity, hours, state="100"):
    return {"entity_id": entity, "state": state, "last_updated": T.isoformat(),
            "attributes": {"wh_period": hours, "watts": {"DO_NOT_INTEGRATE": 999999}, "other_private": "ignore"}}


def om_mapping():
    return capture.parse_mapping({"mappings": [{"inverter_id": "roof", "source": "open_meteo",
        "wh_period_entities": [["sensor.east_today", "sensor.east_tomorrow"], ["sensor.west_today", "sensor.west_tomorrow"]]}]})


def test_open_meteo_day_union_then_array_sum_preserves_native_wh_dst_and_missing_days():
    today = {"2026-10-25T02:00:00+02:00": 100.25, "2026-10-25T02:00:00+01:00": 150.75}
    tomorrow = {"2026-10-26T01:00:00+01:00": 200}
    states = [wh_state("sensor.east_today", today), wh_state("sensor.west_today", today),
              wh_state("sensor.east_tomorrow", tomorrow), wh_state("sensor.west_tomorrow", tomorrow),
              wh_state("sensor.unrequested", {T.isoformat(): 999999})]
    groups, snapshots = capture.native_wh_state_groups(states, om_mapping(), T)
    group = groups[0]
    assert group["status"] == "available"
    assert [row["energy_wh"] for row in group["records"]] == [200.5, 301.5, 400]
    assert len(group["records"]) == 3  # No missing hour/day receives a fabricated zero.
    assert group["records"][0]["end"] == group["records"][1]["start"]
    assert set(snapshots) == {"sensor.east_today", "sensor.east_tomorrow", "sensor.west_today", "sensor.west_tomorrow"}
    assert "watts" not in json.dumps(snapshots)
    assert all(row["power_w"] == row["energy_wh"] for row in group["records"])


@pytest.mark.parametrize("problem,status", [("missing", "missing_entity"), ("unavailable", "unavailable_entity"),
    ("incompatible", "incompatible_hours"), ("malformed", "invalid_entity")])
def test_open_meteo_missing_contribution_never_becomes_partial_array_total(problem, status):
    hours = {T.isoformat(): 100}
    states = [wh_state(entity, hours) for entity in ("sensor.east_today", "sensor.east_tomorrow", "sensor.west_today", "sensor.west_tomorrow")]
    if problem == "missing":
        states.pop()
    elif problem == "unavailable":
        states[-1]["state"] = "unavailable"
    elif problem == "incompatible":
        for state in states[2:]:
            state["attributes"]["wh_period"] = {(T + timedelta(hours=1)).isoformat(): 100}
    else:
        states[-1]["attributes"]["wh_period"] = {T.isoformat(): True}
    groups, _ = capture.native_wh_state_groups(states, om_mapping(), T)
    assert groups[0]["status"] == status
    assert groups[0]["records"] == []


def reference_mapping():
    return capture.parse_mapping({"mappings": [{"inverter_id": "roof", "source": "helios",
                                               "reference_entry_ids": ["first", "second"]}]})


def bridge_response(wh=None, domain="helios_forecast", status="available"):
    return {"domain": domain, "status": status, "forecast": snapshot() if wh is None else wh, "retrieved_at": T.isoformat()}


@pytest.mark.parametrize("response,status", [
    ({"first": bridge_response(), "second": bridge_response()}, "available"),
    ({"first": bridge_response()}, "missing_entries"),
    ({"first": bridge_response(), "second": bridge_response(domain="open_meteo_solar_forecast")}, "invalid_entries"),
    ({"first": bridge_response(), "second": bridge_response(status="timeout")}, "missing_entries"),
    ({"first": bridge_response(), "second": bridge_response({"wh_hours": {T.isoformat(): False}})}, "invalid_entries"),
    (None, "missing_entries"),
])
def test_reference_bridge_requires_native_schema_domain_and_all_contributions(response, status):
    received = T + timedelta(hours=1)
    groups, _ = capture.reference_groups(response, reference_mapping(), received)
    assert groups[0]["status"] == status
    assert groups[0]["issued_at"] == groups[0]["retrieved_at"] == received.isoformat()
    if status == "available":
        assert groups[0]["records"][0]["energy_wh"] == 200
    else:
        assert groups[0]["records"] == []


class ReferenceWS(FakeWS):
    def __init__(self, success=True):
        super().__init__({})
        self.responses = self.responses[:2] + [{"id": 3, "type": "result", "success": success,
            "result": {"context": {}, "response": {"first": bridge_response(), "second": bridge_response()}}}]


@pytest.mark.parametrize("success", [True, False])
async def test_collector_calls_only_fixed_readonly_bridge_and_preserves_missing_service_issue(success):
    ws = ReferenceWS(success)
    before = datetime.now(timezone.utc)
    captured = await capture.capture_forecasts("http://ha.example.invalid", TOKEN, reference_mapping(), session=FakeSession(ws))
    after = datetime.now(timezone.utc)
    assert ws.sent[-1] == {"id": 3, "type": "call_service", "domain": "adaptive_solar",
        "service": "get_reference_forecasts", "service_data": {"config_entry_ids": ["first", "second"]}, "return_response": True}
    group = captured["groups"][0]
    assert before <= datetime.fromisoformat(group["retrieved_at"]) <= after
    assert group["issued_at"] == group["retrieved_at"]
    assert group["status"] == ("available" if success else "missing_entries")
    if not success:
        assert group["records"] == []


@pytest.mark.parametrize("selector", [
    {"wh_period_entities": [["sensor.a"], ["sensor.a"]]},
    {"reference_entry_ids": [f"id-{i}" for i in range(17)]},
])
def test_new_selectors_reject_duplicates_and_oversized_requests(selector):
    with pytest.raises(capture.CaptureError):
        capture.parse_mapping({"mappings": [{"source": "open_meteo", "inverter_id": "roof", **selector}]})


def dc_mapping(**overrides):
    row = {"inverter_id": "dc_group", "source": "open_meteo",
           "wh_period_15m_entities": [["sensor.array_a"], ["sensor.array_b"]],
           "output_cap_w": 2000, "measurement_boundary": "dc_charge_controller_output",
           "measurement_boundary_evidence": "synthetic-test-boundary-proof-v1", **overrides}
    return capture.parse_mapping({"mappings": [row]})


def quarter_state(entity, values, start=T):
    quarters = values if isinstance(values, dict) else {
        (start + timedelta(minutes=15 * index)).isoformat(): value for index, value in enumerate(values)}
    return {"entity_id": entity, "state": "available", "last_updated": T.isoformat(),
            "attributes": {"wh_period_15m": quarters, "wh_period": {T.isoformat(): 999999},
                           "watts": {T.isoformat(): 999999}, "foreign_private": "must not persist"}}


def test_native_quarter_sum_is_capped_jointly_before_hour_aggregation_with_raw_preserved():
    states = [quarter_state("sensor.array_a", [400, 400, 0, 0]),
              quarter_state("sensor.array_b", [400, 400, 0, 0])]
    before = deepcopy(states)
    groups, snapshots = capture.native_dc_wh_state_groups(states, dc_mapping(), T)
    group = groups[0]
    assert group["status"] == "available"
    # Native hourly sums and an hourly cap would give 1600Wh. The shared
    # 2000W output allows only 500Wh in each native quarter: 1000Wh total.
    assert group["records"][0]["energy_wh"] == 1000
    assert group["records"][0]["power_w"] == 1000
    assert group["normalization"]["method"] == "native_15m_sum_shared_cap_then_hour_sum"
    assert group["normalization"]["native_key_semantics"] == "interval_start"
    assert group["normalization"]["interval_closure"] == "[start,end)"
    assert group["normalization"]["quarters"][0]["start"] == T.isoformat()
    assert group["normalization"]["quarters"][0]["end"] == (T + timedelta(minutes=15)).isoformat()
    assert group["normalization"]["quarters"][0]["native_component_wh"] == [400, 400]
    assert group["normalization"]["quarters"][0]["sum_before_cap_wh"] == 800
    assert group["normalization"]["quarters"][0]["output_energy_wh"] == 500
    assert group["normalization"]["native_array_limits_preserved"]
    assert snapshots["sensor.array_a"]["attributes"] == {"wh_period_15m": states[0]["attributes"]["wh_period_15m"]}
    assert "watts" not in json.dumps(snapshots) and "foreign_private" not in json.dumps(snapshots)
    assert states == before


@pytest.mark.parametrize("missing", ["omitted", None, True, -1])
def test_missing_or_invalid_native_quarter_never_fills_hour_but_other_hours_survive(missing):
    states = [quarter_state("sensor.array_a", [100] * 8), quarter_state("sensor.array_b", [100] * 8)]
    key = (T + timedelta(minutes=30)).isoformat()
    if missing == "omitted":
        del states[1]["attributes"]["wh_period_15m"][key]
    else:
        states[1]["attributes"]["wh_period_15m"][key] = missing
    groups, _ = capture.native_dc_wh_state_groups(states, dc_mapping(), T)
    group = groups[0]
    assert group["status"] == "available"
    assert len(group["records"]) == 1
    assert group["records"][0]["start"] == (T + timedelta(hours=1)).isoformat()
    assert group["records"][0]["energy_wh"] == 800
    assert group["normalization"]["incomplete_hours"] == [T.isoformat()]
    missing_slot = group["normalization"]["quarters"][2]
    assert missing_slot["status"] == "missing_component"
    assert missing_slot["missing_array_indices"] == [1]


def test_native_quarter_source_does_not_expand_hourly_wh_or_instantaneous_watts():
    states = [wh_state("sensor.array_a", {T.isoformat(): 1000}), wh_state("sensor.array_b", {T.isoformat(): 1000})]
    groups, _ = capture.native_dc_wh_state_groups(states, dc_mapping(), T)
    assert groups[0]["status"] == "invalid_entity"
    assert groups[0]["records"] == []
    groups, _ = capture.native_dc_wh_state_groups([quarter_state("sensor.array_a", [100] * 4)], dc_mapping(), T)
    assert groups[0]["status"] == "missing_entity" and groups[0]["records"] == []


@pytest.mark.parametrize("date,hours", [("2026-03-29", 23), ("2026-10-25", 25)])
def test_native_quarter_day_union_keeps_real_dst_intervals(date, hours):
    local = datetime.fromisoformat(date)
    zone = ZoneInfo("Europe/Berlin")
    start = local.replace(tzinfo=zone).astimezone(timezone.utc)
    end = (local + timedelta(days=1)).replace(tzinfo=zone).astimezone(timezone.utc)
    quarters = {(start + timedelta(minutes=15 * index)).astimezone(zone).isoformat(): 100
                for index in range(int((end - start).total_seconds() / 900))}
    states = [quarter_state("sensor.array_a", quarters), quarter_state("sensor.array_b", quarters)]
    group = capture.native_dc_wh_state_groups(states, dc_mapping(), end)[0][0]
    assert len(group["records"]) == hours
    assert len(group["normalization"]["quarters"]) == hours * 4
    assert sum(row["energy_wh"] for row in group["records"]) == hours * 800
    assert all(left["end"] == right["start"] for left, right in zip(group["records"], group["records"][1:]))


@pytest.mark.parametrize("overrides", [{"output_cap_w": True}, {"output_cap_w": 0}, {"output_cap_w": -1},
    {"measurement_boundary": "ac_inverter_output"}, {"measurement_boundary": {}},
    {"measurement_boundary_evidence": ""}, {"source": "helios"},
    {"wh_period_15m_entities": [["sensor.array_a"], ["sensor.array_a"]]}])
def test_quarter_reference_requires_explicit_valid_common_output_contract(overrides):
    with pytest.raises(capture.CaptureError):
        dc_mapping(**overrides)


def test_native_quality_output_metadata_preserved_and_declared_boundary_checked():
    config = capture.parse_mapping({"mappings": [{"inverter_id": "dc_group", "source": "adaptive",
        "quality_entity_id": "sensor.stage_quality", "measurement_boundary": "dc_charge_controller_output",
        "measurement_boundary_evidence": "synthetic-private-readback-reference"}]})
    state = quality_state("sensor.stage_quality")
    metadata = {"output_type": "dc", "output_types": ["dc"],
                "measurement_boundary": "dc_charge_controller_output",
                "measurement_boundaries": ["dc_charge_controller_output"],
                "output_stage_boundaries": {"stage": "dc_charge_controller_output"},
                "native_energy_eligible": False}
    state["attributes"].update(metadata)
    groups, snapshots = capture.quality_groups([state], config, T)
    assert groups[0]["status"] == "available"
    assert groups[0]["measurement_boundary_check"] == "matched"
    assert groups[0]["native_metadata"] == metadata
    assert all(snapshots["sensor.stage_quality"]["attributes"][key] == value for key, value in metadata.items())
    # A mixed entry's stage curve is still safe to read even when its native
    # entry-wide Energy sum is ineligible; no site total is disaggregated.
    assert groups[0]["records"]
    state["attributes"]["measurement_boundary"] = "mixed_output_generation_sum"
    groups, snapshots = capture.quality_groups([state], config, T)
    assert groups[0]["status"] == "invalid_entity"
    assert groups[0]["records"] == []
    assert groups[0]["measurement_boundary_check"] == "conflict"
    assert snapshots["sensor.stage_quality"]["attributes"]["measurement_boundary"] == "mixed_output_generation_sum"
    # Legacy metadata-free curves remain readable, but are not certified.
    groups, _ = capture.quality_groups([quality_state("sensor.stage_quality")], config, T)
    assert groups[0]["status"] == "available"
    assert groups[0]["measurement_boundary_check"] == "legacy_unverified"


def test_cutoff_preflight_requires_declared_boundary_evidence_and_timing_only():
    ready = capture.cutoff_preflight(T, now=T - timedelta(seconds=36), mappings=dc_mapping())
    assert ready["forecast_capture_ready"]
    assert ready["latest_recommended_start"] == (T - timedelta(seconds=35)).isoformat()
    assert ready["actual_quality"] == ready["benchmark_acceptance"] == "not_checked"
    assert ready["availability"] == "not_probed" and ready["scheduler_changed"] is False
    late = capture.cutoff_preflight(T, now=T, mappings=dc_mapping())
    assert not late["timing_ready"] and not late["forecast_capture_ready"]
    legacy = capture.cutoff_preflight(T, now=T - timedelta(minutes=1), mappings=mapping())
    assert legacy["timing_ready"] and not legacy["forecast_capture_ready"]


async def test_cutoff_uses_each_complete_response_time_and_late_groups_remain_raw(monkeypatch):
    config = capture.parse_mapping({"mappings": [
        {"inverter_id": "dc_group", "source": "helios", "entry_ids": ["first"]},
        {"inverter_id": "dc_group", "source": "adaptive", "quality_entity_id": "sensor.stage_quality"},
        *dc_mapping()]})
    target = T + timedelta(hours=1)
    states = [quarter_state("sensor.array_a", [100] * 4, start=target),
              quarter_state("sensor.array_b", [100] * 4, start=target),
              quality_state("sensor.stage_quality", [{"start": target.isoformat(), "end": (target + timedelta(hours=1)).isoformat(),
                  "power_w": 100, "energy_kwh": 0.1}])]
    with freeze_time(T - timedelta(seconds=2), real_asyncio=True) as frozen:
        # This file loads the standalone script through an unregistered import
        # spec; explicitly connect that module's clock to the frozen HA reply.
        monkeypatch.setattr(capture, "datetime", datetime)
        class TimedWS(FakeWS):
            async def receive_json(self):
                response = await super().receive_json()
                if response.get("id") == 1:
                    frozen.move_to(T - timedelta(seconds=1))
                elif response.get("id") == 2:
                    frozen.move_to(T + timedelta(seconds=1))
                return response

        ws = TimedWS({"first": snapshot({target.isoformat(): 100})}, states)
        captured = await capture.capture_forecasts("http://ha.example.invalid", TOKEN, config,
                                                   session=FakeSession(ws), cutoff=T)
    groups = {group["source"]: group for group in captured["groups"]}
    assert groups["helios"]["cutoff_eligible"]
    assert not groups["adaptive"]["cutoff_eligible"] and not groups["open_meteo"]["cutoff_eligible"]
    assert captured["cutoff_check"]["late_group_count"] == 2
    assert groups["open_meteo"]["records"] and captured["entity_snapshots"]["sensor.array_a"]
    for source in ("adaptive", "open_meteo"):
        assert groups[source]["retrieved_at"] == (T + timedelta(seconds=1)).isoformat()
        assert groups[source]["records"][0]["issued_at"] == (T + timedelta(seconds=1)).isoformat()
    from scripts.evaluate import forecast_records_from_captures
    from custom_components.adaptive_solar.core.evaluation import ActualRecord, EvaluationWindow, evaluate_forecasts

    windows = [EvaluationWindow(T, target, target + timedelta(hours=1), "dc_group")]
    actuals = [ActualRecord(target, target + timedelta(hours=1), "dc_group", 100, target + timedelta(hours=1))]
    evaluated = evaluate_forecasts(forecast_records_from_captures([captured], windows), actuals, windows,
                                   as_of=target + timedelta(hours=2), sources=("adaptive", "helios", "open_meteo"))
    assert evaluated["paired_intervals"] == 0
    assert evaluated["missing"][0]["missing_sources"] == ["adaptive", "open_meteo"]


def test_native_quarter_day_components_are_unioned_without_inventing_missing_days():
    config = dc_mapping(wh_period_15m_entities=[["sensor.a_today", "sensor.a_tomorrow"],
                                               ["sensor.b_today", "sensor.b_tomorrow"]])
    states = [quarter_state(f"sensor.{array}_{day}", [100] * 4, start=T + timedelta(days=offset))
              for array in ("a", "b") for day, offset in (("today", 0), ("tomorrow", 1))]
    group = capture.native_dc_wh_state_groups(states, config, T)[0][0]
    assert group["status"] == "available"
    assert len(group["records"]) == 2
    assert group["records"][0]["start"] == T.isoformat()
    assert group["records"][1]["start"] == (T + timedelta(days=1)).isoformat()


def test_late_cli_capture_is_appended_then_returns_nonzero_without_backdating(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "ROOT", tmp_path)
    private = tmp_path / "data"
    private.mkdir()
    config, output = private / "mapping.json", private / "capture.jsonl"
    config.write_text(json.dumps({"mappings": list(dc_mapping())}))
    payload = {"schema_version": 1, "groups": [{"retrieved_at": (T + timedelta(seconds=1)).isoformat(),
        "cutoff_eligible": False, "timing_status": "late"}],
        "cutoff_check": {"declared_cutoff": T.isoformat(), "late_group_count": 1, "all_groups_on_time": False}}
    monkeypatch.setattr(capture, "capture_forecasts", AsyncMock(return_value=payload))
    monkeypatch.setattr(sys, "argv", ["capture_ha", "--config", str(config), "--output", str(output), "--cutoff", T.isoformat()])
    assert capture.main() == 1
    assert json.loads(output.read_text())["groups"][0]["retrieved_at"] == (T + timedelta(seconds=1)).isoformat()


def test_real_cli_preflight_needs_no_credentials_and_never_appends(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "data").mkdir()
    shutil.copyfile(SCRIPT, root / "scripts/capture_ha.py")
    shutil.copyfile(SCRIPT.with_name("replay_paths.py"), root / "scripts/replay_paths.py")
    config, output = root / "data/map.json", root / "data/capture.jsonl"
    config.write_text(json.dumps({"mappings": list(dc_mapping())}))
    env = dict(os.environ)
    env.pop("HA_URL", None)
    env.pop("HA_TOKEN", None)
    run = subprocess.run([sys.executable, str(root / "scripts/capture_ha.py"), "--config", str(config),
                          "--output", str(output), "--cutoff", "2050-01-01T09:00:00+01:00", "--preflight"],
                         env=env, capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["forecast_capture_ready"]
    assert not output.exists()
