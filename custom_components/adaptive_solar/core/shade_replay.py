"""Chronological shade-learning replay on a complete, frozen capture episode.

The exact baseline and experimental shade tables have separate state. No fitted
residual rows are ever loaded into candidate arms. A session's recorded seed is
explicitly preexisting, unverified history; ``empty`` relearns only the observed
segment and does not turn it into a complete historical training archive.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import chain
import hashlib
from typing import Callable

from .archive import canonical_bytes
from .engine import ForecastEngine
from .models import Observation, SiteConfig, finite_number, utc_time
from .replay import (
    hydrate_forecast, reconstruct_state, replay_forecast, timed_record, timestamp,
    verify_weather_receipts, weather_from_json,
)
from .shading import BeamShadeTable
from .shade_learning import ShadeLearningPolicy, evaluate_shade_step


@dataclass(frozen=True)
class ShadeCandidate:
    """Explicitly versioned policy or independent step implementation."""

    name: str
    version: str
    policy: ShadeLearningPolicy | None = None
    step: Callable = evaluate_shade_step


def _json(value):
    from ..archive_export import json_value

    return json_value(value)


def _same(left, right):
    return canonical_bytes(_json(left)) == canonical_bytes(_json(right))


def _table(value, site, cutoff):
    table = BeamShadeTable.from_dict(value, inverter_ids={inv.id for inv in site.inverters})
    if not _same(table.to_dict(), value):
        raise ValueError("invalid or incompatible shading table")
    if any(timestamp(row["quarter_hour"]) > cutoff for bins in value["inverters"].values()
           for rows in bins.values() for row in rows):
        raise ValueError("future shade seed/sample")
    return table


def _raw_number(raw, now, kind):
    """Recheck numeric source units/freshness independently of archived masks."""
    if raw is None or raw.get("state") in (None, "unknown", "unavailable"):
        return None, None
    attrs = raw.get("attributes", {})
    if attrs.get("restored") or isinstance(raw["state"], bool):
        return None, None
    stamp = raw.get("last_reported") or raw.get("last_updated")
    if stamp is None:
        return None, None
    at = timestamp(stamp)
    if not 0 <= (now - at).total_seconds() <= (300 if kind == "irradiance" else 900):
        return None, None
    factors = {
        "power": {"W": 1, "kW": 1000, "MW": 1000000},
        "irradiance": {"W/m²": 1, "W/m2": 1, "kW/m²": 1000, "kW/m2": 1000},
        "energy": {"Wh": .001, "kWh": 1, "MWh": 1000},
        "wind": {"m/s": 1, "km/h": 1 / 3.6, "mph": .44704, "kn": .514444444},
    }
    try:
        raw_value = finite_number(float(raw["state"]), kind)
        unit = attrs.get("unit_of_measurement")
        if kind == "temperature":
            value = {"°C": lambda: raw_value, "°F": lambda: (raw_value - 32) * 5 / 9,
                     "K": lambda: raw_value - 273.15}[unit]()
            value = finite_number(value, kind, -100, 70)
        else:
            value = raw_value * factors[kind][unit]
            value = finite_number(value, kind, 0, 1600 if kind == "irradiance" else 150 if kind == "wind" else None)
    except (ValueError, TypeError, KeyError, OverflowError):
        return None, None
    return value, at



def _validate_sources(learning, site, observations, now):
    """Close every configured source and every actually used observation."""
    snapshot = learning.get("raw_state_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("missing raw shade input snapshot")
    roles = [(site.irradiance_entity_id, "irradiance", "irradiance"),
             (site.temperature_entity_id, "temperature", "temperature"), (site.wind_entity_id, "wind", "wind")]
    for inv in site.inverters:
        roles.extend(((inv.power_entity_id, f"power_{inv.id}", "power"),
                      (inv.energy_entity_id, f"energy_{inv.id}", "energy"),
                      (inv.curtailed_entity_id, f"curtailment_{inv.id}", "control"),
                      (inv.measurement_valid_entity_id, f"measurement_valid_{inv.id}", "validity")))
    normalized = {}
    for entity_id, role, kind in roles:
        if not entity_id:
            continue
        raw = snapshot.get(entity_id)
        if not isinstance(raw, dict) or raw.get("entity_id") != entity_id:
            raise ValueError("missing original raw configured source")
        qualification = raw.get("quality", {}).get(role)
        if not isinstance(qualification, dict) or not isinstance(qualification.get("status"), str):
            raise ValueError("missing original raw source qualification")
        if kind not in {"control", "validity"}:
            number, at = _raw_number(raw, now, kind)
            if qualification.get("normalized_value") != number:
                raise ValueError("raw source normalization disagrees with original value/units/cutoff")
            normalized[role] = number, at
    stage_ids = {inv.id for inv in site.inverters}
    for observation in observations:
        if observation.inverter_id not in stage_ids:
            raise ValueError("observation refers to an unknown output stage")
        for field, role in (("power_w", f"power_{observation.inverter_id}"), ("ghi_w_m2", "irradiance"),
                            ("temperature_c", "temperature"), ("wind_m_s", "wind")):
            number = getattr(observation, field)
            if number is not None:
                expected, at = normalized.get(role, (None, None))
                if number != expected or observation.time != at:
                    raise ValueError("observation disagrees with original raw source/qualification")

def _stage_input(learning, inv, site, now):
    value = learning["inputs"][inv.id]
    if set(value) != {"power_w", "power_time", "ghi_w_m2", "ghi_time", "curtailed_or_invalid"}:
        raise ValueError("incomplete normalized shade input")
    parsed = dict(value)
    if type(parsed["curtailed_or_invalid"]) is not bool:
        raise ValueError("invalid curtailed_or_invalid shade input")
    snapshot = learning.get("raw_state_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("missing raw shade input snapshot")
    for field, time_field, entity_id, role, kind in (
        ("power_w", "power_time", inv.power_entity_id, f"power_{inv.id}", "power"),
        ("ghi_w_m2", "ghi_time", site.irradiance_entity_id, "irradiance", "irradiance"),
    ):
        raw = snapshot.get(entity_id) if entity_id else None
        if entity_id and (not isinstance(raw, dict) or raw.get("entity_id") != entity_id):
            raise ValueError("missing original raw shade input")
        number, at = _raw_number(raw, now, kind)
        if value[field] != number or value[time_field] != (at.isoformat() if at else None):
            # Compare aware instants, not the spelling of a timezone offset.
            if value[field] != number or at is None or value[time_field] is None or timestamp(value[time_field]) != at:
                raise ValueError("normalized shade input disagrees with raw source or cutoff")
        if raw is not None:
            qualification = raw.get("quality", {}).get(role)
            if not isinstance(qualification, dict) or qualification.get("normalized_value") != number:
                raise ValueError("raw shade input lacks consistent qualification")
        parsed[time_field] = at
    if parsed["power_w"] is not None and parsed["power_w"] > inv.output_cap_w * 1.1 and not parsed["curtailed_or_invalid"]:
        raise ValueError("over-cap shade input is not excluded")
    for entity_id, role in ((inv.curtailed_entity_id, f"curtailment_{inv.id}"),
                            (inv.measurement_valid_entity_id, f"measurement_valid_{inv.id}")):
        if entity_id:
            raw = snapshot.get(entity_id)
            qualification = raw.get("quality", {}).get(role) if isinstance(raw, dict) else None
            if not isinstance(qualification, dict):
                raise ValueError("missing control qualification in raw shade inputs")
            state = raw.get("state")
            restored = raw.get("attributes", {}).get("restored")
            if role.startswith("curtailment_"):
                expected = "unknown" if state is None or restored else {"off": "clear", "on": "active"}.get(state, "unknown")
            else:
                expected = "valid" if state == "on" and not restored else "invalid" if state in {"on", "off"} else "unknown"
            if qualification.get("status") != expected:
                raise ValueError("control qualification disagrees with original raw state")
            predates = (role.startswith("curtailment_") and expected == "clear" and parsed["power_time"] is not None
                        and parsed["power_time"] <= max(timestamp(raw["last_changed"]), timestamp(raw["last_updated"])))
            if (expected in {"active", "unknown", "invalid"} or predates) and not parsed["curtailed_or_invalid"]:
                raise ValueError("invalid control was admitted to shade learning")
    return parsed


def replay_shading(events, dependencies=(), *, candidates=(), initial_state="recorded",
                   session_id=None, as_of: datetime | None = None, max_input_bytes=256 * 1024 * 1024):
    """Small in-memory convenience wrapper; use the stream for long archives.

    ``max_input_bytes`` bounds serialized envelopes only, not decoded data or
    Python peak RSS. The CLI separately limits declared decoded bytes per step.
    ``events`` must contain the complete selected forecast stream, including
    rejected/no-change steps. Dependencies contain original weather and chunks.
    Multiple sessions require explicit selection. Missing steps fail even when
    the neighboring shading tables happen to be identical.
    """
    if initial_state not in {"recorded", "empty"}:
        raise ValueError("initial_state must be recorded or empty")
    if not events:
        raise ValueError("no shade-learning events")
    if type(max_input_bytes) is not int or max_input_bytes <= 0:
        raise ValueError("max_input_bytes must be a positive integer")
    dependencies = list(dependencies)
    events = list(events)
    total = 0
    for event in [*events, *dependencies]:
        total += len(canonical_bytes(event))
        if total > max_input_bytes:
            raise ValueError("selected shade session exceeds serialized-envelope byte bound (not peak RSS)")
    resolved = [hydrate_forecast(event, dependencies) for event in events]
    if any(event.get("kind") != "forecast_issued" for event in resolved):
        raise ValueError("expected forecast_issued shade events")
    if as_of is not None:
        resolved = [event for event in resolved if timestamp(event["received_at"]) <= utc_time(as_of)]
    if any(not isinstance(event["payload"].get("shade_learning"), dict) for event in resolved):
        raise ValueError("missing shade-learning capture contract")
    sessions = {event["payload"]["shade_learning"].get("session_id") for event in resolved}
    if session_id is None and len(sessions) != 1:
        raise ValueError("multiple shade sessions require explicit session_id")
    session_id = session_id if session_id is not None else next(iter(sessions), None)
    resolved = [event for event in resolved if event["payload"]["shade_learning"].get("session_id") == session_id]
    if not resolved or not isinstance(session_id, str) or not session_id:
        raise ValueError("no matching declared shade session")
    resolved.sort(key=lambda event: event["payload"]["shade_learning"]["step_sequence"])
    rows = list(replay_shading_stream(((event, dependencies) for event in resolved), candidates=candidates,
                                     initial_state=initial_state, session_id=session_id, as_of=as_of))
    summary = rows.pop()
    summary.pop("record_type")
    summary["steps"] = rows
    return summary


def replay_shading_stream(stream, *, candidates=(), initial_state="recorded", session_id=None, as_of=None):
    """Yield step records then a summary, retaining no historical fit/output rows.

    The input iterator supplies ``(forecast_event, referenced_dependencies)`` in
    chronological step order. Consumers must publish only after the final
    summary; an exception means any preceding records are incomplete evidence.
    The selected episode starts at step 1 and may not cross sessions.
    """
    from ..archive_export import software_provenance

    if initial_state not in {"recorded", "empty"}:
        raise ValueError("initial_state must be recorded or empty")
    stream = iter(stream)
    try:
        first, first_dependencies = next(stream)
    except StopIteration as err:
        raise ValueError("no shade-learning events") from err
    first = hydrate_forecast(first, first_dependencies)
    first_learning = first["payload"].get("shade_learning")
    if not isinstance(first_learning, dict):
        raise ValueError("missing shade-learning capture contract")
    session_id = session_id if session_id is not None else first_learning.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("missing declared shade session")
    current = software_provenance()
    source = (first.get("source"), first.get("generation"))
    if not all(isinstance(value, str) and value for value in source):
        raise ValueError("missing source or generation identity")
    first_payload = first["payload"]
    site = SiteConfig.from_dict(first_payload["site"])
    baseline = None
    arms = {}
    for candidate in candidates:
        if not candidate.name or candidate.name in arms or candidate.name == "baseline" or not candidate.version:
            raise ValueError("shade candidate needs unique name and explicit version")
        if candidate.policy is not None and candidate.policy.version != candidate.version:
            raise ValueError("candidate version must match policy version")
        arms[candidate.name] = {"candidate": candidate, "table": None}
    previous_id, previous_time = None, None
    seen_steps = set()
    baseline_ok = True
    software_match = all(current.get(key) == first_payload["software"].get(key)
                         for key in ("source_sha256", "libraries", "export_schema"))
    count = 0
    for sequence, (event, dependencies) in enumerate(chain(((first, first_dependencies),), stream), 1):
        count = sequence
        event = hydrate_forecast(event, dependencies)
        if event.get("kind") != "forecast_issued":
            raise ValueError("expected forecast_issued shade events")
        if as_of is not None and timestamp(event["received_at"]) > utc_time(as_of):
            raise ValueError("shade step was not archived at requested as-of cutoff")
        payload = event["payload"]
        learning = payload.get("shade_learning")
        if not isinstance(learning, dict):
            raise ValueError("missing shade-learning capture contract")
        if learning.get("session_id") != session_id:
            raise ValueError("shade stream crosses declared session")
        if (event.get("source"), event.get("generation")) != source:
            raise ValueError("shade session crosses source or generation")
        if not _same(payload["site"], first_payload["site"]):
            raise ValueError("shade session crosses configuration")
        if not _same(payload["software"], first_payload["software"]):
            raise ValueError("shade session crosses software versions")
        if (type(learning.get("schema")) is not int or learning.get("schema") != 1
                or type(learning.get("step_sequence")) is not int
                or learning["step_sequence"] != sequence or learning.get("previous_step_id") != previous_id
                or not isinstance(learning.get("step_id"), str) or not learning["step_id"]
                or learning["step_id"] in seen_steps):
            raise ValueError("missing, duplicate or inconsistent shade step chain")
        if learning.get("initial_state_source") != ("session_seed" if sequence == 1 else "previous_step"):
            raise ValueError("shade session lacks declared start seed/continuity")
        if sequence == 1 and learning.get("initial_state_scope") != "unverified_preexisting_history":
            raise ValueError("shade session lacks explicit preexisting seed scope")
        if learning.get("policy_version") != ShadeLearningPolicy().version:
            raise ValueError("unsupported original shade policy version")
        now = timestamp(payload["issued_at"])
        if (timestamp(learning["evaluated_at"]) != now or now > timestamp(event["received_at"])
                or (previous_time is not None and now < previous_time)):
            raise ValueError("shade evaluation violates chronological cutoff")
        state = reconstruct_state(event, dependencies)
        receipts = verify_weather_receipts(event, dependencies)
        before = _table(state["shading_before"], site, now)
        after = _table(state["shading"], site, now)
        if baseline is None:
            baseline = before
            for arm in arms.values():
                arm["table"] = before.copy() if initial_state == "recorded" else BeamShadeTable()
        if not _same(baseline.to_dict(), before.to_dict()):
            raise ValueError("recorded shade state does not continue previous step")
        weather = tuple(weather_from_json(row) for row in payload["weather"])
        observations = tuple(timed_record(Observation, row, {"time"}) for row in payload["observations"])
        if any(row.time > now for row in observations) or any(row.issued_at > now for row in weather):
            raise ValueError("future observation/weather in shade replay")
        _validate_sources(learning, site, observations, now)
        stage_ids = {inv.id for inv in site.inverters}
        if set(learning["inputs"]) != stage_ids or set(learning["decisions"]) != stage_ids:
            raise ValueError("incomplete shade stage decisions/inputs")
        decisions, arm_decisions = {}, {name: {} for name in arms}
        for inv in site.inverters:
            stage_input = _stage_input(learning, inv, site, now)
            decisions[inv.id] = evaluate_shade_step(site, inv, weather, now, observations, baseline, stage_input)
            for name, arm in arms.items():
                candidate = arm["candidate"]
                arm_decisions[name][inv.id] = candidate.step(site, inv, weather, now, observations,
                                                            arm["table"], dict(stage_input), policy=candidate.policy)
        decision_match = _same(decisions, learning["decisions"])
        state_match = _same(baseline.to_dict(), after.to_dict())
        original_forecast = replay_forecast(event, dependencies, as_of=as_of)["baseline"]
        baseline_ok &= decision_match and state_match and original_forecast["accepted"]
        # An incorrect baseline cannot be reset from the next recorded state.
        if not state_match:
            raise ValueError("baseline shade state mismatch; refusing a silent state reset")
        input_hash = hashlib.sha256(canonical_bytes({"payload": payload, "state": state})).hexdigest()
        outputs = {}
        for name, arm in arms.items():
            forecast = ForecastEngine(site, arm["table"]).forecast(weather, now)
            outputs[name] = {"version": arm["candidate"].version, "decisions": arm_decisions[name],
                             "shading": arm["table"].to_dict(), "result": forecast,
                             "support_status": "available_intervals_only" if forecast.points else "unavailable:no_forecast_support",
                             "coverage_policy": "omitted_intervals_are_unavailable"}
        yield {"record_type": "step", "event_id": event["event_id"], "step_id": learning["step_id"], "step_sequence": sequence,
                        "issued_at": now.isoformat(), "input_sha256": input_hash, "replay_source_sha256": current["source_sha256"],
                        "baseline": {"decisions_match": decision_match, "state_match": state_match,
                                     "decisions": decisions, "original_forecast": original_forecast},
                        "verified_weather_receipts": receipts, "candidates": outputs}
        seen_steps.add(learning["step_id"])
        previous_id, previous_time = learning["step_id"], now
    yield {"record_type": "summary", "schema": 1, "session_id": session_id, "source": source[0], "generation": source[1],
            "initial_state": initial_state, "initial_state_scope": "unverified_preexisting_history" if initial_state == "recorded"
            else "observed_segment_only", "baseline": {"accepted": bool(baseline_ok and software_match),
                                                        "software_match": software_match},
            "candidate_versions": {name: arm["candidate"].version for name, arm in arms.items()},
            "replay_software": current, "step_count": count,
            "accuracy_status": "unevaluated:no_qualified_paired_actuals", "residual_learning": "disabled_in_candidates"}
