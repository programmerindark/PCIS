# PCIS — handoff for next session

_Last updated: 2026-07-23_

## Where things stand

The **heater** feature is complete and tested end-to-end. PCIS now answers both
sides of the climate problem:

- getting heat **out** — fans, cooling pads, tunnel air speed, wind-chill
  effective temperature (built earlier);
- putting heat **in** — supplemental heating for cold weather / brooding (this
  session).

### What was built this session (the heater)

- `pcis/core/heating.py` — steady-state house energy balance. Losses (envelope
  conduction `U·A·ΔT` + warming the minimum-ventilation air, ASHRAE `Q=ṁ·cp·ΔT`)
  minus bird sensible heat (CIGR) = heating deficit. Given a heater capacity it
  also returns a **duty fraction** and an **undersized** flag. No new constants —
  every piece reuses already-cited modules.
- `tests/test_heating.py` — 14 tests. Encodes the non-obvious real result that
  **peak heat demand is around week 1–2, not day 1** (min-ventilation load grows
  faster than bird heat early on), then falls to zero by ~4 weeks.
- `pcis/core/recommendation_engine.py` — `recommend()` now takes
  `heater_capacity_w`, computes the heating requirement, and adds a cited
  "HEATING NEEDED" explanation (kW breakdown + duty %). Also carries the
  air-speed / effective-temp fields.
- `pcis/core/digital_twin.py` — schedule/grow-out sims take `heater_capacity_w`,
  track `heating_needed` / `heater_duty_fraction` per step, split blocks on
  heating state, and show a "Heat" column in the table.
- `pcis/gui/main_window.py` —
  - Recommendation tab: new **Heating** metric ("off" or e.g. "31 kW (31%)").
  - Schedule tab: new **Heater capacity (kW)** input, wired into the twin;
    block display shows "heat ON/off".

Full suite: **321 passed**. Heater-specific: heating(14) + twin(44) +
recommendation_engine all green.

## What's NEXT (dad's request — not started)

Dad's feedback: the app should, from a single setup, ask for **farm dimensions,
fan capacity, day-wise target-temperature chart, bird age & weight, outside
temperature**, and return **required number of fans with on/off times, cooling
pad on/off times, and heater on/off times**. The engine already computes all of
this — the gap is the **UX**.

He also said the **Schedule tab is confusing to use**. So the task is a
**guided flow / wizard**: one setup screen → a complete day-by-day schedule
(fans + pads + heaters + times) + the Aviagen day-wise target-temperature chart
surfaced directly.

**Do this in a session with a working Qt display** so the new flow can be
screenshotted and iterated visually — building a new UX blind risks recreating
the "confusing" version. (The engine/data-model parts are testable without a
display; the visual layout is not.)

### Suggested approach for the wizard
1. Design the step model + data flow first (testable headless).
2. One "Farm setup" step: dimensions, fan capacity/count, heater capacity,
   bird strain.
3. One "Conditions" step: age/weight (auto from Ross-308 curve), outside temp,
   the day-wise target-temp chart shown for reference.
4. Output: consolidated schedule from the digital twin — fans on/off, pad
   on/off, heater on/off per time block.
5. Keep the existing tabs as an "advanced" view; the wizard is the default.

## Engineering-honesty rule (unchanged, non-negotiable)
Every equation/constant traces to a cited published source (ASHRAE, CIGR,
Aviagen, manufacturer data). Never fabricate numbers. Flag anything uncertain
explicitly. Never extrapolate past published table ranges.

## Environment notes
- Repo is the connected folder `PCIS_flat` (OneDrive-synced). The OneDrive mount
  blocks the sandbox from removing `.git/index.lock` — commits must be run from
  your own terminal.
- Qt (`libEGL.so.1`) went missing after a mid-session VM reset and can't be
  reinstalled without root here. A fresh session should boot a clean VM with it.
