"""Reliability tests for the data layer: retries, malformed responses, validation, cache + freshness status."""
from datetime import datetime, timedelta, timezone

import pytest
import requests

import config
import data_service as ds
import sample_data as sd
from helpers import LOC, START, raw_weather

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)


class Resp:
    def __init__(self, payload=None, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


def script_get(monkeypatch, steps):
    """steps: list of Resp or Exception, consumed one per HTTP call. Returns the call counter."""
    calls = {"n": 0}

    def fake(url, params=None, timeout=None):
        step = steps[min(calls["n"], len(steps) - 1)]
        calls["n"] += 1
        if isinstance(step, Exception):
            raise step
        return step
    monkeypatch.setattr(ds.requests, "get", fake)
    return calls


# ------------------------------------------------------------------ retries --
def test_temporary_network_error_is_retried_then_succeeds(monkeypatch):
    calls = script_get(monkeypatch, [requests.exceptions.ConnectionError("x"), requests.exceptions.Timeout("y"),
                                     Resp(sd.make_sample_weather_raw(START))])
    assert len(ds.fetch_weather(LOC).daily) == 7
    assert calls["n"] == 3


def test_retries_are_bounded(monkeypatch):
    calls = script_get(monkeypatch, [requests.exceptions.Timeout("x")])
    with pytest.raises(ds.NetworkError):
        ds.fetch_weather(LOC)
    assert calls["n"] == config.MAX_RETRIES + 1


def test_server_errors_are_retried(monkeypatch):
    calls = script_get(monkeypatch, [Resp({}, 503), Resp(sd.make_sample_air_raw(START))])
    assert ds.fetch_air_quality(LOC).hourly is not None
    assert calls["n"] == 2


def test_persistent_server_error_raises_service_unavailable(monkeypatch):
    script_get(monkeypatch, [Resp({}, 500)])
    with pytest.raises(ds.ServiceUnavailableError):
        ds.fetch_weather(LOC)


@pytest.mark.parametrize("status", [429, 400, 404])
def test_rate_limit_and_client_errors_are_not_retried(monkeypatch, status):
    calls = script_get(monkeypatch, [Resp({"error": True, "reason": "no"}, status)])
    with pytest.raises(ds.DataServiceError):
        ds.fetch_weather(LOC)
    assert calls["n"] == 1


def test_error_messages_do_not_leak_request_urls(monkeypatch):
    script_get(monkeypatch, [requests.exceptions.InvalidURL("https://x?apikey=SECRET")])
    with pytest.raises(ds.NetworkError) as info:
        ds.fetch_weather(LOC)
    assert "SECRET" not in str(info.value)


# ------------------------------------------------------- malformed responses --
@pytest.mark.parametrize("mutate", [
    lambda r: r["daily"].__setitem__("temperature_2m_max", "not a list"),
    lambda r: r["daily"].__setitem__("time", 5),
    lambda r: r.__setitem__("current", [1, 2, 3]),
    lambda r: r["daily"].__setitem__("precipitation_sum", [1.0]),
])
def test_malformed_weather_raises_data_format_error(mutate):
    raw = raw_weather()
    mutate(raw)
    with pytest.raises(ds.DataFormatError):
        ds.parse_weather(raw, LOC)


def test_response_that_is_not_an_object():
    with pytest.raises(ds.DataFormatError):
        ds.parse_weather([1, 2], LOC)


def test_implausible_values_are_ignored_and_reported():
    raw = raw_weather()
    raw["current"]["temperature_2m"] = 999
    raw["current"]["relative_humidity_2m"] = "wet"
    raw["hourly"]["temperature_2m"][3] = -500
    w = ds.parse_weather(raw, LOC, is_sample=True)
    assert w.current["temperature_2m"] is None and w.current["relative_humidity_2m"] is None
    assert w.hourly["temperature_2m"].isna().sum() == 1
    assert len(w.warnings) == 3


def test_bad_weather_code_does_not_crash():
    raw = raw_weather()
    raw["current"]["weather_code"] = "banana"                  # non-numeric: ignored + reported
    w = ds.parse_weather(raw, LOC)
    assert w.current["weather_text"] == "Unavailable" and any("weather_code" in x for x in w.warnings)
    raw["current"]["weather_code"] = 12345                     # numeric but not a WMO code
    assert ds.parse_weather(raw, LOC).current["weather_text"] == "Unknown"


def test_duplicate_and_unordered_timestamps_are_cleaned():
    raw = raw_weather()
    raw["hourly"] = {"time": ["2026-10-20T01:00", "2026-10-20T00:00", "2026-10-20T01:00", "bad-date"],
                     "temperature_2m": [2.0, 1.0, 3.0, 4.0]}
    h = ds.parse_weather(raw, LOC).hourly
    assert list(h["temperature_2m"]) == [1.0, 2.0]          # sorted, first duplicate kept, bad date dropped


def test_missing_air_quality_hourly_and_non_list_column():
    with pytest.raises(ds.DataFormatError):
        ds.parse_air_quality({"current": {}}, LOC)
    raw = sd.make_sample_air_raw(START)
    raw["hourly"]["us_aqi"] = "oops"
    with pytest.raises(ds.DataFormatError):
        ds.parse_air_quality(raw, LOC)


# ------------------------------------------------------------ cache + status --
def make_fetcher(outcomes):
    """Returns (fetcher, calls). Each outcome is data or an Exception."""
    calls = {"n": 0}

    def fetcher(location):
        out = outcomes[min(calls["n"], len(outcomes) - 1)]
        calls["n"] += 1
        if isinstance(out, Exception):
            raise out
        return out
    return fetcher, calls


def weather_at(when):
    return ds.parse_weather(raw_weather(), LOC, fetched_at=when, is_sample=False)


def test_fresh_cache_is_reused_without_a_new_request():
    cache = ds.DataCache()
    fetcher, calls = make_fetcher([weather_at(NOW)])
    ds.fetch_with_cache(cache, "weather", LOC, fetcher, now=NOW)
    again = ds.fetch_with_cache(cache, "weather", LOC, fetcher, now=NOW + timedelta(seconds=300))
    assert calls["n"] == 1 and again.status == ds.STATUS_LIVE


def test_expired_cache_triggers_a_refresh():
    cache = ds.DataCache()
    fetcher, calls = make_fetcher([weather_at(NOW), weather_at(NOW + timedelta(seconds=700))])
    ds.fetch_with_cache(cache, "weather", LOC, fetcher, now=NOW)
    r = ds.fetch_with_cache(cache, "weather", LOC, fetcher, now=NOW + timedelta(seconds=700))
    assert calls["n"] == 2 and r.status == ds.STATUS_LIVE


def test_forced_refresh_bypasses_fresh_cache():
    cache = ds.DataCache()
    fetcher, calls = make_fetcher([weather_at(NOW)])
    ds.fetch_with_cache(cache, "weather", LOC, fetcher, now=NOW)
    ds.fetch_with_cache(cache, "weather", LOC, fetcher, force=True, now=NOW + timedelta(seconds=5))
    assert calls["n"] == 2


def test_stale_cache_after_failed_refresh_is_never_labelled_live():
    cache = ds.DataCache()
    fetcher, _ = make_fetcher([weather_at(NOW), ds.NetworkError("down")])
    ds.fetch_with_cache(cache, "weather", LOC, fetcher, now=NOW)
    later = NOW + timedelta(hours=2)
    r = ds.fetch_with_cache(cache, "weather", LOC, fetcher, now=later)
    assert r.status == ds.STATUS_CACHED and r.ok and r.error == "down"
    assert "Cached (stale)" in r.label(later) and "Live" not in r.label(later) and "2 h" in r.label(later)


def test_failure_without_cache_is_unavailable():
    r = ds.fetch_with_cache(ds.DataCache(), "weather", LOC, make_fetcher([ds.RateLimitError("slow down")])[0], now=NOW)
    assert (r.status, r.data, r.error) == (ds.STATUS_UNAVAILABLE, None, "slow down")


def test_unexpected_exception_is_contained():
    r = ds.fetch_with_cache(ds.DataCache(), "air", LOC, make_fetcher([KeyError("boom")])[0], now=NOW)
    assert r.status == ds.STATUS_UNAVAILABLE and "KeyError" in r.error


def test_weather_and_air_failures_are_independent():
    cache = ds.DataCache()
    ok = ds.fetch_with_cache(cache, "weather", LOC, make_fetcher([weather_at(NOW)])[0], now=NOW)
    bad = ds.fetch_with_cache(cache, "air", LOC, make_fetcher([ds.NetworkError("x")])[0], now=NOW)
    assert ok.ok and not bad.ok


def test_cache_key_is_per_location():
    cache = ds.DataCache()
    other = ds.Location("Madurai", 9.92, 78.12)
    f1, c1 = make_fetcher([weather_at(NOW)])
    ds.fetch_with_cache(cache, "weather", LOC, f1, now=NOW)
    ds.fetch_with_cache(cache, "weather", other, f1, now=NOW)
    assert c1["n"] == 2


@pytest.mark.parametrize("last,now_offset,allowed", [(None, 0, True), (NOW, 10, False), (NOW, 59, False), (NOW, 60, True), (NOW, 600, True)])
def test_refresh_cooldown(last, now_offset, allowed):
    ok, wait = ds.can_refresh(last, NOW + timedelta(seconds=now_offset))
    assert ok is allowed and (wait == 0) == allowed


def test_describe_age():
    assert ds.describe_age(None) == "unknown age" and ds.describe_age(5) == "just now"
    assert ds.describe_age(180) == "3 min ago" and ds.describe_age(7500) == "2 h 5 min ago"
