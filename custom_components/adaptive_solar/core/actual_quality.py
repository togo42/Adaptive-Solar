"""Offline whole-hour quality from original meter intervals and attestations.

Hashes establish byte integrity, not source authenticity or physical validity.
Native qualified_interval events lack configuration/producer identifiers. A
bounded external attestation must bind those facts before a mask is published.
No interval energy is apportioned: Recorder remains the hourly energy source.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
import hashlib

from ..const import MAX_ENERGY_GAP_SECONDS, MEASUREMENT_CONTRACT
from .archive import canonical_bytes, validate_envelope
from .models import SiteConfig, finite_number, utc_time
from .replay import hydrate_forecast, timestamp

BINDINGS_SCHEMA = "adaptive-solar-actual-quality-bindings-v1"
REPORT_SCHEMA = "adaptive-solar-actual-quality-report-v1"
POLICY = "qualified-original-interval-hour-coverage-v1"
CONTROL_CONTRACT = "non-restored-control-v1"
MAX_EVENTS = 500_000
MAX_BINDINGS = 1024
_BINDING_KEYS = {"id", "inverter_id", "statistic_id", "source", "generation",
                 "source_inverter_id", "config_event_id", "config_sha256", "producer_sha256",
                 "valid_from", "valid_to", "measurement_kind", "curtailment_mode", "qualification"}
_INTERVAL_KEYS = {"inverter_id", "start", "end", "observed_at", "energy_kwh",
                  "measurement_contract", "continuity_id", "boundary_reason"}
_INVALIDATING_REASONS = {"conflicting_interval_evidence", "mixed_measurement_lineage",
                         "measurement_boundary_in_hour", "contradictory_archive_generation",
                         "contradictory_configuration_in_binding_period", "energy_above_bound_output_cap",
                         "contradictory_curtailment_configuration"}


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _text(value):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 4096:
        raise ValueError("expected nonempty bounded text")
    return value


def _hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("expected SHA256")
    return value


def _events(values):
    if not isinstance(values, list) or len(values) > MAX_EVENTS:
        raise ValueError("invalid event array or event limit")
    unique, sequences = {}, {}
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("invalid event")
        event = dict(value)
        source = _text(event.pop("source", None))
        validate_envelope(event)
        identity = (source, event["event_id"])
        sequence = (source, event["generation"], event["sequence"])
        if (identity in unique and unique[identity]["sha256"] != event["sha256"]
                or sequence in sequences and sequences[sequence] != event["sha256"]):
            raise ValueError("conflicting event identity or sequence")
        unique[identity] = {**event, "source": source}
        sequences[sequence] = event["sha256"]
    return sorted(unique.values(), key=lambda e: (e["source"], e["generation"], e["sequence"]))


def _mappings(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 256:
        raise ValueError("invalid actual mappings")
    result, used = {}, set()
    for row in values:
        if not isinstance(row, dict) or set(row) != {"inverter_id", "statistic_ids"}:
            raise ValueError("invalid actual mapping")
        scope, ids = _text(row["inverter_id"]), row["statistic_ids"]
        if not isinstance(ids, list) or len(ids) != 1:
            raise ValueError("quality adapter requires one original statistic per scope")
        statistic = _text(ids[0])
        if scope in result or statistic in used:
            raise ValueError("duplicate actual scope or statistic")
        result[scope] = statistic
        used.add(statistic)
    return result


def _forecast(event, events):
    result = hydrate_forecast(event, events)
    payload = result["payload"]
    issue, receipt = timestamp(payload["issued_at"]), timestamp(event["received_at"])
    computed = timestamp(payload.get("computed_at", payload["issued_at"]))
    if not issue <= computed <= receipt:
        raise ValueError("configuration anchor chronology is invalid")
    return result


def _bindings(payload, events, mappings, as_of, generated):
    if (not isinstance(payload, dict) or set(payload) != {"schema", "bindings"}
            or payload["schema"] != BINDINGS_SCHEMA or not isinstance(payload["bindings"], list)
            or len(payload["bindings"]) > MAX_BINDINGS):
        raise ValueError("invalid binding document")
    by_id = {(e["source"], e["event_id"]): e for e in events}
    result, ids = [], set()
    for raw in payload["bindings"]:
        if not isinstance(raw, dict) or set(raw) != _BINDING_KEYS:
            raise ValueError("invalid binding fields")
        row = dict(raw)
        for key in _BINDING_KEYS - {"qualification"}:
            _text(row[key])
        if row["id"] in ids:
            raise ValueError("duplicate binding ID")
        ids.add(row["id"])
        if mappings.get(row["inverter_id"]) != row["statistic_id"]:
            raise ValueError("binding does not match actual statistic")
        if row["measurement_kind"] not in {"native_counter", "power_integral"}:
            raise ValueError("unsupported meter kind")
        if row["curtailment_mode"] not in {"signal", "unconstrained"}:
            raise ValueError("unsupported curtailment mode")
        a, b = timestamp(row["valid_from"]), timestamp(row["valid_to"])
        if not a < b <= generated:
            raise ValueError("binding must describe an elapsed bounded period")
        if any(old["inverter_id"] == row["inverter_id"] and a < old["end"] and old["start"] < b
               for old in result):
            raise ValueError("overlapping source bindings")
        original = by_id.get((row["source"], row["config_event_id"]))
        if original is None or original["generation"] != row["generation"] or original["kind"] != "forecast_issued":
            raise ValueError("missing same-source configuration anchor")
        forecast = _forecast(original, events)
        site_json = forecast["payload"]["site"]
        site = SiteConfig.from_dict(site_json)
        producer = forecast["payload"]["software"]["source_sha256"]
        if digest(site_json) != _hash(row["config_sha256"]) or producer != _hash(row["producer_sha256"]):
            raise ValueError("configuration or producer pin mismatch")
        inverter = next((i for i in site.inverters if i.id == row["source_inverter_id"]), None)
        if inverter is None or inverter.energy_entity_id != row["statistic_id"]:
            raise ValueError("binding must use the exact configured energy statistic")
        if bool(inverter.curtailed_entity_id) != (row["curtailment_mode"] == "signal"):
            raise ValueError("curtailment mode disagrees with configuration")
        facets = row["qualification"]
        if not isinstance(facets, dict) or set(facets) != {"configuration", "meter", "curtailment"}:
            raise ValueError("qualification facets required")
        unavailable = []
        for name, facet in facets.items():
            if (not isinstance(facet, dict) or set(facet) != {"verified", "evidence", "validated_at"}
                    or type(facet["verified"]) is not bool):
                raise ValueError("invalid qualification facet")
            if facet["evidence"] is not None:
                _text(facet["evidence"])
            if facet["validated_at"] is not None and timestamp(facet["validated_at"]) > generated:
                raise ValueError("qualification timestamp is in the future")
            if facet["verified"]:
                _text(facet["evidence"])
                if facet["validated_at"] is None:
                    raise ValueError("verified qualification requires timestamp")
                if timestamp(facet["validated_at"]) > as_of:
                    unavailable.append(f"{name}_qualification_not_available")
            else:
                unavailable.append(f"{name}_unverified")
        if timestamp(original["received_at"]) > as_of:
            unavailable.append("configuration_anchor_not_available")
        result.append({**row, "start": a, "end": b, "cap_w": inverter.output_cap_w,
                       "unavailable": unavailable, "binding_sha256": digest(raw)})
    return result


def _intervals(events, binding, as_of):
    """Only positive original deltas, no absent-negative-event inference."""
    unique = {}
    for event in events:
        p = event["payload"]
        if (event["kind"] != "qualified_interval" or event["source"] != binding["source"]
                or p.get("inverter_id") != binding["source_inverter_id"]):
            continue
        if set(p) not in (_INTERVAL_KEYS, _INTERVAL_KEYS | {"curtailment_measurement_contract"}):
            raise ValueError("unexpected original measurement payload fields")
        a, b, observed, received = (timestamp(v) for v in (p["start"], p["end"], p["observed_at"], event["received_at"]))
        if not a < b <= observed <= received:
            raise ValueError("invalid measured interval chronology")
        duration = (b - a).total_seconds()
        finite_number(p["energy_kwh"], "original energy", 0)
        if duration > MAX_ENERGY_GAP_SECONDS:
            raise ValueError("event is not an original bounded meter delta")
        if received > as_of or b <= binding["start"] or a >= binding["end"]:
            continue
        reasons = []
        if event["generation"] != binding["generation"]:
            reasons.append("contradictory_archive_generation")
        if p.get("measurement_contract") != MEASUREMENT_CONTRACT or not p.get("continuity_id"):
            reasons.append("unsupported_measurement_contract")
        if p.get("continuity_id") is not None:
            _text(p["continuity_id"])
        if p.get("boundary_reason") is not None:
            _text(p["boundary_reason"])
        if p["energy_kwh"] > binding["cap_w"] * 1.1 * duration / 3_600_000:
            reasons.append("energy_above_bound_output_cap")
        if binding["curtailment_mode"] == "signal" and p.get("curtailment_measurement_contract") != CONTROL_CONTRACT:
            reasons.append("unverified_curtailment_contract")
        if binding["curtailment_mode"] == "unconstrained" and "curtailment_measurement_contract" in p:
            reasons.append("contradictory_curtailment_configuration")
        key = event["generation"], digest(p)
        if key not in unique:
            unique[key] = {"start": a, "end": b, "lineage": p.get("continuity_id"),
                           "boundary": p.get("boundary_reason"), "reasons": reasons, "events": []}
        unique[key]["events"].append({"event_id": event["event_id"], "sha256": event["sha256"],
                                      "received_at": event["received_at"]})
    return sorted(unique.values(), key=lambda x: (x["start"], x["end"]))


def _config_changes(events, binding, as_of):
    """An explicit contradictory snapshot overrides a positive attestation."""
    result = []
    for event in events:
        if (event["kind"] != "forecast_issued" or event["source"] != binding["source"]
                or timestamp(event["received_at"]) > as_of):
            continue
        stamp = timestamp(event["payload"]["issued_at"])
        if not binding["start"] <= stamp < binding["end"]:
            continue
        p = _forecast(event, events)["payload"]
        if (event["generation"] != binding["generation"] or digest(p["site"]) != binding["config_sha256"]
                or p["software"]["source_sha256"] != binding["producer_sha256"]):
            result.append(event["event_id"])
    return result


def _hour(intervals, binding, start, end):
    rows = [r for r in intervals if r["start"] < end and start < r["end"]]
    reasons, evidence = set(), []
    cursor, covered, lineages = start, timedelta(0), set()
    previous_end = None
    for row in rows:
        left, right = max(start, row["start"]), min(end, row["end"])
        # Exact microsecond durations: a floating sum of many real report
        # intervals can turn 3600 seconds into 3599.9999999999986.
        covered += max(timedelta(0), right - max(cursor, left))
        cursor = max(cursor, right)
        if previous_end is not None and row["start"] < previous_end:
            reasons.add("conflicting_interval_evidence")
        previous_end = max(previous_end or row["end"], row["end"])
        lineages.add(row["lineage"])
        reasons.update(row["reasons"])
        if row["boundary"] is not None and start <= row["start"] < end:
            reasons.add("measurement_boundary_in_hour")
        # Binding must cover entire original evidence, even across hour edges.
        if row["start"] < binding["start"] or row["end"] > binding["end"]:
            reasons.add("interval_outside_binding_period")
        evidence.extend(row["events"])
    if not rows:
        reasons.add("missing_qualified_intervals")
    if covered != end - start:
        reasons.add("incomplete_interval_coverage")
    if len(lineages) > 1:
        reasons.add("mixed_measurement_lineage")
    return covered.total_seconds(), reasons, evidence


def build_quality(events, bindings, mappings, *, start, end, as_of, generated_at=None):
    """Derive a new quality revision, retaining unverified hours as diagnostics.

    as_of bounds available input evidence. generated_at is the actual validation
    time (injectable for tests), never the old measured hour or its receipt.
    Caller must verify the actual capture independently with capture_actuals.
    """
    start, end, as_of = (utc_time(t) for t in (start, end, as_of))
    generated = utc_time(generated_at or datetime.now(UTC))
    if (not start < end <= start + timedelta(days=32) or as_of > generated
            or any(t.minute or t.second or t.microsecond for t in (start, end))):
        raise ValueError("invalid UTC target hours or evidence cutoff")
    events, mapping = _events(events), _mappings(mappings)
    binding_rows = _bindings(bindings, events, mapping, as_of, generated)
    prepared = {b["id"]: (_intervals(events, b, as_of), _config_changes(events, b, as_of)) for b in binding_rows}
    hours, masks = [], []
    summary = {scope: {"total_hours": 0, "covered_hours": 0, "qualified_hours": 0, "invalidated_hours": 0, "reasons": Counter()}
               for scope in mapping}
    used = {}
    hour = start
    while hour < end:
        stop = hour + timedelta(hours=1)
        for scope in mapping:
            candidates = [b for b in binding_rows if b["inverter_id"] == scope and b["start"] <= hour and stop <= b["end"]]
            reasons, evidence, covered = set(), [], 0.0
            binding = candidates[0] if len(candidates) == 1 else None
            if binding is None:
                reasons.add("missing_whole_hour_binding")
            else:
                intervals, changes = prepared[binding["id"]]
                covered, reasons, evidence = _hour(intervals, binding, hour, stop)
                reasons.update(binding["unavailable"])
                if changes:
                    reasons.add("contradictory_configuration_in_binding_period")
                for item in evidence:
                    used[(binding["source"], item["event_id"])] = {"source": binding["source"], **item}
            if stop > as_of:
                reasons.add("target_not_finished_at_cutoff")
            eligible = not reasons
            # Explicit counterevidence must revoke earlier positive revisions.
            # Missing data/attestations alone must not. An unverified proposal
            # cannot even attribute a negative claim to this Recorder scope.
            invalidated = (binding is not None and stop <= as_of
                           and not any(reason.startswith("configuration_") for reason in binding["unavailable"])
                           and bool(reasons & _INVALIDATING_REASONS))
            row = {"inverter_id": scope, "start": hour.isoformat(), "end": stop.isoformat(),
                   "binding_id": binding["id"] if binding else None, "covered_seconds": covered,
                   "coverage_complete": covered == 3600, "qualified": eligible,
                   "mask_status": "valid" if eligible else "invalid" if invalidated else "omitted",
                   "reasons": sorted(reasons), "evidence_event_ids": sorted({e["event_id"] for e in evidence})}
            hours.append(row)
            stat = summary[scope]
            stat["total_hours"] += 1
            stat["covered_hours"] += row["coverage_complete"]
            stat["qualified_hours"] += eligible
            stat["invalidated_hours"] += invalidated
            stat["reasons"].update(reasons)
            if eligible:
                masks.append({"inverter_id": scope, "start": row["start"], "end": row["end"],
                              "quality": "valid", "complete_coverage": True, "curtailed": False, "counter_reset": False})
            elif invalidated:
                masks.append({"inverter_id": scope, "start": row["start"], "end": row["end"],
                              "quality": "invalid", "complete_coverage": False, "curtailed": None, "counter_reset": None})
        hour = stop
    for stat in summary.values():
        stat["reasons"] = dict(sorted(stat["reasons"].items()))
    provenance = {"policy": POLICY, "bindings_sha256": digest(bindings), "mappings_sha256": digest(mappings),
                  "event_set_sha256": digest(events), "as_of": as_of.isoformat(), "generated_at": generated.isoformat()}
    quality = {"schema_version": 1, "validated": True,
               "provenance": {"source": f"{POLICY}:sha256:{digest(provenance)}", "validated_at": generated.isoformat()},
               "intervals": masks}
    return {"schema": REPORT_SCHEMA, **provenance, "summary": summary, "hours": hours, "quality": quality,
            "binding_checks": [{"id": b["id"], "sha256": b["binding_sha256"], "unavailable": b["unavailable"],
                                "configuration_conflicts": prepared[b["id"]][1]} for b in binding_rows],
            "evidence_events": sorted(used.values(), key=lambda e: (e["source"], e["event_id"])),
            "hash_semantics": "byte_integrity_not_authenticity_or_physical_source_certification",
            "energy_source": "unchanged_recorder_hourly_change", "operational_use": False}
