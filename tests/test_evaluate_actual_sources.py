"""CLI actual sources cannot bypass a later archived quality invalidation."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from scripts.capture_actuals import normalize_capture
from tests.test_capture_actuals import END, START, capture, mask
from tests.test_cli import offline_process as offline_process


def inputs():
    raw = capture()
    valid = normalize_capture(raw, mask(), normalized_at=END + timedelta(hours=3))
    negative_mask = mask(curtailed=True)
    negative_mask["provenance"]["validated_at"] = (END + timedelta(hours=2)).isoformat()
    invalid = normalize_capture(raw, negative_mask, normalized_at=END + timedelta(hours=3))
    window = {"cutoff": (START - timedelta(days=1)).isoformat(), "start": START.isoformat(),
              "end": (START + timedelta(hours=1)).isoformat(), "inverter_id": "roof"}
    payload = {"as_of": (END + timedelta(hours=3)).isoformat(), "sources": ["adaptive"],
               "windows": [window], "forecasts": [{"source": "adaptive", "issued_at": window["cutoff"],
                   "start": window["start"], "end": window["end"], "inverter_id": "roof", "power_w": 1000}],
               "actuals": valid["normalization"]["records"]}
    return payload, valid, invalid


def test_later_negative_capture_cannot_be_combined_with_older_inline_actual(offline_process, tmp_path):
    payload, valid, invalid = inputs()
    assert valid["normalization"]["records"][0]["observed_at"] < invalid["quality"]["provenance"]["validated_at"]
    assert not invalid["normalization"]["records"]
    source, captures, output = (tmp_path / name for name in ("input.json", "actuals.jsonl", "report.json"))
    source.write_text(json.dumps(payload))
    captures.write_text(json.dumps(invalid) + "\n")
    output.write_text("existing report remains unchanged\n")
    before = {path: path.read_bytes() for path in (source, captures, output)}
    process = offline_process("evaluate.py", source, "--actual-captures", captures, "--output", output)
    assert process.returncode != 0
    assert "--actual-captures cannot be combined with nonempty input.actuals" in process.stderr
    assert "quality revisions cannot be bypassed" in process.stderr
    assert all(path.read_bytes() == original for path, original in before.items())


@pytest.mark.parametrize("source_mode", ["inline", "captures_missing_actuals", "captures_empty_actuals"])
def test_exclusive_actual_source_modes_remain_available(offline_process, tmp_path, source_mode):
    payload, valid, _ = inputs()
    payload = deepcopy(payload)
    source, captures, output = (tmp_path / name for name in ("input.json", "actuals.jsonl", "report.json"))
    args = []
    if source_mode != "inline":
        if source_mode == "captures_missing_actuals":
            payload.pop("actuals")
        else:
            payload["actuals"] = []
        captures.write_text(json.dumps(valid) + "\n")
        args = ["--actual-captures", captures]
    source.write_text(json.dumps(payload))
    original = source.read_bytes()
    process = offline_process("evaluate.py", source, *args, "--output", output)
    assert process.returncode == 0, process.stderr
    report = json.loads(output.read_text())
    assert report["paired_intervals"] == 1
    assert report["scores"]["adaptive"]["overall"]["mae_w"] == 0
    assert source.read_bytes() == original
