#!/usr/bin/env python3
"""Read-only, prospective capture of native HA Energy solar forecasts.

Verified against HA 2026.10.3 components/energy/websocket_api.py and types.py:
request {"id": 1, "type": "energy/solar_forecast"}; there is NO entry-id
filter argument. The reply maps Energy-linked config entries to
{"wh_hours": {aware-hour-start: Wh}}. Filter only the private mapping locally.
No Energy preferences, providers or other HA state are modified.

Private JSON schema (store in ignored data/):
{"mappings": [{"inverter_id": "site_total", "source": "adaptive",
               "entry_ids": ["PRIVATE_ENTRY_ID"]}]}
A site-total provider must be compared with the same physical scope, never
assigned separately to multiple inverters. No provider issue time is invented:
issued_at is the first local receipt of this captured response, NOT the first
appearance of a provider curve over its entire history. Each replay is retained.

Native quarter-hour contract verified 2026-10-25 against the HA adapter's
sensor.py/local_days.py and published open-meteo-solar-forecast 0.1.32 source:
the producer subtracts 15 minutes from the API end label, then builds
wh_period_15m from that start-keyed interval-average power. The public producer
contract also documents [start,start+15min):
https://github.com/rany2/open-meteo-solar-forecast/blob/5a8f3da2620c163e6f360f3c063823e273a7e140/src/open_meteo_solar_forecast/open_meteo_solar_forecast.py
The collector therefore never subtracts another 15 minutes from native keys.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import fcntl
import json
import math
import os
import stat
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit
import uuid

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.replay_paths import validate_append_output  # noqa: E402

SOURCES = {"adaptive", "helios", "open_meteo"}
BOUNDARIES = {"ac_inverter_output", "dc_charge_controller_output", "mixed_output_generation_sum"}


def _finite(value) -> bool:
    try:
        return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        return False


class CaptureError(ValueError):
    """A capture could not be completed safely; messages contain no credentials."""


def parse_mapping(payload: dict) -> tuple[dict, ...]:
    if not isinstance(payload, dict) or set(payload) != {"mappings"}:
        raise CaptureError("Mapping must contain only a mappings list")
    rows = payload["mappings"]
    if not isinstance(rows, list) or not rows:
        raise CaptureError("Mapping list must not be empty")
    groups, used_entries, used_groups = [], set(), set()
    for row in rows:
        shapes = [{"inverter_id", "source", selector} for selector in
                  ("entry_ids", "quality_entity_id", "wh_period_entities", "reference_entry_ids")]
        shapes.append({"inverter_id", "source", "wh_period_15m_entities", "output_cap_w"})
        if (not isinstance(row, dict)
                or set(row) - {"measurement_boundary", "measurement_boundary_evidence"} not in shapes):
            raise CaptureError("Each mapping requires inverter_id, source and exactly one forecast selector")
        if "measurement_boundary" in row and (not isinstance(row["measurement_boundary"], str)
                                               or row["measurement_boundary"] not in BOUNDARIES):
            raise CaptureError("Mapping requires a canonical measurement boundary")
        if "measurement_boundary_evidence" in row and (
                "measurement_boundary" not in row or not isinstance(row["measurement_boundary_evidence"], str)
                or not row["measurement_boundary_evidence"].strip()):
            raise CaptureError("Mapping evidence must be a private provenance reference for its declared boundary")
        inverter, source = row["inverter_id"], row["source"]
        if not isinstance(inverter, str) or not inverter.strip() or inverter != inverter.strip():
            raise CaptureError("Invalid inverter scope")
        if not isinstance(source, str) or source not in SOURCES:
            raise CaptureError("Unknown forecast source")
        if (inverter, source) in used_groups:
            raise CaptureError("Duplicate source/inverter scope")
        if "wh_period_entities" in row or "wh_period_15m_entities" in row:
            selector = "wh_period_15m_entities" if "wh_period_15m_entities" in row else "wh_period_entities"
            arrays = row[selector]
            if (source != "open_meteo" or not isinstance(arrays, list) or not arrays
                    or any(not isinstance(array, list) or not array for array in arrays)):
                raise CaptureError("Native Wh selector requires nonempty Open-Meteo array/day entity groups")
            if selector == "wh_period_15m_entities":
                cap = row["output_cap_w"]
                if (not _finite(cap) or cap <= 0
                        or row.get("measurement_boundary") != "dc_charge_controller_output"):
                    raise CaptureError("Native quarter-hour DC reference requires a positive cap and dc_charge_controller_output boundary")
            entities = [entity for array in arrays for entity in array]
            if any(not isinstance(entity, str) or not entity.startswith("sensor.") or entity != entity.strip() for entity in entities):
                raise CaptureError("Invalid native Wh sensor selector")
            if len(entities) != len(set(entities)) or used_entries.intersection(entities):
                raise CaptureError("Each native Wh entity may be assigned only once")
            used_entries.update(entities)
            used_groups.add((inverter, source))
            groups.append({**row, selector: [list(array) for array in arrays]})
            continue
        if "reference_entry_ids" in row:
            entries = row["reference_entry_ids"]
            if (source not in {"helios", "open_meteo"} or not isinstance(entries, list) or not entries
                    or len(entries) > 16 or any(not isinstance(entry, str) or not entry.strip() or entry != entry.strip() for entry in entries)):
                raise CaptureError("reference_entry_ids requires 1-16 explicit reference entry identifiers")
            if len(entries) != len(set(entries)) or used_entries.intersection(entries):
                raise CaptureError("Each reference entry may be assigned only once")
            used_entries.update(entries)
            used_groups.add((inverter, source))
            groups.append({**row, "reference_entry_ids": list(entries)})
            continue
        if "quality_entity_id" in row:
            entity = row["quality_entity_id"]
            if (source != "adaptive" or not isinstance(entity, str)
                    or not entity.startswith("sensor.") or entity != entity.strip()):
                raise CaptureError("quality_entity_id requires an adaptive sensor entity")
            if entity in used_entries:
                raise CaptureError("A quality entity may be assigned only once")
            used_entries.add(entity)
            used_groups.add((inverter, source))
            groups.append(dict(row))
            continue
        entries = row["entry_ids"]
        if (not isinstance(entries, list) or not entries
                or any(not isinstance(entry, str) or not entry.strip() or entry != entry.strip() for entry in entries)):
            raise CaptureError("entry_ids must be a nonempty list of strings")
        if len(entries) != len(set(entries)) or used_entries.intersection(entries):
            raise CaptureError("An entry may be assigned only once, avoiding double counting")
        used_entries.update(entries)
        used_groups.add((inverter, source))
        groups.append({**row, "entry_ids": list(entries)})
    if sum(len(row.get("reference_entry_ids", ())) for row in groups) > 16:
        raise CaptureError("At most 16 native reference entries may be requested")
    return tuple(groups)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CaptureError("Capture receipt must be timezone aware")
    return value.astimezone(timezone.utc)


def _hours(snapshot) -> dict[datetime, float]:
    if not isinstance(snapshot, dict) or set(snapshot) != {"wh_hours"} or not isinstance(snapshot["wh_hours"], dict):
        raise CaptureError("Malformed forecast snapshot")
    hours = {}
    for key, energy in snapshot["wh_hours"].items():
        if not isinstance(key, str):
            raise CaptureError("Malformed forecast hour")
        try:
            stamp = _utc(datetime.fromisoformat(key))
            if stamp.minute or stamp.second or stamp.microsecond:
                raise CaptureError("Forecast keys must be complete hour starts")
        except (ValueError, TypeError, OverflowError) as exc:
            raise CaptureError("Malformed forecast hour") from exc
        if (isinstance(energy, bool) or not isinstance(energy, (int, float))
                or not math.isfinite(energy) or energy < 0):
            raise CaptureError("Malformed forecast energy")
        if stamp in hours:
            raise CaptureError("Duplicate normalized forecast hour")
        hours[stamp] = float(energy)
    return hours


def build_capture(result: dict, mappings: tuple[dict, ...], retrieved_at: datetime) -> dict:
    """Keep requested original snapshots; require identical keys for a sum.

    Provider omissions remain gaps. Complete identical hourly keys can include
    gaps, and no omitted night or intermediate hour is manufactured as zero.
    """
    if not isinstance(result, dict):
        raise CaptureError("Energy forecast result must be a mapping")
    retrieved_at = _utc(retrieved_at)
    stamp = retrieved_at.isoformat()
    selected = {entry for row in mappings for entry in row.get("entry_ids", [])}
    snapshots = {entry: result[entry] for entry in sorted(selected) if entry in result}
    groups = []
    for mapping in mappings:
        if "entry_ids" not in mapping:
            continue
        group = {**mapping, "issued_at": stamp, "retrieved_at": stamp,
                 "status": "available", "missing_entry_ids": [], "invalid_entry_ids": [], "records": []}
        contributions = []
        for entry in mapping["entry_ids"]:
            if entry not in result:
                group["missing_entry_ids"].append(entry)
                continue
            try:
                contributions.append(_hours(result[entry]))
            except CaptureError:
                group["invalid_entry_ids"].append(entry)
        if group["missing_entry_ids"]:
            group["status"] = "missing_entries"
        elif group["invalid_entry_ids"]:
            group["status"] = "invalid_entries"
        elif any(set(value) != set(contributions[0]) for value in contributions[1:]):
            group["status"] = "incompatible_hours"
        elif not contributions[0]:
            group["status"] = "empty_forecast"
        else:
            for start in sorted(contributions[0]):
                energy_wh = sum(value[start] for value in contributions)
                if not math.isfinite(energy_wh):
                    raise CaptureError("Nonfinite aggregate forecast energy")
                group["records"].append({"source": mapping["source"], "inverter_id": mapping["inverter_id"],
                    "issued_at": stamp, "retrieved_at": stamp, "start": start.isoformat(),
                    "end": (start + timedelta(hours=1)).isoformat(), "energy_wh": energy_wh,
                    "power_w": energy_wh})
        groups.append(group)
    return {"schema_version": 1, "capture_id": str(uuid.uuid4()), "issued_at": stamp,
            "retrieved_at": stamp, "command": "energy/solar_forecast", "snapshots": snapshots, "groups": groups}


def quality_groups(states: list, mappings: tuple[dict, ...], retrieved_at: datetime) -> tuple[list, dict]:
    """Read native per-inverter curves without deriving them from site totals."""
    if not isinstance(states, list):
        raise CaptureError("HA state result must be a list")
    stamp = _utc(retrieved_at).isoformat()
    groups, snapshots = [], {}
    for mapping in mappings:
        entity = mapping.get("quality_entity_id")
        if entity is None:
            continue
        matched = [state for state in states if isinstance(state, dict) and state.get("entity_id") == entity]
        group = {**mapping, "issued_at": stamp, "retrieved_at": stamp,
                 "status": "available", "records": []}
        if not matched:
            group["status"] = "missing_entity"
        elif len(matched) != 1:
            group["status"] = "invalid_entity"
        else:
            state = matched[0]
            attributes = state.get("attributes")
            forecast = attributes.get("forecast") if isinstance(attributes, dict) else None
            metadata_keys = {"output_type", "output_types", "measurement_boundary", "measurement_boundaries",
                             "output_stage_boundaries", "native_energy_eligible", "forecast_scope",
                             "operational_curtailment", "operational_curtailment_modelled", "control_status_as_of",
                             "power_nowcast_control", "coverage"}
            native_metadata = {key: attributes[key] for key in metadata_keys if isinstance(attributes, dict) and key in attributes}
            group["native_metadata"] = native_metadata
            snapshots[entity] = {"entity_id": entity, "state": state.get("state"),
                                 "last_updated": state.get("last_updated"), "attributes": {"forecast": forecast, **native_metadata}}
            declared = mapping.get("measurement_boundary")
            expected_type = {"ac_inverter_output": "ac", "dc_charge_controller_output": "dc",
                             "mixed_output_generation_sum": "mixed"}.get(declared)
            expected_types = ["ac", "dc"] if expected_type == "mixed" else [expected_type]
            expected_boundaries = ["ac_inverter_output", "dc_charge_controller_output"] if expected_type == "mixed" else [declared]
            conflict = declared is not None and any(
                key in native_metadata and native_metadata[key] != expected
                for key, expected in (("measurement_boundary", declared), ("output_type", expected_type),
                                      ("output_types", expected_types), ("measurement_boundaries", expected_boundaries)))
            if declared is not None and "output_stage_boundaries" in native_metadata:
                stages = native_metadata["output_stage_boundaries"]
                conflict = (conflict or not isinstance(stages, dict) or not stages
                            or any(not isinstance(value, str) for value in stages.values())
                            or set(stages.values()) != set(expected_boundaries))
            group["measurement_boundary_check"] = ("conflict" if conflict else "matched" if declared is not None
                and native_metadata.get("measurement_boundary") == declared else "legacy_unverified" if declared else "undeclared")
            if state.get("state") in {None, "unknown", "unavailable"}:
                group["status"] = "unavailable_entity"
            elif conflict:
                group["status"] = "invalid_entity"
            elif not isinstance(forecast, list):
                group["status"] = "invalid_entity"
            elif not forecast:
                group["status"] = "empty_forecast"
            else:
                try:
                    previous_end = None
                    records = []
                    for point in forecast:
                        if (not isinstance(point, dict)
                                or not {"start", "end", "power_w", "energy_kwh"} <= set(point)
                                or set(point) - {"start", "end", "power_w", "energy_kwh", "lower_w", "upper_w"}):
                            raise CaptureError("Malformed native forecast interval")
                        start, end = (_utc(datetime.fromisoformat(point[key])) for key in ("start", "end"))
                        if end <= start or previous_end is not None and start < previous_end:
                            raise CaptureError("Native forecast intervals overlap or are unordered")
                        power, energy = point["power_w"], point["energy_kwh"]
                        if any(isinstance(value, bool) or not isinstance(value, (int, float))
                               or not math.isfinite(value) or value < 0 for value in (power, energy)):
                            raise CaptureError("Malformed native forecast power/energy")
                        expected = power * (end - start).total_seconds() / 3_600_000
                        # HA quality sensors round kWh to four decimals and W
                        # to two; allow only that published rounding precision.
                        if not math.isclose(energy, expected, rel_tol=1e-6, abs_tol=0.00006):
                            raise CaptureError("Native forecast energy differs from interval mean power")
                        records.append({"source": mapping["source"], "inverter_id": mapping["inverter_id"],
                            "issued_at": stamp, "retrieved_at": stamp, "start": start.isoformat(),
                            "end": end.isoformat(), "energy_wh": energy * 1000, "power_w": power})
                        previous_end = end
                    group["records"] = records
                except (ValueError, TypeError, OverflowError):
                    group["status"] = "invalid_entity"
        groups.append(group)
    return groups, snapshots


def native_wh_state_groups(states: list, mappings: tuple[dict, ...], retrieved_at: datetime) -> tuple[list, dict]:
    """Exact Open-Meteo native Wh, not integration of instantaneous watts.

    Primary source: rany2/ha-open-meteo-solar-forecast commit 7af5d681,
    sensor.py:311-349 exposes wh_period, energy.py returns the same values.
    Union selected day sensors inside each physical array, then sum arrays only
    when their complete normalized hourly key sets agree. Omitted days remain
    omitted. A missing selected day entity invalidates the complete group.
    """
    if not isinstance(states, list):
        raise CaptureError("HA state result must be a list")
    stamp = _utc(retrieved_at).isoformat()
    groups, snapshots = [], {}
    for mapping in mappings:
        arrays = mapping.get("wh_period_entities")
        if arrays is None:
            continue
        group = {**mapping, "issued_at": stamp, "retrieved_at": stamp, "status": "available", "records": []}
        contributions = []
        for entities in arrays:
            hours = {}
            for entity in entities:
                matches = [state for state in states if isinstance(state, dict) and state.get("entity_id") == entity]
                if not matches:
                    group["status"] = "missing_entity"
                    continue
                if len(matches) != 1:
                    group["status"] = "invalid_entity"
                    continue
                state = matches[0]
                attributes = state.get("attributes")
                wh_period = attributes.get("wh_period") if isinstance(attributes, dict) else None
                snapshots[entity] = {"entity_id": entity, "state": state.get("state"),
                    "last_updated": state.get("last_updated"), "attributes": {"wh_period": wh_period}}
                if not isinstance(state.get("state"), str) or state["state"] in {"unknown", "unavailable"}:
                    group["status"] = "unavailable_entity"
                    continue
                try:
                    day = _hours({"wh_hours": wh_period})
                    if any(hour in hours and hours[hour] != energy for hour, energy in day.items()):
                        raise CaptureError("Conflicting duplicate native Wh day")
                    hours.update(day)
                except CaptureError:
                    group["status"] = "invalid_entity"
            contributions.append(hours)
        if group["status"] == "available":
            if any(set(hours) != set(contributions[0]) for hours in contributions[1:]):
                group["status"] = "incompatible_hours"
            elif not contributions[0]:
                group["status"] = "empty_forecast"
            else:
                for start in sorted(contributions[0]):
                    energy = sum(hours[start] for hours in contributions)
                    if not math.isfinite(energy):
                        group["status"], group["records"] = "invalid_entries", []
                        break
                    group["records"].append({"source": mapping["source"], "inverter_id": mapping["inverter_id"],
                        "issued_at": stamp, "retrieved_at": stamp, "start": start.isoformat(),
                        "end": (start + timedelta(hours=1)).isoformat(), "energy_wh": energy, "power_w": energy})
        groups.append(group)
    return groups, snapshots


def _quarters(values) -> dict[datetime, float | None]:
    """Read original Wh/15min only. Invalid numeric slots stay explicit gaps."""
    if not isinstance(values, dict):
        raise CaptureError("Missing native quarter-hour energies")
    result = {}
    for key, value in values.items():
        try:
            start = _utc(datetime.fromisoformat(key))
        except (ValueError, TypeError, OverflowError) as exc:
            raise CaptureError("Invalid native quarter-hour timestamp") from exc
        if start.minute % 15 or start.second or start.microsecond or start in result:
            raise CaptureError("Native quarter-hour keys must be unique absolute quarter-hour starts")
        valid = _finite(value) and value >= 0
        result[start] = float(value) if valid else None
    return result


def native_dc_wh_state_groups(states: list, mappings: tuple[dict, ...], retrieved_at: datetime) -> tuple[list, dict]:
    """Sum synchronous ORIGINAL array Wh/15min, cap jointly, then aggregate.

    No instantaneous watts or hourly averages are expanded into quarter hours.
    Native per-array provider limits remain part of the reference; this adds
    the explicitly declared common output constraint after their native sum.
    Four fully known capped slots are necessary for an hourly record. Original
    selected attributes remain unchanged in snapshots; normalization is separate.
    """
    if not isinstance(states, list):
        raise CaptureError("HA state result must be a list")
    stamp = _utc(retrieved_at).isoformat()
    groups, snapshots = [], {}
    for mapping in mappings:
        arrays = mapping.get("wh_period_15m_entities")
        if arrays is None:
            continue
        group = {**mapping, "issued_at": stamp, "retrieved_at": stamp, "status": "available", "records": []}
        normalization = {"schema_version": 1, "method": "native_15m_sum_shared_cap_then_hour_sum",
                         "measurement_boundary": mapping["measurement_boundary"], "output_cap_w": mapping["output_cap_w"],
                         "source_attribute": "wh_period_15m", "slot_duration_seconds": 900,
                         "native_key_semantics": "interval_start", "interval_closure": "[start,end)",
                         "native_array_limits_preserved": True, "quarters": [], "incomplete_hours": []}
        group["normalization"] = normalization
        contributions = []
        for entities in arrays:
            quarters = {}
            for entity in entities:
                matches = [state for state in states if isinstance(state, dict) and state.get("entity_id") == entity]
                if len(matches) != 1:
                    group["status"] = "missing_entity" if not matches else "invalid_entity"
                    continue
                state = matches[0]
                attrs = state.get("attributes")
                raw = attrs.get("wh_period_15m") if isinstance(attrs, dict) else None
                snapshots[entity] = {"entity_id": entity, "state": state.get("state"),
                                     "last_updated": state.get("last_updated"), "attributes": {"wh_period_15m": raw}}
                if not isinstance(state.get("state"), str) or state["state"] in {"unknown", "unavailable"}:
                    group["status"] = "unavailable_entity"
                    continue
                try:
                    parsed = _quarters(raw)
                    if any(start in quarters and quarters[start] != value for start, value in parsed.items()):
                        raise CaptureError("Conflicting native day components")
                    quarters.update(parsed)
                except CaptureError:
                    group["status"] = "invalid_entity"
            contributions.append(quarters)
        if group["status"] == "available":
            slots = sorted({start for array in contributions for start in array})
            combined = {}
            for start in slots:
                values = [array.get(start) for array in contributions]
                if any(value is None for value in values):
                    normalization["quarters"].append({"start": start.isoformat(), "status": "missing_component",
                        "missing_array_indices": [index for index, value in enumerate(values) if value is None]})
                    continue
                total = sum(values)
                if not math.isfinite(total):
                    group["status"] = "invalid_entries"
                    break
                energy = min(total, mapping["output_cap_w"] / 4)
                combined[start] = energy
                normalization["quarters"].append({"start": start.isoformat(), "end": (start + timedelta(minutes=15)).isoformat(),
                    "status": "available", "native_component_wh": values, "sum_before_cap_wh": total,
                    "output_energy_wh": energy, "cap_applied": energy < total})
            if group["status"] == "available":
                for start in sorted({slot.replace(minute=0) for slot in slots}):
                    keys = [start + timedelta(minutes=15 * index) for index in range(4)]
                    if any(key not in combined for key in keys):
                        normalization["incomplete_hours"].append(start.isoformat())
                        continue
                    energy = sum(combined[key] for key in keys)
                    if not math.isfinite(energy):
                        group["status"], group["records"] = "invalid_entries", []
                        break
                    group["records"].append({"source": mapping["source"], "inverter_id": mapping["inverter_id"],
                        "issued_at": stamp, "retrieved_at": stamp, "start": start.isoformat(),
                        "end": (start + timedelta(hours=1)).isoformat(), "energy_wh": energy, "power_w": energy})
                if not group["records"] and group["status"] == "available":
                    group["status"] = "empty_forecast"
        groups.append(group)
    return groups, snapshots


def cutoff_preflight(cutoff: datetime, *, now: datetime | None = None, timeout: float = 30, margin: float = 5,
                     mappings: tuple[dict, ...] = ()) -> dict:
    """Local timing plan only; no HA requests, file writes or scheduling."""
    cutoff, now = _utc(cutoff), _utc(now or datetime.now(timezone.utc))
    for value in (timeout, margin):
        if not _finite(value):
            raise CaptureError("Invalid cutoff planning duration")
    if not 0 < timeout <= 120 or not 0 <= margin <= 3600:
        raise CaptureError("Invalid cutoff planning duration")
    latest = cutoff - timedelta(seconds=timeout + margin)
    boundaries_declared = bool(mappings) and all(row.get("measurement_boundary") in BOUNDARIES
                                                 and row.get("measurement_boundary_evidence") for row in mappings)
    return {"schema_version": 1, "declared_cutoff": cutoff.isoformat(), "checked_at": now.isoformat(),
            "latest_recommended_start": latest.isoformat(), "timeout_seconds": timeout, "margin_seconds": margin,
            "timing_ready": now <= latest, "mapping_boundary_evidence_declared": bool(boundaries_declared),
            "forecast_capture_ready": bool(now <= latest and boundaries_declared),
            "evidence_semantics": "declared_private_provenance_reference_not_automatic_certification",
            "availability": "not_probed", "actual_quality": "not_checked", "benchmark_acceptance": "not_checked",
            "scheduler_changed": False}


def reference_groups(result, mappings: tuple[dict, ...], retrieved_at: datetime) -> tuple[list, dict]:
    """Normalize only the fixed response-only bridge's native Energy payload."""
    groups, snapshots = [], {}
    stamp = _utc(retrieved_at).isoformat()
    domains = {"helios": "helios_forecast", "open_meteo": "open_meteo_solar_forecast"}
    for mapping in mappings:
        ids = mapping.get("reference_entry_ids")
        if ids is None:
            continue
        group = {**mapping, "issued_at": stamp, "retrieved_at": stamp,
                 "status": "available", "records": []}
        entries = {}
        for entry in ids:
            if result is None or not isinstance(result, dict) or entry not in result:
                group["status"] = "missing_entries"
                continue
            response = result[entry]
            if (not isinstance(response, dict) or set(response) != {"domain", "status", "forecast", "retrieved_at"}
                    or response.get("domain") != domains[mapping["source"]]):
                group["status"] = "invalid_entries"
                continue
            try:
                # Server receipt is preserved as provenance only; actual local
                # WS reception is the conservative issue used for evaluation.
                _utc(datetime.fromisoformat(response["retrieved_at"]))
                if response["status"] != "available":
                    group["status"] = "missing_entries"
                else:
                    _hours(response["forecast"])
                    entries[entry] = response["forecast"]
                snapshots[entry] = response
            except (ValueError, TypeError, KeyError, OverflowError):
                group["status"] = "invalid_entries"
        if group["status"] == "available":
            native_map = ({"source": mapping["source"], "inverter_id": mapping["inverter_id"], "entry_ids": ids},)
            built = build_capture(entries, native_map, retrieved_at)["groups"][0]
            group.update({key: value for key, value in built.items() if key != "entry_ids"})
        groups.append(group)
    return groups, snapshots


def websocket_url(ha_url: str) -> str:
    try:
        parsed = urlsplit(ha_url)
        if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise CaptureError("HA_URL must be a base HTTP(S) or WS(S) URL without credentials or query")
        _ = parsed.port  # Validate a numeric, legal port without reporting URL.
        path = parsed.path.rstrip("/")
        if not path.endswith("/api/websocket"):
            path += "/api/websocket"
        return urlunsplit(("wss" if parsed.scheme in {"https", "wss"} else "ws", parsed.netloc, path, "", ""))
    except ValueError as exc:
        raise CaptureError("Invalid HA_URL") from exc


async def capture_forecasts(ha_url: str, token: str, mappings: tuple[dict, ...], *, timeout: float = 30,
                            session=None, cutoff: datetime | None = None) -> dict:
    cutoff = _utc(cutoff) if cutoff is not None else None
    if not isinstance(token, str) or not token.strip():
        raise CaptureError("HA_TOKEN is required")
    if not _finite(timeout) or not 0 < timeout <= 120:
        raise CaptureError("Timeout must be between zero and 120 seconds")
    url = websocket_url(ha_url)

    async def request(client):
        async with asyncio.timeout(timeout):
            async with client.ws_connect(url, max_msg_size=8 * 1024 * 1024) as ws:
                required = await ws.receive_json()
                if not isinstance(required, dict) or required.get("type") != "auth_required":
                    raise CaptureError("Unexpected HA authentication handshake")
                await ws.send_json({"type": "auth", "access_token": token})
                authenticated = await ws.receive_json()
                if not isinstance(authenticated, dict) or authenticated.get("type") != "auth_ok":
                    raise CaptureError("HA authentication failed")
                async def command(identifier, kind, *, allow_failure=False, **fields):
                    await ws.send_json({"id": identifier, "type": kind, **fields})
                    response = await ws.receive_json()
                    # Receipt time, after this complete response arrived.
                    received = datetime.now(timezone.utc)
                    if (not isinstance(response, dict) or response.get("type") != "result"
                            or type(response.get("id")) is not int or response["id"] != identifier
                            or type(response.get("success")) is not bool):
                        raise CaptureError("HA read-only request failed or returned an unexpected response")
                    if response["success"] is not True:
                        if allow_failure:
                            return None, received
                        raise CaptureError("HA read-only request failed or returned an unexpected response")
                    if "result" not in response:
                        raise CaptureError("HA read-only response is missing its result")
                    return response["result"], received

                first_receipt = None
                if any("entry_ids" in row for row in mappings):
                    result, received = await command(1, "energy/solar_forecast")
                    capture = build_capture(result, mappings, received)
                    first_receipt = received
                else:
                    capture = build_capture({}, mappings, datetime.now(timezone.utc))
                capture["entity_snapshots"] = {}
                has_states = any("quality_entity_id" in row or "wh_period_entities" in row
                                 or "wh_period_15m_entities" in row for row in mappings)
                if has_states:
                    states, received = await command(2, "get_states")
                    groups, snapshots = quality_groups(states, mappings, received)
                    native_groups, native_snapshots = native_wh_state_groups(states, mappings, received)
                    groups.extend(native_groups)
                    snapshots.update(native_snapshots)
                    dc_groups, dc_snapshots = native_dc_wh_state_groups(states, mappings, received)
                    groups.extend(dc_groups)
                    snapshots.update(dc_snapshots)
                    capture["groups"].extend(groups)
                    capture["entity_snapshots"] = snapshots
                    capture["retrieved_at"] = received.isoformat()
                    capture["issued_at"] = (first_receipt or received).isoformat()
                capture["commands"] = (["energy/solar_forecast"] if first_receipt else []) + (["get_states"] if has_states else [])
                ids = [entry for row in mappings for entry in row.get("reference_entry_ids", ())]
                capture["reference_snapshots"] = {}
                if ids:
                    response, received = await command(3, "call_service", allow_failure=True,
                        domain="adaptive_solar", service="get_reference_forecasts",
                        service_data={"config_entry_ids": ids}, return_response=True)
                    bridge = response.get("response") if isinstance(response, dict) else None
                    groups, snapshots = reference_groups(bridge, mappings, received)
                    capture["groups"].extend(groups)
                    capture["reference_snapshots"] = snapshots
                    capture["commands"].append("adaptive_solar.get_reference_forecasts")
                receipts = [group["retrieved_at"] for group in capture["groups"]]
                capture["issued_at"], capture["retrieved_at"] = min(receipts), max(receipts)
                if cutoff is not None:
                    for group in capture["groups"]:
                        on_time = _utc(datetime.fromisoformat(group["retrieved_at"])) <= cutoff
                        group.update(declared_cutoff=cutoff.isoformat(), cutoff_eligible=on_time,
                                     timing_status="on_time" if on_time else "late")
                    capture["cutoff_check"] = {"schema_version": 1, "declared_cutoff": cutoff.isoformat(),
                        "all_groups_on_time": all(group["cutoff_eligible"] for group in capture["groups"]),
                        "late_group_count": sum(not group["cutoff_eligible"] for group in capture["groups"])}
                capture.pop("command", None)
                # Provider/auth text is never printed. Refuse even an unexpected
                # reflected credential inside a provider snapshot before storing.
                encoded = json.dumps(capture, ensure_ascii=False, allow_nan=False)
                if token in encoded or ha_url in encoded:
                    raise CaptureError("Response contained private connection credentials")
                return capture
    try:
        if session is not None:
            return await request(session)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as client:
            return await request(client)
    except CaptureError:
        raise
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError, OverflowError) as exc:
        # Never expose raw transport exceptions: they may include URL/token.
        raise CaptureError("HA capture transport failed or exceeded its deadline") from exc


def _validate_output(output, inputs=(), *, descriptor=None, protected_identities=()):
    try:
        return validate_append_output(output, inputs, descriptor=descriptor, protected_identities=protected_identities)
    except ValueError as exc:
        raise CaptureError("Capture output must be separate from inputs, programs and hardlink aliases") from exc


def append_capture(output: Path, capture: dict, *, inputs=(), protected_identities=()) -> None:
    """Append one capture under a nonblocking exclusive file lock."""
    protected = _validate_output(output, inputs, protected_identities=protected_identities)
    encoded = (json.dumps(capture, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CaptureError("Capture output is locked by another writer") from exc
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CaptureError("Capture output must be a regular file")
        if metadata.st_size:
            # Append only to complete JSONL, preserving a partial prior write
            # as evidence instead of joining the new record to it.
            if os.pread(descriptor, 1, metadata.st_size - 1) != b"\n":
                raise CaptureError("Existing capture file ends with an incomplete record")
        _validate_output(output, inputs, descriptor=descriptor, protected_identities=protected)
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise CaptureError("Capture append was incomplete")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _private_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to((ROOT / "data").resolve()):
        raise CaptureError("Private capture configuration and output must stay inside ignored data/")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Private mappings JSON below data/")
    parser.add_argument("--output", type=Path, required=True, help="Append-only JSONL below data/")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--cutoff", help="Fixed aware ISO deadline, evaluated against each actual complete-response receipt")
    parser.add_argument("--preflight", action="store_true", help="Check private mapping and timing budget locally; no HA call or append")
    parser.add_argument("--cutoff-margin", type=float, default=5, help="Preflight lead margin beyond the total request timeout, seconds")
    args = parser.parse_args()
    try:
        config, output = _private_path(args.config), _private_path(args.output)
        if config == output or output.exists() and os.path.samefile(config, output):
            raise CaptureError("Configuration and output paths must differ")
        protected = _validate_output(output, (config,))
        mappings = parse_mapping(json.loads(config.read_text(encoding="utf-8")))
        try:
            cutoff = _utc(datetime.fromisoformat(args.cutoff)) if args.cutoff else None
        except (ValueError, TypeError, OverflowError) as exc:
            raise CaptureError("Cutoff must be a timezone-aware ISO timestamp") from exc
        if args.preflight:
            if cutoff is None:
                raise CaptureError("Preflight requires a fixed --cutoff")
            plan = cutoff_preflight(cutoff, timeout=args.timeout, margin=args.cutoff_margin, mappings=mappings)
            print(json.dumps(plan, allow_nan=False, sort_keys=True))
            return 0 if plan["forecast_capture_ready"] else 1
        capture = asyncio.run(capture_forecasts(os.environ.get("HA_URL", ""), os.environ.get("HA_TOKEN", ""), mappings,
                                               timeout=args.timeout, cutoff=cutoff))
        append_capture(output, capture, inputs=(config,), protected_identities=protected)
    except (CaptureError, OSError, json.JSONDecodeError) as exc:
        # Do not echo path, URL, token, snapshots or transport exception details.
        message = str(exc) if isinstance(exc, CaptureError) else "Capture input/output failed"
        print(message, file=sys.stderr)
        return 2
    print(f"Captured {len(capture['groups'])} requested source/inverter groups; records appended")
    if capture.get("cutoff_check", {}).get("late_group_count", 0):
        print(f"Late groups: {capture['cutoff_check']['late_group_count']}; raw replies retained, declared cutoff unchanged")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
