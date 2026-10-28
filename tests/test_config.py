"""Configuration validation: invalid values are reported, never silently repaired."""
import copy
import math

import pytest

import config


def thr(**changes):
    t = copy.deepcopy(config.DEFAULT_THRESHOLDS)
    t.update(changes)
    return t


def test_default_thresholds_are_valid():
    config.validate_thresholds(config.DEFAULT_THRESHOLDS)


@pytest.mark.parametrize("bad", [
    {"info": 100, "caution": 50, "high": 150},        # decreasing
    {"info": 50, "caution": 50, "high": 150},         # equal -> a level could never trigger
    {"info": 10, "caution": 20, "high": 20},
])
def test_cutoffs_must_increase_strictly(bad):
    with pytest.raises(config.ConfigError) as info:
        config.validate_thresholds(thr(us_aqi=bad))
    assert "increase strictly" in str(info.value)


@pytest.mark.parametrize("value", [-1, 501, 10_000])
def test_out_of_range_rejected(value):
    with pytest.raises(config.ConfigError) as info:
        config.validate_thresholds(thr(us_aqi={"info": value, "caution": 600, "high": 700}))
    assert "outside the allowed range" in str(info.value)


@pytest.mark.parametrize("value", [None, "50", float("nan"), math.inf, True])
def test_non_numeric_values_rejected(value):
    with pytest.raises(config.ConfigError):
        config.validate_thresholds(thr(us_aqi={"info": value, "caution": 101, "high": 151}))


def test_missing_and_unknown_rules_and_wrong_shape():
    t = thr()
    del t["wind_gust_kmh"]
    t["made_up"] = {"info": 1, "caution": 2, "high": 3}
    t["us_aqi"] = {"info": 1, "caution": 2}
    problems = " | ".join(_problems(t))
    assert "Missing rule 'wind_gust_kmh'" in problems and "Unknown rule 'made_up'" in problems
    assert "exactly the cut-offs" in problems


def test_all_problems_reported_together_and_input_not_modified():
    t = thr(us_aqi={"info": 300, "caution": 200, "high": 100}, temp_max_c={"info": 99, "caution": 100, "high": 101})
    before = copy.deepcopy(t)
    with pytest.raises(config.ConfigError) as info:
        config.validate_thresholds(t)
    assert len(info.value.problems) >= 2
    assert t == before                                  # nothing was silently "fixed"


def test_not_a_dict():
    with pytest.raises(config.ConfigError):
        config.validate_thresholds(None)


def test_every_threshold_is_documented_with_unit_and_limits():
    for key in config.DEFAULT_THRESHOLDS:
        assert key in config.THRESHOLD_DOCS and key in config.THRESHOLD_LIMITS and key in config.THRESHOLD_LABELS
        assert config.THRESHOLD_DOCS[key]["unit"] and config.THRESHOLD_DOCS[key]["validation"]


def _problems(t):
    try:
        config.validate_thresholds(t)
    except config.ConfigError as exc:
        return exc.problems
    return []
