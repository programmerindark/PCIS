# PCIS — handoff for next session

_Last updated: 2026-07-23 (guided flow session)_

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
- **Tests** — `tests/test_guided.py` (new, 18 tests, run headlessly) covers the
  curve, the summary/block formatting, and the widget (build, blocks, unit
  round-trip, age→weight auto-fill, chart marker, shortfall notes). The old
  schedule-tab tests in `test_gui.py` were rewritten to target `window.guided`.

### Test status

- Headless suite (everything not needing the QtCharts add-on): **327 passed**,
  including the 18 new guided tests.
- `test_gui.py` / `test_charts.py` / `test_packaging.py` import `QtCharts`
  (via `main_window` → `charts`). They could not be run in the sandbox this
  session because the PySide6 **Addons** wheel (~175 MB, which carries QtCharts)
  is too large to install inside the sandbox's execution limit. They should run
  normally on your Windows machine, where PySide6 is fully installed.
  → **Please run the full `pytest` on Windows once to confirm all green.**
  Construction of `MainWindow` and the changed `test_gui` structural tests were
  verified in-sandbox using a lightweight QtCharts stub, so the wiring is sound;
  the only thing the stub cannot check is chart pixel/axis behaviour.

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
