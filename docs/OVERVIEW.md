# PCIS — Project Overview

_Poultry Climate Intelligence System — a plain-language tour of what the
project contains, how it works, and why it matters._

_Last updated: 2026-07-24_

## What it is

PCIS is a decision-support application for climate control in broiler
(meat-chicken) houses. You describe your house, your flock, and the weather, and
it tells you what to run — how many fans, whether the cooling pads should be on,
whether heaters are needed, and what air speed to aim for — and it estimates how
the birds are likely to feel as a result.

It is a Python desktop app (PySide6 / Qt) built on one strict rule: **every
number it shows traces to a published source, and anything uncertain is labelled
as an estimate.** It cites ASHRAE, CIGR, Aviagen and Cobb, and attaches a
confidence score to each recommendation.

## How it is built — three layers

### 1. The engineering core (`pcis/core/`)

Pure physics, no interface code. This is where every number is actually
calculated and where the citations live.

- **`psychrometrics.py`** — the foundation: moist-air properties (saturation
  vapor pressure, humidity ratio, wet-bulb, dew point, enthalpy, density, and
  vapor-pressure deficit), from ASHRAE / Buck equations.
- **`bird_metabolism.py`** — how much heat, moisture and CO₂ the birds produce
  (CIGR formulas).
- **`growth_curve.py`** — the Aviagen Ross-308 body-weight-by-age table.
- **`comfort_engine.py`** — target house temperature (Aviagen), the
  temperature-humidity heat-stress index (THI), and a composite comfort score.
- **`heat_moisture_balance.py`** — the house energy balance: bird heat vs. heat
  lost/gained through the envelope (Q = U·A·ΔT).
- **`ventilation_solver.py`** — required airflow for each need (sensible heat,
  moisture, CO₂, minimum ventilation), tunnel air speed, and fan-count sizing.
- **`wind_chill.py`** — the estimated felt ("effective") temperature from air
  speed, anchored to Aviagen's worked example (reported, never used to size fans).
- **`target_airspeed.py`** — the cited target tunnel air velocity for wind-chill
  cooling (young-chick 0.15 m/s ceiling; 3.0 m/s tunnel target in heat).
- **`heating.py`** — the cold-weather counterpart: supplemental heating
  requirement from the same energy balance.
- **`envelope_presets.py`** — cited U-value presets by construction type, so an
  operator who doesn't know their wall/ceiling U-value can pick one.
- **`bird_status.py`** — turns a result into the bird-centred dashboard (comfort,
  heat-stress risk, panting, water intake), evaluated at the realistic
  temperature the house can actually hold.
- **`validation.py`** — hooks to fit per-house correction factors against logged
  data (calibration groundwork).

### 2. The decision engine

- **`recommendation_engine.py`** is the brain. It calls the core modules, asks
  "which requirement is the largest?" — sensible heat, moisture, CO₂, minimum
  ventilation, or target air velocity — and sizes fans to that **governing
  constraint**, correcting fan output for the actual static pressure. It returns
  one bundle: fans, pads, governing constraint, air speed, felt temperature, VPD,
  heating, a comfort assessment, a confidence score, and a written explanation of
  every step.
- **`digital_twin.py`** runs that engine across a day's weather (or a full
  grow-out) and collapses the result into a consolidated schedule of blocks.

### 3. The application (`pcis/gui/`)

- **`main_window.py`** — the tabbed window (House & Equipment, Flock,
  Environment, Recommendation, Guided Schedule, History).
- **`guided.py` / `guided_model.py`** — the single-page guided flow: one setup →
  full day schedule + day-wise target-temperature chart + bird-status dashboard.
- **`widgets.py`** — shared widgets (unit-aware inputs, the envelope editor with
  its construction-type picker).
- **`charts.py`, `units.py`, `style.py`** — visualizations, metric/imperial
  switching, theming.

### Supporting parts

- **`pcis/db/`** — a SQLite database that logs every run (the History tab) as
  groundwork for future machine-learning calibration.
- **`pcis/reports/pdf_report.py`** — PDF report export.
- Packaging/build scripts, plus a test suite of **~24 files / ~418 tests** that
  verifies the physics without ever opening the GUI.

## How it works, end to end

1. You enter house dimensions, envelope surfaces (cited U-value presets
   available), fan model, flock age and count, and a weather profile.
2. Age auto-fills body weight from the Aviagen curve, which sets the target
   temperature.
3. The engine computes each airflow requirement, picks the governing one, sizes
   and rounds up the fan count, checks the resulting air speed, and reports felt
   temperature, VPD and comfort.
4. The digital twin collapses the day into blocks
   (e.g. "06:00–09:00: 4 fans, pads off, heat off").
5. The bird-status dashboard shows how the birds fare at the worst point of the
   day.

## How relevant it is

Two things make PCIS genuinely useful:

- **It calculates dynamically** instead of reading a fixed fan-stage table. Most
  commercial controllers switch fan stages on temperature alone; PCIS reasons
  from airflow physics and a target air velocity, and estimates how the birds
  actually feel (felt temperature, panting, water demand).
- **Sourcing discipline.** It won't invent numbers. It cites its sources, and it
  flags its own uncertainty with a confidence score — exactly what you want
  before trusting advice near live animals.

## Honest limits

- It is an **advisor, not a live hardware controller** — it says what to run but
  does not yet read sensors or switch fans itself.
- Some outputs (felt temperature, panting index, water multiplier) are
  **estimates**, labelled as such, because the published data only supports
  estimates.
- It currently models **Ross-308** birds.

The History database and calibration hooks are the runway toward closing these
gaps later.
