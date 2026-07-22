# PCIS — Poultry Climate Intelligence System

## Status: engineering core, equipment data, recommendation engine, persistence, validation, PDF reports, a working PySide6 desktop GUI, and embedded charts are all functional and tested end-to-end. Two real-world usability issues reported after a working farm operator demoed it (indoor RH sometimes hits 80%, and weight should follow bird age) are now fixed. Every recommendation run is logged automatically (by bird age/day and timestamp, with outputs) as soon as you hit "Run Recommendation" -- no separate save step -- and the accumulated history can be exported as a CSV for future ML/calibration work. The Ross 308 growth-curve module is wired into the GUI and ready for the digital twin, which is still paused per your instruction pending the fan-scheduling feature below.

**367/367 unit tests passing.** ~5,400 lines of source, ~3,600 lines of tests.

### Latest changes (History tab — data curation)

You spotted the real hole: every "Run Recommendation" click was logged identically, exploratory clicks and mistyped numbers included, with no way to see the history or remove garbage. Capture without curation isn't a dataset, it's noise.

Added a **History tab** and the schema/DB support behind it:

- **See every logged run** in a table — when, house, age, conditions, the decision, confidence, and whether it's flagged as a test.
- **Mark runs as test vs real.** A "Log this as a test run" checkbox on the Recommendation tab tags exploratory runs up front; the History tab lets you re-tag any row afterwards. Test rows stay visible but are excluded from the training export. Reversible.
- **Delete garbage permanently**, with a confirmation prompt. Deletion is real (that's the point); the dialog steers you toward "mark as test" if you only want it out of the export rather than gone.
- **Two export modes:** the full dump (every row, with an `is_test` column so you can filter downstream) and "Export real data (CSV)" which drops test rows entirely.

Schema: `RecommendationLog` gained `is_test` and `note` columns; `session.py` gained `all_recommendation_logs`, `count_recommendation_logs`, `delete_recommendation_logs`, `set_recommendation_test_flag`, `set_recommendation_note`; the CSV export gained an `exclude_test` option. 20 new tests (12 GUI + 5 DB + existing coverage extended).

**A process note worth recording honestly:** building this, I corrupted the working tree by copying an older snapshot over the current one and lost the dark-theme and packaging work from the in-progress copy. Recovered by rebuilding from the last shipped release (v18) and re-applying the History changes onto it cleanly. Everything verified green afterwards — but it's a reminder that this project has been carried in two parallel directories the whole time, and that's exactly the kind of drift the app's own "one source of truth" rule exists to prevent. The repository on GitHub should be the single source from here.

### Latest changes (dark mode — desktop)

Running Windows in dark mode made the app partly unreadable: the engineering explanation panel rendered near-black text on a dark grey background.

**Root cause.** The stylesheet only ever defined light colours. Any widget it did not explicitly name — `QTextBrowser`, plain container widgets, `QMessageBox`, `QFileDialog` — fell through to the *system* palette. On a dark desktop Qt painted those dark while our authored text stayed dark. Not a contrast oversight; a half-styled application.

**Fix.** `style.py` now carries two complete palettes with identical keys and builds the stylesheet from whichever is active, and `apply_theme()` sets a matching `QPalette` as well — the stylesheet covers widgets it names, the palette catches everything it doesn't. Theme follows the OS by default, detected from Qt's own reported window colour rather than per-platform registry reads. `ExplanationView` and the status banners now read the live palette instead of import-time constants, which is precisely why they kept painting dark text after the theme changed.

**Three further defects surfaced while fixing it:**

- **A quadratic slowdown I introduced.** Applying the theme from `MainWindow.__init__` set an *application-wide* stylesheet, forcing Qt to re-polish every widget of every existing window. Invisible with one window; the 49-window test suite stopped dead. Now guarded by `ensure_theme()`, which applies once per process.
- **Eleven hard-coded hex values** still sat inside the stylesheet builder — including the table header band, which stayed white on a dark window. All mapped to palette keys; a test now fails if any literal colour reappears.
- **My own column fix clipped the headers.** Switching tables to `Interactive` let users resize columns but left them at Qt's default width, so "Surface name" rendered as "urface nam". Columns are now sized to their header text once, then remain draggable.

`QChart` needed separate handling: it paints its own opaque white plot area and dark axis labels, neither reachable from the widget stylesheet. Making it transparent alone would have hidden the labels, so `_theme_chart()` moves background, title, legend, axis labels and gridlines together.

`tests/test_style.py` (13 tests) guards the palette contract: both themes define identical keys, every value is a valid hex colour, the generated stylesheet contains no literal colours, and every text-bearing widget class is explicitly named.

### Latest changes (UI audit pass)

A systematic audit of the desktop app: an automated pass over the widget tree at three window sizes checking for overflow, clipped text, inconsistent control sizing and missing accessible names, plus visual inspection of rendered screenshots at the window's **minimum** size — which is where layouts actually break and where every defect below was found.

| # | Severity | Defect | Root cause |
|---|---|---|---|
| 1 | **Major** | "GOVERNING CONSTRAINT" and "CONFIDENCE" rendered touching, reading as one run-on label | Five equal-width grid columns; captions differ ~3x in length, so equal widths cannot fit the longest at 940px |
| 2 | **Major** | Empty chart frame — a titled box with no axes — occupied ~190px above the fold before any run | Chart widget always constructed and shown, with no empty state |
| 3 | **Major** | Pressing "Build Schedule" appeared to do nothing at minimum size | Results render below the fold; nothing scrolled them into view |
| 4 | **Minor** | Every input lacked a tooltip and accessible name | Never added; screen readers had nothing to announce |
| 5 | **Minor** | Table columns could not be resized | `QHeaderView.Stretch` locks widths; long surface names were unreadable |
| 6 | **Minor** | Header labels rendered ~1.5pt smaller than every other label | Header sits outside the tab tree and fell back to Qt's platform default instead of the stylesheet base |
| 7 | **Minor** | Dead space in the Schedule settings card | `minimumHeight` set to 400px for ~250px of content |

**Fixes.** `MetricsPanel` replaces the fixed grid and recomputes its column count from the available width, wrapping to a second row when narrow. Charts start hidden behind a short instruction and appear once there is data. Both action buttons scroll their results into view. Every input carries a tooltip and accessible name, set in one place. Tables became `Interactive` with a stretching last column and alternating row colours.

**Two findings were false positives, and checking mattered.** The audit flagged 16 "undersized" `QLineEdit`s — all internal editors of spinboxes, not fields. It also flagged inconsistent button heights, which turned out to be the intentional 44px primary action versus 40px secondary buttons on different rows. Both were verified before being "fixed"; blindly acting on either would have made the app worse.

**A measurement bug worth recording:** the audit script initially reported problems that were already fixed. `python /tmp/audit.py` puts the *script's* directory on `sys.path`, not the working directory, so it silently imported a different installed copy of `pcis`. Every conclusion from a tool like this is only as good as the code it actually loaded.

**Deliberately not changed:** table sorting stays off. The envelope table and the outdoor profile are *ordered* data — sorting the profile by temperature would destroy the chronology the simulation depends on.

**Scope note:** the audit brief listed screens this app does not have — Dashboard, Settings, Help/About, menu bars, export dialogs beyond the two file pickers. PCIS has five tabs, two file dialogs and three message-box paths. Everything that exists was audited; nothing was invented to match the list.

### Latest changes (mobile web build — offline PWA)

`web/` is a mobile web app that runs **the actual Python engineering core in the browser** via Pyodide (CPython compiled to WebAssembly). Deployable to Vercel as static files; installable to a phone home screen; works with no signal after first load.

**Why this shape, and not a rewrite.** The alternative was porting `pcis/core` to JavaScript. That would be smaller and faster to start, but it would create a second source of truth for the physics — every Aviagen table and confidence deduction maintained twice, in two languages, drifting silently. The browser instead loads the *same* `.py` files the desktop app and the test suite use, built by `tools/build_web_payload.py`.

**What made it possible:** `pcis.core` and `pcis.equipment` import only `math`, `bisect` and `dataclasses` — pure standard library. `pyproject.toml` had declared `numpy` and `scipy` as base dependencies, but **nothing in the codebase ever imported either**; they're now removed. SQLAlchemy, reportlab and PySide6 moved to extras (`db`, `reports`, `gui`, or `desktop` for all three), so the base package installs with zero third-party dependencies. Verified by installing it into a clean venv with no extras and computing a real recommendation.

**Parity is verified, not assumed.** Five scenarios — pads on/off, target reachable/unreachable, extreme heat, cold weather, two fan models — were run through native CPython and through WebAssembly and compared byte-for-byte on fan count, airflow, governing constraint, confidence, THI, comfort index and supply-air temperature. Identical across all five. The desktop screenshot's 10 fans / 317,626 m³/h / moisture-governed / confidence 85 reproduces exactly in the browser.

**Measured performance** (Pyodide 0.28, Node harness): runtime boot ~3.5 s, engineering core load ~50 ms, and ~117 ms to compute a recommendation *plus* an 8-step schedule simulation. The 3.5 s is a one-time cost — the service worker caches the runtime, so subsequent launches are fast and need no network.

**Deliberately a subset, not a shrunken desktop.** The phone shows the daily loop (age, bird count, indoor/outdoor conditions → fans, pads, confidence, unreachable-target warning) plus the schedule. Envelope U-values and house dimensions stay on the desktop behind a collapsed "setup" section — configuring those by thumb would be miserable, and they change rarely.

**Still missing on mobile:** no data logging (the desktop's automatic `RecommendationLog` needs SQLAlchemy, absent in the browser), no PDF export, no unit switching, and the schedule chart is a table rather than a graph. Logging is the notable gap — the phone is where field readings would naturally be captured, so this is the obvious next piece.

### Latest changes (GUI overhaul)

The desktop app was restyled and reorganised, and the digital twin finally has a UI.

- **Visual pass.** Calm slate/teal palette with saturated colour reserved for things that carry meaning (status, warnings) — if everything is colourful nothing reads as urgent. Larger base type, card-grouped inputs, explicit focus rings for keyboard entry, and headline result metrics rendered large enough to read at a glance.
- **Unit selector (metric / imperial).** Display-only by construction: `UnitAwareSpinBox` stores SI internally and converts only for presentation, so the solver and the database never see anything but SI. `pcis/gui/units.py` holds the conversions with exact definitional factors (1 ft = 0.3048 m, 1 lb = 0.45359237 kg), and `tests/test_units.py` checks them against independent reference points (water freezing/boiling, a known CFM figure) rather than against the code's own arithmetic.
- **Schedule tab** — the digital twin, now usable without writing Python. Edit the day's outdoor profile, set bird age and installed fan count, get the consolidated schedule ("09:00 – 21:00: 6 fans, pads ON"), a fan-count-vs-temperature chart, and the warnings inline.
- **Windows sizing.** Every tab scrolls, inputs have minimum heights, and sizes are in points — so 125%/150% display scaling (the default on most Windows laptops) no longer squeezes controls out of reach.

**Five defects found by actually looking at rendered screenshots**, not by tests passing:

1. **Schedule tab's buttons drew on top of its table.** Qt lays out a `QGroupBox`'s children using layout margins, which know nothing about the stylesheet's `padding`. Compounded by the tab not scrolling, so widgets were squeezed below their stated minimums. Fixed at the cause for every card at once.
2. **The comfort chart's y-axis started at 18.7 °C**, rendering a 20.7 °C target as a sliver beside a 35 °C supply bar — implying a ~20x difference where the real one is under 2x. Now zero-baselined. (Noted in the code: temperature is an interval scale, so bar *length* isn't strictly meaningful either way — the honest reading is the gap between bars.)
3. **The explanation list silently truncated with an ellipsis.** `QListWidget`'s word wrap doesn't work for long strings, so the single most important sentence on the screen — the unreachable-target warning — ended mid-clause while looking complete. Replaced with a view that actually wraps, and warnings/deductions are now colour-tinted.
4. **Unit switching reinterpreted the schedule table instead of converting it**, reading an on-screen "24" as 24 °F rather than converting the 24 °C it represented. Caught by a test written for exactly this.
5. **Unit round-trips drifted.** 150 m → 492.13 ft → 150.0012 m per toggle, compounding. Spinboxes and table cells now retain exact SI behind the rounded display.

**One inconsistency deliberately left, and labelled:** the engineering explanation text stays in SI even in imperial mode. Converting it would mean regex-rewriting numbers out of prose (a wrong match silently corrupts an engineering statement) or teaching the solver about display units. The panel says so on screen instead of quietly disagreeing with the header.

### Latest changes (Munters pad curve digitized — and a disagreement it exposed)

You supplied the CELdek 7090-15 product sheet, so the saturation-efficiency curve is now in the code: `MUNTERS_CELDEK_7090_SATURATION_EFFICIENCY_PCT` (all four plotted depths — 100/150/200/300 mm — read at the chart's labelled gridlines) plus `saturation_efficiency_at_velocity()` to interpolate, `exceeds_droplet_risk_velocity()` for the shaded carry-over zone, and a stated **±3 percentage point reading tolerance**, because these are chart-read values and not published numbers.

**The curve disagrees with the design guidance already in the module, and the gap is not small:**

| 150mm pad @ 1.78 m/s design velocity | Saturation efficiency |
|---|---|
| Munters product-sheet curve (laboratory) | ~90% |
| MSU / UGA Extension design guidance (field) | 70–75% |

15 percentage points. It's robust to my chart-reading error — even the *thinnest* pad Munters plots (100mm) reads ~84% at that velocity, still well above the extension figure. This is the standard laboratory-versus-field gap: Munters' number is a new pad, perfectly and uniformly wetted, no bypass air, no scaling, no aging; the extension number derates for exactly those things.

**The default was deliberately left on the conservative extension figure.** Concretely, on a 38 °C / 30% RH day: the extension figure predicts 27.2 °C supply air, the Munters figure predicts 25.1 °C — 2.2 °C colder. Colder predicted supply air flows straight through to lower required airflow and *fewer recommended fans*. Adopting the lab number would quietly make every cooling recommendation more optimistic for houses that are neither new nor perfectly maintained, and being wrong in that direction means under-ventilated birds in a heat wave. The manufacturer curve is available to callers who explicitly want "what's the best this equipment could do", and there are tests (`test_defaults_still_use_the_conservative_extension_figure`) specifically to stop anyone quietly switching the default to the more flattering number later.

**What would actually settle it:** a measured supply-air temperature from one of your real houses on a hot day, logged against the prediction via `pcis.core.validation`. That's the only thing that can say which figure describes *your* pads. Two published numbers disagreeing is a reason to measure, not a reason to pick the nicer one.

### Previous changes (unreachable-target warning now on the main screen)

The warning the digital twin was surfacing is now built into `recommendation_engine.recommend()` itself, so it reaches **every** consumer — the Recommendation tab, the PDF report, the digital twin, and the saved dataset — from one definition:

- **`Recommendation.target_unreachable`** is set whenever supply air is at or above the comfort target. The explanation text lives in one named constant (`TARGET_UNREACHABLE_WARNING`) so all four surfaces say it identically rather than paraphrasing a safety caveat four different ways. The digital twin now *reads* this flag instead of re-deriving the rule — two copies of a safety check is one copy too many.
- **The Recommendation tab shows it in red, directly under the fan count**, because that adjacency is the entire point: "Fans ON: 6" on its own reads as *run 6 fans and you'll hit target*, which is false whenever this flag is set. The warning states plainly that more fans will not close the gap.
- **Deliberately NOT folded into the confidence score.** Confidence means "how well-sourced are these numbers"; unreachability is not an uncertainty, it's a physical certainty. Deducting for it would blur a well-defined meaning *and* make the app look less sure exactly when it's most sure something is wrong. It gets its own flag. There's a test asserting the confidence score is unchanged by it.
- **`supply_air_t_c`, `supply_air_rh_pct`, and `target_unreachable` are now persisted** to `RecommendationLog` and the training CSV. This matters for the ML work specifically: `fans_on` means something different when the target was unreachable ("run what you have" rather than "this achieves target"), so a model trained without that column would be learning from mislabelled examples.

### Previous changes (digital twin — the fan-schedule feature your dad asked for)

`pcis/core/digital_twin.py` is built and tested (38 tests). It answers the question the current app couldn't: **"how many fans, at what time, should be on for how long?"** Two entry points:

- **`simulate_schedule(...)`** — a day in the life. You give it the outdoor conditions at each point in the day; it returns the fan count and pad state at each step, then collapses consecutive identical staging into blocks ("09:00 - 21:00: 6 fans, pads ON").
- **`simulate_grow_out(...)`** — the same weather across advancing bird age, isolating how the requirement grows with the flock. Bird weight comes from the real Aviagen table at each age, and the indoor target temperature is derived from it, so staging genuinely changes with the grow-out stage.

`format_schedule_table(...)` renders either as a plain-text table with the warnings inline.

**Three things it deliberately refuses to do**, each of which would have made the output look better while making it less true:

1. **It does not invent weather.** There is no built-in diurnal temperature curve, because a defensible one is site- and season-specific and I have no cited source for yours. You supply the profile from your own records. Every number downstream would otherwise inherit a fabricated input.
2. **It does not extrapolate bird age.** Ages outside the published Aviagen range raise rather than guess.
3. **It does not cap the fan count at what you have installed.** If a step needs 14 fans and you own 8, it reports 14 and flags the shortfall. Capping it would hide the problem.

**Three real findings that came out of building it** (all now documented in the module docstring and locked in by tests):

- **Fan requirement is not always monotonic in bird age.** For one real house config at a fixed 30C day: 3 fans at day 7, but only 2 at day 14. Not a bug — at day 7 the governing constraint is *moisture removal*, from day 14 it's *sensible heat*, and the two don't hand over smoothly. `governing_constraint` on every step tells you which is in charge.
- **Day 0 cannot be simulated at all.** The Aviagen growth curve starts at 0.044 kg but the Aviagen minimum-ventilation table starts at 0.05 kg. That's a gap between two Aviagen publications, not something PCIS will paper over by picking a number. `MIN_SIMULATABLE_AGE_DAYS` (derived from the two tables, currently day 1) detects it up front with a message that explains the actual cause.
- **⚠ The biggest one: the target indoor temperature is often physically unreachable, and the app was not saying so.** Ventilation can only move the house toward the supply-air temperature — it can never cool below it. On a 37C afternoon, post-pad supply air is ~28C while 35-day birds want ~20.7C. The old code still returned a finite fan count, which reads as "run this many and you'll hit target." You won't. Every step is now checked (`SimulationStep.target_unreachable`) and the schedule says so plainly, including that *more fans will not help* — the fix is more evaporative capacity or accepting a higher indoor temperature. **Note this affects the main Recommendation tab too, which does not yet carry this warning — see "Not yet built" below.**

### Previous changes (recording is now automatic, not a button)

- **No more "Save to Database" button.** Every time you click "Run Recommendation," the run is logged to the database immediately and silently -- the inputs (house, age, flock, environment) and outputs (fans/pads decision, airflow, confidence, full comfort breakdown) are all written in one step. A small status line under the explanation list confirms each log ("Logged automatically: 'House 1', age 35 days, ..."), but there's nothing to click and no dialog to dismiss.
- **`get_or_create_house_config`** (new in `db/session.py`) makes this safe to call on every single run: `HouseConfig.name` is a unique column, so a plain create would fail the second time you ran a recommendation for the same house. This helper fetches the existing house (refreshing its dimensions/envelope surfaces to whatever you last entered) instead of erroring.
- **"Export Training Data (CSV)" stays a manual button** -- exporting a file for external use is a different action from recording it, and still needs you to choose where the file goes. It now pulls from a history that's growing on its own from ordinary use of the app, rather than requiring you to remember to save first.

### Previous changes (data logging for ML)

- **Every logged recommendation is a self-contained, ML-ready training row.** `RecommendationLog` gained an `age_days` column (bird age at the moment of that snapshot -- nullable, since not every historical caller supplies it) plus the full comfort-assessment breakdown that used to only exist in memory: `target_temp_c`, `deviation_c`, `thi`, `thi_class`, `comfort_index`, and `target_temp_rh_clamped`. So a saved row now captures not just the fan/pad decision but the derived features behind it.
- **Not yet done: fan-on/off scheduling by time of day / grow-out stage.** This is exactly what the paused digital twin is for -- see "Paused" below.

### Previous changes (farm-operator feedback pass)

- **Indoor humidity above 70% no longer crashes the app.** The Aviagen target-temperature table is only published for RH 40-70%; real houses go higher. `comfort_engine.target_temperature` now clamps to the nearest tested edge instead of raising, and flags every clamped call (`ComfortAssessment.target_temp_rh_clamped`, a new `-10` confidence deduction, and an explanation line) so the number is never silently trusted as precise. The THI half of the comfort score is untouched by this -- it's a closed-form formula valid at any RH -- so high-humidity heat stress is still caught even when the target-temperature figure is a flagged floor. See `comfort_engine.py`'s new docstring section for the full reasoning.
- **Body weight now follows bird age.** The Flock tab has a new "Bird age" field wired to the real Aviagen Ross 308 growth curve (`pcis/core/growth_curve.py`, days 0-56) -- change the age and body weight auto-fills, with a status line telling you where the number came from. You can still type over it by hand if your actual flock differs from the table; ages outside 0-56 days just leave the weight field alone with a warning rather than guessing.

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
    growth_curve.py        Ross 308 as-hatched weight-for-age (Aviagen 2022)
    digital_twin.py        Fan/pad SCHEDULE across time: "how many fans, when, how long".
                            Composes recommend() over a caller-supplied weather profile
                            or an advancing bird age. Flags unreachable targets and
                            installed-capacity shortfalls. No GUI yet.
  equipment/              Manufacturer data, each record carries a provenance citation
    fan_curve.py           Big Dutchman AirMaster V130/VC130 (4 real curves)
    cooling_pad.py          Munters CELdek 7090-15 specs + MSU Extension AND UGA
                             Extension design points (two independent citations now)
  db/                      SQLAlchemy 2.0 (SQLite now, Postgres-portable later)
    models.py, session.py  HouseConfig, FlockRecord, RecommendationLog (now age+comfort-tagged, exportable to CSV), MeasurementRecord, CalibrationFactorRecord
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
- **`comfort_engine.py`**: `bird_comfort_index` is **PCIS's own composite synthesis**, not a published/validated instrument. Its component metrics (target temperature, THI) are individually cited; the scoring weights are named constants flagged as engineering judgment pending real-data calibration. The target-temperature table only covers RH 40-70%; real indoor RH above that (or below 40%) is now clamped-and-flagged rather than crashing -- see the module docstring and `ComfortAssessment.target_temp_rh_clamped`.
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
`HouseConfig`+`EnvelopeSurface`, `FlockRecord`, `RecommendationLog`, `MeasurementRecord`, `CalibrationFactorRecord`. Full save/fetch helper functions. `RecommendationLog` now also carries `age_days` and the full `ComfortAssessment` breakdown (`target_temp_c`, `deviation_c`, `thi`, `thi_class`, `comfort_index`, `target_temp_rh_clamped`), and `export_recommendation_logs_csv(session, output_path, house=None)` dumps the saved history to a flat CSV (`RECOMMENDATION_LOG_CSV_COLUMNS`) for external ML/calibration work -- optionally filtered to one house. `get_or_create_house_config` fetches-or-creates by name (refreshing dimensions/surfaces on reuse) so the GUI can log a row every single run without hitting the `HouseConfig.name` uniqueness constraint. 30 tests (15 original + 8 validation-persistence + 4 age/comfort/CSV-export + 3 get-or-create).

### `reports/pdf_report.py`
`generate_recommendation_report(...)` — ReportLab PDF with flock summary, environmental conditions, comfort assessment, recommendation, and the full explanation list rendered verbatim (nothing summarized away). 4 tests verifying actual extracted PDF text, not just "didn't crash".

### `gui/main_window.py`
A `QTabWidget`-based desktop app: **House & Equipment** (house dimensions, an editable envelope-surface table backed 1:1 by `heat_moisture_balance.Surface`, fan model picker populated from `FAN_CATALOG`, cooling-pad picker populated from `COOLING_PAD_CATALOG` with "no pad installed" as a valid choice), **Flock** (breed — labeled informational-only in the UI itself, bird age auto-filling body weight from the Ross 308 growth curve, bird count), **Environment** (indoor/outdoor T & RH, design ΔT, outdoor CO₂ background), and **Recommendation** (Run button → calls `recommendation_engine.recommend()` with the gathered inputs, displays fans-on/pads-on/airflow/governing-constraint/confidence, lists every explanation line verbatim, **automatically logs the run to the database** with a quiet status-line confirmation, then Export-PDF and Export-Training-Data-(CSV) buttons for the two things that still need an explicit "give me a file" action).

The window contains **no new engineering logic** — `gather_inputs()` is a pure widget-to-dict reader, and every computed number comes from a `core/*` function that already has its own citation and unit tests. Invalid input (e.g. a non-numeric envelope cell) raises `ValueError`, caught and surfaced as a `QMessageBox.warning` rather than crashing or silently defaulting.

Verified end-to-end headlessly (`QT_QPA_PLATFORM=offscreen`): construct window → fill defaults → run recommendation → automatically persisted to SQLite → export a real, text-verified PDF, all in one pass. `tests/test_gui.py` covers the envelope-surface editor, input gathering, the run/auto-record/export flow (including that running twice under the same house name doesn't hit the name-uniqueness constraint), and the bad-input warning path. `tests/conftest.py` defaults `QT_QPA_PLATFORM` to `offscreen` so the whole suite runs without a display. One testability note worth recording: `export_pdf`/`export_training_data` each end with a `QMessageBox.information(...)` confirmation dialog — correct, desirable behavior for an interactive user, but a blocking modal with no one to click OK will hang forever in a headless run. Tests patch `QMessageBox.information`/`.warning` to no-ops to observe return values without blocking; this is a test-harness workaround only, the production dialogs are unchanged. The automatic database recording itself shows no dialog at all (that's the point), so those tests need no patching.

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
5. **GUI, full loop**: `MainWindow` constructed headlessly → default inputs gathered from every tab → `Run Recommendation` produced a real result (11 fans, pads off, confidence 85/100 on the seeded defaults) and **automatically** persisted house/flock/recommendation rows to SQLite (no separate save step), confirmed by querying them back → `Export PDF` wrote a real PDF, confirmed non-empty on disk.
6. **GUI charts, full loop**: `MainWindow` constructed headlessly → fan curve chart auto-populated from the default fan selection with 2 series (curve + operating point) → `Run Recommendation` → comfort chart populated with 4 real temperature bars (38.0, `supply_air_t_c`, `comfort.t_c`, `comfort.target_temp_c`) and a title reporting the actual THI/comfort-index values.

---

## Explicitly out of scope (your instruction)

- **Cross-ventilation / natural-ventilation modeling** — skipped for now. Only tunnel/mechanical ventilation sizing is implemented; nothing in the codebase assumes natural ventilation will be added later, so this is a clean deferral, not a partial/broken feature.
- **Cobb 500 (or any non-Ross breed)** — skipped for now. `growth_curve.py` is Ross 308/308 FF only; `FlockRecord.breed` remains a free-text, informational-only field with no engineering logic reading it. Adding Cobb later would mean sourcing a real Cobb 500 performance-objectives table and adding a parallel growth-curve/target-temperature path -- not attempted here since you said to skip it.

## Now built (was paused: "digital twin can wait")

- **Digital twin** — **now built** (`pcis/core/digital_twin.py`, 38 tests) — see "Latest changes" at the top for what it does and the three findings that came out of it. It is a **core module only so far: not yet wired into the GUI**, so today you'd call it from Python rather than clicking a button. GUI integration (a "Schedule" tab with the table and a chart) is the obvious next step and is listed under "Not yet built" below. The original design sketch, which the built module follows closely, is preserved here for reference: Your dad's feedback ("how many fans at what time should be on for how long") is exactly this feature -- the current app only answers "what should be running right now, for these exact conditions," not a schedule across a day or grow-out stage. Design plan for when you're ready to resume: step through a grow-out day-by-day (or hour-by-hour, if you want sub-day fan staging) using `growth_curve` for bird weight at each step, reuse `recommendation_engine.recommend()` to get the target indoor setpoint / fan-and-pad decision at that step, then -- if you also want to model a house with a *fixed, physically-installed* fan count (rather than the "however many fans are needed" the recommendation engine currently assumes) -- solve the actual achieved indoor temperature/humidity/CO2 from the energy/moisture/CO2 balance equations already implemented in `heat_moisture_balance.py`/`ventilation_solver.py` when that installed capacity is insufficient. No new engineering constants would be needed; it would purely recombine what's already built and cited. Output would be a table/chart of fan-on-count and pad-on/off by time-of-day or day-of-grow-out -- directly answering the "how many fans at what time, for how long" question.

## Not yet built

- **Digital twin GUI integration** — the module is complete and tested but has no UI yet. Needs a "Schedule" tab: enter the day's outdoor profile (or import it), pick the age, get the table plus a fan-count-vs-time chart. The text renderer (`format_schedule_table`) is already there for the PDF/export path to reuse. **This is the next thing to build.**
- **A measured pad efficiency from a real house.** Now the highest-value missing data point in the whole project, because two credible published sources disagree by 15 percentage points (see "Latest changes") and only measurement can settle which applies to your equipment. Needs: outdoor dry-bulb + RH and the air temperature just downstream of the pad, on a hot day, ideally at a few different fan stages. `pcis.core.validation` already exists to log predicted-vs-measured pairs and fit a calibration from them.
- **Pad pressure-drop curve** — the same product sheet has a second figure ("Pressure drop CELdek 7090-15", 5–200 Pa vs 0.5–5 m/s, same four depths) that has *not* been digitized. Lower priority than the efficiency curve since PCIS currently takes static pressure as a caller-supplied design input, but it's the obvious next thing if you want the app to compute system static pressure itself rather than asking for it.
- **Packaging as a standalone Windows executable** (e.g. PyInstaller) — currently runs as a Python app via `python -m pcis.gui.main_window` with `pip install -e ".[gui]"`.
- **AI-based recommendations** — explicitly "later" per the original project plan.

## How to run the GUI

```
pip install -e ".[gui]"
python -m pcis.gui.main_window
```

## Suggested next step

The engineering core, persistence, reporting, GUI, charts, and now ML-ready data logging all work together end-to-end against real, cited data (202/202 tests passing), with cooling-pad data upgraded to two independent citations. Every recommendation you run is automatically an age-tagged, comfort-scored row in the database -- no save step, no button -- so a real dataset builds itself just from using the app day to day, exportable as a CSV whenever you want it. When you're ready, say the word and the digital twin (design already sketched above) is the natural next build.
