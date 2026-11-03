"""Adapter/fallback tests have no compiler or optional-extension dependency.

The explicit real-extension differential gate lives outside default testpaths.
"""
from contextlib import contextmanager
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import struct
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from custom_components.adaptive_solar.core import archive
from scripts import rust_archive_probe as subject

GENERATION = "00000000-0000-0000-0000-000000000001"
STAMP = "2026-01-01T00:00:00+00:00"


def valid_wrapper(payload=None):
    event = dict(schema=1, generation=GENERATION, sequence=1, event_id="synthetic-event",
                 kind="diagnostic", received_at=STAMP, payload=payload if payload is not None else {"number": 1})
    event["sha256"] = hashlib.sha256(archive.canonical_bytes(event)).hexdigest()
    page = dict(schema=1, generation=GENERATION, oldest_sequence=1, requested_cursor=None,
                next_cursor=f"{GENERATION}:1", events=[event], gap=None)
    return dict(schema=1, source="synthetic-source", ingest_order=1, stored_at=STAMP,
                archive_started_at=STAMP, page=page)


def raw_json(wrapper):
    return json.dumps(wrapper, ensure_ascii=True, separators=(",", ":")).encode()


def differential_cases():
    cases = [("ordinary", raw_json(valid_wrapper({"nested": [False, None, "ümlaut\n", 1, 0.125]})), "gzip")]
    random_source, values = random.Random(47113), [0.0, -0.0, 1e-7, 1e-6, 1e15, 1e16, 1e20, 1e21, 1e23]
    while len(values) < 512:
        value = struct.unpack(">d", random_source.getrandbits(64).to_bytes(8, "big"))[0]
        if math.isfinite(value):
            values.append(value)
    cases.append(("float64_rounding", raw_json(valid_wrapper({"values": values})), "gzip"))
    base = raw_json(valid_wrapper())
    zero = raw_json(valid_wrapper({"number": 0})).replace(b'"number":0', b'"number":-0')
    cases.extend((name, raw, "gzip") for name, raw in [
        ("negative_integer_zero", zero),
        ("duplicate_early_nan", base.replace(b'"number":1', b'"number":NaN,"number":1')),
        ("duplicate_early_surrogate", base.replace(b'"number":1', b'"number":"\\ud800","number":1')),
        ("utf8_bom", b"\xef\xbb\xbf" + base),
        ("utf16_json", base.decode().encode("utf-16")),
    ])
    source_surrogate = valid_wrapper()
    source_surrogate["source"] = "\ud800"
    cases.append(("wrapper_source_surrogate", raw_json(source_surrogate), "gzip"))
    for name, mutate in [
        ("bad_wrapper_schema", lambda w: w.update(schema=2)),
        ("boolean_schema", lambda w: w["page"].update(schema=True)),
        ("bad_event_hash", lambda w: w["page"]["events"][0].update(sha256="f" * 64)),
        ("bad_cursor", lambda w: w["page"].update(next_cursor=f"{GENERATION}:2")),
        ("bad_gap", lambda w: w["page"].update(gap={"reason": "retention_or_overflow", "from": 1, "to": 0})),
        ("payload_nan", lambda w: w["page"]["events"][0]["payload"].update(number=float("nan"))),
    ]:
        wrapper = valid_wrapper()
        mutate(wrapper)
        cases.append((name, raw_json(wrapper), "gzip"))
    cases.extend((name, base, compression) for name, compression in
                 [("concatenated_members", "members"), ("bad_trailing_data", "trailing"), ("bad_crc", "bad_crc")])
    cases.append(("large_integer", raw_json(valid_wrapper({"number": 10**1000})), "gzip"))
    return cases


def write_original(tmp_path, raw, compression="gzip"):
    digest = hashlib.sha256(raw).hexdigest()
    parent = tmp_path / "originals" / digest[:2]
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / f"{digest}.json.gz"
    if compression == "members":
        split = len(raw) // 2
        compressed = gzip.compress(raw[:split], mtime=0) + gzip.compress(raw[split:], mtime=0)
    else:
        compressed = gzip.compress(raw, mtime=0)
    if compression == "trailing":
        compressed += b"invalid trailing bytes"
    elif compression == "bad_crc":
        compressed = compressed[:-8] + bytes([compressed[-8] ^ 1]) + compressed[-7:]
    path.write_bytes(compressed)
    reader = object.__new__(archive.ArchiveStore)
    reader.root, reader.originals = tmp_path, tmp_path / "originals"
    return reader, path


def outcome(reader, path):
    try:
        return "ok", reader._read_original(path)
    except Exception as error:
        return "error", type(error).__name__, str(error)


@pytest.fixture
def fake_probe(tmp_path, monkeypatch):
    binary = tmp_path / "fixture-probe.so"
    binary.write_bytes(b"synthetic extension identity")
    expected = hashlib.sha256(binary.read_bytes()).hexdigest()
    native = archive.ArchiveStore._read_original

    @contextmanager
    def enter(mode="none", module=archive):
        def read_original(path, **kwargs):
            if mode == "error":
                raise RuntimeError("synthetic extension error")
            if mode == "invalid_return":
                return b"{}"
            if mode == "checked":
                reader = object.__new__(archive.ArchiveStore)
                reader.root, reader.originals = Path(path).parent, Path(path).parent
                try:
                    native(reader, Path(path))
                    return gzip.decompress(Path(path).read_bytes())
                except Exception:
                    return None
            return None
        extension = SimpleNamespace(read_original=read_original, PROTOCOL_VERSION=1, MAX_FAST_DEPTH=64)
        monkeypatch.setattr(subject, "_load_extension", lambda *args: extension)
        with subject.rust_original_reader(module, binary, expected) as stats:
            yield stats
    return enter, binary, expected


CASES = differential_cases()


@pytest.mark.parametrize("mode", ["none", "error", "checked", "invalid_return"])
@pytest.mark.parametrize("name,raw,compression", CASES, ids=[row[0] for row in CASES])
def test_optional_adapter_and_fallback_match_native_exactly(tmp_path, fake_probe, mode, name, raw, compression):
    reader, path = write_original(tmp_path, raw, compression)
    baseline, original = outcome(reader, path), archive.ArchiveStore._read_original
    enter, _, _ = fake_probe
    with enter(mode) as stats:
        assert outcome(reader, path) == baseline
    assert stats["closed"] and stats["calls"] == stats["fast_reads"] + stats["native_fallbacks"] == 1
    assert archive.ArchiveStore._read_original is original
    assert not any(key.startswith("__archive_probe_bridge_") for key in vars(archive))


def test_low_headroom_and_unsupported_runtime_always_run_native(tmp_path, fake_probe, monkeypatch):
    reader, path = write_original(tmp_path, raw_json(valid_wrapper()))
    enter, _, _ = fake_probe
    monkeypatch.setattr(subject, "_headroom", lambda: 255)
    with enter("checked") as stats:
        assert reader._read_original(path)["schema"] == 1
    assert stats["fallback_reasons"] == {"low_headroom": 1}
    monkeypatch.setattr(subject, "_headroom", lambda: 500)
    monkeypatch.setattr(archive, "SCHEMA", 2)
    baseline = outcome(reader, path)
    with enter("checked") as stats:
        assert outcome(reader, path) == baseline
    assert stats["fast_reads"] == 0 and stats["fallback_reasons"] == {"unsupported_runtime": 1}


def test_fallback_keeps_native_recursion_acceptance_without_an_extra_reader_frame(tmp_path, fake_probe):
    original_limit, cases = sys.getrecursionlimit(), []
    try:
        sys.setrecursionlimit(5000)
        for depth in (600, 1100):
            payload = 0
            for _ in range(depth):
                payload = [payload]
            cases.append(write_original(tmp_path / str(depth), raw_json(valid_wrapper({"deep": payload}))))
    finally:
        sys.setrecursionlimit(original_limit)
    before = [outcome(reader, path) for reader, path in cases]
    enter, _, _ = fake_probe
    with enter("none"):
        after = [outcome(reader, path) for reader, path in cases]
    assert after == before and {item[0] for item in before} == {"ok", "error"}


def test_restore_on_failure_and_binary_changes_are_not_success(tmp_path, fake_probe):
    enter, binary, _ = fake_probe
    original = archive.ArchiveStore._read_original
    with pytest.raises(RuntimeError, match="caller failed"):
        with enter():
            raise RuntimeError("caller failed")
    assert archive.ArchiveStore._read_original is original
    with pytest.raises(ValueError, match="changed"):
        with enter():
            binary.write_bytes(b"modified binary")
    assert archive.ArchiveStore._read_original is original


def test_protocol_binary_hash_and_depth_are_checked_before_installing(tmp_path, monkeypatch):
    binary = tmp_path / "probe.so"
    binary.write_bytes(b"fake")
    expected = hashlib.sha256(binary.read_bytes()).hexdigest()
    monkeypatch.setattr(subject, "_load_extension", lambda *args: SimpleNamespace(PROTOCOL_VERSION=2, MAX_FAST_DEPTH=64))
    for arguments in [(expected, 64), ("0" * 64, 64), (expected, 65)]:
        with pytest.raises(ValueError):
            with subject.rust_original_reader(archive, binary, arguments[0], max_depth=arguments[1]):
                pytest.fail("invalid contract must fail before installing a trampoline")


def test_unknown_native_source_is_fallback_only(tmp_path, monkeypatch):
    source = tmp_path / "source"
    native_path = source / "custom_components/adaptive_solar/core/archive.py"
    adapter_path = source / "scripts/rust_archive_probe.py"
    native_path.parent.mkdir(parents=True)
    adapter_path.parent.mkdir(parents=True)
    native_path.write_text(Path(archive.__file__).read_text() + "\n# different native version\n")
    adapter_path.write_bytes(Path(subject.__file__).read_bytes())
    modules = []
    try:
        for path in (native_path, adapter_path):
            name = "rust_test_" + uuid4().hex
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            modules.append(module)
        native, adapter = modules
        binary = tmp_path / "probe.so"
        binary.write_bytes(b"fake")
        monkeypatch.setattr(adapter, "_load_extension", lambda *args: SimpleNamespace(
            PROTOCOL_VERSION=1, MAX_FAST_DEPTH=64, read_original=lambda *args, **kwargs: pytest.fail("unknown native version")))
        _, path = write_original(tmp_path / "archive", raw_json(valid_wrapper()))
        reader = object.__new__(native.ArchiveStore)
        with adapter.rust_original_reader(native, binary, hashlib.sha256(binary.read_bytes()).hexdigest()) as stats:
            assert reader._read_original(path)["schema"] == 1
        assert not stats["qualified_native_source"] and stats["fast_reads"] == 0
        assert stats["fallback_reasons"] == {"unsupported_source": 1}
    finally:
        for module in modules:
            sys.modules.pop(module.__name__, None)

