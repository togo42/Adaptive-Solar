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
