"""
risk.py - overall environmental risk category (Low / Moderate / High / Very High).

This is an APPLICATION-GENERATED classification built from the rule-based alerts. It is not an
official government risk index and not a scientifically validated composite score.

Rules (deliberately simple and conservative):
  * The category follows the HIGHEST single alert level. Alert levels are never added together.
        no alert, or only 'Information' alerts  -> Low
        highest alert is 'Caution'              -> Moderate
        highest alert is 'High concern'         -> High
  * 'Very High' needs 'High concern' in TWO DIFFERENT hazard groups at overlapping times.
    Heat (air temperature + feels-like) counts as ONE group because they measure the same hazard.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from config import Level


class RiskCategory(IntEnum):
    LOW = 1
    MODERATE = 2
    HIGH = 3
    VERY_HIGH = 4

    @property
    def label(self) -> str:
        return {1: "Low", 2: "Moderate", 3: "High", 4: "Very High"}[int(self)]


HAZARD_GROUP = {"temperature": "heat", "feels_like": "heat", "rain": "rain", "wind": "wind",
                "air_quality": "air quality"}

CATEGORY_RECOMMENDATION = {
    RiskCategory.LOW: "Conditions are within the configured ranges. Forecasts change, so re-check before travel or outdoor events.",
    RiskCategory.MODERATE: "Some precautions are advisable, especially for outdoor plans, children, older adults and people with health conditions. See the precautions below.",
    RiskCategory.HIGH: "Limit non-essential outdoor exposure where you can, follow the precautions below and check official sources (IMD, CPCB, local authorities).",
    RiskCategory.VERY_HIGH: "More than one serious hazard may overlap. Postpone non-essential outdoor activity if possible and follow official advisories.",
}
DISCLAIMER = ("Application-generated classification from simple threshold rules. It is NOT an official "
              "government risk index or warning.")


@dataclass
class Contribution:
    """One alert or forecast event that feeds the overall classification."""
    key: str
    variable: str
    level: Level
    basis: str                       # "current" or "forecast"
    when: str                        # human-readable timing
    detail: str = ""                 # e.g. "peak 43.0 °C, rule >= 41 °C"
    start: Optional[object] = None   # pandas Timestamp; None = unknown timing
    end: Optional[object] = None


@dataclass
class OverallRisk:
    category: RiskCategory
    headline: str
    reasons: list = field(default_factory=list)
    contributors: list = field(default_factory=list)
    recommendation: str = ""
    disclaimer: str = DISCLAIMER
    caveats: list = field(default_factory=list)   # data problems that make the category less certain


def _overlap(a: Contribution, b: Contribution) -> bool:
    """Unknown timing is treated as overlapping (the conservative choice)."""
    if a.start is None or b.start is None:
        return True
    return a.start <= (b.end or b.start) and b.start <= (a.end or a.start)


def _very_high(high_items: list) -> bool:
    for i, first in enumerate(high_items):
        for second in high_items[i + 1:]:
            if HAZARD_GROUP.get(first.key, first.key) != HAZARD_GROUP.get(second.key, second.key) and _overlap(first, second):
                return True
    return False


def classify_overall(contributions: list, scope: str = "current conditions and the next 24 hours") -> OverallRisk:
    """Turn alert contributions into one category with a plain-language explanation."""
    items = [c for c in contributions if c is not None]
    if not items:
        return OverallRisk(RiskCategory.LOW, f"No configured alert rule is triggered for {scope}.",
                           ["No rule was triggered (or the data needed to check it were unavailable)."], [],
                           CATEGORY_RECOMMENDATION[RiskCategory.LOW])
    top = max(int(c.level) for c in items)
    top_items = [c for c in items if int(c.level) == top]
    category = {int(Level.INFO): RiskCategory.LOW, int(Level.CAUTION): RiskCategory.MODERATE,
                int(Level.HIGH): RiskCategory.HIGH}[top]
    reasons = []
    if category == RiskCategory.HIGH and _very_high(top_items):
        category = RiskCategory.VERY_HIGH
        groups = sorted({HAZARD_GROUP.get(c.key, c.key) for c in top_items})
        reasons.append("'High concern' alerts for different hazards (" + ", ".join(groups) + ") overlap in time.")
    top_level = Level(top)
    reasons.append(f"Highest triggered alert level: {top_level.label}.")
    for c in top_items[:4]:
        reasons.append(f"{c.variable} - {c.when}" + (f" ({c.detail})" if c.detail else "") + ".")
    if category == RiskCategory.LOW:
        reasons.append("Only 'Information' level items are active: values are above a comfortable range but "
                       "no action is usually needed.")
    headline = f"{category.label} risk for {scope}"
    ordered = sorted(items, key=lambda c: -int(c.level))
    return OverallRisk(category, headline, reasons, ordered, CATEGORY_RECOMMENDATION[category])
