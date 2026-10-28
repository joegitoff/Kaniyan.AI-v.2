"""
config.py - central settings for Kaniyan.AI.

Python concepts: constants, dictionaries, enums (IntEnum), module-level configuration.

IMPORTANT: The thresholds below are ILLUSTRATIVE values chosen for a student
project. They are loosely inspired by commonly published categories (for example
IMD daily-rainfall classes and the US EPA AQI bands) but they are NOT official
warning criteria. Always follow official advisories (IMD, state disaster
management authorities, CPCB) for real decisions.
"""
import math
from enum import IntEnum


class Level(IntEnum):
    """Warning levels. IntEnum lets us sort and compare levels (HIGH > CAUTION)."""
    INFO = 1
    CAUTION = 2
    HIGH = 3

    @property
    def label(self) -> str:
        return {1: "Information", 2: "Caution", 3: "High concern"}[int(self)]


LEVEL_DEFINITIONS = {
    Level.INFO: "A value is above a normal/comfortable range. Be aware; no action usually needed.",
    Level.CAUTION: "A value is high enough that sensitive people or outdoor plans may need precautions.",
    Level.HIGH: "A value is very high on our scale. Take precautions and check official sources.",
}

# --- Data-source endpoints (verified against Open-Meteo documentation) --------
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
REQUEST_TIMEOUT_SECONDS = 10

FORECAST_DAYS = 7          # weather: API supports up to 16
AIR_QUALITY_DAYS = 5       # air quality: API default is 5, maximum 7

DEFAULT_CITY = "Chennai"
QUICK_CITIES = ["Chennai", "Thanjavur", "Madurai", "Coimbatore", "Tiruchirappalli",
                "Salem", "Tirunelveli", "Vellore", "Bengaluru", "Mumbai", "Delhi"]

# --- Alert thresholds (illustrative, editable from the app sidebar) ----------
# Each rule has three cut-offs. A value >= cut-off triggers that level.
DEFAULT_THRESHOLDS = {
    "rain_daily_mm":    {"info": 15.6, "caution": 64.5, "high": 115.6},   # mm per day
    "temp_max_c":       {"info": 35.0, "caution": 38.0, "high": 40.0},    # deg C
    "feels_like_max_c": {"info": 38.0, "caution": 41.0, "high": 46.0},    # deg C
    "wind_gust_kmh":    {"info": 40.0, "caution": 60.0, "high": 80.0},    # km/h
    "us_aqi":           {"info": 51.0, "caution": 101.0, "high": 151.0},  # US AQI scale
}

THRESHOLD_LABELS = {
    "rain_daily_mm": "Daily rainfall total (mm)",
    "temp_max_c": "Daily maximum temperature (°C)",
    "feels_like_max_c": "Daily maximum 'feels-like' temperature (°C)",
    "wind_gust_kmh": "Daily maximum wind gust (km/h)",
    "us_aqi": "Air quality index (US AQI scale)",
}

THRESHOLD_NOTE = (
    "Thresholds are illustrative and editable. They are not official warning criteria. "
    "AQI is on the US AQI scale as computed by the Open-Meteo/CAMS model - it is not the "
    "Indian CPCB National AQI and not a ground-station reading."
)

# WMO weather interpretation codes (copied from the Open-Meteo documentation)
WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snowfall", 73: "Moderate snowfall", 75: "Heavy snowfall", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 97: "Heavy thunderstorm",
    99: "Thunderstorm with heavy hail",
}

# US AQI category bands (as documented by Open-Meteo)
US_AQI_BANDS = [
    (50, "Good"), (100, "Moderate"), (150, "Unhealthy for sensitive groups"),
    (200, "Unhealthy"), (300, "Very unhealthy"), (500, "Hazardous"),
]

ATTRIBUTION = (
    "Weather data: Open-Meteo.com (CC BY 4.0), combining national weather-service models. "
    "Air quality: Open-Meteo Air Quality API using CAMS (Copernicus Atmosphere Monitoring "
    "Service) model data. Locations: GeoNames via the Open-Meteo Geocoding API. "
    "Open-Meteo's free API is for non-commercial use."
)


# =============================================================================
# Reliability, caching and data-validation settings (added in v2)
# =============================================================================
MAX_RETRIES = 2                    # extra attempts after the first, only for timeouts / connection errors / HTTP 5xx
RETRY_BACKOFF_SECONDS = 0.5        # waits 0.5 s, then 1 s (doubles each time)
CACHE_TTL_SECONDS = 600            # data younger than this is shown as "Live (updated N min ago)"
MIN_REFRESH_INTERVAL_SECONDS = 60  # manual-refresh button cooldown, protects the free API quota

FORECAST_WINDOW_HOURS = 24         # length of the hourly risk timeline
# UNVALIDATED, configurable: a rain probability at/above this is called "a high chance of rain" in
# recommendations. It is NOT an official criterion and does not create an alert by itself.
RAIN_PROB_NOTABLE_PERCENT = 60.0

# Values outside these (min, max) ranges are physically implausible and are ignored (treated as missing).
PLAUSIBLE_RANGES = {
    "temperature_2m": (-90, 60), "apparent_temperature": (-100, 70),
    "temperature_2m_max": (-90, 60), "temperature_2m_min": (-90, 60),
    "apparent_temperature_max": (-100, 70), "relative_humidity_2m": (0, 100),
    "precipitation": (0, 500), "precipitation_sum": (0, 2000),
    "precipitation_probability": (0, 100), "precipitation_probability_max": (0, 100),
    "wind_speed_10m": (0, 400), "wind_gusts_10m": (0, 500),
    "wind_speed_10m_max": (0, 400), "wind_gusts_10m_max": (0, 500),
    "us_aqi": (0, 1000), "european_aqi": (0, 1000), "pm2_5": (0, 5000), "pm10": (0, 5000),
    "uv_index_max": (0, 25),
}

# --- Threshold validation -----------------------------------------------------
# (min, max) allowed for every cut-off of a rule. Guard-rails against typos, not health limits.
THRESHOLD_LIMITS = {
    "rain_daily_mm": (0.0, 1000.0), "temp_max_c": (-50.0, 60.0), "feels_like_max_c": (-50.0, 70.0),
    "wind_gust_kmh": (0.0, 400.0), "us_aqi": (0.0, 500.0),
}

# What each threshold means. "validation" says how far the default values are backed by a published scale.
THRESHOLD_DOCS = {
    "rain_daily_mm": {"unit": "mm per 24 h", "meaning": "Forecast rainfall total for a day (or the running total inside the 24-hour window).",
                      "validation": "Defaults equal the lower bounds of IMD's moderate / heavy / very-heavy 24-h rainfall classes "
                                    "(as recalled by the authors; not re-verified online). Rainfall amount only - not a flood predictor."},
    "temp_max_c": {"unit": "deg C", "meaning": "Air temperature at or above which an alert level starts.",
                   "validation": "Illustrative / unvalidated student values."},
    "feels_like_max_c": {"unit": "deg C", "meaning": "'Feels-like' (apparent) temperature including humidity and wind.",
                         "validation": "Illustrative / unvalidated student values."},
    "wind_gust_kmh": {"unit": "km/h", "meaning": "Wind gust speed at 10 m height.",
                      "validation": "Illustrative / unvalidated student values."},
    "us_aqi": {"unit": "US AQI", "meaning": "US AQI (model) at which each level starts.",
               "validation": "Defaults equal the lower bounds of the US EPA 'Moderate', 'Unhealthy for sensitive groups' "
                             "and 'Unhealthy' bands. This is NOT the Indian CPCB scale."},
}


class ConfigError(ValueError):
    """Invalid configuration. `.problems` lists every individual problem found."""
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def validate_thresholds(thresholds) -> None:
    """Raise ConfigError (a ValueError) listing ALL problems; never repairs values silently."""
    if not isinstance(thresholds, dict):
        raise ConfigError(["Thresholds must be a dictionary of rules."])
    problems = [f"Missing rule '{name}'." for name in DEFAULT_THRESHOLDS if name not in thresholds]
    for name, cut in thresholds.items():
        if name not in THRESHOLD_LIMITS:
            problems.append(f"Unknown rule '{name}'.")
            continue
        label = THRESHOLD_LABELS.get(name, name)
        if not isinstance(cut, dict) or set(cut) != {"info", "caution", "high"}:
            problems.append(f"{label}: needs exactly the cut-offs info, caution and high.")
            continue
        lo, hi = THRESHOLD_LIMITS[name]
        values, ok = {}, True
        for level in ("info", "caution", "high"):
            v = cut[level]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                problems.append(f"{label}: '{level}' must be a finite number.")
                ok = False
            elif not lo <= v <= hi:
                problems.append(f"{label}: '{level}' = {v:g} is outside the allowed range {lo:g} to {hi:g}.")
                ok = False
            else:
                values[level] = v
        if ok and not (values["info"] < values["caution"] < values["high"]):
            problems.append(f"{label}: cut-offs must increase strictly (info < caution < high); "
                            f"got {values['info']:g} / {values['caution']:g} / {values['high']:g}.")
    if problems:
        raise ConfigError(problems)


# --- Activities (optional personalisation; no personal data is collected) ----------
ACTIVITIES = {
    "general": "General daily planning",
    "travel": "Travelling or commuting",
    "outdoor_work": "Outdoor work",
    "exercise": "Walking or exercising",
    "school": "School or college activities",
}
DEFAULT_ACTIVITY = "general"

# --- AI limits ---------------------------------------------------------------------
MAX_QUESTION_CHARS = 600
MAX_ANSWER_CHARS = 2500
