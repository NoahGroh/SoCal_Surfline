"""Forecast data fetchers: Open-Meteo Marine, Open-Meteo Weather, NOAA Tides.

All three are free, keyless, and explicitly allow this kind of use.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime
from zoneinfo import ZoneInfo
import httpx

TZ = ZoneInfo("America/Los_Angeles")
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
TIDES_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

HTTP_TIMEOUT = 15.0


def _resolve_date(date_str: str | None) -> date_cls:
    if date_str:
        return date_cls.fromisoformat(date_str)
    return datetime.now(TZ).date()


def current_session_pt() -> str:
    """Map current PT time to a named session: dawn / midday / sunset."""
    hr = datetime.now(TZ).hour
    if hr < 11: return "dawn"
    if hr < 15: return "midday"
    return "sunset"


def current_hour_pt() -> int:
    """Current hour-of-day in Pacific time."""
    return datetime.now(TZ).hour


def now_pt() -> datetime:
    """Current datetime in Pacific time."""
    return datetime.now(TZ)


async def fetch_marine(lat: float, lon: float, target_date: date_cls) -> dict:
    """Hourly wave + sea-surface-temp data for the target date in PT."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "wave_height",
            "wave_period",
            "wave_direction",
            "swell_wave_height",
            "swell_wave_period",
            "swell_wave_direction",
            "wind_wave_height",
            "wind_wave_period",
            "sea_surface_temperature",
        ]),
        "length_unit": "imperial",   # feet
        "timezone": "America/Los_Angeles",
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(MARINE_URL, params=params)
        r.raise_for_status()
        return r.json()


async def fetch_wind(lat: float, lon: float, target_date: date_cls) -> dict:
    """Hourly wind speed/direction (knots) for the target date in PT."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wind_speed_10m,wind_direction_10m,temperature_2m",
        "wind_speed_unit": "kn",
        "temperature_unit": "fahrenheit",
        "timezone": "America/Los_Angeles",
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(WEATHER_URL, params=params)
        r.raise_for_status()
        return r.json()


async def fetch_tides(station: str, target_date: date_cls) -> list[dict]:
    """High/low tide events for the date at the given NOAA station."""
    params = {
        "product": "predictions",
        "station": station,
        "begin_date": target_date.strftime("%Y%m%d"),
        "end_date": target_date.strftime("%Y%m%d"),
        "datum": "MLLW",
        "units": "english",       # feet
        "time_zone": "lst_ldt",   # local standard / daylight
        "format": "json",
        "interval": "hilo",       # only high/low events
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(TIDES_URL, params=params)
        r.raise_for_status()
        data = r.json()

    events = []
    for p in data.get("predictions", []):
        events.append({
            "time": p["t"],                             # "YYYY-MM-DD HH:MM"
            "height_ft": round(float(p["v"]), 2),
            "type": "high" if p["type"] == "H" else "low",
        })
    return events


async def fetch_sun(lat: float, lon: float, target_date: date_cls) -> dict:
    """Sunrise/sunset for the spot — used to pick the dawn-patrol window."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "sunrise,sunset",
        "timezone": "America/Los_Angeles",
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(WEATHER_URL, params=params)
        r.raise_for_status()
        data = r.json()

    daily = data.get("daily", {})
    return {
        "sunrise": daily.get("sunrise", [None])[0],
        "sunset": daily.get("sunset", [None])[0],
    }
