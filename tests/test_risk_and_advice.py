"""Overall risk classification and the activity-recommendation rules."""
import pandas as pd
import pytest

import activity_advice as aa
import alert_engine as ae
import config
import timeline as tl
from config import Level
from helpers import CALM, NOW_UTC, air, series, weather
from risk import Contribution, RiskCategory, classify_overall

T = config.DEFAULT_THRESHOLDS
t0 = pd.Timestamp("2026-10-20 14:00")


def c(key, level, start=0, end=2, **kw):
    return Contribution(key, key, level, "forecast", "x", start=t0 + pd.Timedelta(hours=start), end=t0 + pd.Timedelta(hours=end), **kw)


# --------------------------------------------------------------------- risk --
def test_no_alerts_is_low_and_says_why():
    r = classify_overall([])
    assert r.category == RiskCategory.LOW and r.reasons and r.recommendation and "NOT an official" in r.disclaimer


@pytest.mark.parametrize("levels,expected", [
    ([Level.INFO], RiskCategory.LOW), ([Level.INFO, Level.CAUTION], RiskCategory.MODERATE),
    ([Level.CAUTION], RiskCategory.MODERATE), ([Level.HIGH], RiskCategory.HIGH),
    ([Level.CAUTION, Level.HIGH, Level.INFO], RiskCategory.HIGH)])
def test_category_follows_highest_single_level(levels, expected):
    assert classify_overall([c("rain", lv) for lv in levels]).category == expected


def test_many_cautions_are_not_added_up():
    many = [c(k, Level.CAUTION) for k in ("temperature", "rain", "wind", "air_quality")]
    assert classify_overall(many).category == RiskCategory.MODERATE


def test_very_high_needs_two_different_hazards_overlapping():
    assert classify_overall([c("rain", Level.HIGH), c("wind", Level.HIGH)]).category == RiskCategory.VERY_HIGH


def test_heat_measures_count_as_one_hazard():
    assert classify_overall([c("temperature", Level.HIGH), c("feels_like", Level.HIGH)]).category == RiskCategory.HIGH


def test_non_overlapping_high_alerts_stay_high():
    assert classify_overall([c("rain", Level.HIGH, 0, 2), c("wind", Level.HIGH, 5, 7)]).category == RiskCategory.HIGH


def test_unknown_timing_is_treated_conservatively():
    a, b = Contribution("rain", "rain", Level.HIGH, "current", "now"), Contribution("wind", "wind", Level.HIGH, "current", "now")
    assert classify_overall([a, b]).category == RiskCategory.VERY_HIGH


def test_contributors_listed_most_severe_first():
    r = classify_overall([c("rain", Level.INFO), c("wind", Level.HIGH)])
    assert r.contributors[0].key == "wind" and any("wind" in x for x in r.reasons)


# ------------------------------------------------------------ recommendations --
def build(activity, **hourly):
    wx = weather(**{**CALM, **hourly})
    wx.current.update(temperature_2m=26.0, apparent_temperature=27.0, wind_gusts_10m=15.0)   # calm right now
    w = tl.build_window(wx, None, T, now_utc=NOW_UTC)
    cur = ae.evaluate_current_alerts(wx, None, T, "now")
    return aa.generate_recommendations(activity, cur, tl.find_events(w, T), w, tl.rain_chance_periods(w), tl.quiet_periods(w))


HEAT = dict(temperature_2m=series(26.0, h15=39.0, h16=39.5, h17=39.0))


def test_general_mode_uses_generic_advice_with_traceability():
    rec = build("general", **HEAT)
    assert rec.items and all(r.kind == "general" for r in rec.items)
    top = rec.items[0]
    assert "38" in top.trigger and "forecast" in top.trigger and "15:00" in top.timing and top.hazard in ("temperature", "feels_like")


@pytest.mark.parametrize("activity", ["travel", "outdoor_work", "exercise", "school"])
def test_each_activity_gets_its_own_tip_for_the_same_condition(activity):
    texts = {r.text for r in build(activity, **HEAT).items if r.kind == "activity"}
    assert texts and texts.isdisjoint({r.text for r in build("general", **HEAT).items})


def test_activity_tips_differ_between_activities():
    assert len({tuple(sorted(r.text for r in build(a, **HEAT).items)) for a in ("travel", "outdoor_work", "exercise", "school")}) == 4


def test_unknown_activity_falls_back_to_general():
    assert build("skydiving", **HEAT).activity == "general"


def test_high_level_uses_high_variant():
    rec = build("outdoor_work", temperature_2m=series(26.0, h16=41.0))
    assert any("rescheduling strenuous" in r.text for r in rec.items)


def test_no_alerts_gives_a_neutral_recommendation():
    rec = build("general")
    assert len(rec.items) == 1 and rec.items[0].hazard == "none" and "re-check" in rec.items[0].text


def test_high_rain_probability_alone_gives_rain_chance_advice_without_certainty():
    rec = build("travel", precipitation_probability=series(10, h18=80, h19=85))
    item = next(r for r in rec.items if r.hazard == "rain")
    assert "chance" in item.text and "extra travel time" in item.text and "will rain" not in item.text.lower()
    assert "unvalidated" in item.trigger


def test_missing_air_and_probability_data_produce_uncertainty_notes():
    notes = " ".join(build("general", precipitation_probability=[None] * 168).notes)
    assert "Air-quality" in notes and "Rain-probability" in notes


def test_no_window_gives_note_and_still_works():
    rec = aa.generate_recommendations("general", [], [], None, [], None)
    assert any("No hourly forecast" in n for n in rec.notes) and rec.items


def test_lower_risk_hours_only_for_activity_modes_with_a_real_basis():
    assert "no Caution or High-concern alert".lower() in build("exercise", **HEAT).quiet_note.lower()
    assert "not a safety guarantee" in build("exercise", **HEAT).quiet_note
    assert build("general", **HEAT).quiet_note == ""                 # general mode: no 'safe time' claims
    assert build("exercise").quiet_note == ""                         # nothing serious -> nothing to avoid


def test_missing_hours_are_not_offered_as_lower_risk_hours():
    temps = series(39.0)                                              # Caution all day, every hour
    assert build("exercise", temperature_2m=temps).quiet_note == ""


def test_air_quality_advice_comes_from_air_alerts_and_is_traceable():
    a = air()
    a.current["us_aqi"] = 160
    cur = ae.evaluate_current_alerts(None, a, T, "now")
    rec = aa.generate_recommendations("exercise", cur, [], None, [], None)
    item = next(r for r in rec.items if r.hazard == "air_quality")
    assert "US AQI" in item.trigger and item.timing == "now" and item.kind in ("activity", "general")


def test_no_unsupported_medical_claims_in_any_activity_tip():
    import re
    banned = re.compile(r"\b(cure|cures|treat|treats|treatment|diagnos\w*|prevent disease|guarantee\w*|completely safe)\b")
    texts = [t.lower() for acts in aa.ACTIVITY_TIPS.values() for hz in acts.values() for t in hz.values()] + \
            [t.lower() for t in aa.RAIN_CHANCE_TIPS.values()]
    assert not [t for t in texts if banned.search(t)]
