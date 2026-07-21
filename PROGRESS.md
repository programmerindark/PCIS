# PCIS — Poultry Climate Intelligence System

## Status: engineering core, equipment data, recommendation engine, persistence, validation, PDF reports, a working PySide6 desktop GUI, and embedded charts are all functional and tested end-to-end. Cooling-pad data has been upgraded with a second cited source. A Ross 308 growth-curve module is built and ready for the digital twin, which is paused per your instruction.

**180/180 unit tests passing.** ~3,950 lines of source, ~2,150 lines of tests.

---

## Architecture

```
pcis/
  core/                   Pure computation. No I/O. Every function cites its source.
    psychrometrics.py     Moist-air properties (ASHRAE Fundamentals 2017 / Buck 1996)
    bird_metabolism.py    Per-bird heat/moisture/CO2 (CIGR 2002, via Aarnink 2018 / Pedersen 2008)
    heat_moisture_balance.py   Envelope conduction + flock load aggregation
    ventilation_solver.py Required airflow (heat/moisture/CO2/Aviagen minimum-vent), fan sizing
    comfort_engine.py     Target temperature, THI, composite Bird Comfort Index
    recommendation_engine.py  Ties the above into fan/pad decisions + confidence score
    validation.py          Predicted-vs-measured error metrics + linear calibration fitting
    growth_curve.py        Ross 308 as-hatched weight-for-age (Aviagen 2022) -- built for
                            the digital twin, currently paused; usable standalone too
  equipment/              Manufacturer data, each record carries a provenance citation
    fan_curve.py           Big Dutchman AirMaster V130/VC130 (4 real curves)
    cooling_pad.py          Munters CELdek 7090-15 specs + MSU Extension AND UGA
                             Extension design points (two independent citations now)
  db/                      SQLAlchemy 2.0 (SQLite now, Postgres-portable later)
    models.py, session.py  HouseConfig, FlockRecord, RecommendationLog, MeasurementRecord, CalibrationFactorRecord
  reports/
    pdf_report.py           ReportLab PDF rendering of a Recommendation
  gui/
    main_window.py          PySide6 desktop app: 4-tab MainWindow, no new
                             engineering logic -- pure wiring into core/*
    charts.py                Embedded QtCharts widgets (fan curve, comfort/temperature bars)
tests/                     One test file per module, 180 tests total
```

---

## What's real vs. what's flagged

Every module cites its engineering sources in its docstring. Where I could not find or verify a number, I did not invent one — instead I raised `NotImplementedError`, required the caller to supply the value, or clearly labeled the number as an assumption/estimate. Summary of the honesty flags still standing:

- **`bird_metabolism.py`**: the CIGR (2002) broiler formula itself is known (per its own peer-reviewed critique) to be oversimplified — total heat depends only on body weight, not feed intake; sensible/latent split depends only on temperature, not weight. This is a documented limitation of the accepted method, not a shortcut I took.
- **`comfort_engine.py`**: `bird_comfort_index` is **PCIS's own composite synthesis**, not a published/validated instrument. Its component metrics (target temperature, THI) are individually cited; the scoring weights are named constants flagged as engineering judgment pending real-data calibration.
- **`cooling_pad.py`**: Munters' actual velocity-vs-efficiency curves are still only published as chart images, not machine-readable data, so there is still no continuous curve. But both design points are now doubly-sourced: the 150mm pad (350 fpm, 70-75% efficiency) is cited to both MSU Extension P3329 and, as of your uploaded PDF, UGA Cooperative Extension Vol. 26 No. 4 (2014); the 100mm pad (225 fpm, 70-75% efficiency) is now cited to that same UGA source, upgraded from the previous unverified 0.65 placeholder. A cited pad static-pressure figure (~0.05 in. W.C.) was also added.
- **`fan_curve.py`**: loaded under Big Dutchman's own "AirMaster V130/VC130" branding; a naming discrepancy with your "Multifan 130" terminology is flagged and unresolved pending your Viper Touch simulator's exact model code.
- **`heat_moisture_balance.py`**: envelope U-values/R-values are caller-supplied, not hardcoded for named insulation materials (no verified source for a materials table). Floor/ground-coupled heat loss is explicitly not modeled (needs a different method than simple U·A·ΔT).
- **`recommendation_engine.py`**: confidence score deductions are all named and explained in the output — never a black box.
- **`growth_curve.py`**: Ross 308/308 FF **as-hatched only**, days 0-56, transcribed from the current Aviagen 2022 Performance Objectives booklet. Per your instruction, Cobb 500 is explicitly out of scope -- no Cobb table exists and no code assumes one.
- **`db/models.py`**: `FlockRecord.breed` is stored for record-keeping only; the engineering core is not currently breed-specific (Aviagen/Ross-sourced tables throughout) -- consistent with Cobb being explicitly skipped.
- **`gui/charts.py`**: uses `PySide6.QtCharts` rather than Plotly (named in the original brief) -- see the "Charts: why QtCharts, not Plotly" note below for the reasoning; flagged here as a deliberate deviation, not a silent substitution.

---

## Module-by-module detail

### `psychrometrics.py`
Saturation vapor pressure (Buck 1996), dew point (numerical inversion, exact round-trip), humidity ratio ↔ RH, wet-bulb temperature (ASHRAE energy balance, bisection solve), `humidity_ratio_from_wet_bulb` (direct evaluation, added to support evaporative-cooling calculations), enthalpy, specific volume, density. 32 tests, cross-checked against steam tables and published psychrometric-chart reference points.

### `bird_metabolism.py`
`total_heat_production` (CIGR Eq. 11), `sensible_heat_production`/`latent_heat_production` (CIGR Eq. 13), `moisture_production`, `co2_production` (Pedersen et al. 2008 Table 6). Cross-checked against a published measured-vs-calculated chart. 13 tests.

### `heat_moisture_balance.py`
`envelope_conduction_loss`/`total_envelope_conduction_loss` (Q=UA·ΔT), `flock_load` (per-bird × bird count), `net_house_load` (bird heat − envelope loss + supplemental heat). 10 tests.

### `ventilation_solver.py`
`minimum_ventilation_rate_aviagen` (Aviagen 2018 table, cold-weather minimum), `required_airflow_for_sensible_heat`/`required_airflow_for_moisture` (ASHRAE mass/energy balance), `co2_ventilation_requirement` (dilution ventilation, Aviagen 3000ppm default), `air_changes_per_hour`, `tunnel_airspeed`, `governing_airflow`, `required_fan_count`. 20 tests.

### `comfort_engine.py`
`target_temperature` (Aviagen/Dr. Malcolm Mitchell table, weight+RH bilinear interpolation), `thi_tao_xin`/`thi_marai` (published broiler THI formulas), `bird_comfort_index` (composite, flagged as PCIS synthesis). 17 tests.

### `fan_curve.py` / `cooling_pad.py`
Real manufacturer/extension-sourced equipment data with mandatory provenance strings. 11 + 18 tests. `cooling_pad.py` now cites two independent extension sources per pad depth (MSU Extension P3329 and, from your uploaded PDF, UGA Cooperative Extension "Poultry Housing Tips" Vol. 26 No. 4, Czarick & Fairchild, 2014) plus a cited pad static-pressure figure.

### `growth_curve.py`
`ross_308_body_weight_kg(age_days)` — day-by-day as-hatched body weight, days 0-56, transcribed directly from Aviagen's current Ross 308/308 FF Performance Objectives 2022 booklet (fetched and parsed in this session, not estimated). Linear interpolation for fractional ages; refuses to extrapolate past day 56, matching the project's standing "never invent a number" rule. Built as groundwork for the digital twin (which needs a weight trajectory to simulate a multi-day grow-out) — the twin itself is paused, but this module is complete, tested, and usable on its own (e.g. for "what will my flock weigh on day N"). 6 tests.

### `recommendation_engine.py`
`recommend(...)` — single entry point combining all of the above into fans-on/pads-on/confidence-score output with full engineering explanation. 8 tests, plus verified realistic end-to-end scenarios.

### `validation.py`
`error_metrics` (bias/MAE/RMSE/MAPE), `fit_calibration` (OLS linear correction, R²), `residuals`. Generic, not poultry-specific — the "compare predicted vs. measured, then calibrate per house" requirement from the original spec. 14 tests.

### `db/` (models.py, session.py)
`HouseConfig`+`EnvelopeSurface`, `FlockRecord`, `RecommendationLog`, `MeasurementRecord`, `CalibrationFactorRecord`. Full save/fetch helper functions. 23 tests (15 original + 8 validation-persistence).

### `reports/pdf_report.py`
`generate_recommendation_report(...)` — ReportLab PDF with flock summary, environmental conditions, comfort assessment, recommendation, and the full explanation list rendered verbatim (nothing summarized away). 4 tests verifying actual extracted PDF text, not just "didn't crash".

### `gui/main_window.py`
A `QTabWidget`-based desktop app: **House & Equipment** (house dimensions, an editable envelope-surface table backed 1:1 by `heat_moisture_balance.Surface`, fan model picker populated from `FAN_CATALOG`, cooling-pad picker populated from `COOLING_PAD_CATALOG` with "no pad installed" as a valid choice), **Flock** (breed — labeled informational-only in the UI itself, bird count, body weight), **Environment** (indoor/outdoor T & RH, design ΔT, outdoor CO₂ background), and **Recommendation** (Run button → calls `recommendation_engine.recommend()` with the gathered inputs, displays fans-on/pads-on/airflow/governing-constraint/confidence, lists every explanation line verbatim, then Save-to-Database and Export-PDF buttons).

The window contains **no new engineering logic** — `gather_inputs()` is a pure widget-to-dict reader, and every computed number comes from a `core/*` function that already has its own citation and unit tests. Invalid input (e.g. a non-numeric envelope cell) raises `ValueError`, caught and surfaced as a `QMessageBox.warning` rather than crashing or silently defaulting.

Verified end-to-end headlessly (`QT_QPA_PLATFORM=offscreen`): construct window → fill defaults → run recommendation → save to SQLite → export a real, text-verified PDF, all in one pass. 11 tests in `tests/test_gui.py` cover the envelope-surface editor, input gathering, the run/save/export flow, and the bad-input warning path. `tests/conftest.py` defaults `QT_QPA_PLATFORM` to `offscreen` so the whole suite runs without a display. One testability note worth recording: `save_to_database`/`export_pdf` each end with a `QMessageBox.information(...)` confirmation dialog — correct, desirable behavior for an interactive user, but a blocking modal with no one to click OK will hang forever in a headless run. Tests patch `QMessageBox.information`/`.warning` to no-ops to observe return values without blocking; this is a test-harness workaround only, the production dialogs are unchanged.

### `gui/charts.py`
Two embedded chart widgets, wired into `main_window.py`:
- **`FanCurveChartWidget`** (House & Equipment tab): plots the selected fan's actual tested airflow-vs-static-pressure points (`FanCurve.static_pressure_pa`/`airflow_m3_per_h`) as a line, with the current design static pressure marked as an operating point. Updates live when you change the fan model or static pressure spinner.
- **`ComfortChartWidget`** (Recommendation tab): a 4-bar chart (outdoor / supply-post-pad / indoor / target dry-bulb temperature) plus a title line reporting THI, THI stress class, and the composite comfort index -- all pulled directly from the `Recommendation` object, no new numbers computed in the chart code.

**Charts: why QtCharts, not Plotly.** The original brief named Plotly. Plotly renders to HTML/JS and does not embed into a native desktop Qt widget without `QtWebEngine` -- a large embedded-Chromium dependency that is fragile in minimal/headless environments (the same kind of environment this GUI is smoke-tested in). `PySide6.QtCharts` ships with PySide6 itself, renders natively, and its series data can be read back and asserted on directly in headless pytest (no screenshot/pixel comparison needed) -- see `tests/test_charts.py`. This is a deliberate substitution, flagged rather than silent; Plotly remains an option later for an HTML export view if you want one.

5 tests in `tests/test_charts.py` confirm each chart is plotting the real values it was given (not just "didn't crash"): fan curve point count/values match the `FanCurve` data, the operating-point marker matches `airflow_at_static_pressure`, and the comfort bars/title match the `Recommendation`/`ComfortAssessment` fields exactly.

---

## Verified end-to-end (not just unit-tested in isolation)

1. **Recommendation pipeline**: 20,000-bird, 2.5kg house, hot day (38°C outdoor / 29°C indoor target) → flock load → envelope loss → governing ventilation constraint → real fan curve → 5 fans, pads ON, confidence 70/100, full explanation.
2. **Persistence round-trip**: house config → flock record → recommendation → saved to SQLite → retrieved, all fields consistent.
3. **Validation/calibration round-trip**: synthetic predicted-vs-measured indoor-temperature readings → error metrics computed → linear calibration fit and persisted → retrieved.
4. **PDF report**: generated from a real `Recommendation` object, text-extracted and checked against the source data (not just file-exists).
5. **GUI, full loop**: `MainWindow` constructed headlessly → default inputs gathered from every tab → `Run Recommendation` produced a real result (11 fans, pads off, confidence 85/100 on the seeded defaults) → `Save to Database` persisted house/flock/recommendation rows to SQLite, confirmed by querying them back → `Export PDF` wrote a real PDF, confirmed non-empty on disk.
6. **GUI charts, full loop**: `MainWindow` constructed headlessly → fan curve chart auto-populated from the default fan selection with 2 series (curve + operating point) → `Run Recommendation` → comfort chart populated with 4 real temperature bars (38.0, `supply_air_t_c`, `comfort.t_c`, `comfort.target_temp_c`) and a title reporting the actual THI/comfort-index values.

---

## Explicitly out of scope (your instruction)

- **Cross-ventilation / natural-ventilation modeling** — skipped for now. Only tunnel/mechanical ventilation sizing is implemented; nothing in the codebase assumes natural ventilation will be added later, so this is a clean deferral, not a partial/broken feature.
- **Cobb 500 (or any non-Ross breed)** — skipped for now. `growth_curve.py` is Ross 308/308 FF only; `FlockRecord.breed` remains a free-text, informational-only field with no engineering logic reading it. Adding Cobb later would mean sourcing a real Cobb 500 performance-objectives table and adding a parallel growth-curve/target-temperature path -- not attempted here since you said to skip it.

## Paused (your instruction: "digital twin can wait")

- **Digital twin** — groundwork is done (`growth_curve.py`, real Ross 308 weight-for-age data) but the simulation module itself was not built once you flagged it as lower priority mid-session. Design plan for when you're ready to resume: step through a grow-out day-by-day using `growth_curve` for bird weight, reuse `recommendation_engine.recommend()` at each step to get the target indoor setpoint / fan-and-pad decision, then -- if you also want to model a house with a *fixed, physically-installed* fan count (rather than the "however many fans are needed" the recommendation engine currently assumes) -- solve the actual achieved indoor temperature/humidity/CO2 from the energy/moisture/CO2 balance equations already implemented in `heat_moisture_balance.py`/`ventilation_solver.py` when that installed capacity is insufficient. No new engineering constants would be needed; it would purely recombine what's already built and cited.

## Not yet built

- **Cooling-pad continuous velocity-vs-efficiency curve** — two independent design-point citations now exist (MSU + UGA Extension, see above), but still no continuous manufacturer curve; would need the actual CELdek chart data (image or export) from you or the Viper Touch simulator.
- **Packaging as a standalone Windows executable** (e.g. PyInstaller) — currently runs as a Python app via `python -m pcis.gui.main_window` with `pip install -e ".[gui]"`.
- **AI-based recommendations** — explicitly "later" per the original project plan.

## How to run the GUI

```
pip install -e ".[gui]"
python -m pcis.gui.main_window
```

## Suggested next step

The engineering core, persistence, reporting, GUI, and charts now all work together end-to-end against real, cited data (180/180 tests passing), with cooling-pad data upgraded to two independent citations. When you're ready, say the word and the digital twin (design already sketched above) is the natural next build.
