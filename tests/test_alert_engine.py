"""Alert-rule tests. They use SAMPLE (invented) data, so they check OUR LOGIC - not real weather."""
from datetime import date

import pytest

import alert_engine as ae
import config
import sample_data as sd
from config import Level

START = date(2026, 10, 20)          # a Tuesday


def by_key(alerts, key):
    return [a for a in alerts if a.key == key]


def levels_by_day(alerts, key):
    return {a.when: a.level for a in by_key(alerts, key)}


def test_classify_boundaries():
    cut = {"info": 10, "caution": 20, "high": 30}
    assert ae.classify(9.99, cut) is None
    assert ae.classify(10, cut) == Level.INFO
    assert ae.classify(20, cut) == Level.CAUTION
    assert ae.classify(30, cut) == Level.HIGH


@pytest.mark.parametrize("bad", [None, float("nan"), "abc"])
def test_classify_missing_or_invalid_returns_none(bad):
    assert ae.classify(bad, {"info": 1, "caution": 2, "high": 3}) is None


def test_rain_alerts_from_sample_data():
    alerts = ae.evaluate_alerts(sd.load_sample_weather(START))
    levels = levels_by_day(alerts, "rain")
    # sample rain mm: 0, 2, 72, 118, 30, 4, None
    assert levels == {"Thu 22 Oct 2026": Level.CAUTION,    # 72 mm
                      "Fri 23 Oct 2026": Level.HIGH,       # 118 mm
                      "Sat 24 Oct 2026": Level.INFO}       # 30 mm ; the missing value is ignored


def test_rain_alert_never_claims_flooding_or_official_status():
    for a in by_key(ae.evaluate_alerts(sd.load_sample_weather(START)), "rain"):
        assert "NOT predict street-level flooding" in a.explanation
        assert a.official is False


def test_heat_wind_alerts():
    alerts = ae.evaluate_alerts(sd.load_sample_weather(START))
    assert levels_by_day(alerts, "temperature")["Tue 20 Oct 2026"] == Level.CAUTION   # 39.5 C
    assert levels_by_day(alerts, "feels_like")["Tue 20 Oct 2026"] == Level.CAUTION    # 43 C
    wind = levels_by_day(alerts, "wind")
    assert wind["Fri 23 Oct 2026"] == Level.HIGH                                      # 82 km/h
    assert wind["Thu 22 Oct 2026"] == Level.CAUTION                                   # 66 km/h


def test_air_quality_alerts_use_daily_peak():
    w, a = sd.load_sample_weather(START), sd.load_sample_air_quality(START)
    aqi = by_key(ae.evaluate_alerts(w, a), "air_quality")
    assert [x.level for x in sorted(aqi, key=lambda x: x.sort_time)] == [
        Level.INFO, Level.INFO, Level.CAUTION, Level.HIGH, Level.CAUTION]
    assert max(x.value for x in aqi) == 180
    assert all("not the Indian CPCB" in x.explanation for x in aqi)


def test_sorted_most_severe_first():
    alerts = ae.evaluate_alerts(sd.load_sample_weather(START), sd.load_sample_air_quality(START))
    levels = [int(a.level) for a in alerts]
    assert levels == sorted(levels, reverse=True)


def test_alert_has_all_required_fields():
    a = ae.evaluate_alerts(sd.load_sample_weather(START))[0]
    d = a.to_dict()
    for field in ("location", "variable", "value", "unit", "rule", "when", "level",
                  "explanation", "advice", "source", "generated_at"):
        assert d[field] not in (None, "", [])
    assert "[SAMPLE DATA]" in d["source"]


def test_custom_thresholds_change_results():
    w = sd.load_sample_weather(START)
    strict = {k: dict(v) for k, v in config.DEFAULT_THRESHOLDS.items()}
    strict["rain_daily_mm"] = {"info": 1, "caution": 2, "high": 3}
    assert len(by_key(ae.evaluate_alerts(w, thresholds=strict), "rain")) > 3


def test_invalid_thresholds_rejected():
    bad = {k: dict(v) for k, v in config.DEFAULT_THRESHOLDS.items()}
    bad["us_aqi"] = {"info": 100, "caution": 50, "high": 150}
    with pytest.raises(ValueError):
        ae.evaluate_alerts(sd.load_sample_weather(START), thresholds=bad)


def test_missing_columns_and_all_null_air_quality_are_safe():
    w = sd.load_sample_weather(START)
    w.daily = w.daily.drop(columns=["wind_gusts_10m_max"])           # column missing entirely
    air = sd.load_sample_air_quality(START)
    air.hourly["us_aqi"] = float("nan")                              # every value null
    alerts = ae.evaluate_alerts(w, air)
    assert by_key(alerts, "wind") == [] and by_key(alerts, "air_quality") == []


def test_calm_conditions_give_no_alerts():
    w = sd.load_sample_weather(START)
    for col, val in (("precipitation_sum", 0), ("temperature_2m_max", 25), ("apparent_temperature_max", 26),
                     ("wind_gusts_10m_max", 10)):
        w.daily[col] = val
    assert ae.evaluate_alerts(w) == []
