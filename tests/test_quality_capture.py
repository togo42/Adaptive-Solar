"""Reduced stored diagnostics preserve original decisions and dated revisions."""
from copy import deepcopy
from datetime import timedelta
import hashlib
from unittest.mock import AsyncMock

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar.core.archive import ArchiveError, ArchiveJournal, ArchiveStore, canonical_bytes
from scripts import archive_observations, capture_actuals, continuous_quality, quality_capture
from tests.test_actual_quality import rehash
from tests.test_archive_observations import ingest
from tests.test_capture_actuals import capture
from tests.test_continuous_quality import continuous_case, store_case


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def derived(tmp_path, *, negative=False, revision=1):
    case = continuous_case()
    if negative:
        case[0][2]["payload"]["source_binding"]["energy_entity_id"] = "sensor.changed"
        rehash(case[0][2])
    store = store_case(tmp_path, case)
    raw = capture(start=case[3], end=case[4], received=case[-1])
    with freeze_time(case[-1] + timedelta(hours=revision)):
        result = continuous_quality.derive(store, raw, case[1])
    return result


@pytest.mark.parametrize("negative", [False, True])
def test_compact_keeps_masks_raw_dates_pins_and_all_hour_decisions(tmp_path, negative):
    full = derived(tmp_path, negative=negative)
    before = deepcopy(full)
    compact = quality_capture.compact_capture(full)
    report, reduced = full["quality_derivation"], compact["quality_derivation"]
    assert full == before
    assert {k: v for k, v in full.items() if k != "quality_derivation"} == {
        k: v for k, v in compact.items() if k != "quality_derivation"}
    assert reduced["schema"] == quality_capture.COMPACT_SCHEMA
    assert reduced["full_report_sha256"] == digest(report)
    assert reduced["diagnostic_profile"] == quality_capture.COMPACT_PROFILE
    for key in report.keys() - {"schema", "hours", "evidence_events", "configuration_evidence"}:
        assert reduced[key] == report[key]
    for key in ("evidence_events", "configuration_evidence"):
        assert key not in reduced
        assert reduced["omitted_evidence"][key] == {"count": len(report[key]), "sha256": digest(report[key])}
    for old, new in zip(report["hours"], reduced["hours"], strict=True):
        assert "evidence_event_ids" not in new
        assert {k: v for k, v in old.items() if k != "evidence_event_ids"} == {
            k: v for k, v in new.items() if k not in {"evidence_event_count", "evidence_event_ids_sha256"}}
        assert new["evidence_event_count"] == len(old["evidence_event_ids"])
        assert new["evidence_event_ids_sha256"] == digest(old["evidence_event_ids"])
    assert bool([h for h in reduced["hours"] if h["mask_status"] == "invalid"]) == negative


def test_old_and_compact_captures_roundtrip_and_have_identical_record_availability(tmp_path):
    full = derived(tmp_path / "inputs")
    compact = quality_capture.compact_capture(full)
    store = ArchiveStore(tmp_path / "saved")
    journal = ArchiveJournal(tmp_path / "saved-journal")
    archive_observations.append_capture(journal, "actuals", full)
    archive_observations.append_capture(journal, "actuals", compact)
    ingest(journal, store)
    store.pin("mixed-formats")
    saved = list(archive_observations.captures_from_archive(
        ArchiveStore(store.root), source="test", kind="actuals", dataset="mixed-formats"))
    assert saved == [full, compact]
    validated = capture_actuals.utc(full["quality"]["provenance"]["validated_at"])
    for when, count in ((validated - timedelta(microseconds=1), 0), (validated, 2)):
        assert capture_actuals.actual_records_from_captures(saved[:1], as_of=when) == (
            capture_actuals.actual_records_from_captures(saved[1:], as_of=when))
        assert len(capture_actuals.actual_records_from_captures(saved[1:], as_of=when)) == count


def test_negative_later_revision_still_conflicts_with_earlier_records_after_archival(tmp_path):
    first = derived(tmp_path / "first", revision=1)
    later = derived(tmp_path / "later", negative=True, revision=2)
    journal, store = ArchiveJournal(tmp_path / "journal"), ArchiveStore(tmp_path / "saved")
    for value in (first, later):
        archive_observations.append_capture(journal, "actuals", quality_capture.compact_capture(value))
    ingest(journal, store)
    saved = list(archive_observations.captures_from_archive(store, source="test", kind="actuals"))
    before = capture_actuals.utc(later["quality"]["provenance"]["validated_at"]) - timedelta(microseconds=1)
    assert len(capture_actuals.actual_records_from_captures(saved, as_of=before)) == 2
    for values in (saved, [first, later]):
        with pytest.raises(capture_actuals.CaptureError, match="later invalid actual revision"):
            capture_actuals.actual_records_from_captures(values)


@pytest.mark.parametrize("profile", ["full", "compact"])
async def test_compaction_happens_after_full_derivation_before_capture_size_check(tmp_path, monkeypatch, profile):
    full = derived(tmp_path / "input")
    full["quality_derivation"]["evidence_events"] = [{"large_diagnostic": "x" * 100_000}]
    reduced = quality_capture.compact_capture(full)
    assert len(canonical_bytes(reduced)) < 20_000 < len(canonical_bytes(full))
    monkeypatch.setattr(archive_observations, "MAX_CAPTURE_BYTES", 20_000)
    monkeypatch.setattr(archive_observations, "CHUNK_BYTES", 1024)
    monkeypatch.setattr(continuous_quality, "derive", lambda *_: deepcopy(full))
    raw = {key: full[key] for key in ("schema_version", "kind", "capture_id", "retrieved_at", "raw")}
    monkeypatch.setattr(capture_actuals, "capture_actuals", AsyncMock(return_value=raw))
    store = ArchiveStore(tmp_path / "output")
    result = await archive_observations.archive_observations(
        store, source="test", ha_url="", token="", actual_mappings=full["raw"]["mappings"],
        quality_bindings={"provided": True}, quality_diagnostics=profile)
    saved, = archive_observations.captures_from_archive(store, source="test:actuals", kind="actuals")
    assert result["complete"] == (profile == "compact")
    if profile == "compact":
        assert saved == reduced
        assert result["streams"]["actuals"]["quality_summary"]["qualified_hours"] == 2
    else:
        assert saved["normalization_error"] == "invalid_quality_or_raw"


def test_compact_storage_keeps_existing_32mib_limit_and_rejects_chunk_corruption(tmp_path):
    assert archive_observations.MAX_CAPTURE_BYTES == 32 * 1024 * 1024
    full = derived(tmp_path / "input")
    compact = quality_capture.compact_capture(full)
    journal = ArchiveJournal(tmp_path / "journal")
    archive_observations.append_capture(journal, "actuals", compact)
    events = journal.page()["events"]
    events[0]["payload"]["data_base64"] = "e30="
    class CorruptedStore:
        def iter_events(self, **_):
            return iter(events)
    with pytest.raises(ArchiveError, match="digest mismatch"):
        list(archive_observations.captures_from_archive(CorruptedStore(), source="test", kind="actuals"))
    oversized = {**compact, "raw": {"oversized": "x" * archive_observations.MAX_CAPTURE_BYTES}}
    with pytest.raises(ArchiveError, match="bounded archive size"):
        archive_observations.append_capture(journal, "actuals", oversized)


@pytest.mark.parametrize("profile", ["unknown", "", None, []])
async def test_unknown_profile_fails_before_any_capture_or_store_access(profile):
    with pytest.raises(ArchiveError, match="Unknown quality diagnostics"):
        await archive_observations.archive_observations(
            None, source="test", ha_url="", token="", actual_mappings=[{}], quality_diagnostics=profile)


def test_compaction_rejects_unknown_report_schema(tmp_path):
    full = derived(tmp_path)
    full["quality_derivation"]["schema"] = "future-report"
    with pytest.raises(ValueError, match="full quality report"):
        quality_capture.compact_capture(full)
