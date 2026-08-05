# Contributing to PCIS

PCIS advises a farmer how to run the fans in a shed holding twenty thousand
live birds. A wrong number here is not a rendering glitch — someone acts on
it. That shapes every rule below.

## The rule that governs everything

**Every constant is traceable to a published source, or is labelled as
engineering judgment.**

No exceptions, and in particular no inventing a number at the exact point
where the answer matters most. Where a value genuinely is not published,
PCIS says so and reports what it *can* stand behind.

That property is the whole product. A single fabricated constant would
quietly destroy the credibility of everything around it, because a reader
has no way to tell the invented one from the cited ones.

Current sources: Aviagen Ross 308 (growth curve, target temperatures,
minimum ventilation), CIGR 2002 (bird heat, moisture and CO₂ output),
Tao & Xin 2003 (poultry THI), Buck 1996 / ASHRAE (psychrometrics),
EU Directive 2007/43/EC (mortality ceiling, stocking density), SKOV Viper
Touch (age chill curve, max tunnel air speed).

**SKOV fills gaps; it never overrides research.** Where a breed-published
value exists, Aviagen wins.

## Where code goes

| | |
|---|---|
| `pcis/core/` | The engine. Pure standard library. **All climate maths lives here and nowhere else.** |
| `backend/app/engine_api.py` | The only place the web layer touches the engine. Adds no engineering of its own. |
| `frontend/` | Next.js 14 App Router. Presentation only. |
| `supabase/` | Schema and migrations — ordering matters, see `supabase/README.md`. |

There is exactly **one** exception to "maths only in `pcis/core`":
`frontend/lib/gcPolicy.ts`, a port of the payout formula so the public
calculator answers instantly on a poor connection. It is allowed only
because its tables are *generated* from the Python and its arithmetic is
cross-checked against the engine in CI. Do not add a second exception
without the same machinery.

## What we will not merge

- **A projected profit or yield.** PCIS models climate, not economics. The
  one carve-out is `pcis/core/gc_policy.py`, which evaluates a *published
  contract*, reports a position rather than a forecast, and never nets
  income against farm costs.
- **A number without provenance in the UI.** Every figure on screen must be
  identifiable as measured, computed, cited, or entered by hand.
- **A confidence score presented as if earned.** They are currently
  *assigned*. Until `/validation` has enough paired data to replace them
  with measured error, say so.
- **A metric that hides its own staleness.** "Live" may only be claimed for
  something computed within the last couple of minutes.

## Tests

```bash
python3 -m pytest tests/ -q \
  --ignore=tests/test_gui.py --ignore=tests/test_widgets.py \
  --ignore=tests/test_charts.py --ignore=tests/test_guided.py \
  --ignore=tests/test_style.py --ignore=tests/test_packaging.py
```

Frontend gate is `npx tsc --noEmit` from `frontend/`.

**Tests assert the reasoning, not just the output.** Where a bug has been
fixed, add a test that also asserts the *old* behaviour looks wrong — so
nobody can "simplify" the fix back out. For example, the depletion tests
assert not only that a thin is priced correctly but that treating it as
mortality prices the crop at zero.

## Comments explain why, not what

Especially: why a constant has that value, and what breaks if it changes.
A comment saying `// add 1 to i` is noise; one saying why the 5% mortality
threshold flips the CBW denominator is the reason the next person does not
break it.

## Traps that have already bitten

These were live defects, not hypotheticals. Read `CLAUDE.md` for the full
list before touching the relevant area.

- **Ecowitt names its blocks by sensor TYPE, not placement.** On a reversed
  install the `"outdoor"` block is the indoor reading. Get it backwards and
  the moisture balance inverts — the app recommends fans that make the
  house wetter, and both readings look plausible.
- **Lifting is not mortality.** Birds sent to slaughter are *delivered*.
  Booking a thin as deaths once reported 31.6% mortality against a ~3%
  ceiling, and later priced a crop at Rs 0 instead of Rs 426,448.
- **Shortage is not mortality either.** It has its own line on the
  settlement.
- **A contract's rules belong to its period, not to poultry.** Two
  settlements five weeks apart use different CBW denominators and different
  rate tables. Never generalise a formula across schemes without checking
  they are the same scheme.
- **Evaluate at the achievable temperature, not the target.** Ventilation
  cannot cool below the air it is fed.

## Reporting something wrong

If PCIS told you something about your own house that turned out to be
false, that is the most valuable report this project can receive — more so
than a crash. Include the reading, what it advised, and what actually
happened. The project is at **n = 1**: one house, one sensor. Every
independent observation is worth more than a feature.

## Licence

MIT. By contributing you agree your work ships under it.
