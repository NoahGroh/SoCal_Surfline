"""Objective surf rating + best-window logic.

The rating combines five factors — size, period, swell direction, wind, and
tide — into a 0-100 score and a POOR/FAIR/GOOD/EPIC label. Personalization
(skill, board, "only ping when good") lives in the Poke recipe, not here.
"""
from __future__ import annotations

from datetime import datetime
import math


# Open-Meteo returns significant wave height in deep water; surfers think
# in face height, which runs ~1.5x larger after shoaling.
FACE_FACTOR = 1.5

# Geometric-mean weights for the overall rating. A near-zero factor tanks
# the score, which is what we want (junked wind ruins a good swell, etc.).
WEIGHTS = {"size": 0.25, "period": 0.20, "direction": 0.20, "wind": 0.25, "tide": 0.10}

# Floor inside log() so score 0 doesn't blow up to -inf, but stays low
# enough that "junked" wind (~0.05) still drives the rating down hard.
SCORE_FLOOR = 0.001


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


# ---------- factor scoring ----------

def score_size(face_height_ft: float) -> tuple[float, str]:
    if face_height_ft < 0.5:  return 0.05, "flat"
    if face_height_ft < 1.5:  return 0.25, "ankle-knee"
    if face_height_ft < 2.5:  return 0.55, "knee-waist"
    if face_height_ft < 3.5:  return 0.85, "waist-chest"
    if face_height_ft < 5.0:  return 1.0,  "chest-head"
    if face_height_ft < 7.0:  return 0.9,  "overhead"
    if face_height_ft < 10.0: return 0.7,  "well overhead"
    return 0.4, "huge / closeout risk"


def score_period(period_s: float) -> tuple[float, str]:
    if period_s < 7:  return 0.2, "windswell / mushy"
    if period_s < 10: return 0.5, "mid period"
    if period_s < 13: return 0.8, "clean groundswell"
    return 1.0, "long-period groundswell"


def score_direction(swell_dir_deg: float, ideal_window: tuple[float, float]) -> tuple[float, str]:
    miss = _distance_outside_window(swell_dir_deg, ideal_window)
    if miss == 0:  return 1.0,  "lined up for the spot"
    if miss < 15:  return 0.7,  "just outside ideal window"
    if miss < 30:  return 0.45, "off-angle, partial energy"
    if miss < 60:  return 0.2,  "wrong direction"
    return 0.05, "blocked direction"


def score_wind(wind_speed_kt: float, wind_dir_deg: float, beach_orientation_deg: float) -> tuple[float, str]:
    """Offshore = wind from land out to sea. Onshore = sea to land."""
    diff_from_offshore = _angle_diff(wind_dir_deg, (beach_orientation_deg + 180) % 360)
    diff_from_onshore = _angle_diff(wind_dir_deg, beach_orientation_deg)

    if wind_speed_kt < 3:
        return 0.95, "glassy"

    if diff_from_offshore < 45:
        if wind_speed_kt < 10: return 1.0,  "light offshore"
        if wind_speed_kt < 18: return 0.85, "moderate offshore"
        return 0.55, "strong offshore (spitty)"

    if diff_from_onshore < 45:
        if wind_speed_kt < 6:  return 0.5,  "light onshore"
        if wind_speed_kt < 12: return 0.2,  "onshore, blown out"
        return 0.05, "junked"

    if wind_speed_kt < 6:  return 0.7,  "light cross"
    if wind_speed_kt < 12: return 0.4,  "cross / textured"
    return 0.15, "strong cross"


def score_tide(tide_events: list[dict], tide_pref: str, at_hour: float) -> tuple[float, str]:
    if tide_pref == "any" or not tide_events:
        return 0.8, "tide n/a"

    events = []
    for e in tide_events:
        try:
            t = datetime.fromisoformat(e["time"].replace(" ", "T"))
            events.append((t.hour + t.minute / 60.0, e["height_ft"]))
        except (ValueError, KeyError):
            continue
    if not events:
        return 0.7, "tide unknown"

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
    pref_match = {
        "low":      height < 1.5,
        "mid_low":  0.5 <= height <= 3.0,
        "mid":      1.0 <= height <= 4.0,
        "mid_high": 2.5 <= height <= 5.5,
        "high":     height > 3.5,
    }.get(tide_pref, True)

    if pref_match:
        return 0.9, f"{height:.1f}ft, {phase}"
    return 0.5, f"{height:.1f}ft, {phase} — off preferred"


# ---------- aggregation ----------

def _label_for_score(score: float) -> str:
    if score < 0.25: return "POOR"
    if score < 0.50: return "FAIR"
    if score < 0.75: return "GOOD"
    return "EPIC"


def _wetsuit_for(water_temp_f: float | None) -> str | None:
    if water_temp_f is None:
        return None
    if water_temp_f < 58: return "4/3 + booties"
    if water_temp_f < 62: return "4/3"
    if water_temp_f < 66: return "3/2"
    if water_temp_f < 70: return "springsuit or 2mm top"
    return "trunks"


# Session windows. Times are 24h PT. "sunrise"/"sunset" are placeholders
# resolved from the daily sun data; numeric values are fixed hour-of-day.
SESSIONS = {
    "dawn":   ("sunrise", 11),
    "midday": (11,        15),
    "sunset": (15,        "sunset"),
}


def _round_hour_for_sunrise(sunrise: str | None, default: int = 6) -> int:
    """First hour that's mostly daylight (30-min rule)."""
    if not sunrise:
        return default
    try:
        t = datetime.fromisoformat(sunrise)
        return t.hour + (1 if t.minute >= 30 else 0)
    except (ValueError, TypeError):
        return default


def _round_hour_for_sunset(sunset: str | None, default: int = 19) -> int:
    """Last hour that's mostly daylight (30-min rule)."""
    if not sunset:
        return default
    try:
        t = datetime.fromisoformat(sunset)
        return t.hour - (1 if t.minute < 30 else 0)
    except (ValueError, TypeError):
        return default


def _window_range(session: str, sunrise: str | None, sunset: str | None) -> tuple[int, int]:
    """Resolve a session label to (start_hour, end_hour) for the day."""
    if session not in SESSIONS:
        session = "dawn"
    start, end = SESSIONS[session]
    if start == "sunrise":
        start = _round_hour_for_sunrise(sunrise)
    if end == "sunset":
        end = _round_hour_for_sunset(sunset)
    return start, end


def _score_hour(spot: dict, wave_ft: float, period_s: float,
                swell_deg: float, wind_kt: float, wind_deg: float) -> dict:
    """Score the four per-hour factors (tide is added separately per day)."""
    size_s, size_l = score_size(wave_ft * FACE_FACTOR)
    per_s,  per_l  = score_period(period_s)
    dir_s,  dir_l  = score_direction(swell_deg, tuple(spot["ideal_swell_deg"]))
    wind_s, wind_l = score_wind(wind_kt, wind_deg, spot["beach_orientation_deg"])
    return {
        "size":      {"score": size_s, "label": size_l},
        "period":    {"score": per_s,  "label": per_l},
        "direction": {"score": dir_s,  "label": dir_l},
        "wind":      {"score": wind_s, "label": wind_l},
    }


def _combine(factors: dict) -> float:
    """Weighted geometric mean over WEIGHTS. Renormalizes when only a subset is supplied."""
    items = [(k, v["score"]) for k, v in factors.items() if k in WEIGHTS]
    w_total = sum(WEIGHTS[k] for k, _ in items)
    if w_total <= 0:
        return 0.0
    log_sum = sum(WEIGHTS[k] * math.log(max(s, SCORE_FLOOR)) for k, s in items)
    return math.exp(log_sum / w_total)


def summarize_conditions(spot: dict, marine: dict, wind: dict, tides: list[dict],
                         sunrise: str | None = None, sunset: str | None = None,
                         session: str = "dawn") -> dict:
    """Compute the structured snapshot for the chosen session window."""
    hourly = marine.get("hourly", {})
    wind_h = wind.get("hourly", {})
    times = hourly.get("time", [])
    start_hr, end_hr = _window_range(session, sunrise, sunset)

    in_window = []
    for i, t in enumerate(times):
        h = _hour_of(t)
        if h is not None and start_hr <= h <= end_hr:
            in_window.append(i)

    wave_ft   = _mean([hourly["wave_height"][i] for i in in_window])
    period    = _mean([hourly["swell_wave_period"][i] for i in in_window])
    swell_deg = _circular_mean([hourly["swell_wave_direction"][i] for i in in_window
                                if hourly["swell_wave_direction"][i] is not None])
    wind_kt   = _mean([wind_h["wind_speed_10m"][i] for i in in_window])
    wind_deg  = _circular_mean([wind_h["wind_direction_10m"][i] for i in in_window
                                if wind_h["wind_direction_10m"][i] is not None])
    water_temp_c = _mean([hourly["sea_surface_temperature"][i] for i in in_window], default=None)
    air_temp_f   = _mean([wind_h["temperature_2m"][i] for i in in_window], default=None)
    water_temp_f = water_temp_c * 9 / 5 + 32 if water_temp_c is not None else None

    factors = _score_hour(spot, wave_ft, period, swell_deg, wind_kt, wind_deg)
    mid_hour = (start_hr + end_hr) / 2
    tide_s, tide_l = score_tide(tides, spot["tide_pref"], at_hour=mid_hour)
    factors["tide"] = {"score": tide_s, "label": tide_l}

    overall = _combine(factors)
    face_height_ft = wave_ft * FACE_FACTOR

    return {
        "session": session,
        "session_window": {"start_hour": start_hr, "end_hour": end_hr},
        "rating": {
            "overall": _label_for_score(overall),
            "score_0_100": int(round(overall * 100)),
            "factors": {k: {"score": round(v["score"], 2), "label": v["label"]}
                        for k, v in factors.items()},
        },
        "snapshot": {
            "face_height_ft": round(face_height_ft, 1),
            "face_height_label": factors["size"]["label"],
            "swell_period_s": round(period, 1),
            "swell_direction_deg": round(swell_deg),
            "swell_direction_cardinal": to_cardinal(swell_deg),
            "wind_speed_kt": round(wind_kt, 1),
            "wind_direction_deg": round(wind_deg),
            "wind_direction_cardinal": to_cardinal(wind_deg),
            "wind_character": factors["wind"]["label"],
            "water_temp_f": round(water_temp_f, 1) if water_temp_f is not None else None,
            "air_temp_f": round(air_temp_f, 1) if air_temp_f is not None else None,
            "wetsuit": _wetsuit_for(water_temp_f),
        },
    }


def find_best_window(marine: dict, wind: dict, spot: dict,
                     sunrise: str | None = None, sunset: str | None = None,
                     session: str = "dawn") -> dict | None:
    """Scan each hour in the session window, return the hour with the best score."""
    hourly = marine.get("hourly", {})
    wind_h = wind.get("hourly", {})
    times = hourly.get("time", [])
    start_hr, end_hr = _window_range(session, sunrise, sunset)

    best = None
    for i, t in enumerate(times):
        hr = _hour_of(t)
        if hr is None or not (start_hr <= hr <= end_hr):
            continue

        wave_ft = hourly["wave_height"][i] or 0
        wind_kt = wind_h["wind_speed_10m"][i] or 0
        factors = _score_hour(
            spot,
            wave_ft,
            hourly["swell_wave_period"][i] or 0,
            hourly["swell_wave_direction"][i] or 0,
            wind_kt,
            wind_h["wind_direction_10m"][i] or 0,
        )
        score = _combine(factors)

        if best is None or score > best["score"]:
            best = {
                "time": t,
                "hour": hr,
                "score": score,
                "wind_label": factors["wind"]["label"],
                "wind_kt": round(wind_kt, 1),
                "face_height_ft": round(wave_ft * FACE_FACTOR, 1),
            }
    return best
