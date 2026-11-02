"""The synthetic baseline preserves inputs and separates cost from decisions."""
import json
from pathlib import Path

import pytest

from scripts import benchmark_quality as benchmark


def test_history_growth_reads_more_originals_with_identical_decisions(tmp_path):
    decisions = []
    reads = []
    for days in (1, 2):
        directory = tmp_path / f"days-{days}"
        fixture = benchmark.prepare_fixture(directory, days, 100)
        before = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        plain, profiled = directory / "run-1.json", directory / "profile.json"
        benchmark.measure_worker(directory, plain)
        benchmark.measure_worker(directory, profiled, profile=True)
        result, profile = (json.loads(p.read_text()) for p in (plain, profiled))
        assert result["accepted_records"] == 24
        assert result["result_sha256"] == profile["result_sha256"]
        assert result["total_wall_seconds"] > 0
        assert profile["original_reads"]["calls"] == fixture["batches"]
        assert profile["original_reads"]["events"] == fixture["events"]
        assert profile["original_reads"]["compressed_bytes"] == fixture["compressed_original_bytes"]
        assert all(p.read_bytes() == contents for p, contents in before.items())
        decisions.append(result["decision_sha256"])
        reads.append(profile["original_reads"]["events"])
    assert decisions[0] == decisions[1]
    assert reads[1] > reads[0]


def test_worker_rejects_input_overwrite_and_changed_frozen_bytes(tmp_path):
    directory = tmp_path / "fixture"
    benchmark.prepare_fixture(directory, 1, 100)
    raw = directory / "raw.json"
    before = raw.read_bytes()
    with pytest.raises(ValueError, match="Worker output"):
        benchmark.measure_worker(directory, raw)
    assert raw.read_bytes() == before
    # Whitespace preserves JSON semantics but violates the frozen original bytes.
    raw.write_bytes(before + b"\n")
    output = directory / "run-1.json"
    with pytest.raises(ValueError, match="Frozen synthetic input"):
        benchmark.measure_worker(directory, output)
    assert not output.exists()


@pytest.mark.parametrize("arguments", [
    ["--days", "0"], ["--days", "1", "1"], ["--repeats", "11"], ["--page-events", "0"],
    ["--days", "30", "--page-events", "1"], ["--days", "28", "29", "30"],
])
def test_invalid_workload_is_rejected_before_creating_output(tmp_path, arguments):
    output = tmp_path / "new-baseline"
    with pytest.raises(SystemExit) as error:
        benchmark.main(["--output", str(output), *arguments])
    assert error.value.code == 2
    assert not Path(output).exists()
