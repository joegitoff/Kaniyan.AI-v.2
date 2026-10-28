"""assessment.py orchestration + chart robustness."""
import math

import pandas as pd
import pytest

import assessment as asm
import charts
import config
import data_service as ds
import sample_data as sd
import timeline as tl
from config import Level
from helpers import CALM, NOW_UTC, START, air, result, series, weather
from risk import RiskCategory

T = config.DEFAULT_THRESHOLDS


def full(**kw):
    return asm.assess(result(weather()), result(air()), T, "Sample", now_utc=NOW_UTC, **kw)


def test_sample_assessment_is_moderate_with_reasons_and_separate_sections():
    a = full()
    assert a.overall.category == RiskCategory.MODERATE and a.overall.reasons
    assert a.current_alerts and all(x.basis == "current" for x in a.current_alerts)
    assert a.events and all(e.basis == "forecast" for e in a.events)
    assert a.daily_alerts and all(x.basis == "forecast" for x in a.daily_alerts)
    assert len(a.all_alerts) == len(set((x.key, x.basis, x.when, x.level) for x in a.all_alerts))


def test_invalid_thresholds_raise_and_are_not_repaired():
    bad = {k: dict(v) for k, v in T.items()}
    bad["us_aqi"] = {"info": 200, "caution": 100, "high": 50}
    with pytest.raises(config.ConfigError):
        asm.assess(result(weather()), result(air()), bad, "x")


def test_weather_failure_keeps_air_quality_working():
    a = asm.assess(ds.FetchResult(None, ds.STATUS_UNAVAILABLE, None, "down"), result(air()), T, "x", now_utc=NOW_UTC)
    assert a.window is not None and a.window.air_available and a.daily_alerts
    assert any("Weather data are unavailable" in g for g in a.data_gaps)
    assert a.status_items[0].status == ds.STATUS_UNAVAILABLE and a.overall.caveats


def test_air_failure_keeps_weather_working_and_is_reported():
    a = asm.assess(result(weather()), ds.FetchResult(None, ds.STATUS_UNAVAILABLE, None, "429"), T, "x", now_utc=NOW_UTC)
    assert a.events and any("Air-quality data are unavailable" in g for g in a.data_gaps)
    assert any(i["label"] == "Peak US AQI (model)" and i["value"] == "n/a" for i in asm.forecast_glance(a.window))


def test_both_providers_down_is_safe():
    down = ds.FetchResult(None, ds.STATUS_UNAVAILABLE, None, "down")
    a = asm.assess(down, down, T, "x")
    assert a.window is None and a.overall.category == RiskCategory.LOW and a.overall.caveats
    assert asm.forecast_glance(None) == [] and asm.describe_chart(a, "Temperature (next 24 h)")["facts"]


def test_stale_cached_data_is_reported_as_cached_and_flagged():
    w = weather(is_sample=False)
    stale = ds.FetchResult(w, ds.STATUS_CACHED, w.fetched_at, "refresh failed")
    a = asm.assess(stale, result(air()), T, "x", now_utc=NOW_UTC)
    item = a.status_items[0]
    assert item.status == ds.STATUS_CACHED and "Cached (stale)" in item.label and "Live" not in item.label
    assert any("OLDER" in p for p in item.problems) and any("older cached" in g for g in a.data_gaps)


def test_missing_current_fields_are_listed_as_gaps():
    w = weather()
    w.current["temperature_2m"] = None
    assert any("current temperature" in g for g in asm.assess(result(w), result(air()), T, "x", now_utc=NOW_UTC).data_gaps)


def test_status_items_carry_source_period_and_limitations():
    for item in full().status_items:
        assert item.source != "-" and "Forecast covers" in item.period and item.limitations
    assert "not the Indian CPCB" in " ".join(full().status_items[1].limitations)


def test_describe_chart_returns_python_facts_for_every_chart():
    a = full()
    for name in asm.CHART_NAMES:
        assert asm.describe_chart(a, name)["facts"]


# ---------------------------------------------------------------- charts ----
def all_charts(window, daily, hourly):
    return [charts.hourly_temperature_chart(window, T), charts.hourly_rain_chart(window), charts.hourly_wind_chart(window, T),
            charts.risk_timeline_chart(window), charts.aqi_chart(hourly, 51, 101, 151), charts.pm_chart(hourly),
            charts.temperature_chart(daily, 38), charts.rainfall_chart(daily, 64.5), charts.wind_chart(daily, 60)]


def test_charts_render_with_full_data():
    a = full()
    for fig in all_charts(a.window, weather().daily, air().hourly):
        fig.to_json()


def test_charts_render_when_everything_is_empty_or_none():
    for fig in all_charts(None, pd.DataFrame(), pd.DataFrame()):
        assert fig.layout.annotations and "unavailable" in fig.layout.annotations[0].text.lower() or "No" in fig.layout.annotations[0].text
        fig.to_json()


def test_missing_values_stay_gaps_and_are_not_zero_filled():
    temps = series(26.0, h16=None, h17=None)
    w = tl.build_window(weather(**{**CALM, "temperature_2m": temps}), None, T, now_utc=NOW_UTC)
    y = list(charts.hourly_temperature_chart(w, T).data[0].y)
    assert sum(1 for v in y if v is None or (isinstance(v, float) and math.isnan(v))) == 2
    assert charts.hourly_temperature_chart(w, T).data[0].connectgaps is False


def test_risk_timeline_shows_missing_hours_with_question_mark_and_letters():
    temps = series(26.0, h16=None, h17=39.0)
    w = tl.build_window(weather(**{**CALM, "temperature_2m": temps}), None, T, now_utc=NOW_UTC)
    hm = charts.risk_timeline_chart(w).data[0]
    row = list(hm.text[0])
    assert "?" in row and "C" in row and len(hm.x) == 24 and len(hm.y) == 5   # symbols, not colour alone


def test_rain_chart_with_only_precipitation_or_only_probability():
    only_mm = tl.build_window(weather(**{**CALM, "precipitation_probability": [None] * 168}), None, T, now_utc=NOW_UTC)
    only_p = tl.build_window(weather(**{**CALM, "precipitation": [None] * 168}), None, T, now_utc=NOW_UTC)
    for w in (only_mm, only_p):
        charts.hourly_rain_chart(w).to_json()
