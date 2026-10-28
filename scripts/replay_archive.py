#!/usr/bin/env python3
"""Replay frozen HA forecasts or host EPS weather; never fetch new weather."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.adaptive_solar.archive_export import json_value, software_provenance
from custom_components.adaptive_solar.core.archive import ArchiveStore, canonical_bytes
from custom_components.adaptive_solar.core.ensemble import parse_members
from custom_components.adaptive_solar.core.models import SiteConfig
from custom_components.adaptive_solar.core.probability import (
    CalibrationCase, calibrate_bias, combine_families, probability_scores, window_distribution,
)
from custom_components.adaptive_solar.core.replay import (
    Candidate, hydrate_forecast, member_results, physics_candidate, replay_forecast, timestamp,
)
from scripts.capture_weather import reconstruct_response


def weather_probabilities(manifests, dependency_events, site, cutoff, start, end, *, quorum=1.0,
                          thresholds=(), calibration_cases=(), min_calibration_samples=20, actual_kwh=None):
    """Choose latest receipt per product, then one complete product per family.

    Regional coverage can end before a global window; it never gets stitched to
    unrelated IFS identities. A newer failed receipt invalidates the older one.
    """
    cutoff, start, end = timestamp(cutoff) if isinstance(cutoff, str) else cutoff, start, end
    if start < cutoff or end <= start:
        raise ValueError("target window must start at or after decision cutoff")
    latest = {}
    for event in manifests:
        received = timestamp(event["received_at"])
        if received > cutoff or event["kind"] != "host_weather_response" or not event["payload"]["ensemble"]:
            continue
        product = event["payload"]["product"]
        if product not in latest or (received, event["sequence"]) > (timestamp(latest[product]["received_at"]), latest[product]["sequence"]):
            latest[product] = event
    distributions, diagnostics = {}, {}
    for product, event in sorted(latest.items()):
        try:
            if event["payload"]["status"] != "available":
                raise ValueError("latest response failed")
            raw = reconstruct_response(event, dependency_events)
            archive = parse_members(json.loads(raw), product, timestamp(event["received_at"]), site)
            results = member_results(site, archive, cutoff)
            distribution = window_distribution(product, archive.family, results, start, end, archive.expected_members,
                                               tuple(stage.id for stage in site.inverters), quorum=quorum)
            distributions[product] = distribution
            diagnostics[product] = {"status": "complete" if len(distribution.member_ids) == archive.expected_members else "incomplete_quorum",
                                    "received_at": event["received_at"], "event_id": event["event_id"],
                                    "raw_sha256": event["payload"]["raw_response"]["sha256"],
                                    "archive_software": event["payload"].get("software"),
                                    "collector_source_sha256": event["payload"].get("collector_source_sha256"),
                                    "provider_run_at": event["payload"]["provider_run_at"],
                                    "member_count": len(distribution.member_ids), "expected_members": archive.expected_members}
        except (ValueError, TypeError, KeyError) as err:
            diagnostics[product] = {"status": "unavailable", "reason": str(err), "event_id": event["event_id"]}
    selected = []
    for family, order in (("icon", ("dwd_icon_d2_eps",)),
                          ("ifs", ("ecmwf_ifs_europe_ensemble", "ecmwf_ifs025_ensemble"))):
        choice = next((distributions[product] for product in order if product in distributions), None)
        if choice is not None:
            selected.append(choice)
            diagnostics[family] = {"selected_product": choice.product, "selection": "first_complete_in_declared_priority",
                                   "priority": list(order), "quorum": quorum}
    if not selected:
        return {"status": "unavailable", "diagnostics": diagnostics, "distributions": {}}
    if len(selected) > 1:
        distributions["family_mixture"] = combine_families(tuple(selected))
    summaries = {}
    for product, distribution in distributions.items():
        summary = distribution.summary(thresholds)
        summary["member_energies_kwh"] = dict(zip(distribution.member_ids, distribution.values_kwh, strict=True))
        summary["weights"] = dict(zip(distribution.member_ids, distribution.weights, strict=True))
        if actual_kwh is not None:
            summary["scores"] = probability_scores(distribution, actual_kwh, thresholds)
        if calibration_cases:
            try:
                calibrated = calibrate_bias(distribution, calibration_cases, cutoff, min_samples=min_calibration_samples)
                summary["bias_corrected"] = calibrated.summary(thresholds)
                if actual_kwh is not None:
                    summary["bias_corrected"]["scores"] = probability_scores(calibrated, actual_kwh, thresholds)
            except ValueError as err:
                summary["calibration_status"] = str(err)
        summaries[product] = summary
    return {"status": "raw_probabilities", "decision_cutoff": cutoff.isoformat(), "start": start.isoformat(),
            "end": end.isoformat(), "diagnostics": diagnostics, "distributions": summaries,
            "warning": "Raw weather-ensemble spread and bias-corrected spread have no validated local reliability."}


def _dependencies(store, source, dataset, selected, reference_field):
    payload_ids = {identifier for event in selected for identifier in event["payload"].get("payload_ref", {}).get("event_ids", [])}
    chunks = [event for event in store.iter_events(source=source, dataset=dataset) if event["event_id"] in payload_ids] if payload_ids else []
    resolved = [hydrate_forecast(event, chunks) for event in selected]
    wanted = {identifier for event in resolved for identifier in event["payload"][reference_field]["event_ids"]}
    wanted.update(identifier for event in resolved for identifier in event["payload"].get("weather_receipt_ids", {}).values())
    dependencies = [event for event in store.iter_events(source=source, dataset=dataset) if event["event_id"] in wanted]
    weather_ids = {identifier for event in dependencies if event["kind"] == "weather_response"
                   for identifier in event["payload"].get("payload_ref", {}).get("event_ids", [])}
    weather_chunks = [event for event in store.iter_events(source=source, dataset=dataset)
                      if event["event_id"] in weather_ids] if weather_ids else []
    return chunks + dependencies + weather_chunks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--dataset", help="Optional immutable ArchiveStore dataset pin")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--event-id")
    parser.add_argument("--as-of", type=timestamp)
    parser.add_argument("--tolerance-w", type=float, default=1e-6)
    parser.add_argument("--physics-ablation", action="store_true")
    parser.add_argument("--probabilities", action="store_true", help="Replay host weather EPS instead of HA forecast")
    parser.add_argument("--site-json", type=Path, help="Private SiteConfig JSON, required for host EPS replay")
    parser.add_argument("--start", type=timestamp)
    parser.add_argument("--end", type=timestamp)
    parser.add_argument("--quorum", type=float, default=1.0)
    parser.add_argument("--threshold-kwh", type=float, action="append", default=[])
    parser.add_argument("--calibration-json", type=Path, help="Prior qualified CalibrationCase array, with explicit family/product")
    parser.add_argument("--min-calibration-samples", type=int, default=20)
    parser.add_argument("--actual-kwh", type=float, help="Explicit qualified actual for offline scoring only")
    args = parser.parse_args()
    try:
        store = ArchiveStore(args.archive)
        if args.probabilities:
            if args.site_json is None or args.start is None or args.end is None:
                raise ValueError("host EPS replay requires --site-json, --start and --end")
            cutoff = args.as_of or datetime.now(UTC)
            site = SiteConfig.from_dict(json.loads(args.site_json.read_text()))
            latest = {}
            for event in store.iter_events(source=args.source, kind="host_weather_response", dataset=args.dataset):
                if timestamp(event["received_at"]) <= cutoff and event["payload"]["ensemble"]:
                    product = event["payload"]["product"]
                    if product not in latest or (event["received_at"], event["sequence"]) > (latest[product]["received_at"], latest[product]["sequence"]):
                        latest[product] = event
            selected = list(latest.values())
            dependencies = _dependencies(store, args.source, args.dataset, selected, "raw_response")
            cases = []
            if args.calibration_json:
                for row in json.loads(args.calibration_json.read_text()):
                    cases.append(CalibrationCase(**{key: timestamp(value) if key in {
                        "issued_at", "target_start", "target_end", "available_at"} else value for key, value in row.items()}))
            report = weather_probabilities(selected, dependencies, site, cutoff, args.start, args.end,
                                           quorum=args.quorum, thresholds=args.threshold_kwh,
                                           calibration_cases=tuple(cases), min_calibration_samples=args.min_calibration_samples,
                                           actual_kwh=args.actual_kwh)
            report["site_sha256"] = hashlib.sha256(canonical_bytes(site.to_dict())).hexdigest()
            accepted = report["status"] != "unavailable"
        else:
            selected = []
            chosen = None
            for event in store.iter_events(source=args.source, kind="forecast_issued", dataset=args.dataset):
                if args.event_id is not None and event["event_id"] != args.event_id:
                    continue
                if args.as_of is not None and timestamp(event["received_at"]) > args.as_of:
                    continue
                if chosen is None or (event["received_at"], event["sequence"]) > (chosen["received_at"], chosen["sequence"]):
                    chosen = event
            if chosen is None:
                raise ValueError("no matching archived forecast")
            selected = [chosen]
            dependencies = _dependencies(store, args.source, args.dataset, selected, "replay_state")
            candidates = (Candidate("physics_ablation", "original-nwp-no-observation-no-learning-v1", physics_candidate),) if args.physics_ablation else ()
            report = replay_forecast(chosen, dependencies, as_of=args.as_of, candidates=candidates, tolerance_w=args.tolerance_w)
            accepted = report["baseline"]["accepted"]
        report["dataset"] = args.dataset
        report["source"] = args.source
        report["replay_software"] = software_provenance()
        report["replay_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        report["selected_envelopes_sha256"] = hashlib.sha256(canonical_bytes(sorted(
            event["sha256"] for event in [*selected, *dependencies]))).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(json_value(report), sort_keys=True, indent=2, allow_nan=False) + "\n")
        print(json.dumps({"status": "accepted" if accepted else "unavailable_or_mismatch", "output": str(args.output)}))
        return 0 if accepted else 1
    except (ValueError, OSError, KeyError) as err:
        print(f"Replay failed: {type(err).__name__}: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
