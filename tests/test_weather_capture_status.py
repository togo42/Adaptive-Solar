"""Weather journal discontinuities reach CLI and systemd host status."""
from datetime import UTC, datetime
import hashlib
import json
import shutil
import subprocess
import sys
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from types import SimpleNamespace

from freezegun import freeze_time
import pytest

from custom_components.adaptive_solar.core.archive import ArchiveJournal, ArchiveStore
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig
from scripts import archive, archive_host as host, capture_weather as weather
from tests.test_ensemble_archive import eps_payload, NOW


def test_flush_reports_generation_change_and_retains_confirmed_checkpoint(tmp_path):
    store = ArchiveStore(tmp_path / "store")
    first = ArchiveJournal(tmp_path / "first")
    first.append("event", {}, datetime(2026, 6, 1, tzinfo=UTC))
    assert weather.flush_journal(first, store, "weather")["complete"]
    second = ArchiveJournal(tmp_path / "second")
    second.append("event", {}, datetime(2026, 6, 1, tzinfo=UTC))
    result = weather.flush_journal(second, store, "weather")
    assert not result["complete"] and result["collection_end_confirmed"]
    assert result["gaps"][0]["reason"] == "generation_changed"
    assert store.checkpoint("weather") == result["cursor"]
    assert len(list(store.iter_events())) == 2
    assert weather.flush_journal(second, store, "weather")["complete"]


@pytest.mark.parametrize("case", ["normal", "generation_gap", "final_limit"])
@freeze_time(NOW)
def test_weather_cli_completion_reaches_host_exit(tmp_path, monkeypatch, capsys, case):
    monkeypatch.setattr(host, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    site = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))
    (tmp_path / "data/site.json").write_text(json.dumps(site.to_dict()))
    root = tmp_path / "data/archive"
    store = ArchiveStore(root)
    if case == "generation_gap":
        key = hashlib.sha256(b"weather").hexdigest()[:16]
        path = root / ("weather-staging-" + key)
        old = ArchiveJournal(path)
        old.append("event", {}, NOW)
        assert weather.flush_journal(old, store, "weather")["complete"]
        shutil.rmtree(path)
    payload = json.dumps(eps_payload()).encode()
    requests = []
    class Response:
        status = 200
        content = None
        def __init__(self): self.content = self
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def iter_chunked(self, _): yield payload
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        def get(self, *_args, **_kwargs):
            requests.append(1)
            return Response()
    monkeypatch.setattr(weather.aiohttp, "ClientSession", lambda **_: Client())
    original = weather.flush_journal
    transfers = []
    def flush(*args, **kwargs):
        if case == "final_limit" and len(transfers) == 1:
            kwargs["max_pages"] = 1
        result = original(*args, **kwargs)
        transfers.append(result)
        return result
    monkeypatch.setattr(weather, "flush_journal", flush)
    config = {"archive": "data/archive", "entries": [], "weather_source": "weather",
              "observations_source": "measurements", "site_json": "data/site.json",
              "min_free_bytes": 20, "operation_reserve_bytes": 10, "max_archive_bytes": 1000000,
              "min_free_percent": 15}
    cfg = tmp_path / "data/host.json"
    cfg.write_text(json.dumps(config))
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    reports = []
    def process(command, **_):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            if command[-1] == "stats":
                code = archive.main(command[2:])
            else:
                monkeypatch.setattr(sys, "argv", [*command[1:], "--deterministic", "", "--ensembles", "dwd_icon_d2_eps"])
                code = weather.main()
                reports.append(json.loads(stdout.getvalue()))
        return subprocess.CompletedProcess(command, code, stdout.getvalue(), stderr.getvalue())
    monkeypatch.setattr(host.subprocess, "run", process)
    code = host.main(["weather", "--config", str(cfg)])
    report = json.loads(capsys.readouterr().out)
    assert (code == 0) == report["complete"] == reports[0]["complete"] == (case == "normal")
    if case == "generation_gap":
        assert reports[0]["recovery"]["gaps"][0]["reason"] == "generation_changed"
        assert not requests
    elif case == "final_limit":
        assert reports[0]["transfers"][0]["page_limit_reached"]
    else:
        assert reports[0]["records"][0]["status"] == "available"
