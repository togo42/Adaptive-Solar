"""Hash-prefix migration preserves originals, chronology, pins and recovery paths."""
from datetime import UTC, datetime, timedelta
import gzip
import json
import os

import pytest

from custom_components.adaptive_solar.core import archive as module
from custom_components.adaptive_solar.core.archive import ArchiveError, ArchiveJournal, ArchiveStore
from scripts import archive

NOW = datetime(2026, 10, 28, tzinfo=UTC)


@pytest.fixture
def stored(tmp_path):
    journal = ArchiveJournal(tmp_path / "journal")
    store = ArchiveStore(tmp_path / "archive")
    for index in range(3):
        journal.append("part", {"index": index}, NOW + timedelta(seconds=index))
        store.ingest_page("ha", journal.page(store.checkpoint("ha")), stored_at=NOW)
        if index == 0:
            store.pin("first")
    return store


def snapshot(store):
    return {path.name: path.read_bytes() for path in store.originals.rglob("*.json.gz")}


def flatten_one(store):
    path = next(store.originals.glob("*/*.json.gz"))
    flat = store.originals / path.name
    path.rename(flat)
    return flat


def test_new_writes_and_exports_use_hash_prefix(stored, tmp_path):
    assert not list(stored.originals.glob("*.json.gz"))
    for path in stored.originals.glob("*/*.json.gz"):
        assert path.parent.name == path.name[:2]
    stored.pin("all")
    stored.export_dataset("all", tmp_path / "export")
    exported = ArchiveStore(tmp_path / "export")
    assert snapshot(exported) == snapshot(stored)
    assert list(exported.iter_events(dataset="all")) == list(stored.iter_events())


@pytest.mark.parametrize("layout", ["hash-prefix", "flat"])
@pytest.mark.parametrize("location", ["root", "originals", "prefix", "root_alias", "lexical_escape",
                                      "root_alias_lexical_escape", "normalized"])
def test_dataset_export_refuses_internal_paths_and_aliases_without_harming_archive(stored, tmp_path, layout, location):
    if location == "root":
        target = stored.root / "new-export"
    elif location == "originals":
        target = stored.originals / "export-copy"
    elif location == "prefix":
        target = next(stored.originals.glob("*/*.json.gz")).parent / "export-copy"
    elif location == "root_alias":
        alias = tmp_path / "alias"
        alias.symlink_to(stored.root, target_is_directory=True)
        target = alias / "originals/export-copy"
    elif location in {"lexical_escape", "root_alias_lexical_escape"}:
        outside = tmp_path / "outside"
        outside.mkdir()
        alias = stored.root / "escape"
        alias.symlink_to(outside, target_is_directory=True)
        target = alias / "export-copy"
        if location == "root_alias_lexical_escape":
            root_alias = tmp_path / "archive-alias"
            root_alias.symlink_to(stored.root, target_is_directory=True)
            stored = ArchiveStore(root_alias)
    else:
        target = stored.root / "originals/../new-export"
    before, events = snapshot(stored), list(stored.iter_events())
    pins = (stored.root / "pins.json").read_bytes()
    with pytest.raises(ArchiveError, match="outside.*archive"):
        stored.export_dataset("first", target, layout=layout)
    assert not target.exists()
    assert snapshot(stored) == before and (stored.root / "pins.json").read_bytes() == pins
    assert stored.verify()
    reopened = ArchiveStore(stored.root)
    assert list(reopened.iter_events()) == events
    journal = ArchiveJournal(tmp_path / "journal")
    journal.append("part", {"index": 3}, NOW + timedelta(seconds=3))
    reopened.ingest_page("ha", journal.page(reopened.checkpoint("ha")), stored_at=NOW)
    assert reopened.verify() and len(list(reopened.iter_events())) == len(events) + 1


@pytest.mark.parametrize("layout", ["hash-prefix", "flat"])
def test_dataset_export_rechecks_resolved_parent_after_original_verification(stored, tmp_path, monkeypatch, layout):
    parent = tmp_path / "export-parent"
    parent.mkdir()
    target = parent / "export-copy"
    original_read = stored._read_original
    before = snapshot(stored)

    def redirect_parent(path):
        value = original_read(path)
        if not parent.is_symlink():
            parent.rename(tmp_path / "old-parent")
            parent.symlink_to(stored.originals, target_is_directory=True)
        return value
    monkeypatch.setattr(stored, "_read_original", redirect_parent)
    with pytest.raises(ArchiveError, match="outside.*archive"):
        stored.export_dataset("first", target, layout=layout)
    assert not target.exists() and snapshot(stored) == before
    assert ArchiveStore(stored.root).verify()


@pytest.mark.parametrize("layout", ["hash-prefix", "flat"])
def test_dataset_export_cli_rejects_original_tree_destination(stored, layout):
    target = stored.originals / "export-copy"
    before = snapshot(stored)
    assert archive.main(["--root", str(stored.root), "export-dataset", "first", str(target), "--layout", layout]) == 1
    assert not target.exists() and snapshot(stored) == before
    assert ArchiveStore(stored.root).verify()


@pytest.mark.parametrize("layout", ["hash-prefix", "flat"])
def test_mixed_archive_migration_preserves_bytes_index_pins_and_references(stored, tmp_path, layout):
    flatten_one(stored)
    before = snapshot(stored)
    events = list(stored.iter_events())
    index = (stored.root / "index.sqlite3").read_bytes()
    pins = (stored.root / "pins.json").read_bytes()
    cursor = stored.checkpoint("ha")
    result = stored.migrate_layout(layout=layout)
    assert result["moved_originals"] == (1 if layout == "hash-prefix" else 2)
    assert snapshot(stored) == before
    assert (stored.root / "index.sqlite3").read_bytes() == index
    assert (stored.root / "pins.json").read_bytes() == pins
    assert stored.migrate_layout(layout=layout)["moved_originals"] == 0
    restored = ArchiveStore(stored.root)
    restored.rebuild_index()
    assert restored.checkpoint("ha") == cursor
    assert list(restored.iter_events()) == events
    assert list(restored.iter_events(dataset="first")) == events[:1]
    assert restored.resolve_events([events[0]["event_id"]], source="ha",
                                   generation=events[0]["generation"], dataset="first") == events[:1]
    restored.export_dataset("first", tmp_path / "flat-export", layout="flat")
    assert len(list((tmp_path / "flat-export/originals").glob("*.json.gz"))) == 1
    assert list(ArchiveStore(tmp_path / "flat-export").iter_events()) == events[:1]


@pytest.mark.parametrize("failure", ["link", "destination_sync", "unlink"])
def test_interrupted_migration_resumes_without_missing_original(stored, monkeypatch, failure):
    flat = flatten_one(stored)
    before = snapshot(stored)
    real_sync = module._fsync_dir
    with monkeypatch.context() as patch:
        if failure == "link":
            patch.setattr(module.os, "link", lambda *_: (_ for _ in ()).throw(OSError("interrupted")))
        elif failure == "destination_sync":
            def sync(path):
                if path == stored.originals / flat.name[:2]:
                    raise OSError("interrupted")
                real_sync(path)
            patch.setattr(module, "_fsync_dir", sync)
        else:
            real_unlink = type(flat).unlink
            def unlink(path, *args, **kwargs):
                if path == flat:
                    raise OSError("interrupted")
                return real_unlink(path, *args, **kwargs)
            patch.setattr(type(flat), "unlink", unlink)
        with pytest.raises(OSError, match="interrupted"):
            stored.migrate_layout()
    assert flat.exists()
    restored = ArchiveStore(stored.root)
    assert restored.verify()
    assert len(list(restored.iter_events())) == 3
    restored.migrate_layout()
    assert not flat.exists()
    assert snapshot(restored) == before


def test_corrupt_original_aborts_before_any_relocation(stored):
    flat = flatten_one(stored)
    path = next(stored.originals.glob("*/*.json.gz"))
    path.write_bytes(b"corrupt")
    before = snapshot(stored)
    with pytest.raises(ArchiveError):
        stored.migrate_layout()
    assert flat.exists()
    assert snapshot(stored) == before


def test_conflicting_duplicate_preserved(stored):
    path = next(stored.originals.glob("*/*.json.gz"))
    flat = stored.originals / path.name
    flat.write_bytes(b"corrupt")
    with pytest.raises(ArchiveError):
        stored.migrate_layout()
    assert flat.read_bytes() == b"corrupt"
    assert path.exists()


def test_different_valid_compression_cannot_replace_original_bytes(stored):
    path = next(stored.originals.glob("*/*.json.gz"))
    flat = stored.originals / path.name
    flat.write_bytes(gzip.compress(gzip.decompress(path.read_bytes()), mtime=1))
    before = snapshot(stored)
    with pytest.raises(ArchiveError, match="Conflicting original layout copies"):
        stored.migrate_layout()
    assert snapshot(stored) == before
    assert flat.exists() and path.exists()


@pytest.mark.parametrize("invalid", ["prefix", "symlink", "directory_symlink"])
def test_invalid_layout_not_silently_ignored(stored, invalid):
    path = next(stored.originals.glob("*/*.json.gz"))
    if invalid == "prefix":
        parent = stored.originals / ("00" if path.parent.name != "00" else "01")
        parent.mkdir(exist_ok=True)
        path.rename(parent / path.name)
    elif invalid == "symlink":
        raw = path.read_bytes()
        path.unlink()
        external = stored.root / "outside"
        external.write_bytes(raw)
        path.symlink_to(external)
    else:
        external = stored.root / "outside"
        path.parent.rename(external)
        path.parent.symlink_to(external, target_is_directory=True)
    with pytest.raises(ArchiveError):
        stored.verify()


@pytest.mark.parametrize("layout", ["hash-prefix", "flat"])
def test_retention_in_mixed_and_interrupted_layout_keeps_pin_and_cursor(stored, layout):
    flat = flatten_one(stored)
    # A crash after link but before unlink leaves two names for one original.
    os.link(flat, stored.originals / flat.name[:2] / flat.name)
    stored.migrate_layout(layout=layout)
    assert stored.maintain(now=NOW + timedelta(days=800))["removed_batches"] == 1
    stored.rebuild_index()
    assert [e["payload"]["index"] for e in stored.iter_events()] == [0, 2]
    assert len(snapshot(stored)) == 2


def test_cli_migration_and_flat_compatibility_export(stored, tmp_path, capsys):
    flat = flatten_one(stored)
    assert archive.main(["--root", str(stored.root), "migrate-layout"]) == 0
    assert json.loads(capsys.readouterr().out)["moved_originals"] == 1
    assert not flat.exists()
    output = tmp_path / "flat"
    assert archive.main(["--root", str(stored.root), "export-dataset", "first", str(output),
                         "--layout", "flat"]) == 0
    assert list((output / "originals").glob("*.json.gz"))
