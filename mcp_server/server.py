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

from forecast import fetch_marine, fetch_wind, fetch_tides, fetch_sun, _resolve_date, current_session_pt
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
        "Fetch a SoCal surf report for a single spot. Returns objective data — "
        "wave size, swell period/direction, wind, tide events, water temperature, "
        "wetsuit recommendation, a POOR/FAIR/GOOD/EPIC rating, and the best hour "
        "inside the chosen session. "
        "Use spot_id from list_spots(). "
        "Optional date in YYYY-MM-DD (defaults to today in PT). "
        "Optional session: 'dawn' (sunrise–11am, default), 'midday' (11am–3pm), "
        "'sunset' (3pm–sunset), or 'now' (auto-detect from current PT time). "
        "For the daily dawn-patrol report use the default. For ad-hoc queries "
        "('how is it now', 'evening session?') pick the matching session."
    )
)
async def get_surf_report(spot_id: str, date: Optional[str] = None,
                          session: str = "dawn") -> dict:
    spot = get_spot(spot_id)
    if not spot:
        return {
            "error": f"Unknown spot_id '{spot_id}'. Call list_spots() to see valid ids.",
        }

    if session == "now":
        session = current_session_pt()
    if session not in SESSIONS:
        return {
            "error": f"Unknown session '{session}'. Valid: {sorted(SESSIONS) + ['now']}",
        }

    target_date = _resolve_date(date)

    marine, wind, tides, sun = await asyncio.gather(
        fetch_marine(spot["lat"], spot["lon"], target_date),
        fetch_wind(spot["lat"], spot["lon"], target_date),
        fetch_tides(spot["tide_station"], target_date),
        fetch_sun(spot["lat"], spot["lon"], target_date),
    )

    sunrise, sunset = sun.get("sunrise"), sun.get("sunset")
    summary = summarize_conditions(spot, marine, wind, tides, sunrise, sunset, session)
    best_window = find_best_window(marine, wind, tides, spot, sunrise, sunset, session)

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
        "sun": sun,
        "conditions": summary["snapshot"],
        "rating": summary["rating"],
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
