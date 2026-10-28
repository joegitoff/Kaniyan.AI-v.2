"""
alert_engine.py - transparent, rule-based alert generation.

Every decision here is a plain "if value >= threshold" comparison, so each alert
can be explained to a user (and to a viva examiner). No machine learning.

Python concepts: dataclasses, enums, functions, loops, dictionaries, None/NaN
handling, sorting with key functions, default arguments.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

import pandas as pd

import config
from config import Level
from recommendations import get_advice

RAIN_NOTE = ("This is a rainfall-amount rule only. It does NOT predict street-level flooding, "
             "which depends on drainage, terrain and local conditions.")
AQI_NOTE = ("US AQI scale from the Open-Meteo/CAMS model (not the Indian CPCB NAQI, and not a "
            "monitoring-station reading).")


@dataclass
class Alert:
    location: str
    variable: str            # human-readable, e.g. "Daily rainfall total"
    key: str                 # short key used for advice lookup, e.g. "rain"
    value: float
    unit: str
    rule: str                # e.g. "Daily rainfall >= 64.5 mm"
    when: str                # forecast date/time as text
    level: Level
    explanation: str
    advice: list
    source: str
    generated_at: str
    official: bool = False   # always False: these are app-generated, never official
    sort_time: str = ""      # ISO text used only for chronological sorting
    basis: str = "forecast"  # "current" = model value for the present hour; "forecast" = future value

    @property
    def status(self) -> str:
        """'active' for conditions happening now, 'forecast' for expected ones."""
        return "active" if self.basis == "current" else "forecast"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["level"] = self.level.label
        data.pop("sort_time", None)
        return data


# ----------------------------------------------------------------- helpers ---
def is_missing(value) -> bool:
    """True for None or NaN - so we never compare a missing value with a threshold."""
    if value is None:
        return True
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return True


def classify(value, cutoffs: dict) -> Optional[Level]:
    """Return the highest Level whose cut-off is <= value, or None."""
    if is_missing(value):
        return None
    value = float(value)
    if value >= cutoffs["high"]:
        return Level.HIGH
    if value >= cutoffs["caution"]:
        return Level.CAUTION
    if value >= cutoffs["info"]:
        return Level.INFO
    return None


def _cutoff_for_level(cutoffs: dict, level: Level) -> float:
    return cutoffs[{Level.INFO: "info", Level.CAUTION: "caution", Level.HIGH: "high"}[level]]


def validate_thresholds(thresholds: dict) -> None:
    """Raise config.ConfigError (a ValueError) if any threshold is invalid. Nothing is auto-corrected."""
    config.validate_thresholds(thresholds)


def _day_text(ts) -> str:
    return pd.Timestamp(ts).strftime("%a %d %b %Y")


# ------------------------------------------------------- weather-based rules --
def _daily_rule(daily: pd.DataFrame, column: str, rule_name: str, key: str, variable: str,
                unit: str, cutoffs: dict, location: str, source: str, now_text: str,
                explanation_template: str, extra_note: str = "") -> list:
    alerts = []
    if column not in daily.columns:
        return alerts
    for _, row in daily.iterrows():
        value = row[column]
        level = classify(value, cutoffs)
        if level is None:
            continue
        cutoff = _cutoff_for_level(cutoffs, level)
        explanation = explanation_template.format(value=float(value), unit=unit, cutoff=cutoff)
        if extra_note:
            explanation += " " + extra_note
        alerts.append(Alert(
            location=location, variable=variable, key=key, value=round(float(value), 1), unit=unit,
            rule=f"{variable} >= {cutoff:g} {unit}  ({level.label} level)",
            when=_day_text(row["date"]), level=level, explanation=explanation,
            advice=get_advice(key, level), source=source, generated_at=now_text,
            sort_time=pd.Timestamp(row["date"]).isoformat()))
    return alerts


def evaluate_weather_alerts(weather, thresholds: dict, now_text: str) -> list:
    loc = weather.location.label
    src = weather.source + (" [SAMPLE DATA]" if weather.is_sample else "")
    d = weather.daily
    alerts = []
    alerts += _daily_rule(d, "precipitation_sum", "rain", "rain", "Daily rainfall total", "mm",
                          thresholds["rain_daily_mm"], loc, src, now_text,
                          "Forecast rainfall of {value:.1f} {unit} is at or above the {cutoff:g} {unit} rule.",
                          RAIN_NOTE)
    alerts += _daily_rule(d, "temperature_2m_max", "temp", "temperature", "Daily maximum temperature", "°C",
                          thresholds["temp_max_c"], loc, src, now_text,
                          "Forecast maximum temperature of {value:.1f} {unit} is at or above the {cutoff:g} {unit} rule.")
    alerts += _daily_rule(d, "apparent_temperature_max", "feels", "feels_like",
                          "Daily maximum feels-like temperature", "°C",
                          thresholds["feels_like_max_c"], loc, src, now_text,
                          "Forecast feels-like temperature (includes humidity/wind/sun) of {value:.1f} {unit} "
                          "is at or above the {cutoff:g} {unit} rule.")
    alerts += _daily_rule(d, "wind_gusts_10m_max", "wind", "wind", "Daily maximum wind gust", "km/h",
                          thresholds["wind_gust_kmh"], loc, src, now_text,
                          "Forecast maximum gust of {value:.1f} {unit} is at or above the {cutoff:g} {unit} rule.")
    return alerts


# --------------------------------------------------------- air-quality rules --
def evaluate_air_quality_alerts(air, thresholds: dict, now_text: str) -> list:
    """One alert per forecast day, based on the highest hourly US AQI of that day."""
    alerts = []
    h = air.hourly
    if "us_aqi" not in h.columns:
        return alerts
    cutoffs = thresholds["us_aqi"]
    loc = air.location.label
    src = air.source + (" [SAMPLE DATA]" if air.is_sample else "")
    valid = h.dropna(subset=["us_aqi"]).copy()
    if valid.empty:
        return alerts
    valid["day"] = valid["time"].dt.date
    for _, group in valid.groupby("day"):
        peak = group.loc[group["us_aqi"].idxmax()]
        level = classify(peak["us_aqi"], cutoffs)
        if level is None:
            continue
        cutoff = _cutoff_for_level(cutoffs, level)
        alerts.append(Alert(
            location=loc, variable="Air quality index (US AQI, daily peak)", key="air_quality",
            value=round(float(peak["us_aqi"]), 0), unit="AQI",
            rule=f"US AQI >= {cutoff:g}  ({level.label} level)",
            when=pd.Timestamp(peak["time"]).strftime("%a %d %b %Y, %H:%M"),
            level=level,
            explanation=(f"The highest hourly modelled US AQI on this day is {float(peak['us_aqi']):.0f}, "
                         f"at or above the {cutoff:g} rule. {AQI_NOTE}"),
            advice=get_advice("air_quality", level), source=src, generated_at=now_text,
            sort_time=pd.Timestamp(peak["time"]).isoformat()))
    return alerts


# --------------------------------------------------- current-condition rules --
CURRENT_RULES = (
    # (column in weather.current, threshold key, alert key, variable text, unit)
    ("temperature_2m", "temp_max_c", "temperature", "Current air temperature", "°C"),
    ("apparent_temperature", "feels_like_max_c", "feels_like", "Current feels-like temperature", "°C"),
    ("wind_gusts_10m", "wind_gust_kmh", "wind", "Current wind gust", "km/h"),
)


def evaluate_current_alerts(weather, air, thresholds: dict, now_text: str) -> list:
    """Alerts for conditions happening NOW (basis='current').

    "Current" values from Open-Meteo are model-based estimates for the present hour at the nearest grid
    point, not a station reading. Rainfall is not checked here because the rainfall rules are 24-hour
    totals; the 24-hour timeline handles rain. Missing values are skipped safely.
    """
    alerts = []
    if weather is not None:
        cur = weather.current
        src = weather.source + (" [SAMPLE DATA]" if weather.is_sample else "")
        for column, rule_key, key, variable, unit in CURRENT_RULES:
            level = classify(cur.get(column), thresholds[rule_key])
            if level is None:
                continue
            value, cutoff = float(cur[column]), _cutoff_for_level(thresholds[rule_key], level)
            alerts.append(Alert(
                location=weather.location.label, variable=variable, key=key, value=round(value, 1), unit=unit,
                rule=f"{variable} >= {cutoff:g} {unit}  ({level.label} level)",
                when=f"Now ({cur.get('time', 'time n/a')} local)", level=level,
                explanation=(f"The model's current value of {value:.1f} {unit} is at or above the {cutoff:g} {unit} "
                             "rule. This is a model estimate for the present hour, not a station reading."),
                advice=get_advice(key, level), source=src, generated_at=now_text,
                sort_time="0000-current", basis="current"))
    if air is not None:
        level = classify(air.current.get("us_aqi"), thresholds["us_aqi"])
        if level is not None:
            value, cutoff = float(air.current["us_aqi"]), _cutoff_for_level(thresholds["us_aqi"], level)
            alerts.append(Alert(
                location=air.location.label, variable="Current air quality index (US AQI)", key="air_quality",
                value=round(value, 0), unit="AQI", rule=f"US AQI >= {cutoff:g}  ({level.label} level)",
                when=f"Now ({air.current.get('time', 'time n/a')} local)", level=level,
                explanation=f"The modelled current US AQI is {value:.0f}, at or above the {cutoff:g} rule. {AQI_NOTE}",
                advice=get_advice("air_quality", level),
                source=air.source + (" [SAMPLE DATA]" if air.is_sample else ""), generated_at=now_text,
                sort_time="0000-current", basis="current"))
    return alerts


def dedupe_alerts(alerts: list) -> list:
    """Drop repeated alerts for the same unchanged condition (same variable, time, level and basis)."""
    seen, unique = set(), []
    for alert in alerts:
        signature = (alert.key, alert.basis, alert.when, alert.level)
        if signature not in seen:
            seen.add(signature)
            unique.append(alert)
    return unique


# -------------------------------------------------------------- main entry ---
def evaluate_alerts(weather, air=None, thresholds: Optional[dict] = None,
                    now: Optional[datetime] = None) -> list:
    """Run every rule and return alerts sorted: most severe first, then earliest."""
    thresholds = thresholds or config.DEFAULT_THRESHOLDS
    validate_thresholds(thresholds)
    now_text = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    alerts = evaluate_weather_alerts(weather, thresholds, now_text) if weather is not None else []
    if air is not None:
        alerts += evaluate_air_quality_alerts(air, thresholds, now_text)
    return sorted(dedupe_alerts(alerts), key=lambda a: (-int(a.level), a.sort_time))


def highest_level(alerts) -> Optional[Level]:
    return max((a.level for a in alerts), default=None)
