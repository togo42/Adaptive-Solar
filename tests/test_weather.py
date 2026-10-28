"""Provider contract tests without any live network requests."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig
from custom_components.adaptive_solar.core.engine import ForecastEngine
from custom_components.adaptive_solar.weather import OpenMeteoClient, UNITS, VARIABLES, WeatherError, parse_forecast

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def payload(start=NOW - timedelta(hours=1), count=3):
    return {"hourly_units": dict(UNITS), "hourly": {
        "time": [(start + timedelta(hours=h)).timestamp() for h in range(count)],
        **{key: [value] * count for key, value in zip(VARIABLES, [500, 600, 100, 20, 3, 40], strict=True)}}}


def test_radiation_is_preceding_hour_mean_and_issue_is_receipt():
    result = parse_forecast(payload(), "best_match", NOW)
    assert result.issued_at == NOW
    assert result.points[0].start == NOW - timedelta(hours=1)
    assert result.points[0].end == NOW
    assert result.points[0].ghi_w_m2 == 500
    assert result.points[0].wind_m_s == 3
    assert len(result.points) == 2  # No extrapolated cell before the first endpoint.


@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), True, -1])
def test_missing_or_bad_radiation_is_a_gap_not_zero(invalid):
    data = payload()
    data["hourly"]["shortwave_radiation"][1] = invalid
    result = parse_forecast(data, "icon_d2", NOW)
    assert len(result.points) == 1
    assert result.points[0].start == NOW


def test_wrong_units_and_malformed_arrays_fail_closed():
    data = payload()
    data["hourly_units"]["wind_speed_10m"] = "km/h"
    with pytest.raises(WeatherError, match="units"):
        parse_forecast(data, "x", NOW)
    data = payload()
    data["hourly"]["temperature_2m"] = []
    with pytest.raises(WeatherError, match="arrays"):
        parse_forecast(data, "x", NOW)


def test_linear_instant_endpoints_are_aligned_to_mean_cell_and_engine_features():
    data = payload()
    data["hourly"].update(temperature_2m=[10, 20, 40], wind_speed_10m=[0, 2, 6], cloud_cover=[0, 0, 100])
    # Radiation is already the backwards mean; never average neighbouring means.
    data["hourly"]["shortwave_radiation"] = [900, 800, 500]
    forecast = parse_forecast(data, "best_match", NOW)
    point = forecast.points[1]
    assert (point.start, point.end) == (NOW, NOW + timedelta(hours=1))
    assert (point.temperature_c, point.wind_m_s, point.cloud_cover_pct) == (30, 4, 50)
    assert point.ghi_w_m2 == 500
    site = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))
    result = ForecastEngine(site).forecast((forecast,), NOW)
    assert len(result.points) == 1
    assert {key: result.points[0].features[key] for key in ("temperature_c", "wind_m_s", "cloud_cover_pct")} == {
        "temperature_c": 30, "wind_m_s": 4, "cloud_cover_pct": 50}
    # Cropping a forecast cell does not manufacture a new meteorological
    # interpolation at its later midpoint. Source conditions remain a proxy.
    cropped = ForecastEngine(site).forecast((forecast,), NOW + timedelta(minutes=15))
    assert cropped.points[0].start == NOW + timedelta(minutes=15)
    assert cropped.points[0].features["temperature_c"] == 30
    assert cropped.points[0].features["wind_m_s"] == 4
    assert cropped.points[0].features["cloud_cover_pct"] == 50


@pytest.mark.parametrize("field,invalid", [
    ("temperature_2m", None), ("temperature_2m", float("nan")),
    ("temperature_2m", -120), ("wind_speed_10m", float("inf")),
    ("wind_speed_10m", -1), ("cloud_cover", True), ("cloud_cover", -10),
])
@pytest.mark.parametrize("endpoint", [0, 1])
def test_each_instant_endpoint_is_validated_before_averaging(field, invalid, endpoint):
    data = payload(count=2)
    data["hourly"][field][endpoint] = invalid
    # Bad bounded inputs could average back inside the range; still reject.
    with pytest.raises(WeatherError, match="no usable intervals"):
        parse_forecast(data, "best_match", NOW)


def test_invalid_middle_instant_removes_both_adjoining_cells_without_carry_forward():
    data = payload(count=4)
    data["hourly"]["temperature_2m"][1] = None
    result = parse_forecast(data, "best_match", NOW)
    assert [(p.start, p.end) for p in result.points] == [(NOW + timedelta(hours=1), NOW + timedelta(hours=2))]


def test_invalid_previous_radiation_does_not_destroy_valid_instant_support():
    data = payload()
    data["hourly"]["shortwave_radiation"][1] = None
    data["hourly"]["temperature_2m"] = [10, 20, 30]
    result = parse_forecast(data, "best_match", NOW)
    assert len(result.points) == 1
    assert result.points[0].start == NOW
    assert result.points[0].temperature_c == 25


def test_zero_instants_and_radiation_are_valid_not_missing():
    data = payload()
    for field in VARIABLES:
        data["hourly"][field] = [0, 0, 0]
    result = parse_forecast(data, "best_match", NOW)
    assert len(result.points) == 2
    assert all((p.ghi_w_m2, p.temperature_c, p.wind_m_s, p.cloud_cover_pct) == (0, 0, 0, 0)
               for p in result.points)


def test_timestamp_gap_does_not_interpolate_across_nonadjacent_endpoints():
    data = payload(count=4)
    data["hourly"]["time"] = [(NOW + timedelta(hours=h)).timestamp() for h in (-1, 0, 2, 3)]
    result = parse_forecast(data, "best_match", NOW)
    assert [(p.start, p.end) for p in result.points] == [
        (NOW - timedelta(hours=1), NOW), (NOW + timedelta(hours=2), NOW + timedelta(hours=3))]


@pytest.mark.parametrize("invalid", [None, float("nan"), True])
def test_invalid_timestamp_is_not_a_support_endpoint(invalid):
    data = payload(count=4)
    data["hourly"]["time"][1] = invalid
    result = parse_forecast(data, "best_match", NOW)
    assert len(result.points) == 1
    assert result.points[0].start == NOW + timedelta(hours=1)


def test_duplicate_instant_timestamp_fails_instead_of_selecting_arbitrary_support():
    data = payload()
    data["hourly"]["time"][1] = data["hourly"]["time"][0]
    with pytest.raises(WeatherError, match="Duplicate"):
        parse_forecast(data, "best_match", NOW)


@pytest.mark.parametrize("month,day,hours", [(3, 29, 23), (10, 25, 25)])
def test_linear_endpoint_alignment_uses_utc_hours_across_both_dst_changes(month, day, hours):
    zone = ZoneInfo("Europe/Berlin")
    local = datetime(2026, month, day, tzinfo=zone)
    start, end = local.astimezone(UTC), (local + timedelta(days=1)).astimezone(UTC)
    data = payload(start=start, count=hours + 1)
    data["hourly"]["temperature_2m"] = list(range(hours + 1))
    result = parse_forecast(data, "best_match", start.astimezone(zone))
    assert result.issued_at == start
    assert len(result.points) == hours
    assert result.points[0].start == start and result.points[-1].end == end
    for index, point in enumerate(result.points):
        assert point.start.tzinfo is UTC and point.end - point.start == timedelta(hours=1)
        assert point.temperature_c == index + 0.5


async def test_requests_models_separately_caches_and_does_not_invent_short_horizon():
    site = SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),), weather_models=("best_match", "icon_d2"))
    response = AsyncMock()
    response.raise_for_status = Mock()
    response.json.return_value = payload()
    session = Mock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    client = OpenMeteoClient(session, site)
    now = datetime.now(UTC)
    first = await client.async_forecasts(now)
    second = await client.async_forecasts(datetime.now(UTC))
    assert first == second
    assert session.get.call_count == 2
    params = [call.kwargs["params"] for call in session.get.call_args_list]
    assert {item["models"] for item in params} == {"best_match", "icon_d2"}
    assert all(item["timeformat"] == "unixtime" and item["wind_speed_unit"] == "ms" for item in params)
    assert all("forecast_days" not in item and item["forecast_hours"] == 193 and item["past_hours"] == 1
               for item in params)
    assert len(first[1].points) == 2


@pytest.mark.parametrize("stamp", [datetime(2026, 3, 29, 20, tzinfo=UTC), datetime(2026, 10, 25, 22, tzinfo=UTC)])
@pytest.mark.parametrize("model", ["icon_d2", "meteofrance_arome_france"])
async def test_late_day_short_model_keeps_native_tail_and_previous_endpoint(stamp, model):
    site = SiteConfig(52, 13, "Europe/Berlin", (StringConfig("s", "i", 5, 30, 180),),
                      (InverterConfig("i", 5),), weather_models=(model,), forecast_days=2)
    response = AsyncMock()
    response.raise_for_status = Mock()
    response.json.return_value = payload(start=stamp - timedelta(hours=1), count=52)
    session = Mock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    forecast, = await OpenMeteoClient(session, site).async_forecasts(stamp)
    params = session.get.call_args.kwargs["params"]
    assert params["forecast_hours"] == 73 and params["past_hours"] == 1
    assert forecast.points[0].start == stamp - timedelta(hours=1)
    assert forecast.points[-1].end == stamp + timedelta(hours=50)
    assert len(forecast.points) == 51


async def test_original_response_capture_preserves_failed_normalization_and_success_receipt():
    import json

    site = SiteConfig(52, 13, "UTC", (StringConfig("s", "i", 5, 30, 180),), (InverterConfig("i", 5),))
    response = AsyncMock()
    response.raise_for_status = Mock()
    data = payload()
    response.json.return_value = data
    session = Mock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    client = OpenMeteoClient(session, site)
    sink = Mock()
    client.archive_sink = sink
    await client.async_forecasts(NOW)
    kind, text, received, receipt_id = sink.call_args.args
    assert kind == "weather_response" and receipt_id == client.receipt_ids["best_match"]
    receipt = json.loads(text)
    assert receipt["raw_response"] == data
    assert receipt["status"] == "available"
    assert receipt["normalization"]["received_at"] == received.isoformat()
    client._cache.clear()
    data["hourly_units"]["wind_speed_10m"] = "wrong"
    with pytest.raises(WeatherError):
        await client.async_forecasts(NOW)
    failed = json.loads(sink.call_args.args[1])
    assert failed["status"] == "failed" and failed["raw_response"] == data
    assert sink.call_count == 2
