"""Real EPS identities, exact original bytes and strict member-wise weather."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import base64
import json
import sqlite3

import pytest

from custom_components.adaptive_solar.core.archive import ArchiveJournal, ArchiveStore
from custom_components.adaptive_solar.core.ensemble import ENSEMBLE_COUNTS, UNITS, field_provenance, parse_members, request_params
from scripts.capture_weather import archive_response, flush_journal, reconstruct_response

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def eps_payload(product="dwd_icon_d2_eps", count=4):
    payload = {"hourly": {"time": [(NOW + timedelta(hours=index - 1)).timestamp() for index in range(count)]},
               "hourly_units": {"time": "unixtime"}}
    for member in range(ENSEMBLE_COUNTS[product]):
        suffix = f"_member{member:02d}" if member else ""
        for field, value in zip(UNITS, (500 + member, 600 + member, 100, 20, 3, 40), strict=True):
            payload["hourly"][field + suffix] = [value] * count
            payload["hourly_units"][field + suffix] = UNITS[field]
    return payload


@pytest.mark.parametrize("product,count", list(ENSEMBLE_COUNTS.items()))
def test_all_expected_members_preserve_their_own_trajectory(product, count):
    archive = parse_members(eps_payload(product), product, NOW)
    assert archive.expected_members == count
    assert len(archive.members) == count
    assert archive.missing_members == () and archive.rejected_members == {}
    assert archive.members[-1].points[0].ghi_w_m2 == 500 + count - 1
    assert archive.members[-1].issued_at == NOW
    assert archive.members[-1].points[0].start == NOW - timedelta(hours=1)


def test_missing_member_and_invalid_units_never_change_expected_denominator():
    payload = eps_payload()
    for key in list(payload["hourly"]):
        if key.endswith("_member19"):
            del payload["hourly"][key]
    payload["hourly_units"]["wind_speed_10m_member01"] = "km/h"
    archive = parse_members(payload, "dwd_icon_d2_eps", NOW)
    assert archive.expected_members == 20
    assert archive.missing_members == (19,)
    assert 1 in archive.rejected_members
    assert len(archive.members) == 18


def test_member_ambient_gap_removes_both_adjacent_cells_without_cross_member_fill():
    payload = eps_payload()
    payload["hourly"]["temperature_2m_member01"][1] = None
    archive = parse_members(payload, "dwd_icon_d2_eps", NOW)
    member = archive.members[1]
    assert len(member.points) == 1
    assert member.points[0].start == NOW + timedelta(hours=1)
    assert len(archive.members[0].points) == 3


@pytest.mark.parametrize("bad", [True, None, float("nan"), -5])
def test_member_bad_radiation_remains_gap(bad):
    payload = eps_payload()
    payload["hourly"]["shortwave_radiation_member01"][1] = bad
    archive = parse_members(payload, "dwd_icon_d2_eps", NOW)
    assert archive.members[1].points[0].start == NOW
    assert archive.members[0].points[0].start == NOW - timedelta(hours=1)


def test_unexpected_member_and_duplicate_timestamps_fail_closed():
    payload = eps_payload()
    payload["hourly"]["shortwave_radiation_member20"] = [0] * 4
    with pytest.raises(ValueError, match="identity"):
        parse_members(payload, "dwd_icon_d2_eps", NOW)
    payload = eps_payload()
    payload["hourly"]["time"][1] = payload["hourly"]["time"][0]
    archive = parse_members(payload, "dwd_icon_d2_eps", NOW)
    assert not archive.members and len(archive.rejected_members) == 20


def test_hour_request_includes_previous_endpoint_and_explicit_units():
    params = request_params(52.52, 13.41, "icon_d2", 73)
    assert params["forecast_hours"] == 73 and params["past_hours"] == 1
    assert "forecast_days" not in params
    assert params["timeformat"] == "unixtime" and params["wind_speed_unit"] == "ms"
    with pytest.raises(ValueError):
        request_params(True, 13, "icon_d2")


def test_exact_original_response_roundtrips_chunked_host_store_and_detects_missing(tmp_path, monkeypatch):
    import scripts.capture_weather as collector

    monkeypatch.setattr(collector, "CHUNK_BYTES", 1500)
    raw = json.dumps(eps_payload(), indent=2).encode() + b"\n"
    journal, store = ArchiveJournal(tmp_path / "staging"), ArchiveStore(tmp_path / "host")
    manifest = archive_response(journal, {"url": "https://ensemble-api.open-meteo.com/v1/ensemble", "params": {}},
                                raw, NOW, product="dwd_icon_d2_eps", ensemble=True, http_status=200)
    assert manifest["payload"]["coverage"]["expected_members"] == 20
    assert manifest["payload"]["provider_run_at"] is None
    flush_journal(journal, store, "weather")
    rows = list(store.iter_events(source="weather"))
    event = next(row for row in rows if row["kind"] == "host_weather_response")
    assert reconstruct_response(event, rows) == raw
    assert len(event["payload"]["raw_response"]["event_ids"]) > 1
    with pytest.raises(ValueError, match="missing"):
        reconstruct_response(event, [row for row in rows if row != rows[0]])
    changed = deepcopy(rows)
    changed[0]["payload"]["base64"] = "Zm9v"
    with pytest.raises(ValueError, match="checksum"):
        reconstruct_response(event, changed)


def test_http_error_body_is_archived_but_never_a_member_forecast(tmp_path):
    journal = ArchiveJournal(tmp_path)
    event = archive_response(journal, {}, b'{"error":true}', NOW, product="dwd_icon_d2_eps",
                             ensemble=True, http_status=429)
    assert event["payload"]["status"] == "failed"
    assert event["payload"]["http_status"] == 429
    assert event["payload"]["raw_response"]["event_ids"]


def test_rejected_member_indices_survive_json_canonical_hash_roundtrip(tmp_path):
    raw = eps_payload()
    for index in (1, 2, 10):
        raw["hourly_units"][f"wind_speed_10m_member{index:02d}"] = "km/h"
    journal, store = ArchiveJournal(tmp_path / "journal"), ArchiveStore(tmp_path / "host")
    archive_response(journal, {}, json.dumps(raw).encode(), NOW, product="dwd_icon_d2_eps", ensemble=True, http_status=200)
    flush_journal(journal, store, "weather")
    event = next(store.iter_events(kind="host_weather_response"))
    assert set(event["payload"]["coverage"]["rejected_members"]) == {"1", "2", "10"}


def test_documented_provider_derivations_do_not_get_inferred_for_ensemble_products():
    icon = field_provenance("icon_d2")
    assert icon["shortwave_radiation"]["provider_derivation"] == "sum_native_direct_and_diffuse"
    ifs = field_provenance("ecmwf_ifs")
    assert ifs["diffuse_radiation"]["provider_derivation"] == "global_minus_native_direct"
    eps = field_provenance("ecmwf_ifs_europe_ensemble")
    assert eps["diffuse_radiation"]["origin"] == "provider_output_native_or_derived_unresolved"
    assert all(field["local_derivation"] is None for field in eps.values())


@pytest.mark.parametrize("case", ["declared_bytes", "boolean_bytes", "chunk_count", "encoded_chunk", "decoded_chunk", "total"])
def test_imported_response_bounds_are_enforced_before_join(monkeypatch, case):
    import scripts.capture_weather as collector

    monkeypatch.setattr(collector, "MAX_RESPONSE_BYTES", 8)
    monkeypatch.setattr(collector, "CHUNK_BYTES", 4)
    reference = {"group_id": "g", "sha256": "x", "byte_count": 8, "event_ids": ["a", "b"], "truncated": False}
    manifest = {"payload": {"raw_response": reference}, "received_at": NOW.isoformat()}
    chunks = [{"kind": "host_weather_response_chunk", "event_id": identifier, "received_at": NOW.isoformat(),
               "payload": {"group_id": "g", "response_sha256": "x", "index": index, "count": 2,
                           "base64": base64.b64encode(b"abcd").decode()}}
              for index, identifier in enumerate(("a", "b"))]
    if case == "declared_bytes":
        reference["byte_count"] = 9
    elif case == "boolean_bytes":
        reference["byte_count"] = True
    elif case == "chunk_count":
        reference["event_ids"].append("c")
    elif case == "encoded_chunk":
        chunks[0]["payload"]["base64"] = "A" * 12
    elif case == "decoded_chunk":
        chunks[0]["payload"]["base64"] = base64.b64encode(b"abcde").decode()
    else:
        reference["byte_count"] = 4
    with pytest.raises(ValueError, match="bound|references"):
        reconstruct_response(manifest, chunks)


def test_response_chunks_and_manifest_use_one_atomic_batch(tmp_path, monkeypatch):
    import scripts.capture_weather as collector

    monkeypatch.setattr(collector, "CHUNK_BYTES", 4)
    journal = ArchiveJournal(tmp_path)
    original_append_many = journal.append_many
    batches = []

    def tracked(events):
        batches.append(events)
        return original_append_many(events)

    monkeypatch.setattr(journal, "append_many", tracked)
    raw = b"ten bytes!"
    manifest = archive_response(journal, {}, raw, NOW, product="dwd_icon_d2_eps", ensemble=True, http_status=503)
    assert len(batches) == 1 and len(batches[0]) == 4
    assert all(item[2] == NOW and item[3] for item in batches[0])
    assert manifest["event_id"] == batches[0][-1][3]
    assert manifest["payload"]["raw_response"]["event_ids"] == [item[3] for item in batches[0][:-1]]
    assert reconstruct_response(manifest, journal.page()["events"]) == raw


def test_manifest_write_failure_rolls_back_response_chunks_and_sequence(tmp_path, monkeypatch):
    import scripts.capture_weather as collector

    monkeypatch.setattr(collector, "CHUNK_BYTES", 4)
    journal = ArchiveJournal(tmp_path)
    before = journal.page()
    with journal._db() as connection:
        connection.execute("""CREATE TRIGGER interrupt_manifest BEFORE INSERT ON events
                              WHEN json_extract(CAST(NEW.raw AS TEXT), '$.kind') = 'host_weather_response'
                              BEGIN SELECT RAISE(ABORT, 'simulated manifest interruption'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="simulated manifest interruption"):
        archive_response(journal, {}, b"ten bytes!", NOW, product="dwd_icon_d2_eps", ensemble=True, http_status=503)
    after = journal.page()
    assert after["events"] == [] and after["next_cursor"] == before["next_cursor"]
