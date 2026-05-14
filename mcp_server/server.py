#!/usr/bin/env python3
"""SoCal Surf Report MCP server.

Exposes two tools to Poke:
  - list_spots(region)        : enumerate available SoCal breaks
  - get_surf_report(spot_id)  : fetch today's forecast + objective rating

Data sources (all free, keyless, public):
  - Open-Meteo Marine API   (wave height/period/direction, SST)
  - Open-Meteo Weather API  (wind, air temp, sunrise/sunset)
  - NOAA Tides & Currents   (high/low tide events)
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

from fastmcp import FastMCP

from datetime import datetime

from forecast import (
    fetch_marine, fetch_wind, fetch_tides, fetch_sun,
    _resolve_date, current_session_pt, current_hour_pt, now_pt,
)
from rating import summarize_conditions, find_best_window, SESSIONS
from spots import all_regions, all_spots, get_spot, spots_in_region

mcp = FastMCP("SoCal Surf Report")


@mcp.tool(
    description=(
        "List available SoCal surf spots. Optionally filter by region "
        "(santa-barbara, ventura, la, oc, sd). Use this when the user is "
        "picking which break(s) they want daily reports for."
    )
)
def list_spots(region: Optional[str] = None) -> dict:
    """Return spots grouped by region, with a stable id, display name, and short notes."""
    regions = all_regions()
    if region:
        if region not in regions:
            return {
                "error": f"Unknown region '{region}'. Valid: {list(regions)}",
            }
        spots = spots_in_region(region)
    else:
        spots = all_spots()

    return {
        "regions": regions,
        "spots": [
            {
                "id": s["id"],
                "name": s["name"],
                "region": s["region"],
                "skill_floor": s["skill_floor"],
                "notes": s["notes"],
            }
            for s in spots
        ],
    }


@mcp.tool(
    description=(
        "Fetch a SoCal surf report for a single spot. Returns numeric values "
        "plus surfer-readable labels — face height + label, swell period + "
        "label, swell direction + cardinal + label, wind speed + label, tide "
        "label, water/air temp, wetsuit, and the cleanest-wind hour inside "
        "the chosen session. No overall verdict — you (the agent) form "
        "it from the labels + user context. "
        "Use spot_id from list_spots(). "
        "Optional date in YYYY-MM-DD (defaults to today in PT). "
        "Optional session: 'dawn' (sunrise–11am, default), 'midday' (11am–3pm), "
        "'sunset' (3pm–sunset), or 'now' (auto-detect from current PT time)."
    )
)
async def get_surf_report(spot_id: str, date: Optional[str] = None,
                          session: str = "dawn") -> dict:
    spot = get_spot(spot_id)
    if not spot:
        return {
            "error": f"Unknown spot_id '{spot_id}'. Call list_spots() to see valid ids.",
        }

    requested_now = (session == "now")
    if requested_now:
        session = current_session_pt()
    if session not in SESSIONS:
        return {
            "error": f"Unknown session '{session}'. Valid: {sorted(SESSIONS) + ['now']}",
        }

    target_date = _resolve_date(date)
    # Only truncate to "from now on" when "now" was requested AND the date is today.
    from_hour = current_hour_pt() if (requested_now and target_date == now_pt().date()) else None

    marine, wind, tides, sun = await asyncio.gather(
        fetch_marine(spot["lat"], spot["lon"], target_date),
        fetch_wind(spot["lat"], spot["lon"], target_date),
        fetch_tides(spot["tide_station"], target_date),
        fetch_sun(spot["lat"], spot["lon"], target_date),
    )

    sunrise, sunset = sun.get("sunrise"), sun.get("sunset")
    summary = summarize_conditions(spot, marine, wind, tides, sunrise, sunset, session, from_hour)
    best_window = find_best_window(marine, wind, tides, spot, sunrise, sunset, session, from_hour)

    # Drop sun events that already happened so the recipe doesn't surface them.
    sun_out = dict(sun)
    if from_hour is not None:
        now = now_pt()
        for key in ("sunrise", "sunset"):
            try:
                t = datetime.fromisoformat(sun_out[key])
                if t.tzinfo is None:
                    t = t.replace(tzinfo=now.tzinfo)
                if t < now:
                    sun_out[key] = None
            except (TypeError, ValueError, KeyError):
                pass

    return {
        "spot": {
            "id": spot["id"],
            "name": spot["name"],
            "region": spot["region"],
            "skill_floor": spot["skill_floor"],
            "notes": spot["notes"],
        },
        "date": target_date.isoformat(),
        "session": summary["session"],
        "session_window": summary["session_window"],
        "current_hour_pt": from_hour,
        "sun": sun_out,
        "conditions": summary["snapshot"],
        "tide": {
            "events": tides,
            "preference": spot["tide_pref"],
        },
        "best_window": best_window,
        "attribution": "Forecast data by Open-Meteo.com. Tide data by NOAA.",
    }


@mcp.tool(
    description=(
        "Server health/info. Useful for debugging that the MCP is reachable."
    )
)
def get_server_info() -> dict:
    return {
        "server_name": "SoCal Surf Report",
        "version": "0.1.0",
        "spot_count": len(all_spots()),
        "regions": list(all_regions().keys()),
        "data_sources": [
            "Open-Meteo Marine",
            "Open-Meteo Weather",
            "NOAA Tides & Currents",
        ],
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0"

    print(f"Starting SoCal Surf Report MCP server on {host}:{port}")

    mcp.run(
        transport="http",
        host=host,
        port=port,
        stateless_http=True,
    )
