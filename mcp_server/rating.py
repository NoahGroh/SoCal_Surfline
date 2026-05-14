"""Objective surf-condition labels.

Translates Open-Meteo + NOAA forecast numbers into surfer-readable labels
(face-height range, wind character, swell direction, tide phase). The
verdict on whether a day is GOOD / SKIP / etc. lives in the Poke recipe,
which has the user's profile and can do the fuzzy synthesis better than
any hardcoded weighted-mean ever could.

What this module does:
  - apply per-spot face_factor to deep-water Hs (real shoaling/refraction
    knowledge encoded in spots.yaml)
  - bucket continuous values into surfer-readable labels
  - pick the hour in the session window with the cleanest wind

What it explicitly does not do:
  - compute a numeric 0-100 score (forecast error dwarfs the precision)
  - emit an overall verdict label (that's the recipe's job)
  - apply weights or combine factors (recipe LLM has full context, we don't)
"""
from __future__ import annotations

from datetime import datetime
import math


# We report deep-water significant wave height (Hs) directly. Translating
# Hs → actual face height at the spot involves shoaling/refraction/bathymetry
# physics that varies with swell direction, period, and tide. We don't try
# to fake that with a static per-spot multiplier (those values were guesses).
# The recipe LLM does spot-aware interpretation in prose using spot notes.


# ---------- math helpers ----------

CARDINALS = [
    (0, "N"), (22.5, "NNE"), (45, "NE"), (67.5, "ENE"),
    (90, "E"), (112.5, "ESE"), (135, "SE"), (157.5, "SSE"),
    (180, "S"), (202.5, "SSW"), (225, "SW"), (247.5, "WSW"),
    (270, "W"), (292.5, "WNW"), (315, "NW"), (337.5, "NNW"),
]


def to_cardinal(deg: float | None) -> str | None:
    if deg is None:
        return None
    deg = deg % 360
    nearest = min(CARDINALS, key=lambda c: min(abs(c[0] - deg), 360 - abs(c[0] - deg)))
    return nearest[1]


def _angle_diff(a: float, b: float) -> float:
    d = abs((a - b) % 360)
    return min(d, 360 - d)


def _in_window(deg: float, window: tuple[float, float]) -> bool:
    lo, hi = window
    if lo <= hi:
        return lo <= deg <= hi
    return deg >= lo or deg <= hi


def _distance_outside_window(deg: float, window: tuple[float, float]) -> float:
    if _in_window(deg, window):
        return 0.0
    lo, hi = window
    return min(_angle_diff(deg, lo), _angle_diff(deg, hi))


def _circular_mean(degs: list[float]) -> float:
    if not degs:
        return 0.0
    xs = sum(math.cos(math.radians(d)) for d in degs)
    ys = sum(math.sin(math.radians(d)) for d in degs)
    return math.degrees(math.atan2(ys, xs)) % 360


def _mean(xs: list[float | None], default: float | None = 0.0) -> float | None:
    vals = [x for x in xs if x is not None]
    return sum(vals) / len(vals) if vals else default


def _hour_of(iso_time: str) -> int | None:
    try:
        return datetime.fromisoformat(iso_time).hour
    except (ValueError, TypeError):
        return None


# ---------- label functions (no scores, just labels) ----------

def size_label(face_height_ft: float) -> str:
    if face_height_ft < 0.5:  return "flat"
    if face_height_ft < 1.5:  return "ankle-knee"
    if face_height_ft < 2.5:  return "knee-waist"
    if face_height_ft < 3.5:  return "waist-chest"
    if face_height_ft < 5.0:  return "chest-head"
    if face_height_ft < 7.0:  return "overhead"
    if face_height_ft < 10.0: return "well overhead"
    return "huge / closeout risk"


def period_label(period_s: float) -> str:
    if period_s < 7:  return "windswell / mushy"
    if period_s < 10: return "mid period"
    if period_s < 13: return "clean groundswell"
    return "long-period groundswell"


def direction_label(swell_dir_deg: float, ideal_window: tuple[float, float]) -> str:
    miss = _distance_outside_window(swell_dir_deg, ideal_window)
    if miss == 0:  return "lined up for the spot"
    if miss < 15:  return "just outside ideal window"
    if miss < 30:  return "off-angle, partial energy"
    if miss < 60:  return "wrong direction"
    return "blocked direction"


def wind_label(wind_speed_kt: float, wind_dir_deg: float, beach_orientation_deg: float) -> str:
    """Offshore = wind from land out to sea. Onshore = sea to land."""
    diff_from_offshore = _angle_diff(wind_dir_deg, (beach_orientation_deg + 180) % 360)
    diff_from_onshore = _angle_diff(wind_dir_deg, beach_orientation_deg)

    if wind_speed_kt < 3:
        return "glassy"

    if diff_from_offshore < 45:
        if wind_speed_kt < 10: return "light offshore"
        if wind_speed_kt < 18: return "moderate offshore"
        return "strong offshore (spitty)"

    if diff_from_onshore < 45:
        if wind_speed_kt < 6:  return "light onshore"
        if wind_speed_kt < 12: return "onshore, blown out"
        return "junked"

    if wind_speed_kt < 6:  return "light cross"
    if wind_speed_kt < 12: return "cross / textured"
    return "strong cross"


def tide_label(tide_events: list[dict], tide_pref: str, at_hour: float) -> str:
    """Estimate tide height at `at_hour` via linear interpolation between
    high/low events, label as height + rising/falling + whether it matches
    the spot's preferred window."""
    if not tide_events:
        return "tide unknown"

    events = []
    for e in tide_events:
        try:
            t = datetime.fromisoformat(e["time"].replace(" ", "T"))
            events.append((t.hour + t.minute / 60.0, e["height_ft"]))
        except (ValueError, KeyError):
            continue
    if not events:
        return "tide unknown"

    events.sort()
    prev = next((p for p in reversed(events) if p[0] <= at_hour), None)
    nxt  = next((p for p in events if p[0] > at_hour), None)

    if prev and nxt:
        span = nxt[0] - prev[0]
        frac = (at_hour - prev[0]) / span if span > 0 else 0.5
        height = prev[1] + frac * (nxt[1] - prev[1])
        rising = nxt[1] > prev[1]
    else:
        anchor = prev or nxt
        height = anchor[1]
        rising = nxt is not None

    phase = "rising" if rising else "falling"
    if tide_pref == "any":
        return f"{height:.1f}ft, {phase}"

    pref_match = {
        "low":      height < 1.5,
        "mid_low":  0.5 <= height <= 3.0,
        "mid":      1.0 <= height <= 4.0,
        "mid_high": 2.5 <= height <= 5.5,
        "high":     height > 3.5,
    }.get(tide_pref, True)

    suffix = "" if pref_match else f" — off preferred ({tide_pref})"
    return f"{height:.1f}ft, {phase}{suffix}"


# ---------- wetsuit + session windows ----------

def _wetsuit_for(water_temp_f: float | None) -> str | None:
    if water_temp_f is None:
        return None
    if water_temp_f < 58: return "4/3 + booties"
    if water_temp_f < 62: return "4/3"
    if water_temp_f < 66: return "3/2"
    if water_temp_f < 70: return "springsuit or 2mm top"
    return "trunks"


SESSIONS = {"dawn", "midday", "sunset"}


def _window_range(session: str, sunrise: str | None, sunset: str | None) -> tuple[int, int]:
    """Resolve session → (start_hour, end_hour) Pacific. Dawn = sunrise–11,
    midday = 11–15, sunset = 15–sunset; sunrise/sunset round to the nearest
    mostly-daylight hour. Unknown sessions fall back to dawn."""
    if session == "midday":
        return 11, 15
    if session == "sunset":
        try:
            t = datetime.fromisoformat(sunset)
            return 15, t.hour - (1 if t.minute < 30 else 0)
        except (ValueError, TypeError):
            return 15, 19
    try:
        t = datetime.fromisoformat(sunrise)
        return t.hour + (1 if t.minute >= 30 else 0), 11
    except (ValueError, TypeError):
        return 6, 11


# ---------- aggregation ----------

# Wind ranking from cleanest to junkest, used to pick the best hour.
WIND_RANK = [
    "glassy",
    "light offshore",
    "moderate offshore",
    "light cross",
    "strong offshore (spitty)",
    "cross / textured",
    "light onshore",
    "strong cross",
    "onshore, blown out",
    "junked",
]


def summarize_conditions(spot: dict, marine: dict, wind: dict, tides: list[dict],
                         sunrise: str | None = None, sunset: str | None = None,
                         session: str = "dawn", from_hour: int | None = None) -> dict:
    """Build a labelled snapshot of conditions in the session window.

    Returns numeric values and surfer-readable labels for every factor.
    No overall verdict — the recipe LLM produces that from these inputs
    plus the user's profile.

    If `from_hour` is given, truncate the window start so past hours don't
    influence the snapshot — used for "now" queries.
    """
    hourly = marine.get("hourly", {})
    wind_h = wind.get("hourly", {})
    times = hourly.get("time", [])
    start_hr, end_hr = _window_range(session, sunrise, sunset)
    if from_hour is not None:
        # "now" queries → snapshot of the current hour only, not a forward mean.
        start_hr = end_hr = from_hour

    in_window = []
    for i, t in enumerate(times):
        h = _hour_of(t)
        if h is not None and start_hr <= h <= end_hr:
            in_window.append(i)

    # Use swell_wave_height (clean swell component) instead of wave_height
    # (total Hs including locally-generated wind chop). Surfers care about the
    # rideable swell, not the combined-with-chop number.
    hs_ft     = _mean([hourly["swell_wave_height"][i] for i in in_window])
    period    = _mean([hourly["swell_wave_period"][i] for i in in_window])
    swell_deg = _circular_mean([hourly["swell_wave_direction"][i] for i in in_window
                                if hourly["swell_wave_direction"][i] is not None])
    wind_kt   = _mean([wind_h["wind_speed_10m"][i] for i in in_window])
    wind_deg  = _circular_mean([wind_h["wind_direction_10m"][i] for i in in_window
                                if wind_h["wind_direction_10m"][i] is not None])
    water_temp_c = _mean([hourly["sea_surface_temperature"][i] for i in in_window], default=None)
    air_temp_f   = _mean([wind_h["temperature_2m"][i] for i in in_window], default=None)
    water_temp_f = water_temp_c * 9 / 5 + 32 if water_temp_c is not None else None

    mid_hour = (start_hr + end_hr) / 2

    return {
        "session": session,
        "session_window": {"start_hour": start_hr, "end_hour": end_hr},
        "snapshot": {
            "swell_hs_ft": round(hs_ft, 1),                # deep-water significant wave height
            "swell_hs_label": size_label(hs_ft),           # bucket label for the Hs (NOT spot face)
            "swell_period_s": round(period, 1),
            "swell_period_label": period_label(period),
            "swell_direction_deg": round(swell_deg),
            "swell_direction_cardinal": to_cardinal(swell_deg),
            "swell_direction_label": direction_label(swell_deg, tuple(spot["ideal_swell_deg"])),
            "wind_speed_kt": round(wind_kt, 1),
            "wind_direction_deg": round(wind_deg),
            "wind_direction_cardinal": to_cardinal(wind_deg),
            "wind_label": wind_label(wind_kt, wind_deg, spot["beach_orientation_deg"]),
            "tide_label": tide_label(tides, spot["tide_pref"], at_hour=mid_hour),
            "water_temp_f": round(water_temp_f, 1) if water_temp_f is not None else None,
            "air_temp_f": round(air_temp_f, 1) if air_temp_f is not None else None,
            "wetsuit": _wetsuit_for(water_temp_f),
        },
    }


def find_best_window(marine: dict, wind: dict, tides: list[dict], spot: dict,
                     sunrise: str | None = None, sunset: str | None = None,
                     session: str = "dawn", from_hour: int | None = None) -> dict | None:
    """Pick the hour in the session window with the cleanest wind.

    Wind is the factor that changes hour-to-hour in a session window
    (size and period barely move). Ties broken by earliest hour. If
    `from_hour` is given, only hours from then onwards are considered.
    """
    hourly = marine.get("hourly", {})
    wind_h = wind.get("hourly", {})
    times = hourly.get("time", [])
    start_hr, end_hr = _window_range(session, sunrise, sunset)
    if from_hour is not None:
        # "now" queries → look only at the current hour, not future hours.
        start_hr = end_hr = from_hour

    best = None
    best_rank = None
    for i, t in enumerate(times):
        hr = _hour_of(t)
        if hr is None or not (start_hr <= hr <= end_hr):
            continue

        wind_kt = wind_h["wind_speed_10m"][i] or 0
        wind_deg = wind_h["wind_direction_10m"][i] or 0
        hs_ft = hourly["swell_wave_height"][i] or 0
        wl = wind_label(wind_kt, wind_deg, spot["beach_orientation_deg"])
        rank = WIND_RANK.index(wl) if wl in WIND_RANK else len(WIND_RANK)

        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = {
                "time": t,
                "hour": hr,
                "wind_label": wl,
                "wind_kt": round(wind_kt, 1),
                "swell_hs_ft": round(hs_ft, 1),
                "tide_label": tide_label(tides, spot["tide_pref"], at_hour=hr),
            }
    return best
