# SoCal Surfline — Poke recipe + MCP

A Poke.com recipe (**SoCal Dawn Patrol**) that texts you a daily surf
report for your favorite SoCal breaks, backed by a free, no-auth MCP
server.

```
┌─────────────────────┐     ┌────────────────────────┐
│  Poke recipe        │ ──▶ │  SoCal Surf MCP        │ ──▶ Open-Meteo Marine
│  SoCal Dawn Patrol  │     │  (FastMCP on Render)   │ ──▶ Open-Meteo Weather
└─────────────────────┘     └────────────────────────┘ ──▶ NOAA Tides
       │
       └─▶ iMessage / WhatsApp
```

The MCP holds the data + logic. The recipe holds the personality, memory,
and scheduling. The split is deliberate: numbers are deterministic, prose
is personalized.

## Layout

```
mcp_server/           Python FastMCP server (deploys to Render)
  server.py           Tool definitions: list_spots, get_surf_report, get_server_info
  spots.yaml          44 SoCal breaks, Jalama → OB
  spots.py            YAML loader
  forecast.py         Open-Meteo Marine + Weather, NOAA Tides clients
  rating.py           Objective POOR/FAIR/GOOD/EPIC scoring + best-window
  requirements.txt    fastmcp, uvicorn, httpx, PyYAML
  render.yaml         Render free-tier deployment config
  .env.example        (no env vars required)

recipe/
  recipe.md           The recipe prompt to paste into poke.com/kitchen
  sample_outputs.md   Real example messages built from live API data
```

## How to ship this

### 1. Deploy the MCP to Render (~5 minutes)

The MCP is no-auth — anyone with the URL can call it. That's fine; the data
itself is public.

1. Push this repo to GitHub.
2. Go to <https://render.com> → New → Web Service → connect the repo.
3. Render reads `mcp_server/render.yaml` and configures itself. Pick the
   free plan. Click Deploy.
4. Wait for the build. When it's up, the MCP endpoint is:
   `https://<your-service>.onrender.com/mcp`
5. Sanity-check it's alive:
   ```
   curl https://<your-service>.onrender.com/mcp -i
   ```
   Expect a 200 or 406 (not a 404).

**Free-tier note:** Render sleeps idle services after 15 min. First daily
call has a ~30s cold start — fine for a once-a-day surf report.

### 2. Wire up the recipe in Poke

1. Go to <https://poke.com/kitchen> and click **Create recipe**.
2. Name it `SoCal Dawn Patrol`.
3. Under **Required integrations**, add a Custom MCP Server pointing at
   your Render URL (`https://<your-service>.onrender.com/mcp`). No auth.
4. Paste the **Recipe instructions** section from `recipe/recipe.md` into
   the recipe body.
5. Configure scheduling — daily, user picks the time in onboarding.
6. Save. Poke gives you a shareable link in the form
   `https://poke.com/r/<code>`.

### 3. Install + first-run

Open the install link in your own Poke. The recipe walks you through a
6-step onboarding (spots, level/board, send time, send mode, optional
context, confirm). Your answers land in Poke's memory. Tomorrow morning,
the first report arrives.

## What surfers see in a message

```
🌊 Tue May 13 · Worth a check — small but glassy at Trestles.

Lower Trestles  FAIR
  knee-waist · 12s S · glassy
  Best: 6–7:30am. Clean S groundswell, high tide pushing through dawn.

🌡 65°F · 3/2   ☀ Sunrise 5:54am
```

That's a real output built from live data for 2026-05-13 — see
`recipe/sample_outputs.md` for more scenarios.

## Data sources

| Source | What we use | Auth | Limits |
|---|---|---|---|
| Open-Meteo Marine | Wave height/period/direction, SST | none | generous, commercial use OK with attribution |
| Open-Meteo Weather | Wind, air temp, sunrise/sunset | none | same |
| NOAA Tides & Currents | High/low tide events | none | unlimited |

Attribution lives in the MCP response (`attribution` field). The recipe
can include it in a footer if desired.

## Extending it

- **Add more spots:** new entries in `spots.yaml`. Each needs `id`, `lat`,
  `lon`, NOAA `tide_station`, `ideal_swell_deg` window, and
  `beach_orientation_deg`. No code changes.
- **Tune the rating:** thresholds live in `mcp_server/rating.py`. The
  weights at the bottom of `summarize_conditions` control how much each
  factor matters.
- **New regions:** the structure is region-agnostic. Adding NorCal or
  Hawaii is mostly more rows.
- **Personalization:** belongs in the recipe prompt, not the MCP. Keep
  the MCP returning objective data so it's reusable for other recipes.

## Caveats

- Lat/lon and tide-station mappings in `spots.yaml` are approximate from
  general knowledge; verify any that matter to you.
- `ideal_swell_deg` windows are judgment calls — refine them with a
  surfer who knows each break.
- Open-Meteo's `wave_height` is significant wave height; we treat it as
  approximate face height. Reasonable for most SoCal conditions, off on
  the edges (long-period winter, very steep coastlines).
- Cold-start latency on Render free tier. If it matters: $7/mo for
  always-on.
