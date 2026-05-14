# Sample outputs

Real outputs based on actual API data fetched 2026-05-13, so you can see
what the recipe should produce from real MCP responses.

---

## Scenario 1 — A real morning at Lower Trestles (2026-05-13)

**Raw MCP data:**

```
spot: lower-trestles (Lower Trestles)
date: 2026-05-13
conditions:
  face_height_ft: 2.7        (knee-waist)
  swell_period_s: 11.8       (clean groundswell)
  swell_direction: 186° S
  wind_speed_kt: 1.1
  wind_direction: 315° NW    (very light, basically glassy)
  water_temp_f: 65.5
  wetsuit: 3/2
rating: FAIR (score 58/100)
tide:
  01:27  0.6ft L
  07:22  3.8ft H            ← high pushing through the morning
  13:02  0.8ft L
best_window: 06:00 (glassy + tide push)
sun: sunrise 05:54
```

**Recipe output (user has 1 spot, intermediate shortboard, "always"):**

```
🌊 Tue May 13 · Worth a check — small but glassy at Trestles.

Lower Trestles  FAIR
  knee-waist · 12s S · glassy
  Best: 6–7:30am. Clean S groundswell, high tide pushing through dawn.
  Small for a shortboard but rippable on the right set.

🌡 65°F · 3/2   ☀ Sunrise 5:54am
```

**Same data, beginner longboarder profile:**

```
🌊 Tue May 13 · GO — glassy and your size at Trestles.

Lower Trestles  GOOD (for a longboard)
  knee-waist · 12s S · glassy
  Best: 6–7:30am. Long-period S swell, high tide push. Perfect log day.

🌡 65°F · 3/2   ☀ Sunrise 5:54am
```

---

## Scenario 2 — Skip day (illustrative)

Strong onshore by 7am everywhere, small windswell:

```
🌊 Wed May 14 · Skip — onshore picks up by 7 and the swell is gone.

Lower Trestles  POOR
  knee-high · 8s W · onshore 14kt
  No window — wind is up at dawn.

El Porto  POOR
  ankle-knee · 7s NW · onshore 12kt
  Junked. Save the gas.

🌡 64°F · 3/2
```

---

## Scenario 3 — Mixed day, two spots

```
🌊 Sat May 17 · Trestles is the call. El Porto is junk.

Lower Trestles  GOOD
  chest-head · 14s SSW · light offshore
  Best: 6–8am. Long-period S lighting up the cobble. Will get crowded by 8.

El Porto  POOR
  waist · 9s W · onshore 10kt
  Wind is already up. Skip unless you can't make the drive south.

🌡 66°F · springsuit / 2mm top   ☀ Sunrise 5:51am
```
