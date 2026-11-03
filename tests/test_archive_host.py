"""Bounded archive jobs protect disk, credentials and independent source progress."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts import archive_host as host
from scripts import archive as collector
from scripts import replay_paths


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
    assert report["commands"][0] == {"returncode": None, "status": "failed_or_timed_out",
                                      "exit_kind": "timeout", "timeout_seconds": 1200}
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


def test_growing_native_journal_completes_fixed_prefix_through_host_cli(config, monkeypatch, tmp_path, capsys):
    from contextlib import redirect_stderr, redirect_stdout
    from datetime import UTC, datetime
    from io import StringIO

    from custom_components.adaptive_solar.core.archive import ArchiveJournal, ArchiveStore

    config["entries"] = config["entries"][:1]
    journal = ArchiveJournal(tmp_path / "journal")
    now = datetime(2026, 10, 29, tzinfo=UTC)
    for n in range(2):
        journal.append("event", {"n": n}, now)
    generation = journal.stats()["generation"]
    exported = []

    class NativeSocket:
        def __init__(self):
            self.sent, self.step = [], 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send_json(self, value):
            self.sent.append(value)

        async def receive_json(self):
            self.step += 1
            if self.step == 1:
                return {"type": "auth_required"}
            if self.step == 2:
                return {"type": "auth_ok"}
            request = self.sent[-1]
            assert request["domain"] == "adaptive_solar" and request["service"] == "export_archive"
            cursor = request["service_data"].get("cursor")
            page = journal.page(cursor, limit=1)
            status = {**journal.stats(), "enabled": True, "state": "active", "last_error": None,
                      "pending_events": 0, "inflight_events": 0}
            exported.append(page)
            # The source keeps advancing after every snapshot. No empty page is ever available.
            journal.append("event", {"arrived_after_snapshot": len(exported)}, now)
            return {"type": "result", "id": 1, "success": True,
                    "result": {"response": {"page": page, "status": status}}}

    class NativeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def ws_connect(self, *_args, **_kwargs):
            return NativeSocket()

    monkeypatch.setattr(collector.aiohttp, "ClientSession", NativeClient)
    monkeypatch.setenv("HA_URL", "https://example.invalid")
    monkeypatch.setenv("HA_TOKEN", "private-collector-token")
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))

    def process(command, **_kwargs):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = collector.main(command[2:])
        return subprocess.CompletedProcess(command, code, stdout.getvalue(), stderr.getvalue())

    monkeypatch.setattr(host.subprocess, "run", process)
    cfg = tmp_path / "data/host.json"
    cfg.write_text(json.dumps(config))
    assert host.main(["ha", "--config", str(cfg)]) == 0
    report = json.loads(capsys.readouterr().out)
    summary = report["commands"][0]["collector"]
    assert report["complete"] and summary["complete"] and summary["end_confirmed"]
    assert summary["pages"] == summary["events"] == len(exported) == 2
    assert not summary["page_limit_reached"] and not summary["failures"]
    assert all(page["events"] for page in exported)
    store = ArchiveStore(tmp_path / "data/archive")
    checkpoint = store.checkpoint("ha-one")
    assert checkpoint == exported[-1]["next_cursor"] == f"{generation}:2"
    originals = [{key: value for key, value in event.items() if key != "source"}
                 for event in store.iter_events(source="ha-one")]
    assert originals == [page["events"][0] for page in exported]
    assert journal.stats()["next_sequence"] == 5
    serialized = json.dumps(report)
    assert all(private not in serialized for private in
               ("ha-one", "entry-one", generation, checkpoint, "private-collector-token", "example.invalid"))


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


def test_continuous_quality_is_opt_in_and_cannot_mix_with_static_mask(config):
    config["quality_bindings"] = "data/quality-policy.json"
    command, = host.commands("observations", config, Path("archive"))
    assert command[command.index("--quality-bindings") + 1].endswith("data/quality-policy.json")
    config["quality"] = "data/static.json"
    with pytest.raises(ValueError, match="static quality"):
        host.commands("observations", config, Path("archive"))


@pytest.fixture
def native_config(config):
    config.update(reference_config="data/references.json", quality_bindings="data/bindings.json",
                  quality_backend_manifest="data/native-quality.json", quality_backend_manifest_sha256="a" * 64)
    return config


def native_quality_status():
    return {"schema": "adaptive-solar-native-quality-runtime-status-v1", "requested_backend": "rust",
            "effective_backend": "rust", "protocol_version": 2, "closed": True,
            "sources_projected": 1, "source_fallbacks": 0, "fallback_reasons": {},
            "original_files": 3, "original_events": 20, "selected_events": 10, "configuration_proofs": 1,
            "binary_sha256": "b" * 64, "manifest_sha256": "a" * 64, "source_manifest_sha256": "c" * 64}


@pytest.mark.parametrize("job", host.JOBS)
def test_native_activation_is_forwarded_only_to_actual_stream_jobs(native_config, tmp_path, job):
    commands = host.commands(job, native_config, Path("archive"))
    native_jobs = job in {"actuals", "observations"}
    assert any("--quality-backend-manifest" in command for command in commands) is native_jobs
    assert any("--quality-backend-manifest-sha256" in command for command in commands) is native_jobs
    if native_jobs:
        command, = commands
        assert command[command.index("--quality-backend-manifest") + 1] == str(tmp_path / "data/native-quality.json")
        assert command[command.index("--quality-backend-manifest-sha256") + 1] == "a" * 64
        assert "--quality-bindings" in command and "--actual-config" in command


@pytest.mark.parametrize("job", ["actuals", "observations"])
@pytest.mark.parametrize("missing", ["quality_backend_manifest", "quality_backend_manifest_sha256", "quality_bindings", "actual_config"])
def test_partial_native_activation_blocks_actual_jobs_without_affecting_references(native_config, job, missing):
    native_config.pop(missing)
    with pytest.raises(ValueError):
        host.commands(job, native_config, Path("archive"))
    command, = host.commands("references", native_config, Path("archive"))
    assert "--quality-backend-manifest" not in command and "--quality-bindings" not in command


@pytest.mark.parametrize("pin", [None, True, "A" * 64, "a" * 63, "not-a-hash"])
def test_invalid_native_manifest_pin_is_rejected_before_command_start(native_config, pin):
    native_config["quality_backend_manifest_sha256"] = pin
    with pytest.raises(ValueError, match="manifest/SHA256"):
        host.commands("actuals", native_config, Path("archive"))


@pytest.mark.parametrize("effective", ["rust", "python", "not_used"])
def test_parent_persists_only_bound_backend_status_and_drops_private_child_output(native_config, monkeypatch, tmp_path, effective):
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    mock_process(monkeypatch, iter([]))
    stats_process = host.subprocess.run
    value = native_quality_status()
    value["effective_backend"] = effective
    if effective != "rust":
        for field in ("sources_projected", "original_files", "original_events", "selected_events", "configuration_proofs"):
            value[field] = 0
        if effective == "python":
            value.update(source_fallbacks=1, fallback_reasons={"unsupported_source": 1})

    def process(command, **kwargs):
        if command[-1] == "stats":
            return stats_process(command, **kwargs)
        body = {"complete": True, "quality_backend": value, "raw": "private-token-and-input-identifiers"}
        return subprocess.CompletedProcess(command, 0, json.dumps(body), "private-token-and-error")

    monkeypatch.setattr(host.subprocess, "run", process)
    report = host.run("actuals", native_config)
    assert report["complete"] and report["quality_backend"] == value
    assert json.loads((tmp_path / "data/host-status/actuals.json").read_text()) == report
    runtime = json.loads((tmp_path / "data/host-status/actuals-runtime.json").read_text())
    assert "private-token" not in json.dumps([report, runtime])
    assert "raw" not in report


@pytest.mark.parametrize("fault", ["missing", "none", "string", "extra_private", "open", "manifest", "hash", "backend",
                                   "bool_protocol", "bool_counter", "negative_counter", "huge_counter", "float_counter",
                                   "private_reason", "bool_reason", "reason_sum", "reason_list"])
def test_parent_never_acknowledges_invalid_or_missing_backend_status(native_config, monkeypatch, tmp_path, fault):
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    mock_process(monkeypatch, iter([]))
    stats_process = host.subprocess.run
    value = native_quality_status()
    if fault == "none":
        value = None
    elif fault == "string":
        value = "private-token-from-child"
    elif fault == "extra_private":
        value["credential"] = "private-token-from-child"
    elif fault == "open":
        value["closed"] = False
    elif fault == "manifest":
        value["manifest_sha256"] = "f" * 64
    elif fault == "hash":
        value["binary_sha256"] = "private-token-from-child"
    elif fault == "backend":
        value["effective_backend"] = "private-token-from-child"
    elif fault == "bool_protocol":
        value["protocol_version"] = True
    elif fault.endswith("counter"):
        value["selected_events"] = {"bool_counter": True, "negative_counter": -1,
                                    "huge_counter": 2**63, "float_counter": 1.0}[fault]
    elif fault == "private_reason":
        value.update(source_fallbacks=1, fallback_reasons={"private-token-from-child": 1})
    elif fault == "bool_reason":
        value.update(source_fallbacks=1, fallback_reasons={"unsupported_source": True})
    elif fault == "reason_sum":
        value["fallback_reasons"] = {"unsupported_source": 1}
    elif fault == "reason_list":
        value["fallback_reasons"] = ["private-token-from-child"]

    calls = []

    def process(command, **kwargs):
        calls.append(command)
        if command[-1] == "stats":
            return stats_process(command, **kwargs)
        body = {"complete": True, "private": "private-token-from-child"}
        if fault != "missing":
            body["quality_backend"] = value
        return subprocess.CompletedProcess(command, 0, json.dumps(body), "private-token-from-stderr")

    monkeypatch.setattr(host.subprocess, "run", process)
    report = host.run("actuals", native_config)
    assert not report["complete"] and "quality_backend" not in report
    assert report["commands"][0]["status"] == "invalid_quality_backend_status"
    assert len(calls) == 2 and calls[-1][-1] == "stats"
    runtime = json.loads((tmp_path / "data/host-status/actuals-runtime.json").read_text())
    assert "private-token" not in json.dumps([report, runtime])


def test_backend_status_copy_does_not_alias_child_fallback_counts():
    value = native_quality_status()
    value.update(effective_backend="python", source_fallbacks=1, fallback_reasons={"custom_reader": 1})
    accepted = host.quality_backend_status(value, "a" * 64)
    value["fallback_reasons"]["custom_reader"] = 123
    assert accepted["fallback_reasons"] == {"custom_reader": 1}


def test_activation_manifest_is_protected_from_host_status_output(native_config, tmp_path):
    target = tmp_path / "data/host-status/actuals.json"
    target.parent.mkdir()
    target.write_text("immutable activation manifest bytes")
    native_config["quality_backend_manifest"] = "data/host-status/actuals.json"
    with pytest.raises(ValueError):
        host.run("actuals", native_config)
    assert target.read_text() == "immutable activation manifest bytes"
    assert not (tmp_path / "data/archive").exists()


def test_activation_manifest_must_remain_private_before_host_creates_archive(native_config, tmp_path):
    native_config["quality_backend_manifest"] = str(tmp_path / "outside-data.json")
    with pytest.raises(ValueError, match="private data"):
        host.run("actuals", native_config)
    assert not (tmp_path / "data/archive").exists()


@pytest.mark.parametrize("job", ["actuals", "references", "observations"])
def test_observation_jobs_select_only_their_stream_and_preserve_window(config, job):
    config.update(reference_config="data/references.json", quality_bindings="data/quality-policy.json")
    command, = host.commands(job, config, Path("archive"))
    assert command[command.index("--source") + 1] == "measurement-site"
    assert command[command.index("--lookback-hours") + 1] == "72"
    assert command[command.index("--lag-minutes") + 1] == "10"
    assert ("--actual-config" in command) == (job != "references")
    assert ("--quality-bindings" in command) == (job != "references")
    assert ("--reference-config" in command) == (job != "actuals")
    assert "--quality-diagnostics" not in command  # Omission preserves the CLI's full default.


@pytest.mark.parametrize("job,required,other", [
    ("actuals", "actual_config", "reference_config"),
    ("references", "reference_config", "actual_config"),
])
def test_separate_observation_job_requires_its_own_mapping(config, job, required, other):
    config.pop(required, None)
    config[other] = "data/other-mapping.json"
    with pytest.raises(ValueError, match="mapping required"):
        host.commands(job, config, Path("archive"))


@pytest.mark.parametrize("job", ["actuals", "observations"])
@pytest.mark.parametrize("profile", ["compact", "full"])
def test_actual_jobs_forward_explicit_quality_diagnostics(config, job, profile):
    config["quality_diagnostics"] = profile
    command, = host.commands(job, config, Path("archive"))
    assert command[command.index("--quality-diagnostics") + 1] == profile


@pytest.mark.parametrize("profile", [None, False, [], "unknown"])
def test_bad_quality_diagnostics_blocks_actuals_but_not_references(config, profile):
    config.update(reference_config="data/references.json", quality_diagnostics=profile)
    with pytest.raises(ValueError, match="diagnostics profile"):
        host.commands("actuals", config, Path("archive"))
    command, = host.commands("references", config, Path("archive"))
    assert "--quality-diagnostics" not in command


@pytest.mark.parametrize("job", ["actuals", "observations"])
def test_actual_jobs_reject_conflicting_quality_inputs(config, job):
    config.update(quality="data/static.json", quality_bindings="data/bindings.json")
    with pytest.raises(ValueError, match="static quality"):
        host.commands(job, config, Path("archive"))


def test_separate_jobs_keep_private_credentials_and_independent_failure_receipts(config, monkeypatch, tmp_path):
    credentials = tmp_path / "runtime-credentials"
    credentials.mkdir()
    (credentials / "ha-auth").write_text(json.dumps({"HA_URL": "http://example.invalid", "HA_TOKEN": "test-secret"}))
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials))
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    config.update(reference_config="data/references.json", quality_bindings="data/bindings.json")
    commands = mock_process(monkeypatch, iter([1, 0]))
    actuals = host.run("actuals", config)
    references = host.run("references", config)
    assert not actuals["complete"] and references["complete"]
    assert json.loads((tmp_path / "data/host-status/actuals.json").read_text()) == actuals
    assert json.loads((tmp_path / "data/host-status/references.json").read_text()) == references
    assert not (tmp_path / "data/host-status/observations.json").exists()
    captures = [row for row in commands if row[0][-1] != "stats"]
    assert len(captures) == 2
    assert all(row[1]["env"]["HA_TOKEN"] == "test-secret" for row in captures)
    assert "--reference-config" not in captures[0][0]
    assert "--actual-config" not in captures[1][0] and "--quality-bindings" not in captures[1][0]
    assert all(private not in json.dumps([actuals, references]) for private in
               ("test-secret", "example.invalid", "measurement-site", "bindings.json"))


def archived_original(tmp_path):
    from datetime import UTC, datetime
    from custom_components.adaptive_solar.core.archive import ArchiveJournal, ArchiveStore

    journal = ArchiveJournal(tmp_path / "journal")
    journal.append("event", {"original": True}, datetime(2026, 10, 29, tzinfo=UTC))
    store = ArchiveStore(tmp_path / "data/archive")
    store.ingest_page("ha-one", journal.page())
    return store, next(store.originals.rglob("*.json.gz"))


@pytest.mark.parametrize("existing_archive", [False, True])
def test_main_rejects_status_inside_originals_before_any_creation(config, tmp_path, monkeypatch, capsys, existing_archive):
    from custom_components.adaptive_solar.core.archive import ArchiveStore

    original = archived_original(tmp_path)[1] if existing_archive else None
    before = original.read_bytes() if original else None
    config["status_dir"] = "data/archive/originals/status"
    cfg = tmp_path / "data/host.json"
    cfg.write_text(json.dumps(config))
    monkeypatch.setattr(host.subprocess, "run", lambda *_a, **_k: pytest.fail("invalid output started a child"))
    assert host.main(["status", "--config", str(cfg)]) == 2
    assert not (tmp_path / config["status_dir"]).exists()
    assert not (tmp_path / "data/host-status").exists()
    assert "configuration failed" in capsys.readouterr().err
    if original:
        assert original.read_bytes() == before
        assert ArchiveStore(tmp_path / "data/archive").checkpoint("ha-one") is not None
    else:
        assert not (tmp_path / "data/archive").exists()


def test_main_cannot_replace_its_own_configuration_with_status(config, tmp_path, capsys):
    cfg = tmp_path / "data/host-status/status.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps(config))
    before = cfg.read_bytes()
    assert host.main(["status", "--config", str(cfg)]) == 2
    assert cfg.read_bytes() == before
    assert not (cfg.parent / "writer.lock").exists()
    assert not (tmp_path / "data/archive").exists()
    assert "configuration failed" in capsys.readouterr().err


@pytest.mark.parametrize("key", ["site_json", "actual_config", "reference_config", "quality", "quality_bindings"])
@pytest.mark.parametrize("output", ["weather.json", "writer.lock", "status-runtime.json"])
def test_main_protects_all_configured_inputs_even_for_status_job(config, tmp_path, capsys, key, output):
    source = tmp_path / "data/host-status" / output
    source.parent.mkdir()
    source.write_bytes(b'{"private_input":true}\n')
    config[key] = str(source)
    cfg = tmp_path / "data/host.json"
    cfg.write_text(json.dumps(config))
    assert host.main(["status", "--config", str(cfg)]) == 2
    assert source.read_bytes() == b'{"private_input":true}\n'
    assert not (tmp_path / "data/archive").exists()
    assert "configuration failed" in capsys.readouterr().err


@pytest.mark.parametrize("alias_kind", ["symlink", "hardlink"])
@pytest.mark.parametrize("protected", ["input", "program", "original"])
@pytest.mark.parametrize("output", ["status.json", "writer.lock"])
def test_main_rejects_status_and_lock_aliases_without_mutation(config, tmp_path, monkeypatch, capsys,
                                                             alias_kind, protected, output):
    monkeypatch.setattr(replay_paths, "SOURCE_ROOT", tmp_path)
    if protected == "original":
        store, source = archived_original(tmp_path)
    else:
        source = tmp_path / ("scripts/source.py" if protected == "program" else "data/actuals.json")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b'{"protected":true}\n')
    before = source.read_bytes()
    destination = tmp_path / "data/host-status" / output
    destination.parent.mkdir()
    if alias_kind == "symlink":
        destination.symlink_to(source)
    else:
        destination.hardlink_to(source)
    cfg = tmp_path / "data/host.json"
    cfg.write_text(json.dumps(config))
    assert host.main(["status", "--config", str(cfg)]) == 2
    assert source.read_bytes() == destination.read_bytes() == before
    assert not (destination.parent / "ha.json").exists()
    assert "configuration failed" in capsys.readouterr().err
    if protected == "original":
        from custom_components.adaptive_solar.core.archive import ArchiveStore
        assert ArchiveStore(store.root).checkpoint("ha-one") is not None
    else:
        assert not (tmp_path / "data/archive").exists()


@pytest.mark.parametrize("archive_alias,state_alias", [(False, False), (True, True), (True, False)])
def test_main_rejects_lexical_archive_status_even_through_outward_symlink(config, tmp_path, monkeypatch, capsys,
                                                                      archive_alias, state_alias):
    store, original = archived_original(tmp_path)
    before = original.read_bytes()
    outside = tmp_path / "data/outside"
    outside.mkdir()
    (store.originals / "status-link").symlink_to(outside, target_is_directory=True)
    if archive_alias:
        (tmp_path / "data/archive-alias").symlink_to(store.root, target_is_directory=True)
        config["archive"] = "data/archive-alias"
    status_archive = config["archive"] if state_alias else "data/archive"
    config["status_dir"] = status_archive + "/originals/status-link/new"
    cfg = tmp_path / "data/host.json"
    cfg.write_text(json.dumps(config))
    mock_process(monkeypatch, iter([]))
    assert host.main(["status", "--config", str(cfg)]) == 2
    assert list(outside.iterdir()) == []
    assert original.read_bytes() == before
    assert "configuration failed" in capsys.readouterr().err


def test_main_default_status_preserves_originals_and_archive_reopens(config, monkeypatch, tmp_path, capsys):
    from custom_components.adaptive_solar.core.archive import ArchiveStore

    store, original = archived_original(tmp_path)
    before = original.read_bytes()
    checkpoint = store.checkpoint("ha-one")
    source_scripts = Path(__file__).resolve().parents[1] / "scripts"
    (tmp_path / "scripts").symlink_to(source_scripts, target_is_directory=True)
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    cfg = tmp_path / "data/host.json"
    cfg.write_text(json.dumps(config))
    for _ in range(2):
        assert host.main(["status", "--config", str(cfg)]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["complete"] and report["archive"]["events"] == 1
        assert json.loads((tmp_path / "data/host-status/status.json").read_text()) == report
        assert ArchiveStore(store.root).checkpoint("ha-one") == checkpoint
        assert original.read_bytes() == before


@pytest.mark.parametrize("error,kind", [(subprocess.TimeoutExpired(["private-command"], 1200), "timeout"),
                                       (OSError("private-error"), "os_error")])
def test_child_failure_categories_preserve_other_entry_and_sanitized_evidence(config, monkeypatch, tmp_path, error, kind):
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    mock_process(monkeypatch, iter([0]))
    original, calls = host.subprocess.run, []
    def process(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            raise error
        return original(command, **kwargs)
    monkeypatch.setattr(host.subprocess, "run", process)
    report = host.run("ha", config)
    runtime = json.loads((tmp_path / "data/host-status/ha-runtime.json").read_text())
    assert len(calls) == 3 and report["commands"][1]["returncode"] == 0
    assert report["commands"][0]["exit_kind"] == kind
    assert report["commands"][0]["timeout_seconds"] == 1200
    assert runtime["run_id"] == report["runtime_metrics"]["run_id"]
    assert runtime["phase_summary"]["child_run"]["outcomes"] == {kind: 1, "completed": 1}
    assert not runtime["job_complete"] and runtime["open_phases"] == 0
    assert "private" not in json.dumps([report, runtime])


@pytest.mark.parametrize("error,kind", [(subprocess.TimeoutExpired(["private-command"], 300), "timeout"),
                                       (OSError("private-error"), "os_error")])
def test_stats_failure_is_separate_and_retains_partial_phase_evidence(config, monkeypatch, tmp_path, error, kind):
    def process(*_args, **_kwargs):
        raise error
    monkeypatch.setattr(host.subprocess, "run", process)
    report = host.run("status", config)
    runtime = json.loads((tmp_path / "data/host-status/status-runtime.json").read_text())
    assert report["reason"] == "job_failed" and not report["complete"]
    assert report["stats_process"] == {"returncode": None, "exit_kind": kind, "timeout_seconds": 300}
    assert runtime["phase_summary"]["stats"]["outcomes"] == {kind: 1}
    assert runtime["phase_summary"]["result_write"]["outcomes"] == {"completed": 1}
    assert runtime["phase_summary"]["lock_close"]["outcomes"] == {"completed": 1}
    assert "private" not in json.dumps(runtime)


def test_actual_lock_wait_status_write_and_close_precede_runtime_publication(config, monkeypatch, tmp_path):
    import fcntl
    from scripts.runtime_metrics import PhaseRecorder

    class Clock:
        now = 0
        def __call__(self):
            return self.now
    clock = Clock()
    monkeypatch.setattr(host, "PhaseRecorder", lambda job: PhaseRecorder(job, clock=clock, cpu_clock=clock))
    mock_process(monkeypatch, iter([]))
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    original_flock, original_open, original_write = fcntl.flock, Path.open, host.write_status
    def flock(handle, operation):
        if operation == fcntl.LOCK_EX:
            clock.now += 3
        return original_flock(handle, operation)
    class Handle:
        def __init__(self, handle):
            self.handle = handle
        def fileno(self):
            return self.handle.fileno()
        def close(self):
            clock.now += 7
            self.handle.close()
    def open_path(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        return Handle(handle) if path.name == "writer.lock" else handle
    def write(path, value):
        if path.name == "status-runtime.json":
            # The matching final result is already durable and the writer lock released.
            with original_open(path.parent / "writer.lock", "a") as lock:
                original_flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert json.loads((path.parent / "status.json").read_text())["runtime_metrics"]["run_id"] == value["run_id"]
            clock.now += 100
        else:
            clock.now += 5
        original_write(path, value)
    monkeypatch.setattr(host.fcntl, "flock", flock)
    monkeypatch.setattr(Path, "open", open_path)
    monkeypatch.setattr(host, "write_status", write)
    report = host.run("status", config)
    runtime = json.loads((tmp_path / "data/host-status/status-runtime.json").read_text())
    assert runtime["elapsed_ns"] == runtime["process_cpu_elapsed_ns"] == 15
    assert runtime["phase_summary"]["lock_wait"]["duration_ns"] == 3
    assert runtime["phase_summary"]["result_write"]["duration_ns"] == 5
    assert runtime["phase_summary"]["lock_close"]["duration_ns"] == 7
    assert clock.now == 115
    assert runtime["excludes"] == "own_runtime_sidecar_publication"
    assert json.loads((tmp_path / "data/host-status/status.json").read_text()) == report


def test_status_write_failure_keeps_original_exception_and_close_evidence(config, monkeypatch, tmp_path):
    import fcntl

    mock_process(monkeypatch, iter([]))
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    original_write, error = host.write_status, OSError("private-storage-error")
    def write(path, value):
        if path.name == "status.json":
            raise error
        original_write(path, value)
    monkeypatch.setattr(host, "write_status", write)
    with pytest.raises(OSError) as raised:
        host.run("status", config)
    assert raised.value is error
    runtime = json.loads((tmp_path / "data/host-status/status-runtime.json").read_text())
    assert runtime["run_exit_kind"] == "raised" and runtime["job_complete"] is None
    assert runtime["phase_summary"]["result_write"]["outcomes"] == {"os_error": 1}
    assert runtime["phase_summary"]["lock_close"]["outcomes"] == {"completed": 1}
    assert runtime["open_phases"] == 0 and "private" not in json.dumps(runtime)
    with (tmp_path / "data/host-status/writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_runtime_write_failure_does_not_change_capture_success(config, monkeypatch, tmp_path, capsys):
    mock_process(monkeypatch, iter([0, 0]))
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=10000, total=10000))
    original_write = host.write_status
    def write(path, value):
        if path.name == "ha-runtime.json":
            raise OSError("private-storage-error")
        original_write(path, value)
    monkeypatch.setattr(host, "write_status", write)
    report = host.run("ha", config)
    assert report["complete"]
    assert json.loads((tmp_path / "data/host-status/ha.json").read_text()) == report
    assert not (tmp_path / "data/host-status/ha-runtime.json").exists()
    assert capsys.readouterr().err == "Archive runtime telemetry could not be persisted.\n"


@pytest.mark.parametrize("value", ["private-stats-value", {"private": "value"}, True, -1, float("nan"), float("inf")])
def test_statistics_accept_only_nonnegative_finite_numeric_counters(config, monkeypatch, tmp_path, value):
    mock_process(monkeypatch, iter([]))
    native = host.subprocess.run
    def process(command, **kwargs):
        result = native(command, **kwargs)
        values = json.loads(result.stdout)
        values["events"] = value
        return subprocess.CompletedProcess(command, 0, json.dumps(values), "")
    monkeypatch.setattr(host.subprocess, "run", process)
    report = host.run("status", config)
    assert not report["complete"] and report["reason"] == "job_failed"
    assert "archive" not in report
    runtime = json.loads((tmp_path / "data/host-status/status-runtime.json").read_text())
    assert "private" not in json.dumps([report, runtime], allow_nan=False)
