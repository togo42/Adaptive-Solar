"""Offline whole-hour quality from original meter intervals and attestations.

Hashes establish byte integrity, not source authenticity or physical validity.
Legacy intervals lack configuration/producer identifiers. New pins permit
bounded prospective policies; external source qualification remains required.
No interval energy is apportioned: Recorder remains the hourly energy source.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json

from ..const import MAX_ENERGY_GAP_SECONDS, MEASUREMENT_CONTRACT
from .archive import canonical_bytes, validate_envelope
from .models import SiteConfig, finite_number, utc_time
from .replay import hydrate_forecast, timestamp

BINDINGS_SCHEMA = "adaptive-solar-actual-quality-bindings-v1"
CONTINUOUS_BINDINGS_SCHEMA = "adaptive-solar-actual-quality-bindings-v2"
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
                         "contradictory_curtailment_configuration", "contradictory_interval_source_binding"}
_CONFIGURATION_TOKEN = object()


@dataclass(frozen=True, init=False)
class _ForecastConfiguration:
    """Internal immutable evidence, never a replacement original envelope."""

    _canonical: bytes
    _token: object

    @property
    def retained_bytes(self):
        return len(self._canonical)


def _reference(event):
    return {key: value for key, value in event.items() if key != "payload"}


def configuration_from_forecast(event, dependencies=(), *, retain_site=False):
    """Verify complete originals before discarding irrelevant forecast arrays.

    The Python factory and the separately qualified, scoped native backend may
    issue this internal evidence type. JSON documents cannot opt into
    verification; original envelope hashes stay on references.
    """
    originals = _events([event, *dependencies])
    forecast = next(e for e in originals if (e["source"], e["event_id"]) == (event["source"], event["event_id"]))
    if forecast["kind"] != "forecast_issued":
        raise ValueError("expected an original forecast")
    payload = _forecast(forecast, originals)["payload"]
    value = {"schema": "verified-original-forecast-configuration-v1", "original": _reference(forecast),
             "dependencies": [_reference(e) for e in originals
                              if (e["source"], e["event_id"]) != (forecast["source"], forecast["event_id"])],
             "issued_at": payload["issued_at"], "computed_at": payload.get("computed_at", payload["issued_at"]),
             "site_sha256": digest(payload["site"]), "producer_sha256": payload["software"]["source_sha256"],
             "anchor_site": payload["site"] if retain_site else None}
    proof = object.__new__(_ForecastConfiguration)
    object.__setattr__(proof, "_canonical", canonical_bytes(value))
    object.__setattr__(proof, "_token", _CONFIGURATION_TOKEN)
    return proof


def _configuration_inputs(configurations, events):
    if not isinstance(configurations, list) or any(e["kind"] != "qualified_interval" for e in events):
        raise ValueError("configuration evidence requires original interval inputs")
    records, references = [], [_reference(e) for e in events]
    for proof in configurations:
        if type(proof) is not _ForecastConfiguration or getattr(proof, "_token", None) is not _CONFIGURATION_TOKEN:
            raise ValueError("configuration evidence must come from verified originals")
        row = json.loads(proof._canonical)
        references.append(row["original"])
        references.extend(row["dependencies"])
        records.append(row)
        if len(references) > MAX_EVENTS:
            raise ValueError("invalid event array or event limit")
    identities, sequences = {}, {}
    for ref in references:
        identity = ref["source"], ref["event_id"]
        sequence = ref["source"], ref["generation"], ref["sequence"]
        if (identity in identities and identities[identity]["sha256"] != ref["sha256"]
                or sequence in sequences and sequences[sequence] != ref["sha256"]):
            raise ValueError("conflicting event identity or sequence")
        identities[identity] = ref
        sequences[sequence] = ref["sha256"]
    def order(row):
        return row["source"], row["generation"], row["sequence"]

    unique = {}
    for row in records:
        ref = row["original"]
        identity = ref["source"], ref["event_id"]
        if identity not in unique or row["anchor_site"] is not None:
            unique[identity] = row
    return sorted(unique.values(), key=lambda row: order(row["original"])), sorted(identities.values(), key=order)


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


def _bindings(payload, events, mappings, as_of, generated, configurations=None):
    if (not isinstance(payload, dict) or set(payload) != {"schema", "bindings"}
            or payload["schema"] not in {BINDINGS_SCHEMA, CONTINUOUS_BINDINGS_SCHEMA} or not isinstance(payload["bindings"], list)
            or len(payload["bindings"]) > MAX_BINDINGS):
        raise ValueError("invalid binding document")
    continuous = payload["schema"] == CONTINUOUS_BINDINGS_SCHEMA
    by_id = {(e["source"], e["event_id"]): e for e in events}
    config_by_id = {(e["original"]["source"], e["original"]["event_id"]): e for e in configurations or []}
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
        if not a < b or (not continuous and b > generated):
            raise ValueError("binding must describe an elapsed bounded period")
        if any(old["inverter_id"] == row["inverter_id"] and a < old["end"] and old["start"] < b
               for old in result):
            raise ValueError("overlapping source bindings")
        config = config_by_id.get((row["source"], row["config_event_id"]))
        original = config["original"] if config is not None else by_id.get((row["source"], row["config_event_id"]))
        if original is None or original["generation"] != row["generation"] or original["kind"] != "forecast_issued":
            raise ValueError("missing same-source configuration anchor")
        forecast = _forecast(original, events) if config is None else None
        site_json = forecast["payload"]["site"] if config is None else config["anchor_site"]
        site = SiteConfig.from_dict(site_json)
        producer = forecast["payload"]["software"]["source_sha256"] if config is None else config["producer_sha256"]
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
                       "unavailable": unavailable, "binding_sha256": digest(raw), "continuous": continuous})
    return result


def _intervals(events, binding, as_of, start, end):
    """Only positive original deltas, no absent-negative-event inference."""
    unique = {}
    start, end = max(start, binding["start"]), min(end, binding["end"])
    if start >= end:
        return []
    for event in events:
        p = event["payload"]
        if (event["kind"] != "qualified_interval" or event["source"] != binding["source"]
                or p.get("inverter_id") != binding["source_inverter_id"]
                or timestamp(event["received_at"]) > as_of):
            continue
        # Availability and target/source scope precede semantic validation.
        # Original envelope integrity is still checked for the complete input.
        a, b = timestamp(p["start"]), timestamp(p["end"])
        if b <= start or a >= end:
            continue
        if set(p) - {"curtailment_measurement_contract", "source_binding"} != _INTERVAL_KEYS:
            raise ValueError("unexpected original measurement payload fields")
        observed, received = timestamp(p["observed_at"]), timestamp(event["received_at"])
        if not a < b <= observed <= received:
            raise ValueError("invalid measured interval chronology")
        duration = (b - a).total_seconds()
        finite_number(p["energy_kwh"], "original energy", 0)
        if duration > MAX_ENERGY_GAP_SECONDS:
            raise ValueError("event is not an original bounded meter delta")
        reasons = []
        source_pin = p.get("source_binding")
        expected_pin = {"schema": 1, "energy_entity_id": binding["statistic_id"],
                        "config_sha256": binding["config_sha256"], "producer_sha256": binding["producer_sha256"]}
        if source_pin is not None and canonical_bytes(source_pin) != canonical_bytes(expected_pin):
            reasons.append("contradictory_interval_source_binding")
        elif binding["continuous"] and source_pin is None:
            reasons.append("missing_interval_source_binding")
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


def _config_changes(events, binding, as_of, configurations=None):
    """An explicit contradictory snapshot overrides a positive attestation."""
    result = []
    if configurations is not None:
        for row in configurations:
            event = row["original"]
            if (event["source"] == binding["source"] and timestamp(event["received_at"]) <= as_of
                    and binding["start"] <= timestamp(row["issued_at"]) < binding["end"]
                    and (event["generation"] != binding["generation"] or row["site_sha256"] != binding["config_sha256"]
                         or row["producer_sha256"] != binding["producer_sha256"])):
                result.append(event["event_id"])
        return result
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


def build_quality(events, bindings, mappings, *, start, end, as_of, generated_at=None, configurations=None):
    """Derive a new quality revision, retaining unverified hours as diagnostics.

    as_of bounds available input evidence. generated_at is the actual validation
    time (injectable for tests), never the old measured hour or its receipt.
    Caller must verify the actual capture independently with capture_actuals.
    Without an injected test timestamp, validation is dated after coverage and
    evidence hashing finish; callers must use that returned completion time.
    """
    start, end, as_of = (utc_time(t) for t in (start, end, as_of))
    generated = utc_time(generated_at or datetime.now(UTC))
    if (not start < end <= start + timedelta(days=32) or as_of > generated
            or any(t.minute or t.second or t.microsecond for t in (start, end))):
        raise ValueError("invalid UTC target hours or evidence cutoff")
    events, mapping = _events(events), _mappings(mappings)
    configuration_rows, original_references = (None, None) if configurations is None else _configuration_inputs(configurations, events)
    binding_rows = _bindings(bindings, events, mapping, as_of, generated, configuration_rows)
    prepared = {b["id"]: (_intervals(events, b, as_of, start, end), _config_changes(events, b, as_of, configuration_rows))
                for b in binding_rows}
    # A configuration attestation covers its whole binding period. Its explicit
    # contradiction must therefore revoke old hours outside the current raw
    # query too. One range mask per binding keeps arbitrarily long policies
    # bounded without manufacturing raw observations or per-hour diagnostics.
    period_masks = {}
    for binding in binding_rows:
        if (not prepared[binding["id"]][1]
                or any(reason.startswith("configuration_") for reason in binding["unavailable"])):
            continue
        first = binding["start"].replace(minute=0, second=0, microsecond=0)
        stop = min(binding["end"], as_of).replace(minute=0, second=0, microsecond=0)
        if first < binding["start"] and first < stop:
            first += timedelta(hours=1)
        if first < stop:
            period_masks[binding["id"]] = {
                "inverter_id": binding["inverter_id"], "start": first.isoformat(), "end": stop.isoformat(),
                "quality": "invalid", "complete_coverage": False, "curtailed": None, "counter_reset": None}
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
            elif invalidated and binding["id"] not in period_masks:
                masks.append({"inverter_id": scope, "start": row["start"], "end": row["end"],
                              "quality": "invalid", "complete_coverage": False, "curtailed": None, "counter_reset": None})
        hour = stop
    masks.extend(period_masks.values())
    for stat in summary.values():
        stat["reasons"] = dict(sorted(stat["reasons"].items()))
    binding_checks = [{"id": b["id"], "sha256": b["binding_sha256"], "unavailable": b["unavailable"],
                       "configuration_conflicts": prepared[b["id"]][1]} for b in binding_rows]
    for check in binding_checks:
        if check["id"] in period_masks:
            mask = period_masks[check["id"]]
            check["invalidated_period"] = {"start": mask["start"], "end": mask["end"]}
    evidence_events = sorted(used.values(), key=lambda e: (e["source"], e["event_id"]))
    bindings_hash, mappings_hash = digest(bindings), digest(mappings)
    events_hash = digest(events if original_references is None else original_references)
    configuration_hash = None if configuration_rows is None else digest(configuration_rows)
    # All decision work, including potentially large evidence hashing/sorting,
    # precedes the actual availability timestamp. Injected times are for tests.
    completed = utc_time(generated_at or datetime.now(UTC))
    if completed < generated:
        raise ValueError("clock moved backwards during quality derivation")
    generated = completed
    provenance = {"policy": POLICY, "bindings_sha256": bindings_hash, "mappings_sha256": mappings_hash,
                  "event_set_sha256": events_hash, "as_of": as_of.isoformat(), "generated_at": generated.isoformat()}
    if configuration_rows is not None:
        provenance.update(event_set_hash_format="original-envelope-reference-manifest-v1",
                          configuration_evidence_sha256=configuration_hash)
    quality = {"schema_version": 1, "validated": True,
               "provenance": {"source": f"{POLICY}:sha256:{digest(provenance)}", "validated_at": generated.isoformat()},
               "intervals": masks}
    report = {"schema": REPORT_SCHEMA, **provenance, "summary": summary, "hours": hours, "quality": quality,
            "binding_checks": binding_checks,
            "evidence_events": evidence_events,
            "hash_semantics": "byte_integrity_not_authenticity_or_physical_source_certification",
            "energy_source": "unchanged_recorder_hourly_change", "operational_use": False}
    if configuration_rows is not None:
        report["configuration_evidence"] = configuration_rows
        report["original_event_count"] = len(original_references)
    return report
