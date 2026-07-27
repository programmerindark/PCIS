# PCIS — Web Deployment Runbook

Deploying the **web** PCIS (FastAPI engine API + Next.js dashboard + Supabase).

> Not to be confused with `DEPLOYMENT.md`, which covers the older Windows
> desktop installer. Different product, different steps.

**Architecture being deployed**

```
Browser ──> Vercel (Next.js dashboard)  ──> Render (FastAPI + pcis engine)
                    │                              (all climate maths)
                    ├──> Supabase (auth, farms, houses, flocks, readings)
                    └──> api.ecowitt.net (live sensor, called from the browser
                          and from the 10-minute cron job)
```

Total cost: free tier on all three, with one caveat about Vercel Cron in
Step 5.

---

## Before you start

You need three browser tabs and one terminal:

- github.com (repo is already at `programmerindark/PCIS`)
- render.com (sign up free, "Log in with GitHub" is easiest)
- vercel.com (sign up free, same)
- supabase.com (project already exists)

---

## Step 1 — Commit and push what's on disk

Nothing deploys until it's on GitHub. From `PCIS_flat` in PowerShell:

```powershell
# Only if OneDrive left a stale lock behind:
del ".git\index.lock"

git add -A
git commit -m "Sensor logging, pressure correction, air-speed cross-check, deploy config"
git push
```

If `git push` asks for a password, use a GitHub Personal Access Token, not
your account password (GitHub disabled password auth for git in 2021).

**Check before continuing:** open the repo on github.com and confirm you
can see `frontend/app/api/cron/log-sensor/route.ts`. If it isn't there,
the push didn't include it and the cron job will 404 later.

---

## Step 2 — Run the database migration

Supabase dashboard → your project → **SQL Editor** → **New query**.

Paste the entire contents of `supabase/migration_sensor_log.sql`, then
**Run**.

This adds `pressure_hpa` and `measured_air_speed_mps` to `readings`, plus
the `log_sensor_reading()` function and `farms_with_ecowitt_keys` view the
cron job uses.

**Check:** Table Editor → `readings` → confirm the two new columns exist.

> If you have never run `schema.sql`, `migration_mortality.sql` and
> `migration_sensors.sql` on THIS project, run them first, in that order.

---

## Step 3 — Deploy the backend (Render)

1. render.com → **New +** → **Web Service**
2. Connect the `programmerindark/PCIS` repo
3. Fill in **exactly** this — the defaults are wrong for this repo:

   | Field | Value |
   |---|---|
   | Name | `pcis-api` |
   | Region | whichever is closest to the farm |
   | Branch | `main` |
   | Root Directory | *leave blank* |
   | Runtime | Python 3 |
   | Build Command | `pip install -r backend/requirements.txt` |
   | Start Command | `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT` |
   | Instance Type | Free |

   **Root Directory must stay blank.** The API does `from pcis.core import
   ...`, so it has to run from the repo root or the engine won't import.

   **Build Command must name `backend/requirements.txt` explicitly.** The
   root `requirements.txt` is the desktop app's dependency list — it
   installs PySide6, numpy and scipy, none of which the API uses. Letting
   Render auto-detect it wastes several minutes of build time and can fail
   outright on the free tier.

4. **Create Web Service.** First build takes 2–4 minutes.

5. Copy the URL it gives you, e.g. `https://pcis-api.onrender.com`.

**Check:** open `https://YOUR-API.onrender.com/health` in a browser. You
want `{"status":"ok","service":"pcis-api","version":"1.0.0"}`.

> Free-tier Render sleeps after 15 minutes idle. The first request after a
> sleep takes ~30 seconds to wake. Fine for a dashboard someone opens a few
> times a day; upgrade to the $7/mo tier if the wait becomes annoying.

---

## Step 4 — Collect your secrets

Have these four values ready before touching Vercel. Get the Supabase ones
from **Project Settings → API**.

| Variable | Where from | Safe in browser? |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase → Project URL | yes |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase → anon / public key | yes |
| `NEXT_PUBLIC_PCIS_API_URL` | your Render URL from Step 3 | yes |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase → **service_role** key | **NO — server only** |
| `CRON_SECRET` | invent one, e.g. a 32-char random string | **NO — server only** |

The two marked "server only" have no `NEXT_PUBLIC_` prefix, which is what
keeps Next.js from bundling them into JavaScript sent to the browser. The
service_role key bypasses every Row Level Security policy in your database
— treat it like a root password. Paste it into Vercel's dashboard and
nowhere else. Not into chat, not into a file in the repo.

For `CRON_SECRET`, any random string works. In PowerShell:

```powershell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | % {[char]$_})
```

---

## Step 5 — Deploy the frontend (Vercel)

1. vercel.com → **Add New** → **Project**
2. Import `programmerindark/PCIS`
3. **Root Directory: click Edit and set it to `frontend`.** This is the one
   setting people miss. The repo root contains a stale `vercel.json`
   pointing at an old static prototype in `/web`; pointing Vercel at
   `frontend` bypasses it and picks up `frontend/vercel.json` instead.
4. Framework Preset should auto-detect **Next.js**. Leave build and output
   settings alone.
5. **Environment Variables** — add all five from Step 4.
6. **Deploy.**

**Check:** the deployment URL loads a login page.

### About the cron schedule — read before deploying

Per [Vercel's cron limits](https://vercel.com/docs/cron-jobs/usage-and-pricing):

| Plan | Minimum interval | Timing precision |
|---|---|---|
| **Hobby** (free) | **Once per day** | ±59 min |
| Pro | Once per minute | Per-minute |
| Enterprise | Once per minute | Per-minute |

**A sub-daily cron expression on Hobby fails the deployment.** It does not
quietly run less often — Vercel rejects the build with:

> *Hobby accounts are limited to daily cron jobs. This cron expression
> would run more than once per day.*

So `frontend/vercel.json` ships with a **daily** schedule (`0 3 * * *`),
which deploys cleanly on every plan. Hobby also can't promise punctuality:
a `0 3 * * *` job fires somewhere between 03:00 and 03:59.

That daily job alone is too coarse to watch a house heat up through an
afternoon, so pick one of these:

**Option A — GitHub Actions (free, 10-minute polling).** Already set up in
`.github/workflows/log-sensor.yml`. It calls the same endpoint on a
`*/10 * * * *` schedule. To enable, add two repository secrets under
GitHub → repo **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `PCIS_APP_URL` | `https://your-app.vercel.app` (no trailing slash) |
| `CRON_SECRET` | the same string you set in Vercel's env vars |

Then Actions tab → *Log sensor reading* → **Run workflow** to test it
immediately rather than waiting for the schedule.

Caveats: GitHub doesn't guarantee punctual runs (a poll can be minutes
late or occasionally skipped — fine for climate logging), and scheduled
workflows auto-disable after 60 days of no repo activity; any commit
re-enables them.

**Option B — Vercel Pro ($20/mo).** Change the schedule in
`frontend/vercel.json` to `*/10 * * * *` and delete the GitHub workflow.
Simplest setup, guaranteed per-minute precision.

**Option C — external scheduler.** cron-job.org or UptimeRobot, both free,
pointed at `https://YOUR-APP.vercel.app/api/cron/log-sensor` with an
`Authorization: Bearer YOUR_CRON_SECRET` header. Equivalent to Option A;
useful if you'd rather not depend on GitHub Actions.

Options A and B both leave the daily Vercel job in place as a backstop —
the endpoint is idempotent in the sense that each call simply appends one
reading, so an occasional double-poll costs nothing but a duplicate row.

---

## Step 6 — Close the CORS loop

Back on Render → your service → **Environment** → add:

```
PCIS_CORS_ORIGINS = https://your-actual-app.vercel.app
```

Save. Render redeploys automatically (~1 minute).

Until you do this the API accepts every origin (`*`), which works but means
any website could call your engine. Comma-separate if you later add a
custom domain.

---

## Step 7 — Verify the whole chain

In order, because each step depends on the one before:

1. **API alive** — `https://YOUR-API.onrender.com/health` → `status: ok`
2. **Frontend loads** — your Vercel URL shows the login page
3. **Auth works** — sign up / log in, reach the dashboard
4. **Engine reachable from browser** — dashboard shows a fan
   recommendation, not a red error. If it errors here, it's CORS (Step 6)
   or a wrong `NEXT_PUBLIC_PCIS_API_URL`.
5. **Sensor reads** — Ecowitt card → **Test read** → live temperature/RH
6. **Cron logs** — hit the cron URL by hand once to prove it works:

   ```powershell
   curl.exe -H "Authorization: Bearer YOUR_CRON_SECRET" `
     https://YOUR-APP.vercel.app/api/cron/log-sensor
   ```

   Expect `{"ok":true,"polled":1,"results":{"<farm-id>":"logged"}}`.
   Then check Supabase → Table Editor → `readings` for a row with
   `source = 'sensor'`.

7. **History appears** — after two or more logged readings, the dashboard
   shows the "📡 Measured House History" tile.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Render build fails on PySide6 | Build command left as default | Set it to `pip install -r backend/requirements.txt` |
| `ModuleNotFoundError: pcis` | Root Directory was set on Render | Clear it — must be repo root |
| Dashboard: "Failed to fetch" | CORS, or wrong API URL | Step 6; check `NEXT_PUBLIC_PCIS_API_URL` has no trailing slash |
| First load takes 30s | Render free tier cold start | Expected; upgrade or accept |
| Vercel build fails: "limited to daily cron jobs" | Sub-daily schedule on Hobby | Use `0 3 * * *` in `frontend/vercel.json`; poll via GitHub Actions instead |
| Cron returns 401 | `CRON_SECRET` mismatch | Value in Vercel must match the header you send |
| GitHub Action fails immediately | Repo secrets not set | Add `PCIS_APP_URL` and `CRON_SECRET` under repo Settings → Secrets → Actions |
| GitHub Action stopped running | Auto-disabled after 60 days idle | Push any commit to re-enable |
| Cron: "No farms with Ecowitt keys" | Keys not saved to the farm row | Dashboard → sensor card → **Save & use** |
| Cron: `insert failed` | Migration not run | Step 2 |
| History tile never appears | Fewer than 2 logged readings | Needs 2+ points to draw a line |
| Vercel build: "No Next.js version" | Root Directory not set to `frontend` | Step 5.3 |

---

## After it's live

Every `git push` to `main` redeploys both services automatically. No
further manual steps.

Environment variable changes do **not** redeploy on their own — change one,
then hit Redeploy on that service.
