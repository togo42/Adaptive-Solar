"""Bounded input reading and existing-quality checks for offline adapters.

This module shares adapter I/O only; source qualification stays in the core.
"""
from __future__ import annotations

import hashlib
import json

from custom_components.adaptive_solar.core.archive import canonical_bytes
from scripts import capture_actuals

MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024


class ExistingQualityConflict(ValueError):
    """Existing negative evidence needs resolution outside this adapter."""


def read_json(path, *, remaining):
    """Read bounded JSON and retain the digest and size of its original bytes."""
    limit = min(MAX_INPUT_BYTES, remaining)
    if limit < 0:
        raise ValueError("aggregate input exceeds byte bound")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("input exceeds byte bound")
    value = json.loads(raw)
    canonical_bytes(value)
    return value, {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def validate_existing_quality(capture, *, as_of, validation_time):
    """Never turn an existing rejection into a new automatic qualification."""
    quality = capture.get("quality")
    masks, provenance = capture_actuals.parse_quality(quality, normalized_at=validation_time)
    if provenance is not None and capture_actuals.utc(provenance["validated_at"]) > as_of:
        raise ValueError("existing quality is unavailable at the evidence cutoff")
    if "normalized_at" in capture or "normalization" in capture:
        if "normalized_at" not in capture or "normalization" not in capture:
            raise ValueError("incomplete existing normalization metadata")
        original_time = capture_actuals.utc(capture["normalized_at"])
        if original_time > validation_time:
            raise ValueError("existing normalization is in the future")
        verified = capture_actuals.normalize_capture(capture, quality, normalized_at=original_time)
        if canonical_bytes(verified["normalization"]) != canonical_bytes(capture["normalization"]):
            raise ValueError("existing normalization disagrees with its original inputs")
    if any(capture_actuals._quality_rejections(mask) for mask in masks):
        raise ExistingQualityConflict

