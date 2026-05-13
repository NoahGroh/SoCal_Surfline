"""Objective surf rating + best-window logic.

The rating combines four factors — size, period, swell direction match,
and wind quality — into a 0-100 score and a POOR/FAIR/GOOD/EPIC label.
The "personalization" pieces (skill level, board, "only ping when good")
live in the Poke recipe prompt, not here. This module produces objective
data the recipe can then frame however it wants.
"""
from __future__ import annotations

from datetime import datetime
import math


# ---------- helpers ----------

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
    """Smallest unsigned angle between two compass bearings."""
    d = abs((a - b) % 360)
    return min(d, 360 - d)


def _in_window(deg: float, window: tuple[float, float]) -> bool:
    lo, hi = window
    if lo <= hi:
        return lo <= deg <= hi
    # wraps around 360
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


def _mean(xs: list[float | None]) -> float:
    vals = [x for x in xs if x is not None]
    return sum(vals) / len(vals) if vals else 0.0


# ---------- factor scoring ----------

def score_size(face_height_ft: float) -> tuple[float, str]:
    """Objective size score, peaks around chest-to-overhead."""
    if face_height_ft < 0.5:
        return 0.05, "flat"
    if face_height_ft < 1.5:
        return 0.25, "ankle-knee"
    if face_height_ft < 2.5:
        return 0.55, "knee-waist"
    if face_height_ft < 3.5:
        return 0.85, "waist-chest"
    if face_height_ft < 5.0:
        return 1.0, "chest-head"
    if face_height_ft < 7.0:
        return 0.9, "overhead"
    if face_height_ft < 10.0:
        return 0.7, "well overhead"
    return 0.4, "huge / closeout risk"


def score_period(period_s: float) -> tuple[float, str]:
    if period_s < 7:
        return 0.2, "windswell / mushy"
    if period_s < 10:
        return 0.5, "mid period"
    if period_s < 13:
        return 0.8, "clean groundswell"
    return 1.0, "long-period groundswell"


def score_direction(swell_dir_deg: float, ideal_window: tuple[float, float]) -> tuple[float, str]:
    miss = _distance_outside_window(swell_dir_deg, ideal_window)
    if miss == 0:
        return 1.0, "lined up for the spot"
    if miss < 15:
        return 0.7, "just outside ideal window"
    if miss < 30:
        return 0.45, "off-angle, partial energy"
    if miss < 60:
        return 0.2, "wrong direction"
    return 0.05, "blocked direction"


def score_wind(wind_speed_kt: float, wind_dir_deg: float, beach_orientation_deg: float) -> tuple[float, str]:
    """Wind quality given the spot orientation.

    Offshore = wind blowing from land out to sea (opposite of beach orientation).
    Onshore  = wind blowing from sea to land   (matching beach orientation).
    """
    diff_from_offshore = _angle_diff(wind_dir_deg, (beach_orientation_deg + 180) % 360)
    diff_from_onshore = _angle_diff(wind_dir_deg, beach_orientation_deg)

    if wind_speed_kt < 3:
        return 0.95, "glassy"

    if diff_from_offshore < 45:
        # offshore
        if wind_speed_kt < 10:
            return 1.0, "light offshore"
        if wind_speed_kt < 18:
            return 0.85, "moderate offshore"
        return 0.55, "strong offshore (spitty)"

    if diff_from_onshore < 45:
        # onshore
        if wind_speed_kt < 6:
            return 0.5, "light onshore"
        if wind_speed_kt < 12:
            return 0.2, "onshore, blown out"
        return 0.05, "junked"

    # crossshore
    if wind_speed_kt < 6:
        return 0.7, "light cross"
    if wind_speed_kt < 12:
        return 0.4, "cross / textured"
    return 0.15, "strong cross"


def score_tide(tide_events: list[dict], tide_pref: str, at_hour: int) -> tuple[float, str]:
    """Approximate tide-quality scoring relative to the spot's preference.

    Uses high/low events on the day; estimates whether the morning falls
    in the preferred window. Coarse but useful as a tiebreaker.
    """
    if tide_pref == "any" or not tide_events:
        return 0.8, "tide n/a"

    # find nearest two events bracketing at_hour
    parsed = []
    for e in tide_events:
        try:
            t = datetime.fromisoformat(e["time"].replace(" ", "T"))
            parsed.append((t.hour + t.minute / 60.0, e["type"], e["height_ft"]))
        except Exception:
            continue

    if not parsed:
        return 0.7, "tide unknown"

    # phase: rising or falling around at_hour
    parsed.sort()
    prev = None
    nxt = None
    for entry in parsed:
        if entry[0] <= at_hour:
            prev = entry
        elif nxt is None:
            nxt = entry

    if prev and nxt:
        rising = nxt[2] > prev[2]
        # fraction of the way between events
        span = nxt[0] - prev[0]
        frac = (at_hour - prev[0]) / span if span > 0 else 0.5
        height = prev[2] + frac * (nxt[2] - prev[2])
    elif prev:
        rising = False
        height = prev[2]
    elif nxt:
        rising = True
        height = nxt[2]
    else:
        return 0.7, "tide unknown"

    phase = "rising" if rising else "falling"

    # crude windows by preference
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
    if score < 0.25:
        return "POOR"
    if score < 0.50:
        return "FAIR"
    if score < 0.75:
        return "GOOD"
    return "EPIC"


def _morning_indices(times: list[str], start_hour: int = 5, end_hour: int = 11) -> list[int]:
    out = []
    for i, t in enumerate(times):
        try:
            hr = datetime.fromisoformat(t).hour
        except Exception:
            continue
        if start_hour <= hr <= end_hour:
            out.append(i)
    return out


def summarize_conditions(spot: dict, marine: dict, wind: dict, tides: list[dict]) -> dict:
    """Compute the structured snapshot the recipe will format into prose."""
    hourly = marine.get("hourly", {})
    wind_h = wind.get("hourly", {})
    times = hourly.get("time", [])
    morning = _morning_indices(times)

    wave_h = [hourly["wave_height"][i] for i in morning]
    swell_p = [hourly["swell_wave_period"][i] for i in morning]
    swell_d = [hourly["swell_wave_direction"][i] for i in morning]
    sst = [hourly["sea_surface_temperature"][i] for i in morning]
    wind_s = [wind_h["wind_speed_10m"][i] for i in morning]
    wind_d = [wind_h["wind_direction_10m"][i] for i in morning]
    air_t = [wind_h["temperature_2m"][i] for i in morning]

    face_height = _mean(wave_h)
    period = _mean(swell_p)
    dir_deg = _circular_mean([d for d in swell_d if d is not None])
    wind_speed = _mean(wind_s)
    wind_deg = _circular_mean([d for d in wind_d if d is not None])
    water_temp_c = _mean(sst)
    water_temp_f = water_temp_c * 9 / 5 + 32 if water_temp_c else None
    air_temp_f = _mean(air_t)

    size_s, size_label = score_size(face_height)
    per_s, per_label = score_period(period)
    dir_s, dir_label = score_direction(dir_deg, tuple(spot["ideal_swell_deg"]))
    wind_s_score, wind_label = score_wind(wind_speed, wind_deg, spot["beach_orientation_deg"])
    tide_s, tide_label = score_tide(tides, spot["tide_pref"], at_hour=7)

    # weighted geometric mean — any factor being terrible drags the rating down
    weights = {"size": 0.25, "period": 0.20, "direction": 0.20, "wind": 0.25, "tide": 0.10}
    factors = {
        "size": size_s,
        "period": per_s,
        "direction": dir_s,
        "wind": wind_s_score,
        "tide": tide_s,
    }
    # geometric mean with weights
    log_sum = sum(weights[k] * math.log(max(v, 0.01)) for k, v in factors.items())
    overall = math.exp(log_sum)
    label = _label_for_score(overall)

    return {
        "rating": {
            "overall": label,
            "score_0_100": int(round(overall * 100)),
            "factors": {
                "size":      {"score": round(size_s, 2),      "label": size_label},
                "period":    {"score": round(per_s, 2),       "label": per_label},
                "direction": {"score": round(dir_s, 2),       "label": dir_label},
                "wind":      {"score": round(wind_s_score, 2),"label": wind_label},
                "tide":      {"score": round(tide_s, 2),      "label": tide_label},
            },
        },
        "snapshot": {
            "face_height_ft": round(face_height, 1),
            "face_height_label": size_label,
            "swell_period_s": round(period, 1),
            "swell_direction_deg": round(dir_deg),
            "swell_direction_cardinal": to_cardinal(dir_deg),
            "wind_speed_kt": round(wind_speed, 1),
            "wind_direction_deg": round(wind_deg),
            "wind_direction_cardinal": to_cardinal(wind_deg),
            "wind_character": wind_label,
            "water_temp_f": round(water_temp_f, 1) if water_temp_f else None,
            "air_temp_f": round(air_temp_f, 1) if air_temp_f else None,
            "wetsuit": _wetsuit_for(water_temp_f),
        },
    }


def _wetsuit_for(water_temp_f: float | None) -> str | None:
    if water_temp_f is None:
        return None
    if water_temp_f < 58:
        return "4/3 + booties"
    if water_temp_f < 62:
        return "4/3"
    if water_temp_f < 66:
        return "3/2"
    if water_temp_f < 70:
        return "springsuit or 2mm top"
    return "trunks"


def find_best_window(marine: dict, wind: dict, spot: dict) -> dict | None:
    """Scan hourly data from sunrise-ish to noon, return the hour with the best score."""
    hourly = marine.get("hourly", {})
    wind_h = wind.get("hourly", {})
    times = hourly.get("time", [])

    best = None
    for i, t in enumerate(times):
        try:
            hr = datetime.fromisoformat(t).hour
        except Exception:
            continue
        if not (5 <= hr <= 12):
            continue

        wave = hourly["wave_height"][i] or 0
        period = hourly["swell_wave_period"][i] or 0
        sdir = hourly["swell_wave_direction"][i] or 0
        wspd = wind_h["wind_speed_10m"][i] or 0
        wdir = wind_h["wind_direction_10m"][i] or 0

        size_s, _ = score_size(wave)
        per_s, _ = score_period(period)
        dir_s, _ = score_direction(sdir, tuple(spot["ideal_swell_deg"]))
        win_s, win_label = score_wind(wspd, wdir, spot["beach_orientation_deg"])

        score = (size_s ** 0.25) * (per_s ** 0.20) * (dir_s ** 0.25) * (win_s ** 0.30)

        if best is None or score > best["score"]:
            best = {
                "time": t,
                "hour": hr,
                "score": score,
                "wind_label": win_label,
                "wind_kt": round(wspd, 1),
                "face_height_ft": round(wave, 1),
            }
    return best
