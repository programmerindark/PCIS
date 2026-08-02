# PCIS — Poultry Climate Intelligence System

Decision-support software for broiler house climate control. It advises;
it does not control equipment.

**Owner context:** the user runs the farm and acts as product owner. They
own three questions — does it solve a real farm problem, is it simple
enough, is it scientifically reasonable. Implementation decisions are
delegated, but the reasoning behind them should be stated, not hidden.

---

## The rule that governs everything

**Every constant is traceable to a published source, or is labelled as
engineering judgment.** No exceptions, and no inventing a number at the
exact point where the answer matters most.

Where a value genuinely is not published, PCIS says so and reports what it
*can* stand behind. That property is what makes the rest trustworthy; a
single fabricated constant would quietly destroy it.

Cited sources in use:

| Source | Used for |
|---|---|
| Aviagen Ross Broiler Pocket Guide | target temperature table, minimum ventilation |
| Aviagen Ross 308 | body-weight growth curve, wind-chill anchor |
| CIGR (2002) | bird sensible/latent heat, moisture, CO2 output |
| Tao & Xin (2003) | THI — poultry-specific, `0.85·Tdb + 0.15·Twb` |
| Buck (1996) / ASHRAE | psychrometrics |
| EU Directive 2007/43/EC | mortality ceiling `1% + 0.06%×age`, stocking density |
| SKOV Viper Touch | age chill factor, max tunnel air speed, humidity benchmark |

**Source policy — SKOV fills GAPS, it never overrides research.** Where a
breed-published value exists (target temperature, minimum ventilation),
Aviagen wins. SKOV is used only where nothing researched exists: the
age-dependent chill curve and the 4.0 m/s maximum tunnel air speed. Its
humidity curve is reported as an operator *benchmark* and feeds no
calculation.

---

## Architecture

```
Browser → Vercel (Next.js, frontend/) → Render (FastAPI, backend/) → pcis.core
              ↓                                                       (all maths)
         Supabase (auth, farms, houses, flocks, readings, recommendations)
              ↑
         cron-job.org (1-min poll) → /api/cron/log-sensor → Ecowitt cloud
```

- `pcis/core/` — the engine. Pure standard library. ~500 tests. **All
  climate maths lives here and nowhere else.**
- `backend/app/engine_api.py` — the ONLY place the web layer touches the
  engine. Adds no engineering of its own.
- `frontend/` — Next.js 14 App Router. Root `vercel.json` is stale (points
  at an old static prototype in `/web`); the live config is
  `frontend/vercel.json`.
- Branch is **`master`**, not `main`.

Run tests, excluding the Qt desktop GUI suites which need a display:

```bash
python3 -m pytest tests/ -q \
  --ignore=tests/test_gui.py --ignore=tests/test_widgets.py \
  --ignore=tests/test_gui_flow.py --ignore=tests/test_charts.py \
  --ignore=tests/test_guided.py --ignore=tests/test_style.py \
  --ignore=tests/test_packaging.py
```

Frontend gate is `npx tsc --noEmit`. A full `next build` exceeds the
45-second sandbox limit — do not rely on it.

---

## Traps that have already caused real bugs

Each of these was a live defect, not a hypothetical.

**Ecowitt blocks are named by sensor TYPE, not placement.** On this farm
the install is REVERSED: the WS90 array (Ecowitt's `"outdoor"` block) hangs
INSIDE the house; the gateway console (`"indoor"`) sits outside. So
`ecowitt_indoor_block = 'outdoor'`. Get this backwards and the moisture
balance inverts — the app would recommend fans that make the house wetter.
Nothing can detect it automatically; both readings look plausible.

**Lifting is not mortality.** Birds caught and sent to slaughter go in
`depletions`, never `mortality`. The EU ceiling is ~3% at market age while
a thin removes 20–40% in a morning, so conflating them reports a
catastrophic welfare breach on a routine day. This happened: a 6,940-bird
lift was booked as deaths and showed 31.6% mortality.

**Lifting is not mortality — including in the money path.** The same
confusion reappeared in `gc_policy.project_in_crop`, which passed live
birds in as birds *lifted*, so a routine thin read as ~27% mortality. That
trips the 5% CBW rule, jumps cFCR past the 1.800 cliff, and prices the crop
at **Rs 0 instead of Rs 426,448**. Thinned birds are delivered: add them
back to both the count and the weight. A lift with no recorded weight
cannot be priced at all — feed for those birds is already in the total
while their kilograms are missing — so the engine returns
`incomplete_reason` and the UI shows that instead of a number.

**A settlement's CBW rule belongs to its CONTRACT PERIOD, not to poultry.**
Nine settlements from this farm span four incentive schemes and two legal
entities in two years. Lot B95625 (ABIS Exports, Oct 2025) divides CBW by
chicks housed; lot B95626 (ABIS Foods, Dec 2025, five weeks later) divides
by 0.95 x chicks. Each matches its own slip exactly. `gc_policy` implements
the 16 Oct 2025 - 15 Oct 2026 policy ONLY: applying it to the older crops
overstates the rearing charge by Rs 100k-210k. Never fit incentive formulae
across settlements without first checking they share a scheme — only one
crop is under the current one, so the incentives are not fittable at all.

Scope is checked on the **PLACEMENT** date, not the lift. B95625 was
*lifted* 18.11.2025 — inside the current window — but *placed* 08.10.2025,
eight days before it opens. A lift-date check waves the wrong entity
straight through; only `policy_covers(placement_date)` catches it.

**Shortage is not mortality either.** Settlements carry short-supplied
birds on their own line. Computing deaths as `housed - lifted` swallows
them: lot B95625's 55 short birds read as 8.884% against the slip's 8.635%.
Harmless there, but a crop at 4.9% true mortality would be pushed over the
5% CBW threshold and penalised for birds it never received.

**Evaluate at the ACHIEVABLE temperature, not the target.** Ventilation
cannot cool below the air it is fed. `achievable_indoor_t_c =
max(indoor_t_c, supply_t_c)`. Every bird-facing readout — felt temperature,
comfort, THI — is computed there. Evaluating at target reports a comfort
the birds never get.

**Moisture has a singularity.** Required airflow is
`load / (W_indoor − W_supply)`, which tends to infinity as supply air
approaches indoor humidity. `MOISTURE_MIN_HUMIDITY_RATIO_DIFF` guards it;
above the threshold PCIS reports that ventilation cannot dehumidify and
computes the outdoor RH at which drying resumes.

**Action confidence ≠ metric confidence.** Sizing fans is geometry plus a
cited air-speed target (high confidence). Felt temperature and comfort lean
on humidity inputs (lower). The advisor quotes ACTION confidence, with
metric confidence shown beside the figures it describes.

**Duplicate pollers masquerade as instability.** Several schedulers pointed
at the same endpoint produced 2–7 rows per minute, and change-detection
compared them against each other — making a stable engine look like it was
oscillating (32 apparent changes vs 2 real ones per 102 minutes).
`log_sensor_reading` now returns `'skipped'` within 40 s of the last row.

**Above 70% RH the engine is extrapolating.** Aviagen's target-temperature
table is tested to 70%; this house runs at 96%. RH is clamped to 70%, 10
confidence points are deducted, and the explanation states the target shown
is a FLOOR — the true value is lower. THI and VPD stay valid up there and
are the metrics to trust.

---

## Style

- Comments explain **why**, not what. Especially: why a constant has that
  value, and what breaks if it changes.
- Tests assert the *reasoning*, not just the output. Where a bug has been
  fixed, a test should also assert the old behaviour looks wrong.
- Labels distinguish measured / computed / cited. A reader cannot tell them
  apart otherwise.
- No projected profit or yield. PCIS models climate, not economics — a
  financial figure would be the only uncited number and the most likely to
  be believed uncritically.
- **One exception, narrowly drawn:** `pcis/core/gc_policy.py` computes the
  IB Group growing charge, because the slab tables are a *published
  contract* and evaluating them is arithmetic over a stated rule, like the
  EU mortality ceiling. It reports a POSITION (what today's entered numbers
  are worth), never a forecast, and never nets income against farm costs.
  It must not be extended to predict end-of-crop FCR or weight.
- Entered values are labelled `✎ entered by hand` with their age. Feed and
  sample weight are the only inputs no sensor produces, so they are the
  only ones that can be silently stale while looking as live as the rest.

---

## Where it actually stands

Honest assessment, so nobody overstates it:

- **Solid:** the physics. Psychrometrics validated externally against the
  Devatec table to 0.26%. Air speed computed 3.06 m/s vs measured 3.22 —
  the fan-curve chain survives contact with hardware.
- **Unproven:** every confidence number is still *assigned*, not earned.
  The `/validation` page exists to replace them with measured error once
  enough paired data accumulates. It has not yet.
- **Weakest link:** felt temperature. It drives decisions and nothing in
  the sensor stack can verify it. Reported as a band for that reason.
- **n = 1.** One house, one sensor, one flock. Enough to catch gross
  errors, not enough to calibrate anything.
- Nothing yet connects a climate decision to a mortality or weight
  outcome. That is the claim that would make this a product rather than a
  well-built instrument.
