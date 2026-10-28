"""Offline, version-bound candidates on identical frozen original inputs.

An archived forecast receipt may follow its calculation cutoff. Weather receipt,
measurement time and fitted-label availability must nevertheless respect cutoff.
Replaying today's API response can never reconstruct yesterday's weather vintage.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import base64
import binascii
from datetime import datetime
import hashlib
import json
import zlib
from typing import Callable

from .archive import canonical_bytes
from .engine import ForecastEngine
from .learning import ResidualLearner
from .models import (ForecastPoint, ForecastResult, Observation, SiteConfig, TrainingSample,
                     WeatherForecast, WeatherPoint, utc_time)
from .shading import BeamShadeTable


def timestamp(value):
    return utc_time(datetime.fromisoformat(value))


def timed_record(cls, value, fields):
    return cls(**{key: timestamp(item) if key in fields else item for key, item in value.items()})


def weather_from_json(value):
    return WeatherForecast(value["model"], timestamp(value["issued_at"]),
                           tuple(timed_record(WeatherPoint, point, {"start", "end"}) for point in value["points"]))


def result_from_json(value):
    return ForecastResult(timestamp(value["issued_at"]),
                          tuple(timed_record(ForecastPoint, point, {"start", "end"}) for point in value["points"]),
                          value.get("model_status", {}))


def _reconstruct_json(forecast_event, events, reference, kind, hash_field):
    """Resolve only referenced same-source/generation chunks, verifying bytes."""
    if reference.get("encoding") not in (None, "json", "zlib+base64"):
        raise ValueError("unknown replay state encoding")
    ids = reference["event_ids"]
    if not ids or len(ids) > 1024 or len(set(ids)) != len(ids):
        raise ValueError("invalid replay state references")
    relevant = [event for event in events if event.get("event_id") in ids
                and event.get("source") == forecast_event.get("source")
                and event.get("generation") == forecast_event.get("generation")]
    if len(relevant) != len(ids):
        raise ValueError("missing or duplicate replay state chunks")
    parts = {}
    for event in relevant:
        value = event["payload"]
        index = value["index"]
        if (event["kind"] != kind or value["group_id"] != reference["group_id"]
                or value[hash_field] != reference["sha256"] or type(index) is not int
                or type(value["count"]) is not int or value["count"] != len(ids)
                or not 0 <= index < len(ids) or index in parts
                or timestamp(event["received_at"]) > timestamp(forecast_event["received_at"])):
            raise ValueError("inconsistent replay state chunk")
        if reference.get("encoding") == "zlib+base64":
            if (value.get("encoding") != "zlib+base64"
                    or value.get("uncompressed_bytes") != reference.get("uncompressed_bytes")):
                raise ValueError("inconsistent compressed replay state")
            parts[index] = value["data_fragment"]
        else:
            parts[index] = value["json_fragment"]
    if sum(len(part) for part in parts.values()) > 256 * 1024 * 1024:
        raise ValueError("encoded replay data exceeds bound")
    text = "".join(parts[index] for index in range(len(ids)))
    if reference.get("encoding") == "zlib+base64":
        size = reference.get("uncompressed_bytes")
        if type(size) is not int or not 0 < size <= 128 * 1024 * 1024:
            raise ValueError("invalid decompressed replay state bound")
        decoder = zlib.decompressobj()
        try:
            raw = decoder.decompress(base64.b64decode(text, validate=True), size + 1)
        except (zlib.error, binascii.Error) as err:
            raise ValueError("invalid compressed replay state") from err
        if len(raw) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError("compressed replay state exceeds declared bound or is incomplete")
    else:
        raw = text.encode()
        if len(raw) > 128 * 1024 * 1024:
            raise ValueError("replay data exceeds uncompressed bound")
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("replay state checksum mismatch")
    return json.loads(raw)


def hydrate_forecast(forecast_event: dict, events: list[dict]) -> dict:
    """Resolve a large issued payload before resolving its state/weather links."""
    manifest = forecast_event["payload"]
    if "payload_ref" not in manifest:
        return forecast_event
    payload = _reconstruct_json(forecast_event, events, manifest["payload_ref"], "forecast_payload_chunk", "payload_sha256")
    if not isinstance(payload, dict) or any(payload.get(key) != manifest.get(key) for key in ("issued_at", "computed_at")):
        raise ValueError("issued payload manifest disagrees with original payload")
    if canonical_bytes(payload.get("replay_state")) != canonical_bytes(manifest.get("replay_state")):
        raise ValueError("issued payload manifest disagrees with original replay state")
    return {**forecast_event, "payload": payload}


def hydrate_weather(weather_event: dict, events: list[dict]) -> dict:
    manifest = weather_event["payload"]
    if "payload_ref" not in manifest:
        return weather_event
    payload = _reconstruct_json(weather_event, events, manifest["payload_ref"], "weather_payload_chunk", "payload_sha256")
    if not isinstance(payload, dict) or any(payload.get(key) != manifest.get(key) for key in ("model", "status")):
        raise ValueError("weather payload manifest disagrees with original payload")
    return {**weather_event, "payload": payload}


def reconstruct_state(forecast_event: dict, events: list[dict]) -> dict:
    forecast_event = hydrate_forecast(forecast_event, events)
    return _reconstruct_json(forecast_event, events, forecast_event["payload"]["replay_state"],
                             "forecast_state_chunk", "state_sha256")


def verify_weather_receipts(forecast_event, events):
    """Prove the normalized trajectory reproduces its referenced raw response."""
    from ..archive_export import json_value
    from ..weather import parse_forecast

    payload = forecast_event["payload"]
    references = payload.get("weather_receipt_ids")
    if not isinstance(references, dict):
        raise ValueError("missing original weather receipt references")
    site = SiteConfig.from_dict(payload["site"])
    issue = timestamp(payload["issued_at"])
    verified = []
    for weather in payload["weather"]:
        model = weather["model"]
        identifier = references.get(model)
        matches = [event for event in events if event["event_id"] == identifier
                   and event.get("source") == forecast_event.get("source")
                   and event.get("generation") == forecast_event.get("generation")]
        if identifier is None or len(matches) != 1:
            raise ValueError("missing or ambiguous original weather receipt")
        event = hydrate_weather(matches[0], events)
        original = event["payload"]
        receipt = timestamp(event["received_at"])
        if (event["kind"] != "weather_response" or original.get("model") != model
                or original.get("status") != "available" or receipt > issue
                or receipt != timestamp(weather["issued_at"])):
            raise ValueError("original weather receipt disagrees with issued trajectory/cutoff")
        normalized = parse_forecast(original["raw_response"], model, receipt, site)
        if canonical_bytes(json_value(normalized)) != canonical_bytes(weather):
            raise ValueError("original raw weather differs from issued normalized trajectory")
        verified.append(identifier)
    return verified


@dataclass(frozen=True)
class ReplayInputs:
    site: SiteConfig
    weather: tuple[WeatherForecast, ...]
    issued_at: datetime
    observations: tuple[Observation, ...]
    learner: ResidualLearner
    shading: BeamShadeTable


@dataclass(frozen=True)
class Candidate:
    name: str
    version: str
    run: Callable[[ReplayInputs], ForecastResult]


def engine_candidate(inputs: ReplayInputs):
    return ForecastEngine(inputs.site, inputs.shading).forecast(inputs.weather, inputs.issued_at,
                                                              inputs.observations, inputs.learner)


def physics_candidate(inputs: ReplayInputs):
    """Declared ablation: original NWP and geometry, no learning/observations."""
    return ForecastEngine(inputs.site).forecast(inputs.weather, inputs.issued_at)


def _inputs(payload, state):
    site = SiteConfig.from_dict(payload["site"])
    issued = timestamp(payload["issued_at"])
    weather = tuple(weather_from_json(value) for value in payload["weather"])
    observations = tuple(timed_record(Observation, value, {"time"}) for value in payload["observations"])
    if any(forecast.issued_at > issued for forecast in weather) or any(obs.time > issued for obs in observations):
        raise ValueError("replay input is newer than calculation cutoff")
    samples = tuple(timed_record(TrainingSample, value, {"start", "end", "issued_at", "observed_at"})
                    for value in state["fit_samples"])
    if samples and state.get("fit_as_of") is None:
        raise ValueError("fitted samples lack original fitted-state cutoff")
    fit_as_of = timestamp(state["fit_as_of"]) if state.get("fit_as_of") is not None else issued
    if fit_as_of > issued or any(sample.observed_at > fit_as_of for sample in samples):
        raise ValueError("fitted label is newer than fitted-state cutoff")
    learner = ResidualLearner(timezone_name=site.timezone, output_caps={v.id: v.output_cap_w for v in site.inverters})
    learner.fit(samples, fit_as_of)
    shading = BeamShadeTable.from_dict(state["shading"], inverter_ids={v.id for v in site.inverters})
    if canonical_bytes(shading.to_dict()) != canonical_bytes(state["shading"]):
        raise ValueError("invalid or incompatible frozen shading state")
    return ReplayInputs(site, weather, issued, observations, learner, shading)


def compare_results(expected: ForecastResult, actual: ForecastResult, tolerance_w=1e-6):
    from .models import finite_number

    tolerance_w = finite_number(tolerance_w, "tolerance_w", 0)
    expected_points = {(p.start, p.end, p.inverter_id): p for p in expected.points}
    actual_points = {(p.start, p.end, p.inverter_id): p for p in actual.points}
    if expected.issued_at != actual.issued_at or expected_points.keys() != actual_points.keys():
        return {"matched": False, "reason": "different_interval_support", "max_error_w": None}
    errors = []
    for key, point in expected_points.items():
        other = actual_points[key]
        for field in ("baseline_w", "power_w", "lower_w", "upper_w"):
            left, right = getattr(point, field), getattr(other, field)
            if (left is None) != (right is None):
                return {"matched": False, "reason": "different_uncertainty_support", "max_error_w": None}
            if left is not None:
                errors.append(abs(left - right))
    maximum = max(errors, default=0.0)
    return {"matched": maximum <= tolerance_w, "reason": "numerical_comparison", "max_error_w": maximum,
            "tolerance_w": tolerance_w, "points": len(actual.points)}


def replay_forecast(event: dict, events: list[dict], *, as_of: datetime | None = None,
                    candidates: tuple[Candidate, ...] = (), tolerance_w=1e-6):
    """Rebuild exact fitted baseline and independent candidates on frozen input.

    Candidates receive separately deserialized input/state, preventing mutation
    of another arm. The input hash includes the full archived result/config/state.
    """
    if event["kind"] != "forecast_issued":
        raise ValueError("expected a forecast_issued event")
    event = hydrate_forecast(event, events)
    payload = event["payload"]
    if as_of is not None and timestamp(event["received_at"]) > utc_time(as_of):
        raise ValueError("forecast was not archived at requested as-of cutoff")
    if timestamp(payload["issued_at"]) > timestamp(event["received_at"]):
        raise ValueError("forecast cutoff follows archive receipt")
    state = reconstruct_state(event, events)
    verified_weather = verify_weather_receipts(event, events)
    frozen = canonical_bytes({"payload": payload, "state": state})
    digest = hashlib.sha256(frozen).hexdigest()
    from ..archive_export import software_provenance

    current_software = software_provenance()
    archived_software = payload["software"]
    # A different source/library version can still be explored, but cannot pass
    # exact-baseline acceptance by coincidentally producing similar numbers.
    version_match = all(current_software.get(key) == archived_software.get(key)
                        for key in ("source_sha256", "libraries", "export_schema"))
    baseline = engine_candidate(_inputs(payload, state))
    comparison = compare_results(result_from_json(payload["result"]), baseline, tolerance_w)
    comparison["software_match"] = version_match
    comparison["accepted"] = comparison["matched"] and version_match
    comparison["verified_weather_receipts"] = verified_weather
    outputs = {"baseline": baseline}
    versions = {"baseline": current_software["source_sha256"]}
    for candidate in candidates:
        if not candidate.name or candidate.name in outputs or not candidate.version:
            raise ValueError("candidate needs unique name and explicit version")
        # Rebuild from the frozen byte representation for every candidate.
        fresh = json.loads(frozen)
        outputs[candidate.name] = candidate.run(_inputs(fresh["payload"], fresh["state"]))
        versions[candidate.name] = candidate.version
    return {"input_sha256": digest, "event_id": event["event_id"], "baseline": comparison,
            "candidate_versions": versions, "outputs": outputs,
            "provenance": {"archived_software": archived_software, "replay_software": current_software,
                           "provider_run_time": "unknown_unless_original_response_proves_it"}}


def member_results(site: SiteConfig, archive, issued_at: datetime):
    """Independent physics including shared stage caps, preserving member IDs."""
    issued_at = utc_time(issued_at)
    if archive.received_at > issued_at:
        raise ValueError("ensemble response received after decision cutoff")
    results = {}
    for forecast in archive.members:
        member_site = replace(site, weather_models=(forecast.model,))
        results[forecast.model] = ForecastEngine(member_site).forecast((forecast,), issued_at)
    return results
