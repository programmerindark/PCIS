# PCIS — Poultry Climate Intelligence System

**A tool that tells a poultry farmer how many fans to run.**

---

## The problem

Broiler chickens are raised in long, enclosed sheds holding twenty thousand
birds or more. Those birds are, collectively, a large heater: they give off
body heat, moisture from breathing, and carbon dioxide, continuously.

If the shed gets too hot, birds stop eating, stop growing, and in bad cases
die. Too cold, and they burn feed staying warm instead of growing. Too humid,
and the litter goes wet and ammonia builds up.

So the shed has big fans, and often evaporative cooling pads — wet panels the
incoming air is pulled through, which cool it as the water evaporates.

The daily question is simple to ask and hard to answer: **right now, how many
fans should be running, and should the pads be on?**

Get it wrong one way and you waste electricity. Get it wrong the other way and
you lose birds. In practice this is judged by experience and by feel.

## What PCIS does

You tell it what you have and what things are like right now:

- how big the shed is, and how well insulated
- which fan model, and whether cooling pads are fitted
- how many birds and how old they are
- the temperature and humidity, inside and out

It tells you how many fans to run, whether to switch the pads on — **and why**,
in plain terms, showing every step of the reasoning.

It also builds a **schedule**: give it a whole day's weather and it works out
how many fans should run at each hour, and for how long. That was the specific
thing a working farmer asked for after seeing an early version.

## How it works

The core is about 3,600 lines of Python implementing standard ventilation
engineering. Nothing is invented:

- **Bird heat output** — the CIGR (2002) international standard formula
- **Air properties** (humidity, wet-bulb, density) — ASHRAE handbook methods
- **Target temperatures and growth rates** — Aviagen's published Ross 308
  breed tables
- **Minimum ventilation and air-quality limits** — Aviagen's guidance
- **Fan performance** — real Big Dutchman fan curves
- **Cooling pads** — Munters CELdek data, plus university extension guidance

It calculates four separate air requirements — enough to remove the heat,
enough to remove the moisture, enough to keep CO₂ down, and the minimum for
air quality — then uses whichever is largest, and reports which one is in
charge.

### The rule the project is built on

**Every number traces to a published source. Nothing is estimated to fill a
gap.**

If a figure can't be verified, the code refuses to produce an answer rather
than guessing, and says why. If a published table only covers a certain range,
it won't extrapolate past it — it stops and tells you.

Where a value is a judgement call rather than a citation, the output says so
and subtracts from a confidence score, so you can see exactly how much of the
answer rests on assumption.

## Three ways to use it

| | What it is | Best for |
|---|---|---|
| **Desktop app** | Windows program with charts and PDF reports | Daily use in the farm office |
| **Mobile web app** | Website that installs to a phone home screen and works with no signal | Checking conditions in the shed |
| **Installer** | `PCIS_Setup.exe` | Putting it on a farm PC properly |

The mobile version runs the *same* Python code in the browser, rather than a
separate rewrite, so both give identical answers. That was checked by running
the same scenarios through both and comparing every figure.

## It records as you go

Every recommendation is saved automatically — the conditions, the bird age, the
decision — and can be exported as a spreadsheet. Over a season this becomes a
real dataset of how the house behaved, which is what any future machine
learning work would need.

## What it found

Two things worth knowing came out of building it:

**The target temperature is often physically impossible to reach.** Ventilation
can only pull outside air through the shed — it can never make the inside
cooler than the air coming in. On a 37 °C afternoon, even after the cooling
pads, incoming air is about 28 °C, while five-week-old birds want around 21 °C.
The app used to just say "6 fans", which reads as *run 6 and you'll hit
target*. You won't. It now says so plainly, and says that more fans will not
help — the answer is more cooling capacity, or accepting a warmer shed.

**The manufacturer and the agricultural extension services disagree** about how
well cooling pads perform, by 15 percentage points. Munters measures new,
perfectly wetted pads in a lab; extension figures allow for real pads that are
older and dirtier. PCIS deliberately uses the pessimistic number, because being
over-optimistic about cooling means under-ventilating birds in a heat wave.

## What it is not

**The calculations have never been checked against a real shed.** Not once.

Every formula is cited, the code has 347 automated tests, the arithmetic is
right. But no one has yet stood in a working poultry house with a thermometer
and compared what PCIS predicted to what actually happened.

That is the difference between *defensible* and *proven*, and it is the single
most valuable thing anyone could do with this next: measure the air
temperature just past the cooling pads on a hot day, and compare. There's a
module built specifically to record those comparisons.

It also currently covers only the Ross 308 breed, because that's the breed
whose performance data was available.

**PCIS is decision support, not an autopilot.** It doesn't control anything. It
gives you a number and its reasoning, and the operator decides.

## For developers

```bash
pip install -e ".[desktop,dev]"    # install
python -m pytest                   # 347 tests
python -m pcis.gui.main_window     # run the desktop app
```

- `BUILD_WINDOWS.md` / `README_BUILD.md` — building the executable
- `README_RELEASE.md` — cutting a release
- `DEPLOYMENT.md` — installing and supporting it on farm machines
- `PROGRESS.md` — full development history, including every known limitation

Licensed MIT. See `LICENSE`, which includes an engineering disclaimer worth
reading before anyone relies on the output.
