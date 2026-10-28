"""Data-service tests: network calls are replaced ("mocked") so no internet is needed.
Sample JSON is invented; these tests verify parsing and error handling only."""
from datetime import date

import pytest
import requests

import data_service as ds
import sample_data as sd

LOC = sd.SAMPLE_LOCATION


class FakeResponse:
    def __init__(self, payload=None, status=200, bad_json=False):
        self._payload, self.status_code, self._bad = payload, status, bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._payload


def patch_get(monkeypatch, response=None, exc=None):
    def fake_get(url, params=None, timeout=None):
        if exc:
            raise exc
        return response
    monkeypatch.setattr(ds.requests, "get", fake_get)


# ---- geocoding -------------------------------------------------------------
def test_search_success(monkeypatch):
    payload = {"results": [{"name": "Chennai", "latitude": 13.08, "longitude": 80.27,
                            "country": "India", "admin1": "Tamil Nadu", "timezone": "Asia/Kolkata"}]}
    patch_get(monkeypatch, FakeResponse(payload))
    result = ds.search_locations("Chennai")
    assert result[0].label == "Chennai, Tamil Nadu, India"
    assert result[0].latitude == 13.08


def test_search_unknown_place(monkeypatch):
    patch_get(monkeypatch, FakeResponse({"generationtime_ms": 0.5}))     # API omits "results"
    with pytest.raises(ds.LocationNotFoundError):
        ds.search_locations("Zzzzqqq")


def test_search_too_short():
    with pytest.raises(ds.LocationNotFoundError):
        ds.search_locations(" a ")


def test_search_skips_records_without_coordinates(monkeypatch):
    patch_get(monkeypatch, FakeResponse({"results": [{"name": "Broken"}]}))
    with pytest.raises(ds.LocationNotFoundError):
        ds.search_locations("Broken")


# ---- HTTP failures ----------------------------------------------------------
@pytest.mark.parametrize("exc", [requests.exceptions.ConnectionError("x"), requests.exceptions.Timeout("x")])
def test_network_failure(monkeypatch, exc):
    patch_get(monkeypatch, exc=exc)
    with pytest.raises(ds.NetworkError):
        ds.fetch_weather(LOC)


def test_rate_limit(monkeypatch):
    patch_get(monkeypatch, FakeResponse({}, status=429))
    with pytest.raises(ds.RateLimitError):
        ds.fetch_air_quality(LOC)


def test_api_error_json(monkeypatch):
    patch_get(monkeypatch, FakeResponse({"error": True, "reason": "bad variable"}, status=400))
    with pytest.raises(ds.DataServiceError) as info:
        ds.fetch_weather(LOC)
    assert "bad variable" in str(info.value)


def test_invalid_json(monkeypatch):
    patch_get(monkeypatch, FakeResponse(bad_json=True))
    with pytest.raises(ds.DataFormatError):
        ds.fetch_weather(LOC)


def test_fetch_weather_success_with_mocked_response(monkeypatch):
    patch_get(monkeypatch, FakeResponse(sd.make_sample_weather_raw(date(2026, 10, 20))))
    w = ds.fetch_weather(LOC)
    assert len(w.daily) == 7


# ---- parsing -----------------------------------------------------------------
def test_parse_weather_structure_and_nulls():
    w = sd.load_sample_weather(date(2026, 10, 20))
    assert len(w.daily) == 7 and len(w.hourly) == 7 * 24
    assert w.current["weather_text"] == "Partly cloudy"          # WMO code 2
    assert w.daily["precipitation_sum"].isna().sum() == 1         # None -> NaN, not a crash
    assert w.units["temperature_2m_max"] == "°C"
    assert w.is_sample is True


def test_parse_weather_missing_daily_raises():
    with pytest.raises(ds.DataFormatError):
        ds.parse_weather({"hourly": {}}, LOC)


def test_parse_weather_length_mismatch_raises():
    raw = sd.make_sample_weather_raw(date(2026, 10, 20))
    raw["daily"]["temperature_2m_max"] = [1, 2]
    with pytest.raises(ds.DataFormatError):
        ds.parse_weather(raw, LOC)


def test_parse_air_quality_ok_and_missing_hourly():
    a = sd.load_sample_air_quality(date(2026, 10, 20))
    assert len(a.hourly) == 5 * 24 and a.current["us_aqi"] == 72
    with pytest.raises(ds.DataFormatError):
        ds.parse_air_quality({"current": {}}, LOC)


def test_unavailable_aqi_values():
    assert ds.aqi_category_us(None) == "Unavailable"
    assert ds.aqi_category_us(float("nan")) == "Unavailable"
    assert ds.aqi_category_us("abc") == "Unavailable"
    assert ds.aqi_category_us(42) == "Good"
    assert ds.aqi_category_us(165) == "Unhealthy"
    assert ds.aqi_category_us(999) == "Hazardous"
