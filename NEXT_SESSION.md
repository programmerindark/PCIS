# PCIS — handoff for next session

_Last updated: 2026-07-24 (airspeed + bird-status + day-schedule session)_

## Most recent — day schedule on the Recommendation tab

The Recommendation tab now answers "what to run through the day", not just "right
now". Added a reusable **`WeatherProfileTable`** widget (in `widgets.py`, Qt-only,
unit-aware) and a **Day schedule** section on the Recommendation tab: a weather
profile + fans-installed + heater + step-duration + a "Build day schedule" button
that runs the digital twin (with cross-section, so target airspeed governs) using
the detailed multi-tab inputs, and shows consolidated fan/pad/heater blocks + a
summary + the honest warnings. The single-moment recommendation above it is
unchanged. Live weather-forecast fetching was deferred (manual entry for now).
New methods: `MainWindow.run_day_schedule` / `_render_day_schedule`; the profile
is wired into `_on_units_changed`. Tests: `test_widgets.py` (WeatherProfileTable)
and two day-schedule cases in `test_gui.py`. All suites green (319 headless,
39 Qt, 83 stubbed GUI).

_Prototype note:_ a separate standalone single-page test UI was delivered OUTSIDE
the repo as `PCIS_QuickCheck.zip` (its own bundled engine copy + `app.py`); it is
intentionally not part of this repository.


## Latest session — dynamic airspeed control + bird-status dashboard

Implemented dad's "calculate fans dynamically, not from a fixed table" algorithm
and the bird-centred dashboard, all sourced (airspeed targets were required to be
cited-only). New cores, each Qt-free and unit-tested:

- **`pcis/core/target_airspeed.py`** — cited target tunnel air VELOCITY. Anchors:
  young/small chicks kept BELOW 0.15 m/s (30 ft/min) as a chill ceiling [Aviagen
  2010]; effective wind-chill needs ≥ 2.54 m/s (500 ft/min) [Aviagen]; tunnel
  target 3.0 m/s (600 ft/min), and ≥3.0 m/s when RH can't drop below 70% [Cobb].
  The graded fpm-by-age table dad sketched is NOT published, so it is not invented
  — PCIS switches regime at a disclosed 0.5 kg (~day-14) body-weight boundary.
- **Engine integration** — `recommendation_engine.recommend()` now adds
  `target_airspeed` as a GOVERNING CONSTRAINT (max of sensible/moisture/CO₂/
  min-vent/**target-velocity**). In heat for feathered birds the velocity term
  governs and fans are staged to hit the target (Steps 1–6 of dad's algorithm).
  Reports `target_airspeed_mps`; warns if delivered speed exceeds the young-chick
  ceiling. `digital_twin` now threads `house_cross_section_m2` through so the
  guided SCHEDULE actually uses it.
- **VPD** — `psychrometrics.vapor_pressure_deficit()` (cited; reuses Buck-1996
  SVP). Surfaced on the result (`vpd_kpa`). Matches dad's worked example
  (25.5 °C/93 % → 0.23 kPa).
- **`pcis/core/bird_status.py`** — the "next level" dashboard: comfort score +
  heat-stress risk (reuse of the cited comfort_index / THI), effective felt temp
  (wind-chill estimate), panting index (ESTIMATE, ~30 °C onset [MSU/UF-IFAS]),
  water-intake multiplier (ESTIMATE, ~6.5 %/°F, capped 2–4× [MSU Extension]).
  `from_recommendation()` evaluates at the REALISTIC indoor temp the house can
  hold (max of target, supply air) — so a 37 °C unreachable day reads as real
  heat stress (0/100, High), not a misleading "perfect at target".
- **Guided page** — passes cross-section into the twin (so airspeed governs the
  schedule) and shows a "Bird status — worst point of the day" panel (comfort,
  risk, felt temp, panting, water, VPD, target vs predicted air speed), with
  estimates clearly labelled "(est.)".

Honesty calls to know about: the airspeed regime boundary (0.5 kg) is PCIS's,
disclosed; panting/water are labelled ESTIMATES; a humidity-inflated single
"apparent temperature °C" was deliberately NOT fabricated — VPD + THI are the
cited humidity-stress signals instead (ask if a specific cited index is wanted).

Tests added: `test_target_airspeed.py`, `test_bird_status.py`, VPD cases in
`test_psychrometrics.py`, and guided cases. Full headless suite: **319 passed**;
Qt suite (guided+style) 35; stubbed GUI (test_gui+packaging) 81. Only
`test_comfort_chart_follows_the_unit_selector` needs real QtCharts (Windows).

## Where things stand

Dad's two requests are now both done:

1. **The heater** (previous session) — supplemental heating wired into the
   engine, twin and GUI. Committed as `d4b2edb`.
2. **The guided flow** (this session) — the single "one setup → full schedule"
   screen dad asked for, replacing the Schedule tab he found confusing.

### What was built this session (the guided flow)

Dad's ask: from one setup, enter farm dimensions, fan capacity, day-wise
target-temperature chart, bird age & weight and outside temperature, and get
back the required fans with on/off times, cooling-pad on/off times and heater
on/off times — and he said the old Schedule tab was confusing.

Delivered as a single scrollable page that replaces the Schedule tab:

- **`pcis/gui/widgets.py`** (new) — the shared, Qt-only widgets
  (`UnitAwareSpinBox`, `EnvelopeSurfaceEditor`, `_hint`, `_si_cell`,
  `_cell_si_value`, `_scrollable`) extracted out of `main_window.py`. This lets
  the guided page reuse them **without** importing `main_window` (which pulls in
  `QtCharts`). `main_window` now imports them from here — behaviour unchanged.
- **`pcis/gui/guided_model.py`** (new, Qt-free, fully unit-tested) — the pure
  logic: the day-wise Aviagen target-temperature curve, the schedule summary
  stats, and the one-line block descriptions. No new engineering — every number
  comes from `comfort_engine` / `growth_curve` / `digital_twin`.
- **`pcis/gui/guided.py`** (new) — `GuidedScheduleWidget`: one page, three
  numbered steps (farm & equipment, flock, weather-through-the-day), one
  **Build my schedule** button, and outputs: the **consolidated on/off blocks**
  (fans + pads + heater with times), a **summary strip** (peak fans, fan-hours,
  pad/heat hours, undersized/unreachable flags), the **day-wise target-temp
  chart**, and the model's honesty notes verbatim. Self-contained: the operator
  never has to visit another tab. The chart is drawn with plain `QPainter`
  (no `QtCharts` dependency).
- **`pcis/gui/main_window.py`** — the Schedule tab is replaced by the
  "Guided Schedule" tab; the old schedule-tab code (`_build_schedule_tab`,
  `run_schedule`, `_render_schedule`, the profile-table helpers) is removed;
  `_on_units_changed` now defers to `guided.set_unit_system`. The five other
  tabs (House & Equipment, Flock, Environment, Recommendation, History) are
  untouched and still there as the "advanced" views.
- **Cited envelope U-value presets** — most operators don't know their wall/
  ceiling U-value, so `pcis/core/envelope_presets.py` (new, Qt-free, cited)
  provides construction types (uninsulated / R-7 / R-13 / R-19 walls;
  R-12 / R-21 / R-30 ceilings) with U-values derived from University-of-Georgia
  poultry-housing R-value recommendations + ASHRAE surface films. The shared
  `EnvelopeSurfaceEditor` now has an **"Add a typical surface"** dropdown that
  inserts a row with the cited U-value (editable), and its seeded default rows
  use cited presets (sidewalls U=0.41 / R-13, ceiling U=0.26 / R-21) instead of
  the previous uncited guesses. This flows through to both the guided page and
  the House & Equipment tab.
- **Tests** — `tests/test_guided.py` (guided flow, ~20 tests) and
  `tests/test_envelope_presets.py` (new, presets/conversion). The old
  schedule-tab tests in `test_gui.py` were rewritten to target `window.guided`.

### Debug pass (this session)

Running `test_gui` under a lightweight QtCharts stub surfaced a **real,
pre-existing bug** that had been invisible since QtCharts stopped loading in the
sandbox: `test_metrics_reflow_to_fewer_columns_when_narrow` still hard-coded
"5 metrics", but earlier sessions grew the Recommendation panel to 8 (air speed,
bird-feels, heating). Fixed the test to be count-agnostic. Also smoke-tested the
guided page for age 0 (warns cleanly, no crash), imperial round-trip, empty
envelope, and inserting every preset — all fine.

### Test status

- Headless suite (everything not needing the QtCharts add-on): **334 passed**.
- Under the QtCharts stub, `test_gui.py` + `test_packaging.py`: **81 passed**;
  the only non-passing case is `test_comfort_chart_follows_the_unit_selector`,
  which reads real chart axis titles a stub cannot provide. `test_charts.py` is
  all chart-pixel behaviour and is not meaningfully runnable under the stub.
- `test_gui` / `test_charts` / `test_packaging` import `QtCharts` (via
  `main_window` → `charts`). They can't fully run in the sandbox because the
  PySide6 **Addons** wheel (~175 MB, which carries QtCharts) is too large to
  install within the sandbox's execution limit — but `MainWindow` construction,
  unit switching, the guided build, and the structural `test_gui` cases were all
  verified in-sandbox via the stub.
  → **Please run the full `pytest` on Windows once to confirm all green**
  (there it has real QtCharts).

## How to run it

`python -m pcis` → open the **Guided Schedule** tab. Fill the three steps, press
**Build my schedule**.

## Environment notes (important for the sandbox)

- **Qt rendering in the sandbox is fixed.** The `libEGL.so.1` that went missing
  last session can be restored **without root**:
  `apt-get download libegl1 libglvnd0 libglx0 libgles2`, then `dpkg -x` each
  `.deb` into a local dir and point `LD_LIBRARY_PATH` at its
  `usr/lib/x86_64-linux-gnu`, with `QT_QPA_PLATFORM=offscreen`. With that,
  `PySide6-Essentials` (QtWidgets/QtGui) renders and screenshots fine. Only the
  175 MB **Addons** (QtCharts) wheel won't install in-sandbox — which is exactly
  why the guided chart avoids QtCharts.
- Repo is the connected folder `PCIS_flat` (OneDrive-synced). The OneDrive mount
  blocks the sandbox from removing `.git/index.lock`, so **commits must be run
  from your own terminal** (commands below).

## Engineering-honesty rule (unchanged, non-negotiable)

Every equation/constant traces to a cited published source (ASHRAE, CIGR,
Aviagen, manufacturer data). Never fabricate numbers. The guided page adds **no**
engineering of its own — it only gathers input and arranges already-cited
results, and it surfaces the model's warnings (undersized fans, unreachable
target, heating needed, clamped RH) verbatim rather than hiding them.

## Possible next steps (not started)

- Run the full suite on Windows and confirm the QtCharts-dependent tests pass.
- Optional: a "save/load setup" so a farm's inputs persist between sessions.
- Optional: let the guided page also export its schedule to the PDF report.
