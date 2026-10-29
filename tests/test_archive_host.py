"""Bounded archive jobs protect disk, credentials and independent source progress."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts import archive_host as host
from scripts import archive as collector


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    return {"archive": "data/archive", "entries": [{"source": "ha-one", "entry_id": "entry-one"},
            {"source": "ha-two", "entry_id": "entry-two"}], "weather_source": "weather-site",
            "observations_source": "measurement-site", "site_json": "data/site.json",
            "actual_config": "data/actuals.json", "min_free_bytes": 20, "operation_reserve_bytes": 10,
            "max_archive_bytes": 1000000, "min_free_percent": 15}


def mock_process(monkeypatch, returncodes):
    commands = []

    def process(command, **kwargs):
        commands.append((command, kwargs))
        if command[-1] == "stats":
            values = {key: 0 for key in ("batches", "events", "compressed_bytes", "index_bytes",
                      "observation_days", "compressed_bytes_per_day", "projected_24_month_compressed_bytes")}
            return subprocess.CompletedProcess(command, 0, json.dumps(values), "")
        body = {"complete": True, "collection_end_confirmed": True, "page_limit_reached": False,
                "pages": 1, "events": 0, "gaps": [], "failures": [],
                "producer": collector.producer_status({"enabled": True, "state": "active", "last_error": None,
                    "dropped_events": 0, "pending_events": 0, "inflight_events": 0})}
        return subprocess.CompletedProcess(command, next(returncodes), json.dumps(body), "private failure")

    monkeypatch.setattr(host.subprocess, "run", process)
    return commands


@pytest.mark.parametrize("free,allowed", [(31, True), (29, False), (14, False)])
def test_capacity_reserves_space_before_start(config, monkeypatch, tmp_path, free, allowed):
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=free, total=100))
    assert host.capacity(tmp_path, config)["allowed"] is allowed


def test_capacity_accounts_for_staging_and_excludes_external_symlinks(config, monkeypatch, tmp_path):
    archive = tmp_path / "data/archive"
    archive.mkdir()
    (archive / "staging").mkdir()
    (archive / "staging/raw").write_bytes(b"x" * 4096)
    outside = tmp_path / "outside"
    outside.write_bytes(b"x" * 8192)
    (archive / "external").symlink_to(outside)
    assert host.archive_size(archive) == (archive / "staging/raw").stat().st_blocks * 512
    config["max_archive_bytes"] = 4096
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=100000, total=100000))
    assert not host.capacity(archive, config)["allowed"]


def test_capacity_stop_keeps_status_and_runs_no_capture(config, monkeypatch, tmp_path):
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=25, total=100))
    commands = mock_process(monkeypatch, iter([]))
    report = host.run("ha", config)
    assert report["reason"] == "capacity_guard" and not report["complete"]
    assert len(commands) == 1 and commands[0][0][-1] == "stats"
    assert json.loads((tmp_path / "data/host-status/ha.json").read_text()) == report


def test_failed_entry_does_not_block_other_entry_or_disclose_raw_output(config, monkeypatch):
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    commands = mock_process(monkeypatch, iter([1, 0]))
    report = host.run("ha", config)
    assert [row["returncode"] for row in report["commands"]] == [1, 0]
    assert not report["complete"]
    assert commands[0][0][-1] == "entry-one" and commands[1][0][-1] == "entry-two"
    assert "private" not in json.dumps(report) and "entry-one" not in json.dumps(report)


def test_runtime_credential_only_enters_child_environment(config, monkeypatch, tmp_path):
    credentials = tmp_path / "runtime-credentials"
    credentials.mkdir()
    (credentials / "ha-auth").write_text(json.dumps({"HA_URL": "http://example.invalid", "HA_TOKEN": "test-secret"}))
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials))
    monkeypatch.delenv("HA_TOKEN", raising=False)
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    commands = mock_process(monkeypatch, iter([0, 0]))
    report = host.run("ha", config)
    assert commands[0][1]["env"]["HA_TOKEN"] == "test-secret"
    assert "test-secret" not in json.dumps(report)
    assert all("test-secret" not in str(row[0]) for row in commands)
    assert "HA_TOKEN" not in host.os.environ


def test_retention_runs_below_capacity_floor(config, monkeypatch):
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=1, total=100))
    commands = mock_process(monkeypatch, iter([0]))
    report = host.run("retention", config)
    assert commands[0][0][-1] == "maintain" and report["complete"]
    assert not report["capacity"]["allowed"]


def test_paths_and_source_collisions_rejected(config, tmp_path):
    with pytest.raises(ValueError, match="private data"):
        host.private_path(tmp_path / "outside.json")
    config["entries"][0]["source"] = "measurement-site:actuals"
    with pytest.raises(ValueError, match="separate"):
        host.commands("ha", config, Path("archive"))


def test_status_reads_real_empty_archive(config, monkeypatch, tmp_path):
    source_scripts = Path(__file__).resolve().parents[1] / "scripts"
    (tmp_path / "scripts").symlink_to(source_scripts, target_is_directory=True)
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    report = host.run("status", config)
    assert report["complete"] and report["archive"]["events"] == 0
    assert (tmp_path / "data/archive/index.sqlite3").is_file()


def test_writer_lock_covers_children_and_timeouts_do_not_block_other_entries(config, monkeypatch, tmp_path):
    import fcntl

    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    process = mock_process(monkeypatch, iter([0]))
    normal = host.subprocess.run
    calls = 0

    def run(command, **kwargs):
        nonlocal calls
        calls += 1
        with (tmp_path / "data/host-status/writer.lock").open("a") as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if calls == 1:
            raise subprocess.TimeoutExpired(command, 1200)
        return normal(command, **kwargs)

    monkeypatch.setattr(host.subprocess, "run", run)
    report = host.run("ha", config)
    assert calls == 3 and process[0][0][-1] == "entry-two"
    assert not report["complete"]
    assert report["commands"][0] == {"returncode": None, "status": "failed_or_timed_out"}
    assert report["commands"][1]["returncode"] == 0 and report["commands"][1]["collector"]["complete"]


@pytest.mark.parametrize("case", ["cursor_gap", "page_limit", "producer_error", "producer_pending", "producer_unavailable", "normal_retention"])
def test_real_collector_cli_reaches_host_exit_status_without_private_messages(config, monkeypatch, tmp_path, case, capsys):
    from contextlib import redirect_stdout, redirect_stderr
    from io import StringIO
    from datetime import UTC, datetime
    from custom_components.adaptive_solar.core.archive import ArchiveJournal, ArchiveStore

    config["entries"] = config["entries"][:1]
    journal = ArchiveJournal(tmp_path / "journal", max_events=1)
    for n in range(3):
        journal.append("event", {"n": n}, datetime(2026, 10, 29, tzinfo=UTC))
    archive = tmp_path / "data/archive"
    store = ArchiveStore(archive)
    if case != "cursor_gap":
        store.ingest_page("ha-one", journal.page())
    if case == "page_limit":
        journal.append("event", {"n": 4}, datetime(2026, 10, 29, tzinfo=UTC))
    raw = {"enabled": True, "state": "gap", "last_error": None, "dropped_events": 2,
           "pending_events": 0, "inflight_events": 0}
    if case == "producer_error":
        raw.update(state="error", last_error="private-endpoint-and-credential")
    elif case == "producer_pending":
        raw["pending_events"] = 1
    async def fetch(_url, _token, _entry, cursor, **_):
        return {"page": None if case == "producer_unavailable" else journal.page(cursor),
                "producer": collector.producer_status(raw)}
    monkeypatch.setattr(collector, "fetch_page", fetch)
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    def process(command, **_):
        stdout, stderr = StringIO(), StringIO()
        args = command[2:]
        if case == "page_limit" and "collect" in args:
            args = [*args, "--max-pages", "1"]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = collector.main(args)
        return subprocess.CompletedProcess(command, code, stdout.getvalue(), stderr.getvalue())
    monkeypatch.setattr(host.subprocess, "run", process)
    cfg = tmp_path / "data/host.json"
    cfg.write_text(json.dumps(config))
    code = host.main(["ha", "--config", str(cfg)])
    report = json.loads(capsys.readouterr().out)
    summary = report["commands"][0]["collector"]
    assert (code == 0) == (case == "normal_retention")
    assert report["complete"] == summary["complete"] == (case == "normal_retention")
    assert "private-endpoint-and-credential" not in json.dumps(report)
    assert "ha-one" not in json.dumps(report)
    assert store.checkpoint("ha-one") == journal.page(store.checkpoint("ha-one"))["next_cursor"]


def test_success_exit_without_verified_collector_evidence_is_not_complete(config, monkeypatch):
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    mock_process(monkeypatch, iter([0, 0]))
    normal = host.subprocess.run
    def process(command, **kwargs):
        result = normal(command, **kwargs)
        if "collect" in command:
            return subprocess.CompletedProcess(command, 0, "private unstructured output", "")
        return result
    monkeypatch.setattr(host.subprocess, "run", process)
    report = host.run("ha", config)
    assert not report["complete"]
    assert all(row["status"] == "invalid_collector_status" for row in report["commands"])
