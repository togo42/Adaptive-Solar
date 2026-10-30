"""Replay reports cannot destroy original inputs, including filesystem aliases."""
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from scripts import replay_archive, replay_shading
from scripts.replay_paths import publish_output, validate_output, write_output


def collector_case(tmp_path, monkeypatch, collector):
    from scripts import capture_actuals, capture_ha, replay_paths
    from tests.test_capture_actuals import START, END, capture

    command = capture_actuals if collector == "actuals" else capture_ha
    monkeypatch.setattr(command, "ROOT", tmp_path)
    monkeypatch.setattr(replay_paths, "SOURCE_ROOT", tmp_path)
    private = tmp_path / "data"
    private.mkdir()
    config, output = private / "mapping.json", private / "capture.jsonl"
    mapping = ({"inverter_id": "roof", "statistic_ids": ["sensor.energy"]} if collector == "actuals"
               else {"inverter_id": "roof", "source": "adaptive", "entry_ids": ["entry"]})
    config.write_text(json.dumps({"mappings": [mapping]}) + "\n")
    args = [collector, "--config", str(config), "--output", str(output)]
    if collector == "actuals":
        args.extend(["--start", START.isoformat(), "--end", END.isoformat()])
    monkeypatch.setattr("sys.argv", args)
    payload = capture() if collector == "actuals" else {"groups": []}
    mock = AsyncMock(return_value=payload)
    monkeypatch.setattr(command, "capture_actuals" if collector == "actuals" else "capture_forecasts", mock)
    return command, config, output, mock


@pytest.mark.parametrize("collector", ["actuals", "forecasts"])
@pytest.mark.parametrize("target", ["scripts/collector.py", "custom_components/adaptive_solar/core/models.py",
                                   "custom_components/adaptive_solar/manifest.json"])
@pytest.mark.parametrize("phase", ["before_request", "during_request", "opened_descriptor", "moved_program"])
def test_append_collectors_never_write_program_inodes(tmp_path, monkeypatch, collector, target, phase):
    command, _, output, mock = collector_case(tmp_path, monkeypatch, collector)
    source = tmp_path / target
    source.parent.mkdir(parents=True, exist_ok=True)
    before = b'{"original":"program-or-resource"}\n'
    source.write_bytes(before)

    def alias():
        output.unlink(missing_ok=True)
        output.hardlink_to(source)

    if phase == "before_request":
        alias()
    elif phase in {"during_request", "moved_program"}:
        async def captured(*_, **__):
            if phase == "moved_program":
                source.replace(output)
                source.write_bytes(before)
            else:
                alias()
            return mock.return_value
        mock.side_effect = captured
    else:
        native_open = os.open

        def raced_open(path, flags, *args, **kwargs):
            if Path(path) != output:
                return native_open(path, flags, *args, **kwargs)
            alias()
            descriptor = native_open(path, flags, *args, **kwargs)
            # The pathname is now innocent and the protected FD has only one link.
            output.unlink()
            output.write_bytes(b"{}\n")
            return descriptor
        monkeypatch.setattr(os, "open", raced_open)
    assert command.main() == 2
    assert source.read_bytes() == before
    if phase == "moved_program":
        assert output.read_bytes() == before
    assert mock.await_count == (0 if phase == "before_request" else 1)


@pytest.mark.parametrize("collector,source_kind", [("actuals", "mapping"), ("actuals", "quality"),
                                                   ("forecasts", "mapping")])
@pytest.mark.parametrize("phase", ["during_request", "opened_descriptor", "moved_input"])
def test_append_collectors_recheck_explicit_input_inodes(tmp_path, monkeypatch, collector, source_kind, phase):
    command, config, output, mock = collector_case(tmp_path, monkeypatch, collector)
    if source_kind == "quality":
        source = tmp_path / "data/quality.json"
        source.write_bytes(b"null\n")
        import sys
        monkeypatch.setattr("sys.argv", [*sys.argv, "--quality", str(source)])
    else:
        source = config
    before = source.read_bytes()

    def alias():
        output.unlink(missing_ok=True)
        output.hardlink_to(source)

    if phase in {"during_request", "moved_input"}:
        async def captured(*_, **__):
            if phase == "moved_input":
                source.replace(output)
                source.write_bytes(before)
            else:
                alias()
            return mock.return_value
        mock.side_effect = captured
    else:
        native_open = os.open

        def raced_open(path, flags, *args, **kwargs):
            if Path(path) != output:
                return native_open(path, flags, *args, **kwargs)
            alias()
            descriptor = native_open(path, flags, *args, **kwargs)
            output.unlink()
            output.write_bytes(b"{}\n")
            return descriptor
        monkeypatch.setattr(os, "open", raced_open)
    assert command.main() == 2
    assert source.read_bytes() == before
    if phase == "moved_input":
        assert output.read_bytes() == before
    assert mock.await_count == 1


@pytest.mark.parametrize("collector", ["actuals", "forecasts"])
def test_append_collectors_refuse_replaced_path_even_for_unrelated_single_link_inode(tmp_path, monkeypatch, collector):
    command, _, output, _ = collector_case(tmp_path, monkeypatch, collector)
    old_output = tmp_path / "data/old-capture.jsonl"
    old_output.write_bytes(b"{}\n")
    native_open = os.open

    def raced_open(path, flags, *args, **kwargs):
        if Path(path) != output:
            return native_open(path, flags, *args, **kwargs)
        output.hardlink_to(old_output)
        descriptor = native_open(path, flags, *args, **kwargs)
        output.unlink()
        output.write_bytes(b"{}\n")
        return descriptor
    monkeypatch.setattr(os, "open", raced_open)
    assert command.main() == 2
    assert old_output.read_bytes() == b"{}\n" and output.read_bytes() == b"{}\n"


@pytest.mark.parametrize("filename", ["pins.json", "index.sqlite3", "originals/sha256/aa/bundle.json.gz", "new/report.json"])
@pytest.mark.parametrize("command", [replay_archive, replay_shading])
def test_cli_rejects_archive_output_before_opening_archive(tmp_path, monkeypatch, filename, command):
    archive = tmp_path / "archive"
    target = archive / filename
    target.parent.mkdir(parents=True)
    target.write_bytes(b"original input")
    monkeypatch.setattr(command, "ArchiveStore", lambda *_: pytest.fail("archive opened before output validation"))
    monkeypatch.setattr("sys.argv", ["replay", "--archive", str(archive), "--source", "ha:test",
                                     "--dataset", "pin", "--output", str(target)])
    assert command.main() == 2
    assert target.read_bytes() == b"original input"


@pytest.mark.parametrize("input_name", ["site.json", "calibration.json"])
@pytest.mark.parametrize("alias", ["same", "symlink", "hardlink"])
def test_explicit_inputs_are_protected_before_any_cli_read(tmp_path, monkeypatch, input_name, alias):
    original = tmp_path / input_name
    original.write_bytes(b"original private input")
    output = original if alias == "same" else tmp_path / "report.json"
    if alias == "symlink":
        output.symlink_to(original)
    elif alias == "hardlink":
        output.hardlink_to(original)
    option = "--site-json" if input_name == "site.json" else "--calibration-json"
    monkeypatch.setattr(replay_archive, "ArchiveStore", lambda *_: pytest.fail("archive opened before input alias validation"))
    monkeypatch.setattr("sys.argv", ["replay", "--archive", str(tmp_path / "archive"), "--source", "ha:test",
                                     "--output", str(output), option, str(original)])
    assert replay_archive.main() == 2
    assert original.read_bytes() == b"original private input"
    assert not (tmp_path / "archive").exists()


@pytest.mark.parametrize("alias", ["symlink_file", "symlink_parent", "hardlink", "archive_symlink"])
@pytest.mark.parametrize("command", [replay_archive, replay_shading])
def test_archive_aliases_cannot_escape_output_guard(tmp_path, monkeypatch, alias, command):
    archive = tmp_path / "archive"
    archive.mkdir()
    original = archive / "pins.json"
    original.write_bytes(b"immutable")
    output = tmp_path / "report.json"
    if alias == "symlink_file":
        output.symlink_to(original)
    elif alias == "symlink_parent":
        (tmp_path / "alias").symlink_to(archive, target_is_directory=True)
        output = tmp_path / "alias" / "pins.json"
    elif alias == "hardlink":
        output.hardlink_to(original)
    else:
        (tmp_path / "archive-alias").symlink_to(archive, target_is_directory=True)
        archive = tmp_path / "archive-alias"
        output = original
    monkeypatch.setattr(command, "ArchiveStore", lambda *_: pytest.fail("archive opened before alias validation"))
    monkeypatch.setattr("sys.argv", ["replay", "--archive", str(archive), "--source", "ha:test",
                                     "--dataset", "pin", "--output", str(output)])
    assert command.main() == 2
    assert original.read_bytes() == b"immutable"


@pytest.mark.parametrize("output_via_alias", [False, True])
def test_report_rejects_outward_symlink_under_real_or_aliased_archive_root(tmp_path, output_via_alias):
    archive = tmp_path / "archive"
    archive.mkdir()
    original = archive / "pins.json"
    original.write_bytes(b"immutable")
    alias = tmp_path / "archive-alias"
    alias.symlink_to(archive, target_is_directory=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (archive / "escape").symlink_to(outside, target_is_directory=True)
    output = (alias if output_via_alias else archive) / "escape/new/report.json"
    with pytest.raises(ValueError, match="outside.*archive"):
        write_output("report\n", output, alias)
    assert list(outside.iterdir()) == []
    assert original.read_bytes() == b"immutable"


def test_publication_rechecks_target_after_computation_and_keeps_inputs(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    original = archive / "pins.json"
    original.write_bytes(b"immutable")
    output = tmp_path / "report.json"
    validate_output(output, archive)
    temporary = tmp_path / ".pending"
    temporary.write_bytes(b"report")
    output.hardlink_to(original)
    with pytest.raises(ValueError, match="hardlink"):
        publish_output(temporary, output, archive)
    assert temporary.read_bytes() == b"report"
    assert original.read_bytes() == b"immutable"


def test_atomic_report_does_not_truncate_a_noninput_hardlink(tmp_path):
    unrelated = tmp_path / "previous-report-copy"
    unrelated.write_text("old report")
    output = tmp_path / "report.json"
    output.hardlink_to(unrelated)
    write_output("new report\n", output, tmp_path / "archive")
    assert output.read_text() == "new report\n"
    assert unrelated.read_text() == "old report"
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("target", ["custom_components/adaptive_solar/manifest.json", "scripts/tool-resource.json"])
@pytest.mark.parametrize("alias", ["same", "symlink", "hardlink"])
def test_program_resources_cannot_be_replaced_by_reports(tmp_path, monkeypatch, target, alias):
    from scripts import replay_paths

    root = tmp_path / "project"
    source = root / target
    source.parent.mkdir(parents=True)
    source.write_text('{"original":"resource"}\n')
    monkeypatch.setattr(replay_paths, "SOURCE_ROOT", root)
    output = source if alias == "same" else tmp_path / "report.json"
    if alias == "symlink":
        output.symlink_to(source)
    elif alias == "hardlink":
        output.hardlink_to(source)
    with pytest.raises(ValueError):
        write_output("report\n", output, tmp_path / "archive")
    assert source.read_text() == '{"original":"resource"}\n'


def test_new_report_does_not_place_private_data_in_program_tree(tmp_path, monkeypatch):
    from scripts import replay_paths

    root = tmp_path / "project"
    monkeypatch.setattr(replay_paths, "SOURCE_ROOT", root)
    output = root / "custom_components/adaptive_solar/new-report.json"
    with pytest.raises(ValueError, match="program directories"):
        write_output("report\n", output, tmp_path / "archive")
    assert not root.exists()


def test_reports_remain_utf8_under_a_non_utf8_process_locale(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "report.json"
    code = ("from pathlib import Path; from scripts.replay_paths import write_output; "
            "import sys; write_output('{\\\"name\\\":\\\"Gr\\u00fc\\u00dfe\\\"}\\n', Path(sys.argv[1]), Path(sys.argv[2]))")
    result = subprocess.run([sys.executable, "-c", code, str(output), str(tmp_path / "archive")],
                            cwd=root, env={**os.environ, "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C"},
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert output.read_bytes() == '{"name":"Grüße"}\n'.encode("utf-8")
