"""
data_service.py - talks to the Open-Meteo APIs and turns JSON into pandas tables.

Python concepts: functions, requests library, exceptions (custom classes),
dataclasses, dictionaries/lists, pandas DataFrames, datetime, type hints.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import pandas as pd
import requests

import config


# ---------------------------------------------------------------- exceptions --
class DataServiceError(Exception):
    """Base class: anything that goes wrong while getting data."""


class NetworkError(DataServiceError):
    """No internet, DNS problem or timeout."""


class ServiceUnavailableError(NetworkError):
    """HTTP 5xx from the provider (temporary; retried a bounded number of times)."""


class RateLimitError(DataServiceError):
    """HTTP 429: too many requests."""


class LocationNotFoundError(DataServiceError):
    """Geocoding returned nothing for the typed name."""


class DataFormatError(DataServiceError):
    """The API answered, but the JSON is not in the shape we expect."""


# --------------------------------------------------------------- data classes --
@dataclass
class Location:
    name: str
    latitude: float
    longitude: float
    country: str = ""
    admin1: str = ""          # state / region
    timezone: str = "auto"

    @property
    def label(self) -> str:
        parts = [p for p in (self.name, self.admin1, self.country) if p]
        return ", ".join(parts)


@dataclass
class WeatherData:
    location: Location
    current: dict
    daily: pd.DataFrame
    hourly: pd.DataFrame
    units: dict
    timezone: str
    fetched_at: datetime
    source: str = "Open-Meteo Weather Forecast API (api.open-meteo.com/v1/forecast)"
    is_sample: bool = False
    warnings: list = field(default_factory=list)   # validation notes, e.g. ignored implausible values

    def period(self):
        """(first, last) forecast timestamp covered by the hourly table (or daily if no hourly)."""
        return data_period(self.hourly, "time") or data_period(self.daily, "date")


@dataclass
class AirQualityData:
    location: Location
    current: dict
    hourly: pd.DataFrame
    units: dict
    fetched_at: datetime
    source: str = ("Open-Meteo Air Quality API (CAMS model data) - model estimate, "
                   "not a government monitoring-station reading")
    is_sample: bool = False
    warnings: list = field(default_factory=list)
    timezone: str = "unknown"

    def period(self):
        return data_period(self.hourly, "time")


# ------------------------------------------------------------------ HTTP part --
def _get_json_once(url: str, params: dict) -> dict:
    """One API call. Returns parsed JSON or raises one of our own exceptions."""
    try:
        response = requests.get(url, params=params, timeout=config.REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.Timeout as exc:
        raise NetworkError("The data service took too long to respond (timeout).") from exc
    except requests.exceptions.ConnectionError as exc:
        raise NetworkError("Could not connect. Check your internet connection.") from exc
    except requests.exceptions.RequestException as exc:
        raise NetworkError(f"Network problem: {type(exc).__name__}.") from exc

    if response.status_code == 429:
        raise RateLimitError("Too many requests to the data service. Wait a minute and retry.")
    if response.status_code >= 500:
        raise ServiceUnavailableError(f"The data service is temporarily unavailable (HTTP {response.status_code}).")

    try:
        data = response.json()
    except ValueError as exc:
        raise DataFormatError("The data service returned something that is not valid JSON.") from exc

    if response.status_code >= 400 or (isinstance(data, dict) and data.get("error")):
        reason = data.get("reason", "unknown reason") if isinstance(data, dict) else "unknown reason"
        raise DataServiceError(f"The API reported an error (HTTP {response.status_code}): {reason}")

    if not isinstance(data, dict):
        raise DataFormatError("Unexpected JSON structure (expected an object).")
    return data


def _get_json(url: str, params: dict) -> dict:
    """Call an API with a timeout and a BOUNDED number of retries (config.MAX_RETRIES).

    Only temporary problems (timeouts, connection errors, HTTP 5xx) are retried. Rate limits (429),
    client errors (4xx) and malformed data are not - repeating them would not help and would burn quota.
    """
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            return _get_json_once(url, params)
        except NetworkError:
            if attempt >= config.MAX_RETRIES:
                raise
            time.sleep(config.RETRY_BACKOFF_SECONDS * (2 ** attempt))
    raise NetworkError("Unreachable")  # pragma: no cover


# ------------------------------------------------------------------ geocoding --
def search_locations(query: str, count: int = 5) -> list[Location]:
    """Convert a city name into up to `count` candidate locations."""
    query = (query or "").strip()
    if len(query) < 2:
        raise LocationNotFoundError("Please type at least 2 characters of a place name.")

    data = _get_json(config.GEOCODING_URL, {"name": query, "count": count,
                                            "language": "en", "format": "json"})
    results = data.get("results") or []   # the API omits "results" when nothing is found
    locations = []
    for item in results:
        if item.get("latitude") is None or item.get("longitude") is None:
            continue                       # skip incomplete records safely
        locations.append(Location(
            name=item.get("name", query),
            latitude=float(item["latitude"]),
            longitude=float(item["longitude"]),
            country=item.get("country", ""),
            admin1=item.get("admin1", ""),
            timezone=item.get("timezone", "auto"),
        ))
    if not locations:
        raise LocationNotFoundError(f"No place found for '{query}'. Check the spelling or try a nearby city.")
    return locations


# -------------------------------------------------------------- table helpers --
def data_period(df: pd.DataFrame, time_column: str):
    """(first, last) timestamp of a table, or None when empty."""
    if df is None or df.empty or time_column not in df.columns:
        return None
    return df[time_column].min(), df[time_column].max()


def _frame_from_block(block: Optional[dict], time_column: str) -> pd.DataFrame:
    """Turn {'time': [...], 'x': [...]} into a DataFrame.

    Bad / missing values become NaN. Structural problems (not lists, unequal lengths) raise
    DataFormatError. Rows with an unreadable or DUPLICATE timestamp are dropped so that one
    forecast hour can never produce two alerts.
    """
    if not block:
        return pd.DataFrame()
    if not isinstance(block, dict):
        raise DataFormatError("A data section is not an object of lists.")
    if "time" not in block:
        return pd.DataFrame()
    for key, values in block.items():
        if not isinstance(values, list):
            raise DataFormatError(f"Column '{key}' is not a list of values.")
    length = len(block["time"])
    for key, values in block.items():
        if len(values) != length:
            raise DataFormatError(f"Column '{key}' has {len(values)} values but 'time' has {length}.")
    df = pd.DataFrame(block).rename(columns={"time": time_column})
    df[time_column] = pd.to_datetime(df[time_column], errors="coerce").astype("datetime64[ns]")
    for column in df.columns:
        if column != time_column:
            df[column] = pd.to_numeric(df[column], errors="coerce").astype(float)
    df = df.dropna(subset=[time_column]).drop_duplicates(subset=[time_column], keep="first")
    return df.sort_values(time_column).reset_index(drop=True)


def _sanitize_frame(df: pd.DataFrame, notes: list) -> pd.DataFrame:
    """Replace physically implausible numbers by NaN and record a note (never silent)."""
    for column, (low, high) in config.PLAUSIBLE_RANGES.items():
        if column in df.columns:
            bad = df[column].notna() & ((df[column] < low) | (df[column] > high))
            if bad.any():
                df[column] = df[column].where(~bad)
                notes.append(f"{int(bad.sum())} implausible value(s) in '{column}' were ignored.")
    return df


def _clean_current(block: Any, notes: list) -> dict:
    """Validate the 'current' block: numbers must be numeric and plausible, otherwise None."""
    if block is None:
        return {}
    if not isinstance(block, dict):
        raise DataFormatError("The 'current' section is not an object.")
    cleaned = {}
    for key, value in block.items():
        if key == "time":
            cleaned[key] = value
            continue
        if value is None:
            cleaned[key] = None
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            notes.append(f"Current value '{key}' was not numeric and was ignored.")
            cleaned[key] = None
            continue
        low_high = config.PLAUSIBLE_RANGES.get(key)
        if number != number or (low_high and not low_high[0] <= number <= low_high[1]):
            notes.append(f"Current value '{key}' was implausible and was ignored.")
            cleaned[key] = None
        else:
            cleaned[key] = number
    return cleaned


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _wmo_text(code) -> str:
    try:
        if code is None or code != code:
            return "Unavailable"
        return config.WMO_CODES.get(int(code), "Unknown")
    except (TypeError, ValueError):
        return "Unknown"


# ------------------------------------------------------------------- weather --
def parse_weather(raw: dict, location: Location, fetched_at: Optional[datetime] = None,
                  is_sample: bool = False) -> WeatherData:
    """Pure function (no network): raw API JSON -> WeatherData. Easy to unit-test."""
    if not isinstance(raw, dict) or "daily" not in raw:
        raise DataFormatError("Weather response has no 'daily' section.")
    notes: list = []
    daily = _sanitize_frame(_frame_from_block(raw.get("daily"), "date"), notes)
    hourly = _sanitize_frame(_frame_from_block(raw.get("hourly"), "time"), notes)
    if daily.empty:
        raise DataFormatError("Weather response contains no daily forecast rows.")

    current = _clean_current(raw.get("current"), notes)
    current["weather_text"] = _wmo_text(current.get("weather_code"))
    if "weather_code" in daily.columns:
        daily["weather_text"] = daily["weather_code"].map(_wmo_text)

    units = {}
    for key in ("current_units", "daily_units", "hourly_units"):
        block = raw.get(key)
        if isinstance(block, dict):
            units.update(block)

    return WeatherData(location=location, current=current, daily=daily, hourly=hourly,
                       units=units, timezone=str(raw.get("timezone", "unknown")),
                       fetched_at=fetched_at or _now_utc(), is_sample=is_sample, warnings=notes)


def fetch_weather(location: Location, forecast_days: int = config.FORECAST_DAYS) -> WeatherData:
    params = {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,"
                   "weather_code,wind_speed_10m,wind_gusts_10m",
        "hourly": "temperature_2m,apparent_temperature,precipitation,precipitation_probability,"
                  "wind_speed_10m,wind_gusts_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,"
                 "precipitation_sum,precipitation_probability_max,wind_speed_10m_max,"
                 "wind_gusts_10m_max,uv_index_max",
        "timezone": "auto",
        "forecast_days": forecast_days,
    }
    return parse_weather(_get_json(config.FORECAST_URL, params), location)


# --------------------------------------------------------------- air quality --
def parse_air_quality(raw: dict, location: Location, fetched_at: Optional[datetime] = None,
                      is_sample: bool = False) -> AirQualityData:
    """Pure function: raw air-quality JSON -> AirQualityData."""
    if not isinstance(raw, dict) or "hourly" not in raw:
        raise DataFormatError("Air-quality response has no 'hourly' section.")
    notes: list = []
    hourly = _sanitize_frame(_frame_from_block(raw.get("hourly"), "time"), notes)
    if hourly.empty:
        raise DataFormatError("Air-quality response contains no hourly rows.")
    units = {}
    for key in ("current_units", "hourly_units"):
        block = raw.get(key)
        if isinstance(block, dict):
            units.update(block)
    return AirQualityData(location=location, current=_clean_current(raw.get("current"), notes),
                          hourly=hourly, units=units, fetched_at=fetched_at or _now_utc(),
                          is_sample=is_sample, warnings=notes,
                          timezone=str(raw.get("timezone", "unknown")))


def fetch_air_quality(location: Location, forecast_days: int = config.AIR_QUALITY_DAYS) -> AirQualityData:
    params = {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "current": "us_aqi,european_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,"
                   "sulphur_dioxide,ozone",
        "hourly": "pm10,pm2_5,us_aqi,european_aqi",
        "timezone": "auto",
        "forecast_days": forecast_days,
    }
    return parse_air_quality(_get_json(config.AIR_QUALITY_URL, params), location)


# ------------------------------------------------------------------ utilities --
def aqi_category_us(value: Any) -> str:
    """Name of the US AQI band for a number, or 'Unavailable'."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Unavailable"
    if number != number:          # NaN check
        return "Unavailable"
    for upper, name in config.US_AQI_BANDS:
        if number <= upper:
            return name
    return "Hazardous"


# ====================================================================== cache + status ==
# Freshness vocabulary shown to the user. "live" means: retrieved from the provider within the last
# config.CACHE_TTL_SECONDS. Anything older that is only shown because a refresh FAILED is "cached"
# and is never labelled live.
STATUS_LIVE = "live"
STATUS_CACHED = "cached"
STATUS_UNAVAILABLE = "unavailable"
STATUS_DEMO = "demo"
STATUS_TEXT = {STATUS_LIVE: "Live", STATUS_CACHED: "Cached (stale)", STATUS_UNAVAILABLE: "Unavailable",
               STATUS_DEMO: "Demonstration data"}


def describe_age(seconds: Optional[float]) -> str:
    if seconds is None:
        return "unknown age"
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    return f"{minutes // 60} h {minutes % 60} min ago"


@dataclass
class FetchResult:
    """Outcome of one provider request: the data (maybe None) plus an honest status."""
    data: Any = None
    status: str = STATUS_UNAVAILABLE
    fetched_at: Optional[datetime] = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.data is not None

    def age_seconds(self, now: Optional[datetime] = None) -> Optional[float]:
        if self.fetched_at is None:
            return None
        return ((now or _now_utc()) - self.fetched_at).total_seconds()

    def label(self, now: Optional[datetime] = None) -> str:
        text = STATUS_TEXT.get(self.status, self.status)
        if self.status in (STATUS_LIVE, STATUS_CACHED):
            text += f" - retrieved {describe_age(self.age_seconds(now))}"
        return text


class DataCache:
    """Tiny thread-safe in-memory cache: key -> (data, stored_at)."""

    def __init__(self):
        self._items: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            return self._items.get(key)

    def set(self, key, data, stored_at: datetime) -> None:
        with self._lock:
            self._items[key] = (data, stored_at)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def fetch_with_cache(cache: DataCache, kind: str, location: Location, fetcher: Callable,
                     ttl: float = config.CACHE_TTL_SECONDS, force: bool = False,
                     now: Optional[datetime] = None) -> FetchResult:
    """Fetch (weather or air) with caching. Never raises.

    * fresh cache entry and no forced refresh -> reuse it (no API call), status LIVE
    * otherwise call the provider; on success store it, status LIVE
    * provider failed but an older copy exists -> return the old copy, status CACHED (stale) + error
    * provider failed and nothing cached -> status UNAVAILABLE + error
    Weather and air quality use separate keys, so one provider failing never affects the other.
    """
    now = now or _now_utc()
    key = (kind, round(location.latitude, 2), round(location.longitude, 2))
    entry = cache.get(key)
    if entry and not force:
        data, stored_at = entry
        if (now - stored_at).total_seconds() <= ttl:
            return FetchResult(data, STATUS_LIVE, stored_at)
    try:
        data = fetcher(location)
    except DataServiceError as exc:
        error = str(exc)
    except Exception as exc:  # malformed content that slipped past validation must not crash the app
        error = f"Unexpected problem while processing the data ({type(exc).__name__})."
    else:
        stored_at = getattr(data, "fetched_at", None) or now
        cache.set(key, data, stored_at)
        return FetchResult(data, STATUS_LIVE, stored_at)
    if entry:
        return FetchResult(entry[0], STATUS_CACHED, entry[1], error)
    return FetchResult(None, STATUS_UNAVAILABLE, None, error)


def can_refresh(last_refresh: Optional[datetime], now: Optional[datetime] = None,
                min_interval: float = config.MIN_REFRESH_INTERVAL_SECONDS):
    """(allowed, seconds_to_wait) for the manual-refresh button."""
    if last_refresh is None:
        return True, 0
    wait = min_interval - ((now or _now_utc()) - last_refresh).total_seconds()
    return (wait <= 0), max(0, int(wait + 0.999))
