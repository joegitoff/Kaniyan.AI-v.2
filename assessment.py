"""
assessment.py - ties data, alert rules, the 24-hour timeline, overall risk and recommendations together.

This is the single place where the dashboard's "business logic" runs, so app.py only has to display
the result. It contains no Streamlit code and is covered by unit tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

import alert_engine
import config
import data_service as ds
import timeline
from activity_advice import RecommendationSet, generate_recommendations
from risk import Contribution, OverallRisk, classify_overall

WEATHER_LIMITS = ["'Current' values are a model estimate for the nearest grid point, not a weather-station reading.",
                  "Forecasts are probabilistic and change between model updates.",
                  "Rainfall rules use rainfall AMOUNTS only; the app cannot predict street-level flooding."]
AIR_LIMITS = ["US AQI computed by the CAMS model via Open-Meteo - not the Indian CPCB AQI and not a ground-station reading.",
              "City/regional model values cannot show street-level pollution."]
CHART_NAMES = ["Temperature (next 24 h)", "Rain (next 24 h)", "Risk timeline (next 24 h)", "Air quality (next 24 h)"]


@dataclass
class DataStatusItem:
    name: str
    status: str
    label: str
    source: str
    retrieved: str
    period: str
    limitations: list = field(default_factory=list)
    problems: list = field(default_factory=list)


@dataclass
class Assessment:
    location_label: str
    thresholds: dict
    window: Optional[timeline.Window]
    current_alerts: list
    daily_alerts: list                # day-by-day forecast alerts (from alert_engine.evaluate_alerts)
    events: list                      # 24-hour forecast events (timeline)
    chance: list
    summary_lines: list
    comparison_lines: list
    comparison_data: dict
    overall: OverallRisk
    data_gaps: list
    status_items: list
    quiet: tuple

    @property
    def all_alerts(self) -> list:
        return alert_engine.dedupe_alerts(self.current_alerts + self.daily_alerts)

    def recommendations(self, activity: str) -> RecommendationSet:
        return generate_recommendations(activity, self.current_alerts, self.events, self.window, self.chance, self.quiet)


def _period_text(data, label: str) -> str:
    period = data.period() if data is not None else None
    if not period:
        return "Not available"
    return f"{label} {period[0]:%a %d %b %H:%M} to {period[1]:%a %d %b %H:%M} (local time at the location)"


def build_status_items(weather_result: ds.FetchResult, air_result: ds.FetchResult, now: Optional[datetime] = None) -> list:
    items = []
    for name, result, limits, label in (("Weather", weather_result, WEATHER_LIMITS, "Forecast covers"),
                                         ("Air quality", air_result, AIR_LIMITS, "Forecast covers")):
        data = result.data if result is not None else None
        problems = [result.error] if result is not None and result.error else []
        if result is None or data is None:
            items.append(DataStatusItem(name, ds.STATUS_UNAVAILABLE, "Unavailable", "-", "never", "Not available",
                                        limits, problems or ["No data."]))
            continue
        retrieved = (f"{result.fetched_at:%Y-%m-%d %H:%M} UTC ({ds.describe_age(result.age_seconds(now))})"
                     if result.fetched_at else "unknown")
        problems += list(getattr(data, "warnings", []))
        if result.status == ds.STATUS_CACHED:
            problems.insert(0, "Showing OLDER saved data because the latest refresh failed. It may be out of date.")
        items.append(DataStatusItem(name, result.status, result.label(now),
                                    data.source + (" [SAMPLE DATA]" if data.is_sample else ""), retrieved,
                                    _period_text(data, label), limits, problems))
    return items


def find_data_gaps(weather, air, window: Optional[timeline.Window], weather_result=None, air_result=None) -> list:
    gaps = []
    if weather is None:
        gaps.append("Weather data are unavailable" + (f" ({weather_result.error})" if weather_result and weather_result.error else "") + ".")
    else:
        for column, text in (("temperature_2m", "current temperature"), ("apparent_temperature", "current feels-like temperature"),
                             ("relative_humidity_2m", "current humidity"), ("wind_speed_10m", "current wind speed"),
                             ("wind_gusts_10m", "current wind gusts")):
            if alert_engine.is_missing(weather.current.get(column)):
                gaps.append(f"The {text} is missing from the data service.")
        if weather.hourly.empty or "precipitation_probability" not in weather.hourly.columns:
            gaps.append("Hourly rain probability is not provided.")
    if air is None:
        gaps.append("Air-quality data are unavailable" + (f" ({air_result.error})" if air_result and air_result.error else "") + ".")
    elif "us_aqi" not in air.hourly.columns or air.hourly["us_aqi"].isna().all():
        gaps.append("The hourly US AQI forecast is missing or empty.")
    elif alert_engine.is_missing(air.current.get("us_aqi")):
        gaps.append("The current US AQI value is missing.")
    if window is not None:
        gone = [c for c, n in window.missing_hours.items() if 0 < n < window.hours and window.available.get(c)]
        if gone:
            gaps.append("Some of the next 24 hourly steps are missing for: " + ", ".join(gone) + ".")
    for result in (weather_result, air_result):
        if result is not None and result.status == ds.STATUS_CACHED:
            gaps.append("Some data come from an older cached copy (the refresh failed).")
            break
    return gaps


def assess(weather_result: ds.FetchResult, air_result: ds.FetchResult, thresholds: dict, location_label: str,
           now_utc: Optional[datetime] = None) -> Assessment:
    """Run every rule. Raises config.ConfigError if the thresholds are invalid (never repairs them)."""
    config.validate_thresholds(thresholds)
    now_utc = now_utc or datetime.now(timezone.utc)
    weather = weather_result.data if weather_result is not None else None
    air = air_result.data if air_result is not None else None
    now_text = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    current_alerts = alert_engine.dedupe_alerts(alert_engine.evaluate_current_alerts(weather, air, thresholds, now_text))
    daily_alerts = alert_engine.evaluate_alerts(weather, air, thresholds, now=now_utc) if (weather or air) else []
    window = timeline.build_window(weather, air, thresholds, now_utc=now_utc)
    events = timeline.find_events(window, thresholds)
    chance = timeline.rain_chance_periods(window)
    comparison_lines, comparison_data = timeline.compare_today_tomorrow(
        weather, window.start if window is not None else None)

    contributions = [Contribution(a.key, a.variable, a.level, "current", "now",
                                  f"{a.value:g} {a.unit}, {a.rule}", start=window.start if window else None,
                                  end=window.start if window else None) for a in current_alerts]
    contributions += [Contribution(e.key, e.variable, e.level, "forecast", timeline.event_span_text(e, window),
                                   f"forecast peak {e.peak_value:.1f} {e.unit}; {e.rule}", start=e.start,
                                   end=window.end if e.continues_past_window else e.end) for e in events]
    gaps = find_data_gaps(weather, air, window, weather_result, air_result)
    overall = classify_overall(contributions)
    if window is None or not any(window.available.values()):
        overall.caveats.append("No hourly forecast data were available to check, so the next 24 hours could not be assessed.")
    if gaps:
        overall.caveats.append("Some data are missing, unavailable or older than normal, so this category may understate "
                               "the risk. See the data status below.")
    return Assessment(
        location_label=location_label, thresholds=thresholds, window=window, current_alerts=current_alerts,
        daily_alerts=daily_alerts, events=events, chance=chance,
        summary_lines=timeline.summarize_window(window, events, chance),
        comparison_lines=comparison_lines, comparison_data=comparison_data,
        overall=overall, data_gaps=gaps,
        status_items=build_status_items(weather_result, air_result, now_utc),
        quiet=timeline.quiet_periods(window))


def describe_chart(assessment: Assessment, chart_name: str) -> dict:
    """Plain facts about what a 24-hour chart shows (computed in Python, so an AI cannot invent them)."""
    w, facts = assessment.window, []
    if w is None:
        return {"chart": chart_name, "facts": ["No hourly data are available for this chart."]}
    f, ref = w.frame, w.start
    if chart_name.startswith("Temperature"):
        if w.available.get("temperature_2m"):
            t = f["temperature_2m"]
            facts.append(f"Air temperature ranges from {t.min():.1f} to {t.max():.1f} °C; lowest about {timeline.fmt_time(f.loc[t.idxmin(), 'time'], ref)}, highest about {timeline.fmt_time(f.loc[t.idxmax(), 'time'], ref)}.")
            facts.append(f"The dashed lines are the configured temperature rule cut-offs ({assessment.thresholds['temp_max_c']['info']:g} / {assessment.thresholds['temp_max_c']['caution']:g} / {assessment.thresholds['temp_max_c']['high']:g} °C).")
        else:
            facts.append("Hourly temperature data are unavailable.")
    elif chart_name.startswith("Rain"):
        if w.rain_probability_available:
            p = f["precipitation_probability"]
            facts.append(f"Top panel: rain probability, highest {p.max():.0f}% around {timeline.fmt_time(f.loc[p.idxmax(), 'time'], ref)}.")
        if w.available.get("precipitation"):
            facts.append(f"Bottom panel: forecast precipitation per hour; total {f['precipitation'].sum():.1f} mm, {int((f['precipitation'] >= 0.1).sum())} hour(s) with at least 0.1 mm.")
        if not facts:
            facts.append("Hourly rain data are unavailable.")
    elif chart_name.startswith("Risk"):
        facts.append("Each row is a hazard, each column an hour. Colour AND letter show the level: '-' none, 'i' Information, 'C' Caution, 'H' High concern, '?' no data.")
        for e in assessment.events[:6]:
            facts.append(f"{e.variable}: {e.level.label}, {timeline.event_span_text(e, w)}.")
        if not assessment.events:
            facts.append("No hour reaches any configured threshold.")
    else:
        if w.air_available:
            a = f["us_aqi"]
            facts.append(f"US AQI (CAMS model) ranges from {a.min():.0f} to {a.max():.0f}; highest around {timeline.fmt_time(f.loc[a.idxmax(), 'time'], ref)}. Not a street-level or CPCB value.")
        else:
            facts.append("The hourly air-quality forecast is unavailable.")
    return {"chart": chart_name, "facts": facts}


def forecast_glance(window: Optional[timeline.Window]) -> list:
    """Summary cards for the next 24 hours (all FORECAST values). Unavailable items say so explicitly."""
    if window is None:
        return []
    f, ref = window.frame, window.start
    at = lambda col, fn: timeline.fmt_time(f.loc[getattr(f[col], fn)(), "time"], ref)
    items = []
    if window.available.get("temperature_2m"):
        items.append({"icon": "🌡️", "label": "Peak temperature", "value": f"{f['temperature_2m'].max():.1f} °C",
                      "sub": f"around {at('temperature_2m', 'idxmax')}"})
    else:
        items.append({"icon": "🌡️", "label": "Peak temperature", "value": "n/a", "sub": "forecast unavailable"})
    if window.rain_probability_available:
        items.append({"icon": "🌧️", "label": "Highest rain chance", "value": f"{f['precipitation_probability'].max():.0f} %",
                      "sub": f"around {at('precipitation_probability', 'idxmax')}"})
    else:
        items.append({"icon": "🌧️", "label": "Highest rain chance", "value": "n/a", "sub": "forecast unavailable"})
    if window.available.get("precipitation"):
        items.append({"icon": "☔", "label": "Rain total (model)", "value": f"{f['precipitation'].sum():.1f} mm", "sub": "next 24 h"})
    else:
        items.append({"icon": "☔", "label": "Rain total (model)", "value": "n/a", "sub": "forecast unavailable"})
    if window.available.get("wind_gusts_10m"):
        items.append({"icon": "💨", "label": "Strongest gust", "value": f"{f['wind_gusts_10m'].max():.0f} km/h",
                      "sub": f"around {at('wind_gusts_10m', 'idxmax')}"})
    else:
        items.append({"icon": "💨", "label": "Strongest gust", "value": "n/a", "sub": "forecast unavailable"})
    if window.air_available:
        items.append({"icon": "🌫️", "label": "Peak US AQI (model)", "value": f"{f['us_aqi'].max():.0f}",
                      "sub": f"{ds.aqi_category_us(f['us_aqi'].max())} · around {at('us_aqi', 'idxmax')}"})
    else:
        items.append({"icon": "🌫️", "label": "Peak US AQI (model)", "value": "n/a", "sub": "hourly AQ forecast unavailable"})
    return items
