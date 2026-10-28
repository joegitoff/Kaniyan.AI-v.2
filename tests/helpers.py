"""Shared builders for tests. Everything is INVENTED sample data - tests check our logic, not real weather."""
from datetime import date, datetime, timezone

import data_service as ds
import sample_data as sd

START = date(2026, 10, 20)                              # sample "today"; sample current time is 14:00
NOW_UTC = datetime(2026, 10, 20, 8, 30, tzinfo=timezone.utc)   # = 14:00 in Asia/Kolkata -> window starts 14:00
LOC = sd.SAMPLE_LOCATION
HOURS = 7 * 24


def series(default, **points):
    """168 hourly values; points like h16=38.0 set hour-of-first-day 16 (index = hours since 00:00 of START)."""
    out = [default] * HOURS
    for name, value in points.items():
        out[int(name[1:])] = value
    return out


def raw_weather(**hourly):
    raw = sd.make_sample_weather_raw(START)
    raw["hourly"].update(hourly)
    return raw


def weather(is_sample=True, **hourly):
    return ds.parse_weather(raw_weather(**hourly), LOC, is_sample=is_sample)


def air(**hourly):
    raw = sd.make_sample_air_raw(START)
    raw["hourly"].update(hourly)
    return ds.parse_air_quality(raw, LOC, is_sample=True)


def result(data, status=ds.STATUS_DEMO, error=""):
    return ds.FetchResult(data, status, getattr(data, "fetched_at", None), error)


CALM = dict(  # hourly overrides that trigger nothing
    temperature_2m=series(26.0), apparent_temperature=series(27.0), precipitation=series(0.0),
    precipitation_probability=series(10), wind_speed_10m=series(10.0), wind_gusts_10m=series(15.0))
