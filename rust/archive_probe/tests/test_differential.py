"""Explicit real-Rust gate; missing binary pins fail rather than skip.

Run with ADAPTIVE_SOLAR_RUST_MODULE and ADAPTIVE_SOLAR_RUST_MODULE_SHA256.
This directory is outside the ordinary Python suite's configured testpaths.
"""
import os
from pathlib import Path
import sys

import pytest

from custom_components.adaptive_solar.core import archive
from scripts.rust_archive_probe import rust_original_reader
from tests.test_rust_archive_probe import CASES, outcome, raw_json, valid_wrapper, write_original


@pytest.fixture(scope="module")
def binary():
    path = os.environ.get("ADAPTIVE_SOLAR_RUST_MODULE")
    sha = os.environ.get("ADAPTIVE_SOLAR_RUST_MODULE_SHA256")
    if not path or not sha:
        pytest.fail("The explicit Rust differential gate requires a module path and SHA256")
    return Path(path), sha


@pytest.mark.parametrize("name,raw,compression", CASES, ids=[row[0] for row in CASES])
def test_actual_extension_matches_native_or_falls_back(tmp_path, binary, name, raw, compression):
    reader, path = write_original(tmp_path, raw, compression)
    baseline = outcome(reader, path)
    with rust_original_reader(archive, *binary) as stats:
        result = outcome(reader, path)
    assert result == baseline
    assert stats["closed"] and stats["calls"] == stats["fast_reads"] + stats["native_fallbacks"] == 1
    if name in {"ordinary", "float64_rounding"}:
        assert stats["fast_reads"] == 1


@pytest.mark.parametrize("budget,value", [("MAX_PAGE_BYTES", 1), ("MAX_EVENT_BYTES", 1), ("MAX_PAGE_EVENTS", 0)])
def test_actual_extension_obeys_current_native_budgets(tmp_path, binary, monkeypatch, budget, value):
    reader, path = write_original(tmp_path, raw_json(valid_wrapper()))
    monkeypatch.setattr(archive, budget, value)
    baseline = outcome(reader, path)
    with rust_original_reader(archive, *binary):
        assert outcome(reader, path) == baseline
    assert baseline[0] == "error"


def test_actual_extension_int_digit_limit_and_deep_tree_fallback(tmp_path, binary):
    limit, original_digits = sys.getrecursionlimit(), sys.get_int_max_str_digits()
    try:
        sys.setrecursionlimit(5000)
        sys.set_int_max_str_digits(0)
        deep = 0
        for _ in range(1100):
            deep = [deep]
        inputs = [raw_json(valid_wrapper({"deep": deep})), raw_json(valid_wrapper({"number": 10**4500}))]
    finally:
        sys.setrecursionlimit(limit)
        sys.set_int_max_str_digits(original_digits)
    for n, raw in enumerate(inputs):
        reader, path = write_original(tmp_path / str(n), raw)
        baseline = outcome(reader, path)
        with rust_original_reader(archive, *binary) as stats:
            assert outcome(reader, path) == baseline
        assert stats["native_fallbacks"] == 1

