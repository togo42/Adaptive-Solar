"""Explicitly reduced diagnostics after unchanged full quality derivation.

The compact report retains decisions and provenance, not the omitted evidence
arrays. Their hashes are commitments, not a substitute for retained originals.
"""
from __future__ import annotations

import hashlib

from custom_components.adaptive_solar.core.actual_quality import REPORT_SCHEMA
from custom_components.adaptive_solar.core.archive import canonical_bytes

COMPACT_SCHEMA = "adaptive-solar-actual-quality-report-compact-v1"
COMPACT_PROFILE = "decisions-and-evidence-digests-v1"


def _summary(value):
    return {"count": len(value), "sha256": hashlib.sha256(canonical_bytes(value)).hexdigest()}


def compact_capture(capture):
    """Keep raw/normalization/masks intact; omit only diagnostic detail arrays."""
    report = capture.get("quality_derivation")
    if not isinstance(report, dict) or report.get("schema") != REPORT_SCHEMA:
        raise ValueError("Compact diagnostics require a full quality report")
    # Unknown new report fields must not silently disappear under this profile.
    omitted = {name: _summary(report[name]) for name in ("evidence_events", "configuration_evidence")
               if name in report}
    hours = []
    for row in report["hours"]:
        ids = row["evidence_event_ids"]
        hours.append({**{key: value for key, value in row.items() if key != "evidence_event_ids"},
                      "evidence_event_count": len(ids),
                      "evidence_event_ids_sha256": _summary(ids)["sha256"]})
    compact = {key: value for key, value in report.items() if key not in omitted}
    compact.update(schema=COMPACT_SCHEMA, hours=hours, diagnostic_profile=COMPACT_PROFILE,
                   diagnostic_scope="Decisions retained; detailed event/configuration references omitted.",
                   full_report_schema=REPORT_SCHEMA,
                   full_report_sha256=hashlib.sha256(canonical_bytes(report)).hexdigest(),
                   omitted_evidence=omitted)
    return {**capture, "quality_derivation": compact}
