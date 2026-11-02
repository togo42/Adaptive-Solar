"""Original reads preserve canonical integrity, bounds and strict Python APIs."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from custom_components.adaptive_solar.core import archive
from scripts.profile_quality import worker_environment

STAMP = "2026-10-28T00:00:00+00:00"
GENERATION = "00000000-0000-0000-0000-000000000001"


def page(payload):
    event = {"schema": 1, "generation": GENERATION, "sequence": 1, "event_id": "synthetic-event",
             "kind": "weather_response", "received_at": STAMP, "payload": payload}
    event["sha256"] = hashlib.sha256(archive.canonical_bytes(event)).hexdigest()
    return {"schema": 1, "generation": GENERATION, "oldest_sequence": 1, "requested_cursor": None,
            "next_cursor": f"{GENERATION}:1", "events": [event], "gap": None}


def original(tmp_path, value):
    wrapper = {"schema": 1, "source": "synthetic", "ingest_order": 1,
               "stored_at": STAMP, "archive_started_at": STAMP, "page": value}
    # Escaping also permits testing rejected unpaired surrogate code points.
    raw = json.dumps(wrapper, ensure_ascii=True, separators=(",", ":")).encode()
    path = tmp_path / (hashlib.sha256(raw).hexdigest() + ".json.gz")
    path.write_bytes(gzip.compress(raw, mtime=0))
    return path


def read(path):
    return object.__new__(archive.ArchiveStore)._read_original(path)


@pytest.mark.parametrize("payload", [
    {"unicode": ["ä", "汉字", "e\u0301", "é", "😀", "quote\"slash\\"]},
    {"float": [-0.0, 0.0, 1e-300, 1e300], "containers": [{}, [], {"nested": [True, None, 2]}]},
    {"source_binding": {"schema": 1, "config_sha256": "a" * 64}, "rows": list(range(2000))},
])
def test_original_read_preserves_exact_page_bytes_and_events(tmp_path, payload):
    value = page(payload)
    path = original(tmp_path, value)
    before = path.read_bytes()
    restored = read(path)["page"]
    assert archive.canonical_bytes(restored) == archive.canonical_bytes(value)
    assert archive.validate_page(restored) == value
    assert path.read_bytes() == before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 1e309])
def test_nonfinite_original_is_rejected_after_matching_file_hash(tmp_path, value):
    candidate = page({"value": 0})
    candidate["events"][0]["payload"]["value"] = value
    with pytest.raises(archive.ArchiveError, match="finite JSON"):
        read(original(tmp_path, candidate))


@pytest.mark.parametrize("token", [b"NaN", b"Infinity", b"-Infinity", b"1e999"])
def test_nonfinite_json_tokens_remain_rejected(tmp_path, token):
    path = original(tmp_path, page({"value": 0}))
    raw = gzip.decompress(path.read_bytes()).replace(b'"value":0', b'"value":' + token)
    changed = tmp_path / (hashlib.sha256(raw).hexdigest() + ".json.gz")
    changed.write_bytes(gzip.compress(raw, mtime=0))
    with pytest.raises(archive.ArchiveError, match="finite JSON"):
        read(changed)


def test_surrogate_and_duplicate_json_keys_keep_decoder_semantics(tmp_path):
    candidate = page({"value": "valid"})
    candidate["events"][0]["payload"]["value"] = "\ud800"
    with pytest.raises(archive.ArchiveError):
        read(original(tmp_path, candidate))
    value = page({"value": 2})
    path = original(tmp_path, value)
    raw = gzip.decompress(path.read_bytes()).replace(b'"value":2', b'"value":1,"value":2')
    duplicate = tmp_path / (hashlib.sha256(raw).hexdigest() + ".json.gz")
    duplicate.write_bytes(gzip.compress(raw, mtime=0))
    assert read(duplicate)["page"] == value


@pytest.mark.parametrize("mutation", ["checksum", "sequence", "generation", "schema", "cursor", "flag"])
def test_original_json_never_bypasses_envelope_or_page_checks(tmp_path, mutation):
    value = page({"value": 1})
    event = value["events"][0]
    if mutation == "checksum":
        event["sha256"] = "0" * 64
    elif mutation == "sequence":
        event["sequence"] = True
    elif mutation == "generation":
        event["generation"] = "not-a-generation"
    elif mutation == "schema":
        event["schema"] = True
    elif mutation == "cursor":
        value["next_cursor"] = f"{GENERATION}:2"
    else:
        event["_skip_validation"] = True
    with pytest.raises(archive.ArchiveError):
        archive.validate_page(value)
    with pytest.raises(archive.ArchiveError):
        read(original(tmp_path, value))


@pytest.mark.parametrize("which", ["MAX_EVENT_BYTES", "MAX_PAGE_BYTES"])
def test_original_read_keeps_canonical_byte_boundaries(tmp_path, monkeypatch, which):
    value = page({"value": "ä" * 100})
    path = original(tmp_path, value)
    measured = value["events"][0] if which == "MAX_EVENT_BYTES" else value
    size = len(archive.canonical_bytes(measured))
    monkeypatch.setattr(archive, which, size)
    assert read(path)["page"] == value
    monkeypatch.setattr(archive, which, size - 1)
    with pytest.raises(archive.ArchiveError, match="limit"):
        read(path)


@pytest.mark.parametrize("key", [1, True, None, 1.5])
def test_public_python_entrypoints_still_reject_nonstring_keys(key):
    value = page({"value": 0})
    value["events"][0]["payload"] = {"nested": [{key: "forbidden"}]}
    for validator, argument in ((archive.canonical_bytes, value),
                                (archive.validate_page, value),
                                (archive.validate_envelope, value["events"][0])):
        with pytest.raises(archive.ArchiveError, match="keys must be strings"):
            validator(argument)


def test_cycles_remain_rejected_in_strict_python_api():
    value = []
    value.append(value)
    with pytest.raises(archive.ArchiveError, match="finite JSON"):
        archive.canonical_bytes(value)


@pytest.mark.parametrize("shape", ["list", "dict", "mixed"])
def test_deep_decoded_json_keeps_the_strict_recursion_gate(tmp_path, shape):
    script = r'''
import gzip, hashlib, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from custom_components.adaptive_solar.core import archive
sys.setrecursionlimit(5000)
payload = 0
for i in range(800):
    payload = [payload] if sys.argv[3] == "list" or sys.argv[3] == "mixed" and i % 2 else {"k": payload}
generation = "00000000-0000-0000-0000-000000000001"
stamp = "2026-10-28T00:00:00+00:00"
event = {"schema": 1, "generation": generation, "sequence": 1, "event_id": "deep", "kind": "test",
         "received_at": stamp, "payload": {"value": payload}}
event["sha256"] = hashlib.sha256(archive.canonical_bytes(event)).hexdigest()
page = {"schema": 1, "generation": generation, "oldest_sequence": 1, "requested_cursor": None,
        "next_cursor": generation + ":1", "events": [event], "gap": None}
wrapper = {"schema": 1, "source": "test", "ingest_order": 1, "stored_at": stamp,
           "archive_started_at": stamp, "page": page}
raw = json.dumps(wrapper, sort_keys=True, separators=(",", ":")).encode()
path = Path(sys.argv[2]) / (hashlib.sha256(raw).hexdigest() + ".json.gz")
path.write_bytes(gzip.compress(raw, mtime=0))
sys.setrecursionlimit(400)
for operation in (lambda: archive.validate_page(page), lambda: object.__new__(archive.ArchiveStore)._read_original(path)):
    try:
        operation()
    except archive.ArchiveError:
        pass
    else:
        raise AssertionError("Deep JSON bypassed strict recursive validation")
'''
    subprocess.run([sys.executable, "-I", "-B", "-c", script, str(Path(__file__).resolve().parents[1]),
                    str(tmp_path), shape], check=True, capture_output=True, text=True, env=worker_environment())
