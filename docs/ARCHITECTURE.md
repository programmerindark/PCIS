# PCIS v1 "Phoenix" — Architecture (LOCKED Day 0)

_This is the frozen technical design for the 7-day v1. No stack changes._

## Decisions (locked)

| Area | Decision | Why |
|------|----------|-----|
| Engine | **Reuse `pcis.core` (Python)** behind an API | ~418 cited, tested formulas — re-deriving in TS is a science risk |
| Backend | **FastAPI** wrapping the engine | Thin, typed, imports the engine directly |
| Frontend | **Next.js (React) on Vercel** | Matches the mockup; mobile-responsive; fast deploy |
| DB + Auth | **Supabase** (Postgres + Auth + RLS) | One managed service for data + login |
| Climate data (v1) | **Manual entry + weather API** | Works on any farm today, no hardware |
| 3D house view | Full animated 3D (Day 5), with a **simple status panel as fallback** | Product Owner call; fallback protects the deadline |

## Topology

```
Browser / phone
      │  HTTPS
      ▼
Next.js app  ──────────────►  Supabase (Postgres + Auth)
(Vercel)     auth, CRUD, RLS
      │
      │  POST /recommend, /schedule   (climate math only)
      ▼
FastAPI "PCIS API"  ──imports──►  pcis.core  (the validated engine)
(Render/Railway)
```

Two deploys: the **UI** on Vercel, the **engine API** on a Python host
(Render or Railway free tier). Supabase is the third managed piece. The
UI talks to Supabase for data/auth and to the PCIS API for climate math.

## Monorepo layout

```
PCIS_flat/
  pcis/                 # THE ENGINE — reused as-is (core + equipment)
    core/               #   psychrometrics, comfort, airspeed, twin, bird_status...
    equipment/          #   fan curves, cooling pads
  backend/              # FastAPI service
    app/
      main.py           #   routes: /health /catalog /recommend /schedule
      schemas.py        #   Pydantic request/response models
      engine_api.py     #   the ONLY adapter to pcis.core
    requirements.txt
  frontend/             # Next.js app (Day 2+)
    app/                #   routes (App Router): /login /dashboard /houses ...
    components/         #   UI components
    lib/                #   supabase client, pcis-api client, types
  supabase/
    schema.sql          # tables + RLS (run in Supabase SQL editor)
  docs/
    ARCHITECTURE.md     # this file
    MASTER_PROMPT.md    # standing Claude Code prompt
    OVERVIEW.md         # plain-language project tour
  tests/                # engine test-suite (kept green)
```

The desktop GUI (`pcis/gui`, PySide6) stays in the repo but is **not**
part of the web v1 — only `pcis/core` and `pcis/equipment` are used by
the API.

## API contract (v1)

- `GET /health` → `{status, service, version}`
- `GET /catalog` → `{fans[], pads[], insulation[]}` (populate dropdowns)
- `POST /recommend` (HouseFlockInputs) → single result: `fans_on, pads_on,
  governing_constraint, air_speed_mps, target_airspeed_mps, vpd_kpa,
  heating_needed, heat_deficit_kw, target_unreachable, confidence_score,
  comfort{...}, bird_status{...}, explanation[]`
- `POST /schedule` (HouseFlockInputs + `profile[]` + `step_hours`) →
  `blocks[], peak_fans_on, fan_hours, notes[]`

Inputs and validation live in `backend/app/schemas.py`. The engine's own
outputs are passed through verbatim (rounded for display only).

## Coding standards

- **Engine is sacred.** No engineering in `backend` or `frontend`. Every
  number originates in `pcis.core`, which keeps its cited-source rule and
  its test suite green. If a formula is missing, add it to the engine
  (with a citation + tests), never inline it in the API or UI.
- **Types at the edges.** Pydantic on the backend; TypeScript types in
  `frontend/lib/types.ts` mirroring the API contract.
- **RLS on everything.** No table is readable without an owning farm.
- **Small PRs, green tests.** `pytest` stays green; the API has a smoke
  test; each day ends deployable.
- **Honesty in the UI.** Estimated values (felt temp, panting, water) are
  labelled; confidence score is shown; warnings are surfaced, not hidden.
- **SI internally, display units at the edge** (as the engine already does).

## Definition of done (v1)

Log in → create farm/house/flock → dashboard shows live comfort, feel
temp, heat-stress, and the fan/pad/heater recommendation + day schedule
with the "why" → alerts fire on shortfall/heat-stress → works on phone.
Deployed and reachable at a URL.
