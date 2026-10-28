"""
activity_advice.py - personalised precautions (RECOMMENDATION layer).

Risk DETECTION lives in alert_engine.py / timeline.py. This module only turns already-detected
conditions into advice, using fixed readable rules (no AI, no personal data, no medical claims).
Every recommendation records WHICH condition triggered it and WHEN, so it can be traced.

Modes: 'general' (default) uses the generic precautions from recommendations.py. Any other activity
adds an activity-specific tip first. Activity tips apply from 'Caution' upward; 'Information' items
only get the short generic tip.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import config
from config import Level
from recommendations import get_advice
import timeline

# {activity: {hazard: {"caution": tip, "high": tip}}}; "high" falls back to "caution" when absent.
_HEAT_TRAVEL = {"caution": "Carry drinking water for the journey, and never leave children or pets in a parked vehicle.",
                "high": "If you can, travel outside the hottest hours and plan rest stops in shade or cooled places."}
_HEAT_WORK = {"caution": "Schedule heavy tasks for cooler hours, take regular water breaks in shade, and watch co-workers for signs of heat strain.",
              "high": "Consider reducing or rescheduling strenuous outdoor work; make sure shade, drinking water and a way to call for help are available."}
_HEAT_EXERCISE = {"caution": "Prefer shorter, easier sessions, carry water and choose shaded routes.",
                  "high": "Consider moving exercise indoors or postponing hard efforts."}
_HEAT_SCHOOL = {"caution": "Encourage water breaks and shade during outdoor classes, assemblies and sports.",
                "high": "Consider moving sports and assemblies indoors or to cooler hours."}

ACTIVITY_TIPS = {
    "travel": {
        "temperature": _HEAT_TRAVEL, "feels_like": _HEAT_TRAVEL,
        "rain": {"caution": "Allow extra travel time and check local road and transport updates before leaving.",
                 "high": "Avoid driving or walking through flowing or standing water; consider delaying non-essential trips."},
        "wind": {"caution": "Take extra care on two-wheelers and open roads, and check for transport notices.",
                 "high": "Consider postponing two-wheeler or long-distance trips; do not park under trees or hoardings."},
        "air_quality": {"caution": "Limit time spent walking along heavy-traffic roads where you can.",
                        "high": "Sensitive travellers may want to keep outdoor waiting time short and carry any prescribed medicines."},
    },
    "outdoor_work": {
        "temperature": _HEAT_WORK, "feels_like": _HEAT_WORK,
        "rain": {"caution": "Check site drainage and secure materials and electrical equipment before the expected rain.",
                 "high": "Consider pausing work at exposed or low-lying sites; avoid slippery surfaces and water flow."},
        "wind": {"caution": "Secure loose materials and take extra care when working at height or near signboards.",
                 "high": "Consider postponing work at height and avoid working beneath trees or hoardings."},
        "air_quality": {"caution": "Take breaks away from dust or fume sources where possible.",
                        "high": "Consider reducing prolonged strenuous outdoor work; follow any workplace guidance on masks."},
    },
    "exercise": {
        "temperature": _HEAT_EXERCISE, "feels_like": _HEAT_EXERCISE,
        "rain": {"caution": "Wear grippy footwear, avoid slippery surfaces and carry a light rain layer.",
                 "high": "Consider an indoor alternative and avoid flooded paths or flowing water."},
        "wind": {"caution": "Avoid exposed routes with trees, loose roofing or hoardings overhead.",
                 "high": "Consider exercising indoors."},
        "air_quality": {"caution": "People with asthma or heart/lung conditions may prefer lighter activity or an indoor option.",
                        "high": "Consider reducing prolonged strenuous outdoor exercise; an indoor option is available."},
    },
    "school": {
        "temperature": _HEAT_SCHOOL, "feels_like": _HEAT_SCHOOL,
        "rain": {"caution": "Plan for wet arrival and dismissal, and check for school or local notices.",
                 "high": "Check school and local authority notices before travel and avoid flooded routes."},
        "wind": {"caution": "Keep outdoor activities away from trees, hoardings and loose structures.",
                 "high": "Consider holding activities indoors."},
        "air_quality": {"caution": "Consider shortening outdoor activities, especially for children with asthma.",
                        "high": "Consider holding outdoor sports and assemblies indoors."},
    },
}

RAIN_CHANCE_TIPS = {
    "general": "Consider carrying rain protection and checking local weather updates.",
    "travel": "Allow extra travel time and check local weather updates before leaving.",
    "outdoor_work": "Plan for interruptions and secure materials and equipment.",
    "exercise": "Consider an indoor alternative, or carry a light rain layer.",
    "school": "Plan for wet arrival and dismissal and carry rain gear.",
}


@dataclass
class Recommendation:
    text: str
    hazard: str            # same keys as alerts: temperature, feels_like, rain, wind, air_quality
    level: Optional[Level]  # None for a rain-chance tip (no threshold level)
    trigger: str           # what condition caused this advice (traceability)
    timing: str            # "now" and/or the forecast hours
    activity: str
    kind: str              # "activity" or "general"


@dataclass
class RecommendationSet:
    activity: str
    items: list = field(default_factory=list)
    notes: list = field(default_factory=list)       # uncertainty / missing data
    quiet_note: str = ""

    def as_dicts(self) -> list:
        return [{"advice": r.text, "because": r.trigger, "timing": r.timing} for r in self.items]


def _collect(current_alerts, events, window) -> dict:
    """hazard key -> list of (level, trigger text, timing text)."""
    found: dict = {}
    for a in current_alerts:
        found.setdefault(a.key, []).append((a.level, f"{a.variable} {a.value:g} {a.unit}: {a.rule} [current conditions, model estimate]", "now"))
    for e in events:
        span = timeline.event_span_text(e, window)
        found.setdefault(e.key, []).append((e.level, f"{e.rule}; forecast peak {e.peak_value:.1f} {e.unit} [forecast]", f"forecast {span}"))
    return found


def generate_recommendations(activity: str, current_alerts: list, events: list, window, chance: list,
                             quiet: Optional[tuple] = None) -> RecommendationSet:
    """Build recommendations for the chosen activity. Unknown activity names fall back to 'general'."""
    if activity not in config.ACTIVITIES:
        activity = config.DEFAULT_ACTIVITY
    result = RecommendationSet(activity=activity)
    found = _collect(current_alerts, events, window)
    seen_text = set()

    def add(text, hazard, level, trigger, timing, kind):
        if text not in seen_text:
            seen_text.add(text)
            result.items.append(Recommendation(text, hazard, level, trigger, timing, activity, kind))

    for hazard, records in sorted(found.items(), key=lambda kv: -max(int(r[0]) for r in kv[1])):
        level = max((r[0] for r in records), key=int)
        best = max(records, key=lambda r: int(r[0]))
        timing = "; ".join(dict.fromkeys(r[2] for r in records))
        if activity != "general" and level >= Level.CAUTION:
            tips = ACTIVITY_TIPS.get(activity, {}).get(hazard, {})
            tip = tips.get("high" if level == Level.HIGH else "caution") or tips.get("caution")
            if tip:
                add(tip, hazard, level, best[1], timing, "activity")
        base = get_advice(hazard, level)
        for tip in (base[:1] if activity != "general" else base[:2]):
            add(tip, hazard, level, best[1], timing, "general")

    for c in chance:   # high rain PROBABILITY (not an amount rule)
        if "rain" in found and any(i.hazard == "rain" for i in result.items):
            break
        end = "the end of the window" if c.continues_past_window else timeline.fmt_time(c.end, window.start)
        add(f"A high chance of rain is forecast (up to {c.peak_probability:.0f}%) between "
            f"{timeline.fmt_time(c.start, window.start)} and {end}. " + RAIN_CHANCE_TIPS[activity],
            "rain", None, f"Rain probability >= {config.RAIN_PROB_NOTABLE_PERCENT:g}% [forecast probability, unvalidated cut-off]",
            f"forecast {timeline.fmt_time(c.start, window.start)}-{end}", "activity" if activity != "general" else "general")

    if not result.items:
        result.items.append(Recommendation(
            "No configured rule is triggered for the data available. Forecasts change, so re-check before travel or outdoor events.",
            "none", None, "No alert threshold crossed", "next 24 hours", activity, "general"))
    result.items.sort(key=lambda r: -(int(r.level) if r.level else 1))

    # Uncertainty: say what could NOT be checked
    if window is None:
        result.notes.append("No hourly forecast is available, so only current-condition alerts were used.")
    else:
        if not window.air_available:
            result.notes.append("Air-quality forecast data are unavailable, so no air-quality precautions could be generated.")
        if not window.rain_probability_available:
            result.notes.append("Rain-probability data are unavailable, so 'chance of rain' advice could not be generated.")
        if any(n and window.available.get(c) for c, n in window.missing_hours.items()):
            result.notes.append("Some forecast hours are missing; advice may not cover those hours.")

    # A lower-risk period is mentioned only when the hourly forecast supports it (activity modes only)
    serious = any(i.level and i.level >= Level.CAUTION for i in result.items)
    if activity != "general" and serious and quiet and quiet[0]:
        periods, checked, skipped = quiet
        spans = ", ".join(f"{timeline.fmt_time(a, window.start)}-{timeline.fmt_time(b, window.start)}" for a, b in periods[:3])
        result.quiet_note = (f"Hours with no Caution or High-concern alert in the hourly forecast: {spans}. Factors checked: "
                             + ", ".join(checked) + (f". Not checked (no data): {', '.join(skipped)}" if skipped else "")
                             + ". This is not a safety guarantee; forecasts can change.")
    return result
