"""Authenticated read-only export pagination and durable collector retries."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import pytest

from custom_components.adaptive_solar.core.archive import ArchiveError, ArchiveJournal, ArchiveStore

spec = importlib.util.spec_from_file_location("archive_collector", Path(__file__).parents[1] / "scripts/archive.py")
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


def response(page, **changes):
    status = {"enabled": True, "state": "active", "last_error": None,
              "dropped_events": 0, "pending_events": 0, "inflight_events": 0, **changes}
    return {"page": page, "producer": collector.producer_status(status)}


class Socket:
    def __init__(self, replies):
        self.replies, self.sent = iter(replies), []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def receive_json(self):
        return next(self.replies)

    async def send_json(self, value):
        self.sent.append(value)


class Client:
    def __init__(self, replies):
        self.socket = Socket(replies)
        self.connected = []

    def ws_connect(self, url, **options):
        self.connected.append((url, options))
        return self.socket


def populated(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal")
    for i in range(3):
        journal.append("weather_response", {"i": i}, NOW)
    return journal


async def test_service_uses_auth_and_only_read_export(tmp_path):
    journal = populated(tmp_path)
    page = journal.page()
    client = Client([{"type": "auth_required"}, {"type": "auth_ok"},
                     {"type": "result", "id": 1, "success": True, "result": {"response": {"page": page, "status": {}}}}])
    result = await collector.fetch_page("https://example.invalid", "private-token", "entry", None, session=client)
    assert result["page"] == page
    assert result["producer"]["state"] == "unknown"  # empty producer evidence is not healthy
    assert client.connected[0][0] == "wss://example.invalid/api/websocket"
    sent = client.socket.sent
    assert sent[0] == {"type": "auth", "access_token": "private-token"}
    assert sent[1] == {"id": 1, "type": "call_service", "domain": "adaptive_solar", "service": "export_archive",
                       "service_data": {"config_entry_id": "entry", "limit": 100, "max_bytes": 2097152}, "return_response": True}


async def test_collector_fetches_next_only_after_durable_checkpoint(tmp_path):
    journal = populated(tmp_path)
    store = ArchiveStore(tmp_path / "host")
    seen = []
    async def fetch(cursor):
        assert store.checkpoint("site") == cursor
        seen.append(cursor)
        return response(journal.page(cursor, limit=1))
    result = await collector.collect(store, "site", fetch)
    assert result["events"] == 3
    assert result["pages"] == 4
    assert result["complete"] and result["collection_end_confirmed"]
    assert len(list(store.iter_events())) == 3
    again = await collector.collect(store, "site", fetch)
    assert again["events"] == 0
    assert store.stats()["batches"] == 3


async def test_interrupted_fetch_restarts_at_last_durable_cursor(tmp_path):
    journal = populated(tmp_path)
    store = ArchiveStore(tmp_path / "host")
    calls = 0
    async def fail_second(cursor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise TimeoutError
        return response(journal.page(cursor, limit=1))
    with pytest.raises(TimeoutError):
        await collector.collect(store, "site", fail_second)
    checkpoint = store.checkpoint("site")
    assert checkpoint.endswith(":1")
    async def remaining(cursor):
        return response(journal.page(cursor, limit=1))
    await collector.collect(ArchiveStore(store.root), "site", remaining)
    assert len(list(store.iter_events())) == 3


@pytest.mark.parametrize("replies", [
    [{"type": "auth_failed"}],
    [{"type": "auth_required"}, {"type": "auth_invalid"}],
    [{"type": "auth_required"}, {"type": "auth_ok"}, {"type": "result", "id": 1, "success": False}],
    [{"type": "auth_required"}, {"type": "auth_ok"}, {"type": "result", "id": True, "success": True}],
])
async def test_bad_handshake_and_service_reply_rejected(tmp_path, replies):
    with pytest.raises(ArchiveError):
        await collector.fetch_page("http://example.invalid", "token", "entry", None, session=Client(replies))


@pytest.mark.parametrize("url", ["file:///tmp/a", "https://user:secret@example.invalid", "http://example.invalid?token=secret", "http://example.invalid:bad"])
def test_private_or_invalid_url_rejected(url):
    with pytest.raises(ArchiveError):
        collector.websocket_url(url)


async def test_collector_bounds_pages_and_reports_gap(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal", max_events=1)
    for i in range(3):
        journal.append("event", {"i": i}, NOW)
    store = ArchiveStore(tmp_path / "host")
    async def fetch(cursor):
        return response(journal.page(cursor))
    result = await collector.collect(store, "site", fetch, max_pages=1)
    assert result["page_limit_reached"]
    assert result["gaps"][0]["reason"] == "retention_or_overflow"
    assert result["events"] == 1
    assert not result["complete"]
    assert "cursor_gap" in result["failures"] and "incomplete_collection" in result["failures"]


async def test_empty_last_allowed_page_confirms_completion_without_false_limit(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal")
    store = ArchiveStore(tmp_path / "host")
    async def fetch(cursor):
        return response(journal.page(cursor))
    result = await collector.collect(store, "site", fetch, max_pages=1)
    assert result["complete"] and not result["page_limit_reached"]


async def test_normal_ring_retention_without_cursor_loss_is_not_an_error(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal", max_events=1)
    for i in range(3):
        journal.append("event", {"i": i}, NOW)
    store = ArchiveStore(tmp_path / "host")
    store.ingest_page("site", journal.page())
    async def fetch(cursor):
        return response(journal.page(cursor), state="gap", dropped_events=2)
    result = await collector.collect(store, "site", fetch)
    assert result["complete"] and not result["gaps"]


def test_cli_reports_partial_collection_and_retains_acknowledged_checkpoint(tmp_path, monkeypatch, capsys):
    journal = populated(tmp_path)
    async def fetch(_url, _token, _entry, cursor, **_):
        return response(journal.page(cursor, limit=1))
    monkeypatch.setattr(collector, "fetch_page", fetch)
    args = ["--root", str(tmp_path / "host"), "collect", "--source", "site", "--entry-id", "entry"]
    assert collector.main([*args, "--max-pages", "1"]) == 1
    import json
    partial = json.loads(capsys.readouterr().out)
    assert partial["page_limit_reached"] and not partial["complete"]
    assert ArchiveStore(tmp_path / "host").checkpoint("site") == partial["cursor"]
    assert collector.main(args) == 0
    complete = json.loads(capsys.readouterr().out)
    assert complete["complete"] and complete["events"] == 2


async def test_producer_write_error_is_preserved_without_raw_error_text(tmp_path):
    page = ArchiveJournal(tmp_path / "journal").page()
    client = Client([{"type": "auth_required"}, {"type": "auth_ok"},
        {"type": "result", "id": 1, "success": True, "result": {"response": {
            "page": page, "status": {"enabled": True, "state": "error", "last_error": "private-token-and-url",
            "dropped_events": 4, "pending_events": 0, "inflight_events": 0}}}}])
    reply = await collector.fetch_page("https://example.invalid", "token", "entry", None, session=client)
    async def fetch(_):
        return reply
    result = await collector.collect(ArchiveStore(tmp_path / "host"), "site", fetch)
    assert not result["complete"] and result["producer"]["error"]
    assert "private-token-and-url" not in str(result)


def test_local_cli_help_and_stats(tmp_path, capsys):
    assert collector.main(["--root", str(tmp_path / "host"), "stats"]) == 0
    assert '"events": 0' in capsys.readouterr().out
    assert collector.main(["--root", str(tmp_path / "host"), "verify"]) == 0


def bounded_response(journal, page, **changes):
    result = response(page, **changes)
    result["newest_cursor"] = collector.newest_cursor(journal.stats())
    return result


async def test_growing_journal_stops_at_first_tail_and_next_run_resumes_durable_cursor(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal")
    for i in range(2):
        journal.append("event", {"i": i}, NOW)
    store = ArchiveStore(tmp_path / "host")
    async def fetch(cursor):
        assert store.checkpoint("site") == cursor
        result = bounded_response(journal, journal.page(cursor, limit=1))
        journal.append("event", {"after_response": cursor}, NOW)
        return result
    first = await collector.collect(store, "site", fetch, max_pages=2)
    assert first["complete"] and first["collection_end_confirmed"] and not first["page_limit_reached"]
    assert first["pages"] == first["events"] == 2
    assert first["cursor"] == first["target_cursor"] == store.checkpoint("site")
    assert first["cursor"].endswith(":2")
    second = await collector.collect(store, "site", fetch, max_pages=2)
    assert second["complete"] and second["events"] == 2 and second["cursor"].endswith(":4")
    assert ArchiveStore(store.root).checkpoint("site") == second["cursor"]
    actual = [{k: v for k, v in e.items() if k != "source"} for e in store.iter_events()]
    assert actual == journal.page(limit=100)["events"][:4]


async def test_initial_backlog_uses_numeric_tail_and_last_allowed_page(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal")
    for i in range(12):
        journal.append("event", {"i": i}, NOW)
    async def fetch(cursor):
        return bounded_response(journal, journal.page(cursor, limit=2))
    result = await collector.collect(ArchiveStore(tmp_path / "host"), "site", fetch, max_pages=6)
    assert result["complete"] and result["pages"] == 6 and result["events"] == 12
    assert not result["page_limit_reached"] and result["cursor"].endswith(":12")


async def test_byte_limited_short_page_is_not_a_tail(tmp_path):
    from custom_components.adaptive_solar.core.archive import canonical_bytes

    journal = ArchiveJournal(tmp_path / "journal")
    for i in range(3):
        journal.append("event", {"i": i, "data": "x" * 300}, NOW)
    # Leave room for the subsequent non-null requested_cursor, not a second event.
    bound = len(canonical_bytes(journal.page(limit=1))) + 64
    async def fetch(cursor):
        page = journal.page(cursor, limit=100, max_bytes=bound)
        assert len(page["events"]) == 1
        return bounded_response(journal, page)
    result = await collector.collect(ArchiveStore(tmp_path / "host"), "site", fetch, max_pages=3)
    assert result["complete"] and result["pages"] == result["events"] == 3


async def test_whole_page_can_overshoot_target_without_trimming_originals(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal")
    for i in range(2):
        journal.append("event", {"i": i}, NOW)
    store = ArchiveStore(tmp_path / "host")
    calls = 0
    async def fetch(cursor):
        nonlocal calls
        calls += 1
        if calls == 2:
            for i in range(2):
                journal.append("event", {"new": i}, NOW)
        return bounded_response(journal, journal.page(cursor, limit=1 if calls == 1 else 100))
    result = await collector.collect(store, "site", fetch)
    assert result["complete"] and result["target_cursor"].endswith(":2") and result["cursor"].endswith(":4")
    assert result["events"] == 4
    assert [{k: v for k, v in e.items() if k != "source"} for e in store.iter_events()] == journal.page()["events"]


async def test_limit_before_fixed_target_retains_checkpoint_for_resume(tmp_path):
    journal = populated(tmp_path)
    store = ArchiveStore(tmp_path / "host")
    async def fetch(cursor):
        return bounded_response(journal, journal.page(cursor, limit=1))
    first = await collector.collect(store, "site", fetch, max_pages=2)
    assert not first["complete"] and first["page_limit_reached"] and not first["collection_end_confirmed"]
    assert first["target_cursor"].endswith(":3") and first["cursor"].endswith(":2")
    second = await collector.collect(ArchiveStore(store.root), "site", fetch, max_pages=1)
    assert second["complete"] and second["events"] == 1


@pytest.mark.parametrize("first_metadata", [None, "invalid", "stale", "other_generation"])
async def test_unusable_first_boundary_stays_legacy_even_when_later_metadata_valid(tmp_path, first_metadata):
    journal = populated(tmp_path)
    calls = 0
    async def fetch(cursor):
        nonlocal calls
        calls += 1
        result = bounded_response(journal, journal.page(cursor, limit=1))
        if calls == 1:
            result["newest_cursor"] = {None: None, "invalid": "bad", "stale": journal.page()["generation"] + ":0",
                                       "other_generation": "00000000-0000-0000-0000-000000000001:999"}[first_metadata]
        journal.append("event", {"new": calls}, NOW)
        return result
    result = await collector.collect(ArchiveStore(tmp_path / "host"), "site", fetch, max_pages=2)
    assert result["target_cursor"] is None and not result["complete"] and result["page_limit_reached"]


async def test_empty_page_before_fixed_target_is_not_completion(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal")
    async def fetch(cursor):
        page = journal.page(cursor)
        return {**response(page), "newest_cursor": page["generation"] + ":2"}
    result = await collector.collect(ArchiveStore(tmp_path / "host"), "site", fetch)
    assert result["target_cursor"].endswith(":2")
    assert not result["collection_end_confirmed"] and not result["complete"]
    assert "incomplete_collection" in result["failures"]


async def test_generation_change_cannot_confirm_old_target_by_numeric_overshoot(tmp_path):
    original = populated(tmp_path)
    replacement = ArchiveJournal(tmp_path / "replacement")
    for i in range(10):
        replacement.append("event", {"new_generation": i}, NOW)
    calls = 0
    async def fetch(cursor):
        nonlocal calls
        calls += 1
        journal = original if calls == 1 else replacement
        return bounded_response(journal, journal.page(cursor, limit=1 if calls == 1 else 100))
    store = ArchiveStore(tmp_path / "host")
    result = await collector.collect(store, "site", fetch)
    assert result["target_cursor"] == original.page()["next_cursor"]
    assert result["cursor"] == replacement.page()["next_cursor"]
    assert not result["collection_end_confirmed"] and not result["complete"]
    assert "cursor_gap" in result["failures"]


@pytest.mark.parametrize("status", [{"pending_events": 1}, {"inflight_events": 1}, {"state": "error", "last_error": "failure"}])
async def test_reaching_target_does_not_bypass_producer_pending_or_error(tmp_path, status):
    journal = populated(tmp_path)
    async def fetch(cursor):
        return bounded_response(journal, journal.page(cursor), **status)
    result = await collector.collect(ArchiveStore(tmp_path / "host"), "site", fetch, max_pages=1)
    assert result["collection_end_confirmed"] and not result["page_limit_reached"] and not result["complete"]


@pytest.mark.parametrize("next_sequence", [None, True, 0, -1, 1.5, "2", 2**63])
def test_newest_cursor_rejects_non_native_or_unbounded_sequence(next_sequence):
    assert collector.newest_cursor({"generation": "00000000-0000-0000-0000-000000000001", "next_sequence": next_sequence}) is None


async def test_partial_new_chunk_group_is_preserved_and_resolves_only_after_resume(tmp_path, monkeypatch):
    from custom_components.adaptive_solar import archive_export
    from custom_components.adaptive_solar.core.replay import hydrate_forecast

    monkeypatch.setattr(archive_export, "MAX_INLINE_BYTES", 1)
    monkeypatch.setattr(archive_export, "CHUNK_BYTES", 20)
    payload = {"issued_at": NOW.isoformat(), "computed_at": NOW.isoformat(), "replay_state": {}, "data": list(range(40))}
    group = archive_export.payload_events("forecast_issued", payload, NOW)
    assert len(group) > 2
    journal = ArchiveJournal(tmp_path / "journal")
    journal.append("event", {"initial": 1}, NOW)
    journal.append("event", {"initial": 2}, NOW)
    calls = 0
    async def fetch(cursor):
        nonlocal calls
        calls += 1
        if calls == 2:
            journal.append_many(group)
        return bounded_response(journal, journal.page(cursor, limit=1 if calls == 1 else 2))
    store = ArchiveStore(tmp_path / "host")
    first = await collector.collect(store, "site", fetch)
    assert first["complete"] and first["target_cursor"].endswith(":2") and first["cursor"].endswith(":3")
    ids = [event[3] for event in group[:-1]]
    with pytest.raises(ArchiveError, match="[Mm]issing"):
        store.resolve_events(ids, source="site", generation=journal.page()["generation"])
    second = await collector.collect(store, "site", fetch)
    assert second["complete"]
    events = list(store.iter_events())
    manifest = next(e for e in events if e["kind"] == "forecast_issued")
    assert hydrate_forecast(manifest, events)["payload"] == payload
    expected = journal.page(limit=100)["events"]
    assert [{k: v for k, v in e.items() if k != "source"} for e in events] == expected


async def test_retention_gap_stays_failure_when_durable_page_reaches_target(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal", max_events=3)
    for i in range(3):
        journal.append("event", {"i": i}, NOW)
    calls = 0
    async def fetch(cursor):
        nonlocal calls
        calls += 1
        if calls == 2:
            for i in range(3):
                journal.append("event", {"new": i}, NOW)
        return bounded_response(journal, journal.page(cursor, limit=1 if calls == 1 else 100))
    result = await collector.collect(ArchiveStore(tmp_path / "host"), "site", fetch)
    assert result["collection_end_confirmed"] and not result["complete"]
    assert result["target_cursor"].endswith(":3") and result["cursor"].endswith(":6")
    assert result["gaps"] == [{"reason": "retention_or_overflow", "from": 2, "to": 3}]
    assert "cursor_gap" in result["failures"]


async def test_earlier_producer_error_stays_sticky_after_healthy_target_page(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal")
    for i in range(2):
        journal.append("event", {"i": i}, NOW)
    calls = 0
    async def fetch(cursor):
        nonlocal calls
        calls += 1
        status = {"last_error": "failure", "state": "error"} if calls == 1 else {}
        return bounded_response(journal, journal.page(cursor, limit=1), **status)
    result = await collector.collect(ArchiveStore(tmp_path / "host"), "site", fetch)
    assert result["collection_end_confirmed"] and not result["producer"]["error"]
    assert result["failures"] == ["producer_error"] and not result["complete"]
