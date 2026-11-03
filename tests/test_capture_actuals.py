"""Real Recorder protocol contracts, quality gating and private capture I/O."""
import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import aiohttp
from freezegun import freeze_time
import pytest

from scripts import capture_actuals as actuals

START = datetime(2026, 6, 1, 10, tzinfo=UTC)
END = START + timedelta(hours=2)
MAPPINGS = ({"inverter_id": "roof", "statistic_ids": ["sensor.energy"]},)


def capture(start=START, end=END, value=1, unit="kWh", received=None):
    rows = []
    cursor = start - timedelta(hours=1)
    while cursor < end:
        rows.append({"start": cursor.timestamp() * 1000, "end": (cursor + timedelta(hours=1)).timestamp() * 1000, "change": value})
        cursor += timedelta(hours=1)
    result = actuals.build_raw_capture([{"statistic_id": "sensor.energy", "has_sum": True, "unit_class": "energy", "statistics_unit_of_measurement": unit, "display_unit_of_measurement": "kWh"}], {"sensor.energy": rows}, MAPPINGS, start, end, received or end + timedelta(hours=1))
    return result


def mask(start=START, end=END, **overrides):
    return {"schema_version": 1, "validated": True, "provenance": {"source": "verified interval coverage, curtailment and meter reset event log", "validated_at": (end + timedelta(minutes=30)).isoformat()},
            "intervals": [{"inverter_id": "roof", "start": start.isoformat(), "end": end.isoformat(), "quality": "valid", "complete_coverage": True, "curtailed": False, "counter_reset": False, **overrides}]}


def normalize(raw=None, quality=True):
    raw = raw or capture()
    return actuals.normalize_capture(raw, mask() if quality is True else quality, normalized_at=utc_receipt(raw))


def utc_receipt(raw):
    return actuals.utc(raw["retrieved_at"]) + timedelta(hours=2)


def test_native_ha_websocket_adapter_serializes_milliseconds(hass):
    from homeassistant.components.recorder.websocket_api import _ws_get_statistics_during_period

    native = {"sensor.energy": [{"start": START.timestamp(), "end": (START + timedelta(hours=1)).timestamp(), "change": 1}]}
    with patch("homeassistant.components.recorder.websocket_api.statistics_during_period", return_value=native):
        result = json.loads(_ws_get_statistics_during_period(hass, 2, START, END, {"sensor.energy"}, "hour", {"energy": "kWh"}, {"change"}))
    assert result["result"]["sensor.energy"][0]["start"] == START.timestamp() * 1000
    assert result["result"]["sensor.energy"][0]["end"] == (START + timedelta(hours=1)).timestamp() * 1000


async def test_real_recorder_metadata_and_requested_change_units(recorder_mock, hass):
    from homeassistant.components.recorder.models import StatisticMeanType
    from homeassistant.components.recorder.statistics import async_import_statistics
    from homeassistant.components.recorder.websocket_api import ws_handle_get_statistics_during_period, ws_handle_list_statistic_ids
    from homeassistant.const import UnitOfEnergy
    from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

    assert actuals.ENERGY_UNITS == set(UnitOfEnergy)
    hass.states.async_set("sensor.energy", "3", {"unit_of_measurement": "kWh"})
    async_import_statistics(hass, {"statistic_id": "sensor.energy", "source": "recorder", "name": None,
        "unit_class": "energy", "unit_of_measurement": "Wh", "has_sum": True, "mean_type": StatisticMeanType.NONE},
        [{"start": START + timedelta(hours=i - 2), "state": i * 1000, "sum": i * 1000} for i in range(4)])
    await async_wait_recording_done(hass)
    connection = Mock()
    await ws_handle_list_statistic_ids(hass, connection, {"id": 1, "statistic_type": "sum"})
    metadata = json.loads(connection.send_message.call_args.args[0])["result"]
    meta = next(row for row in metadata if row["statistic_id"] == "sensor.energy")
    assert "unit_of_measurement" not in meta
    assert meta["statistics_unit_of_measurement"] == "Wh" and meta["display_unit_of_measurement"] == "kWh"
    raw = capture()
    await ws_handle_get_statistics_during_period(hass, connection, {"id": 2, **raw["raw"]["request"], "types": {"change"}, "statistic_ids": {"sensor.energy"}})
    raw["raw"].update(metadata=metadata, statistics=json.loads(connection.send_message.call_args.args[0])["result"])
    records = normalize(raw)["normalization"]["records"]
    assert len(records) == 2 and {row["power_w"] for row in records} == {1000}


@pytest.mark.parametrize("units,valid", [
    ({"unit_of_measurement": "Wh"}, True),  # Existing raw archives.
    ({"statistics_unit_of_measurement": "Wh", "display_unit_of_measurement": "kWh"}, True),
    ({"statistics_unit_of_measurement": "J", "unit_of_measurement": "J"}, True),
    ({"statistics_unit_of_measurement": "Wh", "unit_of_measurement": "kWh"}, False),
    ({"statistics_unit_of_measurement": "Wh", "display_unit_of_measurement": "W"}, False),
    ({"statistics_unit_of_measurement": None, "unit_of_measurement": "Wh"}, False),
    ({"statistics_unit_of_measurement": "kWh", "unit_class": "power"}, False),
    ({"statistics_unit_of_measurement": "kWh", "has_sum": 1}, False),
    ({"statistics_unit_of_measurement": "varh"}, False),
    ({"statistics_unit_of_measurement": []}, False),
    ({"display_unit_of_measurement": "kWh"}, False), ({}, False),
])
def test_metadata_unit_variants_do_not_rescale_changes(units, valid):
    raw = capture()
    raw["raw"]["metadata"] = [{"statistic_id": "sensor.energy", "has_sum": True, "unit_class": "energy", **units}]
    result = normalize(raw)["normalization"]
    assert bool(result["records"]) is valid
    if valid:
        assert {row["power_w"] for row in result["records"]} == {1000}
    else:
        assert all("unverified_energy_metadata" in row["reasons"] for row in result["excluded"])


def test_statistics_without_explicit_quality_are_raw_only_never_assumed_valid():
    raw = capture()
    result = normalize(raw, quality=None)
    assert result["raw"] == raw["raw"]
    assert result["normalization"]["records"] == []
    assert len(result["normalization"]["excluded"]) == 2
    assert all("missing_quality_evidence" in row["reasons"] for row in result["normalization"]["excluded"])


def test_change_is_energy_sum_is_never_used_and_receipt_is_not_backdated():
    raw = capture()
    for row in raw["raw"]["statistics"]["sensor.energy"]:
        row["sum"] = 987654321
    result = normalize(raw)
    records = actuals.actual_records_from_captures([result])
    assert len(records) == 2
    assert records[0]["power_w"] == 1000
    assert records[0]["curtailed"] is False
    assert actuals.utc(records[0]["observed_at"]) == actuals.utc(raw["retrieved_at"])
    assert actuals.utc(records[0]["observed_at"]) >= actuals.utc(records[0]["end"])


@pytest.mark.parametrize("unit,value,expected", [("Wh", 1000, 1000), ("kWh", 1, 1000), ("MWh", 0.001, 1000)])
def test_explicit_response_units_are_converted_once(unit, value, expected):
    raw = capture(value=value, unit=unit)
    raw["raw"]["request"]["units"]["energy"] = unit
    assert normalize(raw)["normalization"]["records"][0]["power_w"] == expected
    # Native request kWh converts even a meter stored in Wh; metadata is not
    # the returned numeric unit and must not cause an extra /1000 conversion.
    raw = capture(value=1, unit="Wh")
    assert normalize(raw)["normalization"]["records"][0]["power_w"] == 1000


@pytest.mark.parametrize("bad", [None, -1, True, float("nan"), float("inf")])
def test_missing_negative_boolean_nonfinite_changes_are_excluded(bad):
    raw = capture()
    raw["raw"]["statistics"]["sensor.energy"][1]["change"] = bad
    result = normalize(raw)
    assert result["normalization"]["records"] == []  # following hour also lacks a valid predecessor
    assert "invalid_or_negative_change" in result["normalization"]["excluded"][0]["reasons"]


@pytest.mark.parametrize("flags,reason", [({"curtailed": None}, "unknown_curtailment"), ({"curtailed": True}, "curtailed"), ({"counter_reset": True}, "counter_reset"), ({"counter_reset": None}, "unknown_counter_reset"), ({"complete_coverage": False}, "unverified_measurement_coverage"), ({"quality": "unknown"}, "unverified_measurement_coverage")])
def test_quality_requires_entire_interval_coverage_and_known_no_curtailment_or_reset(flags, reason):
    result = normalize(quality=mask(**flags))
    assert result["normalization"]["records"] == []
    assert all(reason in row["reasons"] for row in result["normalization"]["excluded"])


def test_missing_predecessor_or_hour_cannot_be_filled_as_zero():
    raw = capture()
    raw["raw"]["statistics"]["sensor.energy"].pop(0)
    result = normalize(raw)
    assert len(result["normalization"]["records"]) == 1
    assert "missing_or_invalid_predecessor" in result["normalization"]["excluded"][0]["reasons"]
    raw = capture()
    raw["raw"]["statistics"]["sensor.energy"].pop(1)
    result = normalize(raw)
    assert result["normalization"]["records"] == []
    assert "missing_statistic_hour" in result["normalization"]["excluded"][0]["reasons"]


@pytest.mark.parametrize("day,hours", [(datetime(2026, 3, 29), 23), (datetime(2026, 10, 25), 25)])
def test_dst_local_days_keep_real_utc_intervals(day, hours):
    zone = ZoneInfo("Europe/Berlin")
    start = day.replace(tzinfo=zone).astimezone(UTC)
    end = (day + timedelta(days=1)).replace(tzinfo=zone).astimezone(UTC)
    raw = capture(start, end)
    result = actuals.normalize_capture(raw, mask(start, end), normalized_at=utc_receipt(raw))
    assert len(result["normalization"]["records"]) == hours
    assert sum(row["power_w"] / 1000 for row in result["normalization"]["records"]) == hours
    assert {actuals.utc(row["end"]) - actuals.utc(row["start"]) for row in result["normalization"]["records"]} == {timedelta(hours=1)}


def test_seconds_must_not_be_guessed_as_milliseconds():
    raw = capture()
    for row in raw["raw"]["statistics"]["sensor.energy"]:
        row["start"] /= 1000
        row["end"] /= 1000
    with pytest.raises(actuals.CaptureError, match="UTC hours"):
        normalize(raw)


def test_future_labels_are_excluded_even_if_a_later_mask_claims_quality():
    raw = capture(received=START + timedelta(minutes=30))
    result = actuals.normalize_capture(raw, mask(), normalized_at=END + timedelta(hours=2))
    assert result["normalization"]["records"] == []
    assert all("future_or_unfinished_at_receipt" in row["reasons"] for row in result["normalization"]["excluded"])


def test_quality_validated_later_advances_effective_observed_at_and_as_of_gate():
    raw = capture(received=END + timedelta(minutes=10))
    result = actuals.normalize_capture(raw, mask(), normalized_at=END + timedelta(hours=2))
    assert {row["observed_at"] for row in result["normalization"]["records"]} == {(END + timedelta(minutes=30)).isoformat()}
    assert actuals.actual_records_from_captures([result], as_of=END + timedelta(minutes=20)) == []


def test_revisions_are_append_only_and_conflicting_values_require_explicit_selection(tmp_path):
    first = normalize()
    same = normalize()
    changed = normalize(capture(value=2))
    output = tmp_path / "actuals.jsonl"
    actuals.append_capture(output, first)
    actuals.append_capture(output, same)
    actuals.append_capture(output, changed)
    archived = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(archived) == 3
    assert output.stat().st_mode & 0o777 == 0o600
    assert len(actuals.actual_records_from_captures(archived[:2])) == 2
    with pytest.raises(actuals.CaptureError, match="Conflicting actual revisions"):
        actuals.actual_records_from_captures(archived)
    tampered = deepcopy(first)
    tampered["normalization"]["records"][0]["power_w"] = 1
    with pytest.raises(actuals.CaptureError, match="differ"):
        actuals.actual_records_from_captures([tampered])


def test_append_refuses_locked_symlink_and_partial_record(tmp_path):
    output = tmp_path / "actuals.jsonl"
    output.write_text('{"unfinished":')
    with pytest.raises(actuals.CaptureError, match="incomplete"):
        actuals.append_capture(output, normalize())
    output.write_text("{}\n")
    with output.open("r+") as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(actuals.CaptureError, match="locked"):
            actuals.append_capture(output, normalize())
    linked = tmp_path / "linked"
    linked.symlink_to(output)
    with pytest.raises(actuals.CaptureError):
        actuals.append_capture(linked, normalize())


def session_for(responses):
    ws = AsyncMock()
    ws.receive_json.side_effect = responses
    session = Mock()
    session.ws_connect.return_value.__aenter__ = AsyncMock(return_value=ws)
    session.ws_connect.return_value.__aexit__ = AsyncMock(return_value=False)
    return session, ws


async def test_readonly_protocol_requests_correct_scope_units_and_predecessor_hour():
    raw = capture()
    session, ws = session_for([{"type": "auth_required"}, {"type": "auth_ok"}, {"id": 1, "type": "result", "success": True, "result": raw["raw"]["metadata"]}, {"id": 2, "type": "result", "success": True, "result": raw["raw"]["statistics"]}])
    with freeze_time(END + timedelta(hours=1)):
        result = await actuals.capture_actuals("http://ha.invalid:8123", "secret-auth-token", MAPPINGS, START, END, session=session)
    sent = [call.args[0] for call in ws.send_json.call_args_list]
    assert [row["type"] for row in sent] == ["auth", "recorder/list_statistic_ids", actuals.COMMAND]
    request = sent[2]
    assert request["types"] == ["change"] and request["units"] == {"energy": "kWh"}
    assert request["start_time"] == (START - timedelta(hours=1)).isoformat()
    assert result["retrieved_at"] == (END + timedelta(hours=1)).isoformat()
    assert "secret-auth-token" not in json.dumps(result)


async def test_transport_timeout_and_errors_never_expose_connection_credentials():
    session = Mock()
    session.ws_connect.side_effect = aiohttp.ClientConnectionError("PRIVATE_TOKEN http://private-ha.invalid")
    with pytest.raises(actuals.CaptureError) as caught:
        await actuals.capture_actuals("http://private-ha.invalid", "PRIVATE_TOKEN", MAPPINGS, START, END, session=session)
    assert "PRIVATE_TOKEN" not in str(caught.value) and "private-ha" not in str(caught.value)
    session, ws = session_for([{"type": "auth_required"}])
    async def stall():
        await asyncio.Event().wait()
    ws.receive_json.side_effect = stall
    with pytest.raises(actuals.CaptureError, match="deadline"):
        await actuals.capture_actuals("http://ha.invalid", "token", MAPPINGS, START, END, timeout=0.01, session=session)


def test_cli_uses_private_paths_and_does_not_print_token_or_url(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(actuals, "ROOT", tmp_path)
    private = tmp_path / "data"
    private.mkdir()
    config = private / "mapping.json"
    config.write_text(json.dumps({"mappings": list(MAPPINGS)}))
    output = private / "actuals.jsonl"
    monkeypatch.setenv("HA_TOKEN", "VERY_PRIVATE_TOKEN")
    monkeypatch.setenv("HA_URL", "http://private-ha.invalid")
    monkeypatch.setattr(actuals, "capture_actuals", AsyncMock(return_value=capture()))
    monkeypatch.setattr(sys_module := __import__("sys"), "argv", ["capture_actuals", "--config", str(config), "--output", str(output), "--start", START.isoformat(), "--end", END.isoformat()])
    assert actuals.main() == 0
    text = capsys.readouterr()
    assert "0 accepted" in text.out
    assert "VERY_PRIVATE_TOKEN" not in text.out + text.err and "private-ha" not in text.out + text.err
    assert len(output.read_text().splitlines()) == 1
    monkeypatch.setattr(sys_module, "argv", ["capture_actuals", "--config", str(config), "--output", str(tmp_path / "public.jsonl"), "--start", START.isoformat(), "--end", END.isoformat()])
    assert actuals.main() == 2
    assert not (tmp_path / "public.jsonl").exists()


@pytest.mark.parametrize("parent_alias", [False, True])
def test_cli_rejects_output_symlink_before_capture_and_preserves_unrelated_json(tmp_path, monkeypatch, parent_alias):
    monkeypatch.setattr(actuals, "ROOT", tmp_path)
    private = tmp_path / "data"
    private.mkdir()
    config = private / "mapping.json"
    config.write_text(json.dumps({"mappings": list(MAPPINGS)}))
    target = private / "unrelated.json"
    original = b'{"unrelated":"preserve this JSON"}\n'
    target.write_bytes(original)
    output = private / "actuals.jsonl"
    output.symlink_to(target)
    if parent_alias:
        alias = private / "parent-alias"
        alias.symlink_to(private, target_is_directory=True)
        output = alias / output.name
    collector = AsyncMock(return_value=capture())
    monkeypatch.setattr(actuals, "capture_actuals", collector)
    monkeypatch.setattr(sys, "argv", ["capture_actuals", "--config", str(config), "--output", str(output),
                                      "--start", START.isoformat(), "--end", END.isoformat()])
    result = actuals.main()
    assert target.read_bytes() == original
    assert output.is_symlink()
    assert result == 2
    collector.assert_not_called()


@pytest.mark.parametrize("alias_kind", ["leaf", "parent_leaf", "parent_input", "boundary_escape"])
def test_real_cli_rejects_output_alias_before_network(tmp_path, alias_kind):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    private = root / "data"
    private.mkdir()
    script = Path(actuals.__file__)
    for source in (script, script.with_name("replay_paths.py")):
        shutil.copyfile(source, root / "scripts" / source.name)
    config = private / "mapping.json"
    config.write_text(json.dumps({"mappings": list(MAPPINGS)}))
    target = private / "unrelated.json"
    original = b'{"unrelated":"preserve this JSON"}\n'
    target.write_bytes(original)
    output = private / "actuals.jsonl"
    output.symlink_to(target)
    if alias_kind in {"parent_leaf", "parent_input"}:
        alias = private / "parent-alias"
        alias.symlink_to(private, target_is_directory=True)
        output = alias / (config.name if alias_kind == "parent_input" else output.name)
    elif alias_kind == "boundary_escape":
        outside = root / "outside"
        outside.mkdir()
        target = outside / "unrelated.json"
        target.write_bytes(original)
        alias = private / "escape"
        alias.symlink_to(outside, target_is_directory=True)
        output = alias / target.name
    config_before = config.read_bytes()
    marker = tmp_path / "network-attempt"
    (tmp_path / "sitecustomize.py").write_text(
        "import os\nfrom pathlib import Path\nimport aiohttp\n"
        "def forbidden_network(*args, **kwargs):\n"
        "    Path(os.environ['CAPTURE_NETWORK_MARKER']).write_text('attempted')\n"
        "    raise AssertionError('unexpected capture network setup')\n"
        "aiohttp.ClientSession = forbidden_network\n")
    env = {**os.environ, "PYTHONPATH": str(tmp_path), "HA_URL": "http://ha.invalid",
           "HA_TOKEN": "SYNTHETIC_CAPTURE_TOKEN", "CAPTURE_NETWORK_MARKER": str(marker)}
    run = subprocess.run([sys.executable, str(root / "scripts/capture_actuals.py"), "--config", str(config),
                          "--output", str(output), "--start", START.isoformat(), "--end", END.isoformat()],
                         env=env, capture_output=True, text=True, timeout=10)
    assert not marker.exists(), run.stderr
    assert run.returncode == 2
    expected = ("below ignored data/" if alias_kind == "boundary_escape" else
                "differ from every input" if alias_kind == "parent_input" else "output must be separate")
    assert expected in run.stderr
    assert target.read_bytes() == original
    assert config.read_bytes() == config_before
    if alias_kind in {"leaf", "parent_leaf"}:
        assert output.is_symlink()
    assert env["HA_TOKEN"] not in run.stdout + run.stderr


@pytest.mark.parametrize("outside_exists", [False, True])
def test_cli_pins_parent_alias_before_capture_can_retarget_it(tmp_path, monkeypatch, outside_exists):
    monkeypatch.setattr(actuals, "ROOT", tmp_path)
    private, outside = tmp_path / "data", tmp_path / "outside"
    safe = private / "safe"
    safe.mkdir(parents=True)
    outside.mkdir()
    config = private / "mapping.json"
    config.write_text(json.dumps({"mappings": list(MAPPINGS)}))
    alias = private / "alias"
    alias.symlink_to(safe, target_is_directory=True)
    output = alias / "actuals.jsonl"
    safe_output = safe / output.name
    safe_output.write_bytes(b"{}\n")
    outside_output = outside / output.name
    original = b'{"outside":"preserve this JSON"}\n'
    if outside_exists:
        outside_output.write_bytes(original)

    async def retarget(*args, **kwargs):
        alias.unlink()
        alias.symlink_to(outside, target_is_directory=True)
        return capture()

    monkeypatch.setattr(actuals, "capture_actuals", retarget)
    monkeypatch.setattr(sys, "argv", ["capture_actuals", "--config", str(config), "--output", str(output),
                                      "--start", START.isoformat(), "--end", END.isoformat()])
    assert actuals.main() == 0
    if outside_exists:
        assert outside_output.read_bytes() == original
    else:
        assert not outside_output.exists()
    assert len(safe_output.read_text().splitlines()) == 2


def test_cli_rechecks_pinned_parent_boundary_after_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(actuals, "ROOT", tmp_path)
    private, outside = tmp_path / "data", tmp_path / "outside"
    safe = private / "safe"
    safe.mkdir(parents=True)
    outside.mkdir()
    config = private / "mapping.json"
    config.write_text(json.dumps({"mappings": list(MAPPINGS)}))
    output = safe / "actuals.jsonl"
    original = b'{"original":"preserve this JSON"}\n'
    output.write_bytes(original)
    outside_output = outside / output.name
    outside_output.write_bytes(original)
    moved = private / "original-safe"

    async def replace_parent(*args, **kwargs):
        safe.rename(moved)
        safe.symlink_to(outside, target_is_directory=True)
        return capture()

    monkeypatch.setattr(actuals, "capture_actuals", replace_parent)
    monkeypatch.setattr(sys, "argv", ["capture_actuals", "--config", str(config), "--output", str(output),
                                      "--start", START.isoformat(), "--end", END.isoformat()])
    assert actuals.main() == 2
    assert outside_output.read_bytes() == original
    assert (moved / output.name).read_bytes() == original


def test_later_invalid_revision_cannot_silently_keep_older_accepted_value():
    first = normalize()
    later = capture(received=END + timedelta(hours=2))
    later["raw"]["statistics"]["sensor.energy"][1]["change"] = None
    revised = normalize(later)
    with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
        actuals.actual_records_from_captures([first, revised])
    with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
        actuals.actual_records_from_captures([revised, first])
    # A later, explicitly known revision does not contaminate an earlier as-of.
    assert len(actuals.actual_records_from_captures([first, revised], as_of=END + timedelta(hours=1))) == 2


def test_late_quality_of_old_raw_cannot_hide_newer_invalid_source_revision():
    first = capture(received=END + timedelta(hours=1))
    quality = mask()
    quality["provenance"]["validated_at"] = (END + timedelta(hours=4)).isoformat()
    accepted = actuals.normalize_capture(first, quality, normalized_at=END + timedelta(hours=4))
    later = capture(received=END + timedelta(hours=2))
    later["raw"]["statistics"]["sensor.energy"][1]["change"] = None
    invalid = normalize(later, quality=None)
    for sequence in ([accepted, invalid], [invalid, accepted]):
        assert actuals.actual_records_from_captures(sequence, as_of=END + timedelta(hours=3)) == []
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures(sequence, as_of=END + timedelta(hours=5))


def test_new_valid_raw_can_replace_older_invalid_source_despite_its_late_quality():
    old = capture(received=END + timedelta(hours=1))
    old["raw"]["statistics"]["sensor.energy"][1]["change"] = None
    late_quality = mask()
    late_quality["provenance"]["validated_at"] = (END + timedelta(hours=5)).isoformat()
    invalid = actuals.normalize_capture(old, late_quality, normalized_at=END + timedelta(hours=5))
    newer = capture(received=END + timedelta(hours=2))
    quality = mask()
    quality["provenance"]["validated_at"] = (END + timedelta(hours=3)).isoformat()
    accepted = actuals.normalize_capture(newer, quality, normalized_at=END + timedelta(hours=3))
    for sequence in ([invalid, accepted], [accepted, invalid]):
        # No future labels before the newer raw's evidence is actually known.
        assert actuals.actual_records_from_captures(sequence, as_of=END + timedelta(hours=2, minutes=30)) == []
        rows = actuals.actual_records_from_captures(sequence, as_of=END + timedelta(hours=6))
        assert len(rows) == 2
        assert {row["observed_at"] for row in rows} == {(END + timedelta(hours=3)).isoformat()}


def test_identical_later_valid_raw_restores_after_invalid_revision_without_backdating():
    first = normalize(capture(received=END + timedelta(hours=1)))
    bad_raw = capture(received=END + timedelta(hours=2))
    bad_raw["raw"]["statistics"]["sensor.energy"][1]["change"] = None
    invalid = normalize(bad_raw, quality=None)
    restored_raw = capture(received=END + timedelta(hours=3))
    quality = mask()
    quality["provenance"]["validated_at"] = (END + timedelta(hours=4)).isoformat()
    restored = actuals.normalize_capture(restored_raw, quality, normalized_at=END + timedelta(hours=4))
    for sequence in ([first, invalid, restored], [restored, invalid, first]):
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures(sequence, as_of=END + timedelta(hours=3, minutes=30))
        rows = actuals.actual_records_from_captures(sequence, as_of=END + timedelta(hours=5))
        assert {row["observed_at"] for row in rows} == {(END + timedelta(hours=4)).isoformat()}


def test_source_invalidity_is_known_at_receipt_even_if_quality_is_checked_later():
    first = normalize(capture(received=END + timedelta(hours=1)))
    bad_raw = capture(received=END + timedelta(hours=2))
    bad_raw["raw"]["statistics"]["sensor.energy"][1]["change"] = None
    quality = mask()
    quality["provenance"]["validated_at"] = (END + timedelta(hours=5)).isoformat()
    invalid = actuals.normalize_capture(bad_raw, quality, normalized_at=END + timedelta(hours=5))
    with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
        actuals.actual_records_from_captures([first, invalid], as_of=END + timedelta(hours=3))


@pytest.mark.parametrize("reverse", [False, True])
def test_old_positive_quality_cannot_rehabilitate_newer_invalidation_on_reread(reverse):
    first = normalize(capture(received=END + timedelta(hours=1)))
    bad_mask = mask(curtailed=True)
    bad_mask["provenance"]["validated_at"] = (END + timedelta(hours=2)).isoformat()
    invalid = normalize(capture(received=END + timedelta(hours=2)), quality=bad_mask)
    reread = normalize(capture(received=END + timedelta(hours=3)))
    captures = [first, invalid, reread]
    if reverse:
        captures.reverse()
    assert len(actuals.actual_records_from_captures(captures, as_of=END + timedelta(hours=1))) == 2
    for cutoff in (END + timedelta(hours=2), END + timedelta(hours=4), None):
        with pytest.raises(actuals.CaptureError, match="later invalid actual revision"):
            actuals.actual_records_from_captures(captures, as_of=cutoff)
    good_mask = mask()
    good_mask["provenance"]["validated_at"] = (END + timedelta(hours=5)).isoformat()
    requalified = normalize(capture(received=END + timedelta(hours=3)), quality=good_mask)
    rows = actuals.actual_records_from_captures([requalified, *captures])
    assert {row["observed_at"] for row in rows} == {(END + timedelta(hours=5)).isoformat()}


@pytest.mark.parametrize("reverse", [False, True])
def test_positive_quality_and_raw_revision_advance_independently(reverse):
    # A late quality check of OLD raw and a NEW valid raw both qualify the same
    # values. Neither may hide the other axis or revive the invalid middle raw.
    late_mask = mask()
    late_mask["provenance"]["validated_at"] = (END + timedelta(hours=4)).isoformat()
    qualified_old = actuals.normalize_capture(capture(received=END + timedelta(hours=1)), late_mask,
                                             normalized_at=END + timedelta(hours=4))
    bad_raw = capture(received=END + timedelta(hours=2))
    bad_raw["raw"]["statistics"]["sensor.energy"][1]["change"] = None
    invalid = normalize(bad_raw, quality=None)
    newer = normalize(capture(received=END + timedelta(hours=3)))
    captures = [qualified_old, invalid, newer]
    if reverse:
        captures.reverse()
    rows = actuals.actual_records_from_captures(captures)
    assert len(rows) == 2
    assert {row["observed_at"] for row in rows} == {(END + timedelta(hours=4)).isoformat()}


def test_overflow_energy_is_excluded_and_malformed_units_fail_safely():
    raw = capture(value=1e308)
    result = normalize(raw)
    assert result["normalization"]["records"] == []
    assert "nonfinite_aggregate_energy" in result["normalization"]["excluded"][0]["reasons"]
    raw = capture()
    raw["raw"]["request"]["units"]["energy"] = []
    with pytest.raises(actuals.CaptureError, match="hourly energy change"):
        normalize(raw)


def test_quality_mask_partial_or_ambiguous_coverage_is_not_accepted():
    quality = mask()
    quality["intervals"][0]["start"] = (START + timedelta(minutes=1)).isoformat()
    result = normalize(quality=quality)
    assert len(result["normalization"]["records"]) == 1
    quality = mask()
    quality["intervals"].append(dict(quality["intervals"][0]))
    with pytest.raises(actuals.CaptureError, match="overlap"):
        normalize(quality=quality)
