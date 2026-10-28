"""Alert-engine tests added in v2: exact boundaries, current alerts, conflicts, duplicates, missing data."""
import pytest

import alert_engine as ae
import config
import data_service as ds
import sample_data as sd
from config import Level
from helpers import LOC, START, air, raw_weather, weather

T = config.DEFAULT_THRESHOLDS


@pytest.mark.parametrize("rule", list(T))
def test_every_default_threshold_boundary(rule):
    """Exactly AT a cut-off triggers that level; just below stays at the lower level."""
    cut = T[rule]
    assert ae.classify(cut["info"] - 0.01, cut) is None
    assert ae.classify(cut["info"], cut) == Level.INFO
    assert ae.classify(cut["caution"] - 0.01, cut) == Level.INFO
    assert ae.classify(cut["caution"], cut) == Level.CAUTION
    assert ae.classify(cut["high"] - 0.01, cut) == Level.CAUTION
    assert ae.classify(cut["high"], cut) == Level.HIGH
    assert ae.classify(cut["high"] * 10, cut) == Level.HIGH


def current_weather(**current):
    raw = sd.make_sample_weather_raw(START)
    raw["current"].update(current)
    return ds.parse_weather(raw, LOC, is_sample=True)


def test_current_alerts_are_labelled_current_and_active():
    alerts = ae.evaluate_current_alerts(current_weather(temperature_2m=38.0), None, T, "now")
    temp = [a for a in alerts if a.key == "temperature"]
    assert len(temp) == 1 and temp[0].level == Level.CAUTION
    assert temp[0].basis == "current" and temp[0].status == "active" and temp[0].official is False
    assert "model estimate" in temp[0].explanation and temp[0].rule and temp[0].advice


def test_current_alert_boundary_just_below_threshold():
    alerts = ae.evaluate_current_alerts(current_weather(temperature_2m=37.99, apparent_temperature=20, wind_gusts_10m=5), None, T, "now")
    temp = [a for a in alerts if a.key == "temperature"]
    assert len(temp) == 1 and temp[0].level == Level.INFO          # 37.99 < 38 (Caution) but >= 35 (Information)


def test_current_alerts_skip_missing_values_and_missing_providers():
    w = current_weather(temperature_2m=None, apparent_temperature=None, wind_gusts_10m=None)
    assert ae.evaluate_current_alerts(w, None, T, "now") == []
    assert ae.evaluate_current_alerts(None, None, T, "now") == []


def test_current_air_quality_alert_only_when_air_available():
    a = air()
    a.current["us_aqi"] = 160
    alerts = ae.evaluate_current_alerts(None, a, T, "now")
    assert [x.key for x in alerts] == ["air_quality"] and alerts[0].level == Level.HIGH and "not the Indian CPCB" in alerts[0].explanation


def test_conflicting_conditions_all_reported_most_severe_first():
    raw = raw_weather()
    raw["daily"]["temperature_2m_max"][0] = 41.0          # HIGH heat on day 0
    raw["daily"]["precipitation_sum"][0] = 20.0           # only INFO rain on the same day
    w = ds.parse_weather(raw, LOC, is_sample=True)
    alerts = ae.evaluate_alerts(w)
    day0 = [a for a in alerts if a.when.startswith("Tue 20 Oct") and a.key in ("temperature", "rain")]
    assert {a.key: a.level for a in day0} == {"temperature": Level.HIGH, "rain": Level.INFO}
    assert alerts.index(next(a for a in day0 if a.key == "temperature")) < alerts.index(next(a for a in day0 if a.key == "rain"))
    assert ae.highest_level(alerts) == Level.HIGH


def test_duplicate_forecast_rows_do_not_create_duplicate_alerts():
    raw = raw_weather()
    for column, values in raw["daily"].items():            # repeat day 0 as a malformed duplicate row
        values.insert(1, values[0])
    w = ds.parse_weather(raw, LOC, is_sample=True)
    assert len(w.daily) == 7                                # duplicate timestamp dropped at parse time
    temp_day0 = [a for a in ae.evaluate_alerts(w) if a.key == "temperature" and a.when.startswith("Tue 20 Oct")]
    assert len(temp_day0) == 1


def test_dedupe_alerts_removes_identical_repeats():
    alerts = ae.evaluate_alerts(sd.load_sample_weather(START))
    assert len(ae.dedupe_alerts(alerts + alerts)) == len(alerts)


def test_unchanged_condition_gives_same_alert_on_reevaluation():
    w = sd.load_sample_weather(START)
    first = [(a.key, a.when, a.level, a.value) for a in ae.evaluate_alerts(w)]
    assert first == [(a.key, a.when, a.level, a.value) for a in ae.evaluate_alerts(w)]


def test_evaluate_alerts_handles_missing_providers():
    assert ae.evaluate_alerts(None, None) == []
    only_air = ae.evaluate_alerts(None, sd.load_sample_air_quality(START))
    assert only_air and all(a.key == "air_quality" for a in only_air)


def test_missing_us_aqi_column_is_safe():
    a = air()
    a.hourly = a.hourly.drop(columns=["us_aqi"])
    assert ae.evaluate_air_quality_alerts(a, T, "now") == []


def test_validate_thresholds_raises_config_error_which_is_a_value_error():
    bad = {k: dict(v) for k, v in T.items()}
    bad["wind_gust_kmh"] = {"info": 80, "caution": 60, "high": 40}
    with pytest.raises(config.ConfigError):
        ae.validate_thresholds(bad)
    with pytest.raises(ValueError):
        ae.evaluate_alerts(sd.load_sample_weather(START), thresholds=bad)
