#!/usr/bin/env python3
"""Run the same forecast core offline or explicitly fetch live Open-Meteo data."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import UTC, datetime, time, timedelta
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.adaptive_solar.core.engine import ForecastEngine  # noqa: E402 - source-checkout CLI bootstrap
from custom_components.adaptive_solar.core.models import SiteConfig, WeatherForecast, WeatherPoint  # noqa: E402
from scripts.replay_paths import validate_output, write_output  # noqa: E402


def serializable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def synthetic_weather(config: SiteConfig, issued: datetime) -> tuple[WeatherForecast, ...]:
    """Deterministic clear-sky demonstration; never claim this is real weather."""
    import pandas as pd
    import pvlib

    local = issued.astimezone(ZoneInfo(config.timezone))
    end = datetime.combine(local.date() + timedelta(days=config.forecast_days), time(), ZoneInfo(config.timezone)).astimezone(UTC)
    start = issued.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    times = pd.date_range(start + timedelta(minutes=30), end, freq="h", inclusive="left")
    clear = pvlib.location.Location(config.latitude, config.longitude).get_clearsky(times)
    points = tuple(WeatherPoint(moment.to_pydatetime() - timedelta(minutes=30),
                               moment.to_pydatetime() + timedelta(minutes=30),
                               float(row.ghi), float(row.dni), float(row.dhi), 20, 2, 0)
                   for moment, row in clear.iterrows())
    return (WeatherForecast(config.weather_models[0], issued, points),)


async def live_weather(config):
    import aiohttp
    from custom_components.adaptive_solar.weather import OpenMeteoClient

    async with aiohttp.ClientSession() as session:
        return await OpenMeteoClient(session, config).async_forecasts(datetime.now(UTC))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--synthetic", action="store_true", help="Clear-sky demonstration, no network")
    mode.add_argument("--live", action="store_true", help="Explicitly call Open-Meteo for this configuration")
    parser.add_argument("--as-of", help="Aware ISO timestamp; only available with --synthetic")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.live and args.as_of is not None:
        parser.error("Live forecasts cannot be backdated")
    inputs = (args.config, Path(__file__))
    try:
        validate_output(args.output, args.config, inputs)
    except (OSError, ValueError):
        parser.error("forecast output must not overwrite the configuration or program sources")
    config = SiteConfig.from_dict(json.loads(args.config.read_text(encoding="utf-8")))
    try:
        issued = datetime.fromisoformat(args.as_of) if args.as_of is not None else datetime.now(UTC)
    except ValueError:
        parser.error("--as-of must be a valid ISO timestamp with an explicit timezone")
    if issued.tzinfo is None or issued.utcoffset() is None:
        parser.error("--as-of must include an explicit timezone")
    forecasts = synthetic_weather(config, issued) if args.synthetic else asyncio.run(live_weather(config))
    issued = issued if args.synthetic else datetime.now(UTC)
    result = ForecastEngine(config).forecast(forecasts, issued)
    payload = {"evidence": "synthetic_clear_sky_demo" if args.synthetic else "live_weather_physics_only",
               "outputs": {stage.id: {"output_type": stage.output_type,
                                      "measurement_boundary": stage.measurement_boundary,
                                      "nominal_output_cap_w": stage.output_cap_w}
                           for stage in config.inverters},
               "forecast": asdict(result)}
    encoded = json.dumps(payload, default=serializable, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    try:
        write_output(encoded, args.output, args.config, inputs)
    except (OSError, ValueError):
        parser.error("forecast output publication failed; inputs and program sources must remain separate")
    print(f"{len(result.points)} inverter intervals written to {args.output}")


if __name__ == "__main__":
    main()
