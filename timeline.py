"""
timeline.py - the next-24-hours environmental risk timeline (pure Python, no Streamlit).

Takes the hourly forecast tables that already exist in WeatherData / AirQualityData and:
  1. builds a fixed 24-row hourly window (hours with no data stay MISSING - nothing is invented),
  2. classifies every hour with the SAME configured thresholds the alert engine uses,
  3. finds "events": when a threshold is first crossed and how long the condition persists,
  4. writes cautious plain-language summary lines.

Threshold use:
  * heat, feels-like, wind gust and US AQI: each hourly value is compared with the configured cut-offs.
  * rain: the configured rainfall rule is a 24-hour total, so the timeline compares the RUNNING TOTAL
    of forecast precipitation since the start of the window with it. When some hours are missing, the
    running total is a lower bound (it can only be too low, never too high).
Everything here is forecast-based. Values come from a weather/air-quality MODEL; nothing is certain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

import config
from alert_engine import classify, _cutoff_for_level
from config import Level

# key (same keys as alerts), label, unit, window column, threshold rule
HAZARDS = (
    ("temperature", "Heat (air temperature)", "°C", "temperature_2m", "temp_max_c"),
    ("feels_like", "Heat (feels-like)", "°C", "apparent_temperature", "feels_like_max_c"),
    ("rain", "Rain (running 24-h total)", "mm", "rain_cumulative_mm", "rain_daily_mm"),
    ("wind", "Wind gusts", "km/h", "wind_gusts_10m", "wind_gust_kmh"),
    ("air_quality", "Air quality (US AQI)", "US AQI", "us_aqi", "us_aqi"),
)
WEATHER_COLUMNS = ("temperature_2m", "apparent_temperature", "precipitation", "precipitation_probability",
                   "wind_speed_10m", "wind_gusts_10m")
AIR_COLUMNS = ("us_aqi", "pm2_5", "pm10")


@dataclass
class Window:
    frame: pd.DataFrame            # one row per hour; level_<key> columns: NaN=no data, 0=no alert, 1-3=Level
    start: pd.Timestamp
    end: pd.Timestamp
    hours: int
    available: dict = field(default_factory=dict)       # column -> at least one real value
    missing_hours: dict = field(default_factory=dict)   # column -> number of hours without a value

    @property
    def air_available(self) -> bool:
        return self.available.get("us_aqi", False)

    @property
    def rain_probability_available(self) -> bool:
        return self.available.get("precipitation_probability", False)


@dataclass
class RiskEvent:
    """A contiguous period during which one hazard is at or above a configured threshold."""
    key: str
    variable: str
    level: Level                    # highest level reached during the period
    start: pd.Timestamp
    end: pd.Timestamp               # last hourly step that was still at/above the threshold
    peak_value: float
    peak_time: pd.Timestamp
    unit: str
    rule: str
    first_crossed: dict             # Level -> first hour that level was reached
    ongoing_at_start: bool          # already active in the first hour of the window
    continues_past_window: bool     # still active in the last hour: the end is not covered by the data
    end_unknown_gap: bool           # followed by missing data: the end time cannot be determined
    basis: str = "forecast"

    @property
    def hours(self) -> int:
        return int((self.end - self.start) / pd.Timedelta(hours=1)) + 1


@dataclass
class ProbabilityPeriod:
    start: pd.Timestamp
    end: pd.Timestamp
    peak_probability: float
    peak_time: pd.Timestamp
    continues_past_window: bool


# ------------------------------------------------------------------ window ---
def resolve_start(weather, air, now_utc: Optional[datetime] = None) -> Optional[pd.Timestamp]:
    """Start hour (local time of the location) of the 24-hour window, or None without any data.

    Live data: the real current hour at the location, so an OLD cached forecast cannot pretend that
    past hours are "now" (hours the old forecast no longer covers simply show as missing).
    Demo data: the sample's own "current" time. If no time zone database is available, the data's
    own current time is used.
    """
    sources = [d for d in (weather, air) if d is not None]
    if not sources:
        return None
    if not any(getattr(d, "is_sample", False) for d in sources):
        names = [getattr(weather, "timezone", None), getattr(air, "timezone", None)]
        names += [getattr(d.location, "timezone", None) for d in sources]
        for name in names:
            if not name or name in ("auto", "unknown"):
                continue
            try:
                from zoneinfo import ZoneInfo
                local = (now_utc or datetime.now(timezone.utc)).astimezone(ZoneInfo(name))
                return pd.Timestamp(local.replace(tzinfo=None)).floor("h")
            except Exception:
                continue
    for d in sources:
        t = pd.to_datetime(d.current.get("time"), errors="coerce")
        if pd.notna(t):
            return t.floor("h")
    for d in sources:
        period = d.period()
        if period:
            return period[0].floor("h")
    return None


def _attach(frame: pd.DataFrame, source: Optional[pd.DataFrame], columns) -> None:
    for column in columns:
        if source is not None and not source.empty and column in source.columns:
            frame[column] = frame["time"].map(source.set_index("time")[column])
        else:
            frame[column] = float("nan")
        frame[column] = frame[column].astype(float)


def build_window(weather, air, thresholds: dict, start: Optional[pd.Timestamp] = None,
                 hours: int = config.FORECAST_WINDOW_HOURS, now_utc: Optional[datetime] = None) -> Optional[Window]:
    """Hourly window with per-hazard level columns. Returns None when there is no data at all."""
    if weather is None and air is None:
        return None
    start = start if start is not None else resolve_start(weather, air, now_utc)
    if start is None:
        return None
    start = pd.Timestamp(start).floor("h")
    index = pd.date_range(start, periods=hours, freq="h")
    frame = pd.DataFrame({"time": index.astype("datetime64[ns]")})
    _attach(frame, getattr(weather, "hourly", None), WEATHER_COLUMNS)
    _attach(frame, getattr(air, "hourly", None), AIR_COLUMNS)
    if frame["precipitation"].notna().any():
        frame["rain_cumulative_mm"] = frame["precipitation"].fillna(0).cumsum()
    else:
        frame["rain_cumulative_mm"] = float("nan")
    for key, _label, _unit, column, rule_key in HAZARDS:
        cutoffs = thresholds[rule_key]
        frame[f"level_{key}"] = frame[column].map(
            lambda v, c=cutoffs: float("nan") if pd.isna(v) else float(int(classify(v, c) or 0)))
    levels = [f"level_{h[0]}" for h in HAZARDS]
    frame["level_overall"] = frame[levels].max(axis=1, skipna=True)
    columns = list(WEATHER_COLUMNS) + list(AIR_COLUMNS)
    return Window(frame=frame, start=index[0], end=index[-1], hours=hours,
                  available={c: bool(frame[c].notna().any()) for c in columns},
                  missing_hours={c: int(frame[c].isna().sum()) for c in columns})


# ------------------------------------------------------------------ events ---
def find_events(window: Optional[Window], thresholds: dict) -> list:
    """Contiguous periods at/above a threshold, per hazard. Missing hours break (and end) a period."""
    if window is None:
        return []
    frame, n, events = window.frame, len(window.frame), []
    for key, label, unit, column, rule_key in HAZARDS:
        levels, values, times = frame[f"level_{key}"].to_numpy(), frame[column].to_numpy(), frame["time"]
        i = 0
        while i < n:
            if not levels[i] >= 1:          # NaN or 0
                i += 1
                continue
            j = i
            while j < n and levels[j] >= 1:
                j += 1
            run = range(i, j)
            peak_level = Level(int(max(levels[k] for k in run)))
            peak_idx = max(run, key=lambda k: values[k])
            first = {Level(lv): times[next(k for k in run if levels[k] >= lv)] for lv in (1, 2, 3) if lv <= int(peak_level)}
            cutoff = _cutoff_for_level(thresholds[rule_key], peak_level)
            events.append(RiskEvent(
                key=key, variable=label, level=peak_level, start=times[i], end=times[j - 1],
                peak_value=float(values[peak_idx]), peak_time=times[peak_idx], unit=unit,
                rule=f"{label} >= {cutoff:g} {unit} ({peak_level.label} level)", first_crossed=first,
                ongoing_at_start=(i == 0), continues_past_window=(j == n),
                end_unknown_gap=(j < n and bool(pd.isna(levels[j])))))
            i = j
    return sorted(events, key=lambda e: (-int(e.level), e.start))


def rain_chance_periods(window: Optional[Window], threshold: float = config.RAIN_PROB_NOTABLE_PERCENT) -> list:
    """Periods where the forecast rain PROBABILITY is at/above `threshold` (a probability, not a certainty)."""
    if window is None or not window.rain_probability_available:
        return []
    prob, times, n, out, i = window.frame["precipitation_probability"].to_numpy(), window.frame["time"], len(window.frame), [], 0
    while i < n:
        if not prob[i] >= threshold:
            i += 1
            continue
        j = i
        while j < n and prob[j] >= threshold:
            j += 1
        peak = max(range(i, j), key=lambda k: prob[k])
        out.append(ProbabilityPeriod(times[i], times[j - 1], float(prob[peak]), times[peak], j == n))
        i = j
    return out


def quiet_periods(window: Optional[Window], min_hours: int = 2):
    """Runs of >= min_hours with no Caution/High-concern level and no notable rain chance forecast.

    Only hazards with data are checked. Returns (periods, hazards_checked, hazards_not_checked).
    This is "no Caution or High-concern alert", NOT a guarantee of safety.
    """
    if window is None:
        return [], [], [h[1] for h in HAZARDS]
    frame = window.frame
    checked = [h for h in HAZARDS if frame[f"level_{h[0]}"].notna().any()]
    skipped = [h[1] for h in HAZARDS if h not in checked]
    if not checked:
        return [], [], skipped
    quiet = pd.Series(True, index=frame.index)
    for h in checked:
        quiet &= frame[f"level_{h[0]}"].fillna(3) <= 1          # a missing hour is never "quiet"; 'Information' is allowed
    if window.rain_probability_available:
        quiet &= frame["precipitation_probability"].fillna(100) < config.RAIN_PROB_NOTABLE_PERCENT
    periods, i, n = [], 0, len(frame)
    while i < n:
        if not quiet.iloc[i]:
            i += 1
            continue
        j = i
        while j < n and quiet.iloc[j]:
            j += 1
        if j - i >= min_hours:
            periods.append((frame["time"].iloc[i], frame["time"].iloc[j - 1]))
        i = j
    return periods, [h[1] for h in checked], skipped


# ----------------------------------------------------------------- wording ---
def fmt_time(ts, reference: pd.Timestamp) -> str:
    ts = pd.Timestamp(ts)
    return ts.strftime("%H:%M") if ts.date() == pd.Timestamp(reference).date() else ts.strftime("%a %H:%M")


def event_timing_text(event: RiskEvent, window: Window) -> str:
    ref = window.start
    first = event.first_crossed.get(event.level, event.start)
    parts = ["already at this level at the start of the window" if event.ongoing_at_start
             else f"first reaches {event.level.label} level around {fmt_time(first, ref)}"]
    if event.continues_past_window:
        parts.append("still at/above the threshold at the end of the 24-hour window (end not covered by the data)")
    elif event.end_unknown_gap:
        parts.append(f"at/above the threshold until at least {fmt_time(event.end, ref)}, then data are missing")
    else:
        parts.append(f"at/above the threshold {fmt_time(event.start, ref)}-{fmt_time(event.end, ref)} "
                     f"(about {event.hours} h)")
    return "; ".join(parts)


def event_span_text(event: RiskEvent, window: Window) -> str:
    ref = window.start
    end = "end beyond window" if event.continues_past_window else fmt_time(event.end, ref)
    return f"{fmt_time(event.start, ref)}-{end}"


def summarize_window(window: Optional[Window], events: list, chance: list) -> list:
    """Short, cautious summary of the most important expected changes (list of sentences)."""
    if window is None:
        return ["No hourly forecast data are available, so no 24-hour timeline can be shown."]
    f, ref, lines = window.frame, window.start, []
    lines.append(f"Window: {window.start:%a %d %b %H:%M} to {window.end:%a %d %b %H:%M} (local time at the location). "
                 "Everything below is a model forecast and can change.")
    if not any(window.available.values()):
        lines.append("The forecast data held by the app do not cover this 24-hour window (every hourly value is missing), "
                     "so nothing could be checked. Press Refresh to fetch newer data.")
        return lines
    if not events:
        lines.append("No configured alert threshold is forecast to be crossed in this window, based on the data available.")
    for e in events[:5]:
        lines.append(f"{e.variable}: the forecast peaks at {e.peak_value:.1f} {e.unit} around "
                     f"{fmt_time(e.peak_time, ref)}; {event_timing_text(e, window)}.")
    if len(events) > 5:
        lines.append(f"{len(events) - 5} further, lower-level period(s) are listed in the table.")
    if window.available.get("temperature_2m"):
        t = f["temperature_2m"]
        lines.append(f"Temperature is forecast to range from {t.min():.1f} °C (about {fmt_time(f.loc[t.idxmin(), 'time'], ref)}) "
                     f"to {t.max():.1f} °C (about {fmt_time(f.loc[t.idxmax(), 'time'], ref)}).")
    if window.rain_probability_available:
        p = f["precipitation_probability"]
        text = f"Rain probability is forecast to reach up to {p.max():.0f}% around {fmt_time(f.loc[p.idxmax(), 'time'], ref)}"
        if window.available.get("precipitation"):
            text += f"; the model's rainfall total for these hours is {f['precipitation'].sum():.1f} mm"
        lines.append(text + " (a probability, not a certainty).")
        for c in chance[:2]:
            end = "the end of the window" if c.continues_past_window else fmt_time(c.end, ref)
            lines.append(f"The chance of rain stays at or above {config.RAIN_PROB_NOTABLE_PERCENT:g}% from about "
                         f"{fmt_time(c.start, ref)} to {end}. Consider checking local weather updates before travelling.")
    elif window.available.get("precipitation"):
        lines.append(f"Forecast rainfall total for these hours: {f['precipitation'].sum():.1f} mm "
                     "(rain probability data are unavailable).")
    else:
        lines.append("Hourly rainfall data are unavailable.")
    if window.available.get("wind_gusts_10m"):
        g = f["wind_gusts_10m"]
        lines.append(f"Strongest forecast gust: {g.max():.0f} km/h around {fmt_time(f.loc[g.idxmax(), 'time'], ref)}.")
    if window.air_available:
        a = f["us_aqi"]
        from data_service import aqi_category_us
        lines.append(f"Modelled US AQI is forecast to peak at {a.max():.0f} ({aqi_category_us(a.max())}) around "
                     f"{fmt_time(f.loc[a.idxmax(), 'time'], ref)}. This is a regional model estimate, not a street-level reading.")
    else:
        lines.append("An hourly air-quality forecast is UNAVAILABLE, so air quality is not part of this timeline.")
    gaps = {c: n for c, n in window.missing_hours.items() if n and window.available.get(c)}
    if gaps:
        lines.append("Some hourly steps are missing (" + ", ".join(f"{c}: {n} h" for c, n in gaps.items())
                     + "). They are shown as gaps, not filled in.")
    return lines


# ------------------------------------------------------ today vs tomorrow ---
COMPARE_FIELDS = (
    ("temperature_2m_max", "Maximum temperature", "°C"), ("temperature_2m_min", "Minimum temperature", "°C"),
    ("apparent_temperature_max", "Maximum feels-like temperature", "°C"), ("precipitation_sum", "Rainfall total", "mm"),
    ("precipitation_probability_max", "Highest rain probability", "%"), ("wind_gusts_10m_max", "Strongest gust", "km/h"),
)


def compare_today_tomorrow(weather, today: Optional[pd.Timestamp] = None):
    """(lines, data) comparing tomorrow's daily forecast with today's. Empty if either day is missing."""
    daily = getattr(weather, "daily", None)
    if daily is None or daily.empty:
        return [], {}
    today = pd.Timestamp(today).normalize() if today is not None else daily["date"].iloc[0].normalize()
    d0 = daily[daily["date"].dt.normalize() == today]
    d1 = daily[daily["date"].dt.normalize() == today + pd.Timedelta(days=1)]
    if d0.empty or d1.empty:
        return [], {}
    d0, d1, lines, data = d0.iloc[0], d1.iloc[0], [], {}
    for column, label, unit in COMPARE_FIELDS:
        if column not in daily.columns or pd.isna(d0[column]) or pd.isna(d1[column]):
            continue
        a, b = float(d0[column]), float(d1[column])
        diff = b - a
        trend = "about the same" if abs(diff) < 0.05 else f"{abs(diff):.1f} {unit} {'higher' if diff > 0 else 'lower'}"
        lines.append(f"{label}: today {a:.1f} {unit}, tomorrow {b:.1f} {unit} ({trend}).")
        data[label] = {"today": round(a, 1), "tomorrow": round(b, 1), "unit": unit}
    return lines, data
