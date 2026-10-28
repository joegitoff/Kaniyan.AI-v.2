"""24-hour timeline: window building, threshold crossing times, persistence, missing hours, unavailable data."""
from datetime import datetime, timezone

import pandas as pd

import config
import timeline as tl
from config import Level
from helpers import CALM, NOW_UTC, air, series, weather

T = config.DEFAULT_THRESHOLDS
START_TS = pd.Timestamp("2026-10-20 14:00")


def win(w=None, a=None, **hourly):
    w = w or weather(**{**CALM, **hourly})
    return tl.build_window(w, a, T, now_utc=NOW_UTC)


def events_for(window, key):
    return [e for e in tl.find_events(window, T) if e.key == key]


def test_window_has_24_hourly_rows_starting_at_current_hour():
    w = win()
    assert len(w.frame) == 24 and w.start == START_TS and w.end == START_TS + pd.Timedelta(hours=23)


def test_live_window_starts_at_real_local_hour_not_data_time():
    w = tl.build_window(weather(is_sample=False, **CALM), None, T, now_utc=NOW_UTC)   # 08:30 UTC = 14:00 IST
    assert w.start == START_TS


def test_calm_conditions_give_no_events_and_all_levels_zero():
    w = win()
    assert tl.find_events(w, T) == [] and (w.frame["level_temperature"] == 0).all()


def test_threshold_crossing_time_peak_and_persistence():
    # hours since 00:00 of day 0: 16,17 = 38.0 (Caution, exactly at the cut-off), 18 = 37.99, 19 = 40.0 (High)
    temps = series(26.0, h16=38.0, h17=38.0, h18=37.99, h19=40.0)
    ev = events_for(win(temperature_2m=temps), "temperature")
    # 37.99 is still >= 35 (Information), so hours 16-19 form ONE continuous event reaching High at 19:00
    assert len(ev) == 1
    e = ev[0]
    assert e.level == Level.HIGH and e.start == pd.Timestamp("2026-10-20 16:00") and e.end == pd.Timestamp("2026-10-20 19:00")
    assert e.first_crossed[Level.CAUTION] == pd.Timestamp("2026-10-20 16:00")
    assert e.first_crossed[Level.HIGH] == pd.Timestamp("2026-10-20 19:00")
    assert e.hours == 4 and e.peak_value == 40.0 and not e.ongoing_at_start and not e.continues_past_window


def test_value_just_below_threshold_creates_no_caution():
    ev = events_for(win(temperature_2m=series(26.0, h16=37.99)), "temperature")
    assert len(ev) == 1 and ev[0].level == Level.INFO


def test_ongoing_at_start_and_continues_past_window():
    e = events_for(win(temperature_2m=series(39.0)), "temperature")[0]
    assert e.ongoing_at_start and e.continues_past_window and e.level == Level.CAUTION
    text = tl.event_timing_text(e, win(temperature_2m=series(39.0)))
    assert "already" in text and "not covered" in text


def test_missing_hour_splits_event_and_marks_unknown_end():
    temps = series(26.0, h16=38.0, h17=38.0, h18=None, h19=40.0)
    ev = sorted(events_for(win(temperature_2m=temps), "temperature"), key=lambda e: e.start)
    assert len(ev) == 2
    assert ev[0].end_unknown_gap and ev[0].end == pd.Timestamp("2026-10-20 17:00")
    assert ev[1].level == Level.HIGH and not ev[1].end_unknown_gap


def test_forecast_with_missing_intervals_keeps_gaps_and_reports_them():
    raw_temps = series(26.0)
    for i in (15, 16, 20):
        raw_temps[i] = None
    w = win(temperature_2m=raw_temps)
    assert w.missing_hours["temperature_2m"] == 3 and w.frame["temperature_2m"].isna().sum() == 3
    assert w.frame["level_temperature"].isna().sum() == 3            # gap hours have NO level (not 0)
    assert any("missing" in line for line in tl.summarize_window(w, [], []))


def test_forecast_window_beyond_available_hours_is_missing_not_invented():
    w = tl.build_window(weather(is_sample=False, **CALM), None, T, now_utc=datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc))
    assert w.frame["temperature_2m"].isna().sum() > 0           # sample data end on 26 Oct 23:00
    w2 = tl.build_window(weather(is_sample=False, **CALM), None, T, now_utc=datetime(2026, 12, 1, tzinfo=timezone.utc))
    assert not any(w2.available.values())
    assert "do not cover this 24-hour window" in " ".join(tl.summarize_window(w2, [], []))


def test_rain_uses_running_total_against_the_daily_rule():
    rain = series(0.0, h15=15.0, h16=15.0, h17=15.0, h18=15.0, h19=15.0)       # 15, 30, 45, 60, 75 mm running
    e = events_for(win(precipitation=rain), "rain")[0]
    assert e.level == Level.CAUTION and e.first_crossed[Level.INFO] == pd.Timestamp("2026-10-20 16:00")
    assert e.first_crossed[Level.CAUTION] == pd.Timestamp("2026-10-20 19:00") and e.continues_past_window


def test_rain_total_is_lower_bound_when_hours_missing():
    rain = series(0.0, h15=70.0, h16=None)
    w = win(precipitation=rain)
    assert w.frame["rain_cumulative_mm"].iloc[2] == 70.0           # missing hour counted as 0 -> can only under-state


def test_air_quality_unavailable_is_stated_and_not_invented():
    w = win()                                                    # no air data at all
    assert not w.air_available and w.frame["us_aqi"].isna().all() and w.frame["level_air_quality"].isna().all()
    assert "UNAVAILABLE" in " ".join(tl.summarize_window(w, [], []))
    all_null = win(a=air(us_aqi=[None] * 120))
    assert not all_null.air_available


def test_air_quality_events_when_available():
    aqi = [60.0] * 120
    aqi[16], aqi[17] = 101.0, 160.0                                # hours since day-0 midnight
    e = events_for(win(a=air(us_aqi=aqi)), "air_quality")
    assert any(x.level == Level.HIGH and x.peak_time == pd.Timestamp("2026-10-20 17:00") for x in e)


def test_rain_chance_periods_are_probabilities_with_peak():
    prob = series(10, h17=60, h18=85, h19=60)
    p = tl.rain_chance_periods(win(precipitation_probability=prob))
    assert len(p) == 1 and p[0].peak_probability == 85 and p[0].peak_time == pd.Timestamp("2026-10-20 18:00")
    assert p[0].start == pd.Timestamp("2026-10-20 17:00") and p[0].end == pd.Timestamp("2026-10-20 19:00")
    assert "not a certainty" in " ".join(tl.summarize_window(win(precipitation_probability=prob), [], p))


def test_no_rain_probability_data_gives_no_chance_periods():
    w = win(precipitation_probability=[None] * 168)
    assert tl.rain_chance_periods(w) == [] and not w.rain_probability_available


def test_quiet_periods_exclude_events_and_missing_hours():
    temps = series(26.0, h14=39.0, h15=39.0, h16=39.0)               # hours 14-16 are Caution
    temps[20] = None                                                  # missing hour is never quiet
    periods, checked, skipped = tl.quiet_periods(win(temperature_2m=temps))
    assert periods[0][0] == pd.Timestamp("2026-10-20 17:00") and periods[0][1] == pd.Timestamp("2026-10-20 19:00")
    assert "Air quality (US AQI)" in skipped and "Heat (air temperature)" in checked


def test_everything_missing_means_no_quiet_periods():
    assert tl.quiet_periods(tl.build_window(weather(is_sample=False, **CALM), None, T, now_utc=datetime(2026, 12, 1, tzinfo=timezone.utc)))[0] == []
    assert tl.quiet_periods(None)[0] == []


def test_no_data_returns_none_window_and_safe_summary():
    assert tl.build_window(None, None, T) is None and tl.find_events(None, T) == []
    assert "No hourly forecast data" in tl.summarize_window(None, [], [])[0]


def test_air_only_window_works():
    w = tl.build_window(None, air(), T, now_utc=NOW_UTC)
    assert w is not None and w.air_available and not w.available["temperature_2m"]


def test_compare_today_tomorrow():
    lines, data = tl.compare_today_tomorrow(weather(), pd.Timestamp("2026-10-20"))
    assert data["Maximum temperature"] == {"today": 39.5, "tomorrow": 36.0, "unit": "°C"}
    assert any("3.5 °C lower" in l for l in lines)
    assert tl.compare_today_tomorrow(weather(), pd.Timestamp("2026-12-01")) == ([], {})
    assert tl.compare_today_tomorrow(None) == ([], {})
