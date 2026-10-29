"""Prospective policies never renew themselves or qualify legacy intervals."""
from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar.core.actual_quality import CONTINUOUS_BINDINGS_SCHEMA
from custom_components.adaptive_solar.core.archive import ArchiveJournal, ArchiveStore
from scripts import archive_observations, capture_actuals, continuous_quality
from tests.test_actual_quality import quality_case, rehash, run_case
from tests.test_archive_observations import ingest
from tests.test_capture_actuals import capture


def continuous_case():
    case = quality_case()
    row = case[1]["bindings"][0]
    case[1]["schema"] = CONTINUOUS_BINDINGS_SCHEMA
    row["valid_to"] = (case[-1] + timedelta(days=7)).isoformat()
    for facet in row["qualification"].values():
        facet["validated_at"] = (case[3] - timedelta(hours=2)).isoformat()
    for event in case[0][1:]:
        event["payload"]["source_binding"] = {"schema": 1, "energy_entity_id": row["statistic_id"],
                                              "config_sha256": row["config_sha256"], "producer_sha256": row["producer_sha256"]}
        rehash(event)
    return case


def store_case(tmp_path, case):
    journal = ArchiveJournal(tmp_path / "journal")
    # Native envelope IDs and generation must be those of the actual journal.
    old_anchor = case[1]["bindings"][0]["config_event_id"]
    for event in case[0]:
        result = journal.append(event["kind"], event["payload"], capture_actuals.utc(event["received_at"]), event["event_id"])
        if event["event_id"] == old_anchor:
            case[1]["bindings"][0]["generation"] = result["generation"]
    store = ArchiveStore(tmp_path / "archive")
    ingest(journal, store, "test-source")
    return store


def test_future_policy_is_conditional_and_legacy_v1_stays_elapsed():
    case = continuous_case()
    assert run_case(case)["summary"]["roof"]["qualified_hours"] == 2
    case[1]["schema"] = "adaptive-solar-actual-quality-bindings-v1"
    with pytest.raises(ValueError, match="elapsed"):
        run_case(case)


@pytest.mark.parametrize("field,value", [("config_sha256", "b" * 64), ("producer_sha256", "b" * 64),
                                         ("energy_entity_id", "sensor.other"), ("schema", True)])
def test_interval_source_drift_invalidates_even_with_positive_policy(field, value):
    case = continuous_case()
    case[0][2]["payload"]["source_binding"][field] = value
    rehash(case[0][2])
    report = run_case(case)
    assert report["hours"][0]["mask_status"] == "invalid"
    assert "contradictory_interval_source_binding" in report["hours"][0]["reasons"]


def test_old_intervals_cannot_extend_prospective_policy():
    case = continuous_case()
    del case[0][2]["payload"]["source_binding"]
    rehash(case[0][2])
    report = run_case(case)
    assert report["hours"][0]["mask_status"] == "omitted"
    assert "missing_interval_source_binding" in report["hours"][0]["reasons"]


def test_expired_policy_and_unverified_meter_do_not_release_new_hours():
    case = continuous_case()
    case[1]["bindings"][0]["valid_to"] = case[3].isoformat()
    assert run_case(case)["quality"]["intervals"] == []
    case = continuous_case()
    case[1]["bindings"][0]["qualification"]["meter"]["verified"] = False
    assert run_case(case)["quality"]["intervals"] == []


def test_derive_preserves_raw_and_dates_quality_at_real_execution(tmp_path):
    case = continuous_case()
    store = store_case(tmp_path, case)
    raw = capture(start=case[3], end=case[4], received=case[-1])
    before = deepcopy(raw)
    with freeze_time(case[-1] + timedelta(hours=2)):
        derived = continuous_quality.derive(store, raw, case[1])
    assert raw == before
    assert derived["raw"] == raw["raw"] and derived["retrieved_at"] == raw["retrieved_at"]
    assert len(derived["normalization"]["records"]) == 2
    assert derived["quality_derivation"]["bindings"] == case[1]
    assert derived["quality_derivation"]["raw_capture_sha256"]
    assert len(capture_actuals.actual_records_from_captures([derived])) == 2
    assert capture_actuals.actual_records_from_captures([derived], as_of=case[-1]) == []


async def test_repeated_observation_capture_archives_fresh_quality_and_raw(tmp_path, monkeypatch):
    case = continuous_case()
    store = store_case(tmp_path, case)
    raw = capture(start=case[3], end=case[4], received=case[-1])
    monkeypatch.setattr(capture_actuals, "capture_actuals", AsyncMock(return_value=raw))
    for n in range(2):
        with freeze_time(case[-1] + timedelta(hours=n + 1), real_asyncio=True):
            report = await archive_observations.archive_observations(store, source="test", ha_url="", token="",
                actual_mappings=case[2], quality_bindings=case[1], now=case[-1], lookback_hours=2)
        assert report["complete"]
        assert report["streams"]["actuals"]["quality_summary"]["qualified_hours"] == 2
    archived = list(archive_observations.captures_from_archive(store, source="test:actuals", kind="actuals"))
    assert len(archived) == 2
    assert archived[0]["quality"]["provenance"]["validated_at"] != archived[1]["quality"]["provenance"]["validated_at"]
    assert all(row["raw"] == raw["raw"] for row in archived)


async def test_quality_failure_still_archives_raw_and_flags_job(tmp_path, monkeypatch):
    case = continuous_case()
    store = store_case(tmp_path, case)
    raw = capture(start=case[3], end=case[4], received=case[-1])
    monkeypatch.setattr(capture_actuals, "capture_actuals", AsyncMock(return_value=raw))
    monkeypatch.setattr(continuous_quality, "MAX_BYTES", 1)
    with freeze_time(case[-1], real_asyncio=True):
        report = await archive_observations.archive_observations(store, source="test", ha_url="", token="",
            actual_mappings=case[2], quality_bindings=case[1], now=case[-1], lookback_hours=2)
    assert not report["complete"]
    assert report["streams"]["actuals"]["current_capture_confirmed"]
    archived = list(archive_observations.captures_from_archive(store, source="test:actuals", kind="actuals"))
    assert archived[0]["raw"] == raw["raw"] and archived[0]["quality"] is None


@pytest.mark.parametrize("date,hours", [("2026-03-29", 23), ("2026-10-25", 25)])
def test_continuous_policy_preserves_both_dst_days(date, hours):
    from datetime import datetime, UTC
    from zoneinfo import ZoneInfo

    case = continuous_case()
    new_start = datetime.fromisoformat(date).replace(tzinfo=ZoneInfo("Europe/Berlin")).astimezone(UTC)
    original = quality_case(new_start, hours=hours)
    original[1]["schema"] = CONTINUOUS_BINDINGS_SCHEMA
    for event in original[0][1:]:
        event["payload"]["source_binding"] = deepcopy(case[0][1]["payload"]["source_binding"])
        rehash(event)
    assert run_case(original)["summary"]["roof"]["qualified_hours"] == hours


def test_local_rehearsal_cli_writes_reviewable_capture_and_rejects_alias(tmp_path, capsys):
    import json

    case = continuous_case()
    store = store_case(tmp_path, case)
    policy, raw, output = (tmp_path / name for name in ("policy.json", "raw.json", "derived.json"))
    policy.write_text(json.dumps(case[1]))
    raw.write_text(json.dumps(capture(start=case[3], end=case[4], received=case[-1])))
    original = raw.read_bytes()
    args = ["--archive", str(store.root), "--bindings", str(policy), "--actual-capture", str(raw), "--output"]
    assert continuous_quality.main(args + [str(raw)]) == 2
    assert raw.read_bytes() == original
    assert continuous_quality.main(args + [str(output)]) == 0
    assert len(json.loads(output.read_text())["normalization"]["records"]) == 2
    assert "local_quality_rehearsal" in capsys.readouterr().out


def test_chunked_configuration_anchor_is_resolved_from_originals(tmp_path, monkeypatch):
    from custom_components.adaptive_solar import archive_export

    case = continuous_case()
    journal = ArchiveJournal(tmp_path / "journal")
    anchor = case[0][0]
    monkeypatch.setattr(archive_export, "MAX_INLINE_BYTES", 1)
    for kind, payload, stamp, identifier in archive_export.payload_events(
            anchor["kind"], anchor["payload"], capture_actuals.utc(anchor["received_at"]), anchor["event_id"]):
        result = journal.append(kind, payload, stamp, identifier)
    case[1]["bindings"][0]["generation"] = result["generation"]
    for event in case[0][1:]:
        journal.append(event["kind"], event["payload"], capture_actuals.utc(event["received_at"]), event["event_id"])
    store = ArchiveStore(tmp_path / "store")
    ingest(journal, store, "test-source")
    raw = capture(start=case[3], end=case[4], received=case[-1])
    assert len(continuous_quality.derive(store, raw, case[1])["normalization"]["records"]) == 2


def test_existing_negative_mask_cannot_be_automatically_released(tmp_path):
    from tests.test_capture_actuals import mask
    from scripts.qualify_actuals import ExistingQualityConflict

    case = continuous_case()
    store = store_case(tmp_path, case)
    raw = capture(start=case[3], end=case[4], received=case[-1])
    normalized = capture_actuals.normalize_capture(raw, mask(quality="invalid"))
    with pytest.raises(ExistingQualityConflict):
        continuous_quality.derive(store, normalized, case[1])


async def test_oversized_quality_report_preserves_smaller_raw_capture(tmp_path, monkeypatch):
    from custom_components.adaptive_solar.core.archive import canonical_bytes

    case = continuous_case()
    store = store_case(tmp_path, case)
    raw = capture(start=case[3], end=case[4], received=case[-1])
    monkeypatch.setattr(capture_actuals, "capture_actuals", AsyncMock(return_value=raw))
    original_limit = archive_observations.MAX_CAPTURE_BYTES
    # Fits raw plus error metadata, but not a complete evidence-rich derivation.
    monkeypatch.setattr(archive_observations, "MAX_CAPTURE_BYTES", len(canonical_bytes(raw)) + 1000)
    with freeze_time(case[-1], real_asyncio=True):
        result = await archive_observations.archive_observations(store, source="test", ha_url="", token="",
            actual_mappings=case[2], quality_bindings=case[1], now=case[-1], lookback_hours=2)
    assert not result["complete"]
    assert result["streams"]["actuals"]["current_capture_confirmed"]
    monkeypatch.setattr(archive_observations, "MAX_CAPTURE_BYTES", original_limit)
    archived, = archive_observations.captures_from_archive(store, source="test:actuals", kind="actuals")
    assert archived["raw"] == raw["raw"] and "quality_derivation" not in archived


@pytest.mark.parametrize("alias", ["same", "symlink", "hardlink"])
@pytest.mark.parametrize("module", [continuous_quality, continuous_quality.actual_quality, capture_actuals, continuous_quality.qualify_actuals])
def test_rehearsal_cannot_overwrite_implementation_files(tmp_path, monkeypatch, alias, module):
    import json
    import os

    case = continuous_case()
    store = store_case(tmp_path, case)
    policy, raw = tmp_path / "policy.json", tmp_path / "raw.json"
    policy.write_text(json.dumps(case[1]))
    raw.write_text(json.dumps(capture(start=case[3], end=case[4], received=case[-1])))
    # Substitute a disposable program file; a regression must never damage the real helper.
    protected = tmp_path / "program.py"
    protected.write_text("# original program bytes\n")
    monkeypatch.setattr(module, "__file__", str(protected))
    output = protected if alias == "same" else tmp_path / "output.json"
    if alias == "symlink":
        output.symlink_to(protected)
    elif alias == "hardlink":
        os.link(protected, output)
    monkeypatch.setattr(continuous_quality, "derive", lambda *args: pytest.fail("aliased output must fail before derivation"))
    assert continuous_quality.main(["--archive", str(store.root), "--bindings", str(policy),
                                   "--actual-capture", str(raw), "--output", str(output)]) == 2
    assert protected.read_text() == "# original program bytes\n"


def test_rehearsal_rechecks_program_alias_after_derivation(tmp_path, monkeypatch):
    import json
    import os

    case = continuous_case()
    store = store_case(tmp_path, case)
    policy, raw, output = (tmp_path / name for name in ("policy.json", "raw.json", "output.json"))
    policy.write_text(json.dumps(case[1]))
    raw.write_text(json.dumps(capture(start=case[3], end=case[4], received=case[-1])))
    protected = tmp_path / "program.py"
    protected.write_text("# protected bytes\n")
    monkeypatch.setattr(continuous_quality, "__file__", str(protected))
    original_derive = continuous_quality.derive

    def derive_then_alias(*args):
        result = original_derive(*args)
        os.link(protected, output)
        return result

    monkeypatch.setattr(continuous_quality, "derive", derive_then_alias)
    assert continuous_quality.main(["--archive", str(store.root), "--bindings", str(policy),
                                   "--actual-capture", str(raw), "--output", str(output)]) == 2
    assert protected.read_text() == "# protected bytes\n"


@pytest.mark.parametrize("phase", ["coverage", "hashing"])
def test_slow_quality_derivation_is_only_available_after_it_completes(tmp_path, monkeypatch, phase):
    case = continuous_case()
    store = store_case(tmp_path, case)
    raw = capture(start=case[3], end=case[4], received=case[-1])
    original = continuous_quality.actual_quality._hour
    with freeze_time(case[-1] + timedelta(hours=2)) as clock:
        started = capture_actuals.utc(raw["retrieved_at"]) + timedelta(hours=2)

        def slow_hour(*args):
            result = original(*args)
            clock.tick(delta=timedelta(seconds=10))
            return result

        if phase == "coverage":
            monkeypatch.setattr(continuous_quality.actual_quality, "_hour", slow_hour)
        else:
            digest = continuous_quality.actual_quality.digest

            def slow_digest(value):
                result = digest(value)
                if isinstance(value, list) and value and "event_id" in value[0]:
                    clock.tick(delta=timedelta(seconds=20))
                return result

            monkeypatch.setattr(continuous_quality.actual_quality, "digest", slow_digest)
        result = continuous_quality.derive(store, raw, case[1])
        finished = capture_actuals.utc(result["normalized_at"])
    assert finished == started + timedelta(seconds=20)
    assert result["quality_derivation"]["generated_at"] == result["quality"]["provenance"]["validated_at"] == finished.isoformat()
    assert capture_actuals.actual_records_from_captures([result], as_of=started + timedelta(seconds=15)) == []
    assert len(capture_actuals.actual_records_from_captures([result], as_of=finished)) == 2


def test_clock_moving_backwards_during_quality_derivation_fails_closed(tmp_path, monkeypatch):
    case = continuous_case()
    store = store_case(tmp_path, case)
    raw = capture(start=case[3], end=case[4], received=case[-1])
    original = continuous_quality.actual_quality._hour
    with freeze_time(case[-1] + timedelta(hours=2)) as clock:
        def backwards(*args):
            result = original(*args)
            clock.tick(delta=timedelta(seconds=-1))
            return result

        monkeypatch.setattr(continuous_quality.actual_quality, "_hour", backwards)
        with pytest.raises(ValueError, match="clock moved backwards"):
            continuous_quality.derive(store, raw, case[1])
