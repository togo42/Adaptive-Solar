"""Replay reports cannot destroy original inputs, including filesystem aliases."""
import pytest

from scripts import replay_archive, replay_shading
from scripts.replay_paths import publish_output, validate_output, write_output


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
