"""
sample_data.py - OFFLINE DEMO / TEST DATA. *** NOT LIVE DATA ***

These numbers are INVENTED by us so the app can be demonstrated and unit-tested
without internet. They have the same JSON shape as the real Open-Meteo responses.
The app always shows a "SAMPLE DATA" banner when this module is used, so an
audience can never mistake it for a live forecast.
"""
from datetime import date, timedelta

import data_service

SAMPLE_LOCATION = data_service.Location(
    name="Sample City (demo)", latitude=13.08, longitude=80.27,
    country="India", admin1="Tamil Nadu", timezone="Asia/Kolkata")


def _dates(start: date, n: int):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def make_sample_weather_raw(start: date = None) -> dict:
    start = start or date.today()
    n = 7
    days = _dates(start, n)
    hours = [f"{d}T{h:02d}:00" for d in days for h in range(24)]
    daily = {
        "time": days,
        "weather_code": [2, 3, 65, 95, 63, 3, 1],
        "temperature_2m_max": [39.5, 36.0, 30.5, 29.8, 31.0, 34.5, 36.8],
        "temperature_2m_min": [28.0, 27.5, 25.0, 24.8, 25.5, 26.0, 26.5],
        "apparent_temperature_max": [43.0, 40.0, 33.0, 32.0, 34.0, 38.0, 41.5],
        "precipitation_sum": [0.0, 2.0, 72.0, 118.0, 30.0, 4.0, None],   # None = missing value
        "precipitation_probability_max": [5, 20, 85, 95, 70, 25, 10],
        "wind_speed_10m_max": [22.0, 25.0, 38.0, 45.0, 30.0, 20.0, 18.0],
        "wind_gusts_10m_max": [38.0, 45.0, 66.0, 82.0, 52.0, 35.0, 30.0],
        "uv_index_max": [9.5, 8.0, 3.0, 2.5, 4.0, 7.0, 9.0],
    }
    return {
        "timezone": "Asia/Kolkata",
        "current_units": {"temperature_2m": "°C", "relative_humidity_2m": "%",
                          "apparent_temperature": "°C", "wind_speed_10m": "km/h",
                          "wind_gusts_10m": "km/h", "precipitation": "mm"},
        "current": {"time": f"{days[0]}T14:00", "temperature_2m": 34.2,
                    "relative_humidity_2m": 62, "apparent_temperature": 40.1,
                    "precipitation": 0.0, "weather_code": 2,
                    "wind_speed_10m": 14.0, "wind_gusts_10m": 28.0},
        "daily_units": {"temperature_2m_max": "°C", "temperature_2m_min": "°C",
                        "apparent_temperature_max": "°C", "precipitation_sum": "mm",
                        "precipitation_probability_max": "%", "wind_speed_10m_max": "km/h",
                        "wind_gusts_10m_max": "km/h", "uv_index_max": ""},
        "daily": daily,
        "hourly_units": {"temperature_2m": "°C", "apparent_temperature": "°C", "precipitation": "mm",
                         "precipitation_probability": "%", "wind_speed_10m": "km/h", "wind_gusts_10m": "km/h"},
        "hourly": _sample_hourly(hours, daily),
    }


def _sample_hourly(hours, d) -> dict:
    """INVENTED hourly curves built from the invented daily values (so hourly and daily agree)."""
    import math
    out = {"time": hours, "temperature_2m": [], "apparent_temperature": [], "precipitation": [],
           "precipitation_probability": [], "wind_speed_10m": [], "wind_gusts_10m": []}
    for i in range(len(hours)):
        day, hour = divmod(i, 24)
        shape = max(0.0, math.sin(math.pi * (hour - 6) / 16)) if 6 <= hour <= 22 else 0.0   # peaks at 14:00
        temp = d["temperature_2m_min"][day] + (d["temperature_2m_max"][day] - d["temperature_2m_min"][day]) * shape
        out["temperature_2m"].append(round(temp, 1))
        out["apparent_temperature"].append(round(temp + (d["apparent_temperature_max"][day] - d["temperature_2m_max"][day]) * shape, 1))
        total, rainy_hour = d["precipitation_sum"][day], 16 <= hour <= 21
        out["precipitation"].append(None if total is None else (round(total / 6, 2) if rainy_hour else 0.0))
        pmax = d["precipitation_probability_max"][day]
        out["precipitation_probability"].append(pmax if rainy_hour else max(5, round(pmax * 0.3)))
        out["wind_speed_10m"].append(round(d["wind_speed_10m_max"][day] * (0.5 + 0.5 * shape), 1))
        out["wind_gusts_10m"].append(round(d["wind_gusts_10m_max"][day] * (0.55 + 0.45 * shape), 1))
    return out


def make_sample_air_raw(start: date = None) -> dict:
    start = start or date.today()
    n = 5
    days = _dates(start, n)
    hours = [f"{d}T{h:02d}:00" for d in days for h in range(24)]
    base = [60, 85, 120, 165, 90]            # invented daily AQI levels
    us_aqi, eu_aqi, pm25, pm10 = [], [], [], []
    for i, _ in enumerate(hours):
        d = i // 24
        wave = 15 if 6 <= (i % 24) <= 10 else 0   # morning "peak" in the invented data
        us_aqi.append(base[d] + wave)
        eu_aqi.append((base[d] + wave) * 0.6)
        pm25.append((base[d] + wave) * 0.4)
        pm10.append((base[d] + wave) * 0.8)
    return {
        "current_units": {"us_aqi": "USAQI", "european_aqi": "EAQI", "pm10": "μg/m³",
                          "pm2_5": "μg/m³", "carbon_monoxide": "μg/m³",
                          "nitrogen_dioxide": "μg/m³", "sulphur_dioxide": "μg/m³",
                          "ozone": "μg/m³"},
        "current": {"time": f"{days[0]}T14:00", "us_aqi": 72, "european_aqi": 45,
                    "pm10": 58.0, "pm2_5": 27.0, "carbon_monoxide": 310.0,
                    "nitrogen_dioxide": 22.0, "sulphur_dioxide": 9.0, "ozone": 71.0},
        "hourly_units": {"pm10": "μg/m³", "pm2_5": "μg/m³", "us_aqi": "USAQI", "european_aqi": "EAQI"},
        "hourly": {"time": hours, "pm10": pm10, "pm2_5": pm25,
                   "us_aqi": us_aqi, "european_aqi": eu_aqi},
    }


def load_sample_weather(start: date = None):
    return data_service.parse_weather(make_sample_weather_raw(start), SAMPLE_LOCATION, is_sample=True)


def load_sample_air_quality(start: date = None):
    return data_service.parse_air_quality(make_sample_air_raw(start), SAMPLE_LOCATION, is_sample=True)
