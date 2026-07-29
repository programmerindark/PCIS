# Go live: minute-by-minute logging

Ordered. Each step's check gates the next — don't skip ahead, because a
failure at step 5 is very hard to diagnose if step 2 silently didn't run.

Roughly 20 minutes.

---

## Step 1 — Run the two migrations

Supabase dashboard → **SQL Editor** → **New query**.

**1a.** Paste the whole of `supabase/migration_sensor_log.sql` → **Run**.

Safe to re-run even though you ran an earlier version — it uses
`create or replace` and `add column if not exists` throughout. This time it
adds `log_recommendation_thin`, which is what keeps minute-logging from
filling the database.

**1b.** New query. Paste the whole of `supabase/migration_depletion.sql` →
**Run**.

This one is new: the `depletions` table (lifting ≠ mortality) and an
updated view that subtracts lifted birds from the ventilation calculation.

**Check — run this and confirm both come back:**

```sql
select routine_name from information_schema.routines
where routine_name in ('log_recommendation_thin', 'log_sensor_reading');

select * from public.farms_with_ecowitt_keys;
```

The second must return a row with `bird_count`, `placement_date` and
`cumulative_depleted` populated. If `flock_id` is null the house has no
active flock, and the poller will log readings but skip recommendations.

---

## Step 2 — Push the code

PowerShell, from `C:\Users\amits\OneDrive\Desktop\PCIS_flat`:

```powershell
del ".git\index.lock"
git add -A
git commit -m "Minute-level logging, depletion tracking, house log page"
git push
```

Branch is `master`, already tracking `origin/master`, so plain `git push`
is right.

**Check:** Vercel shows a new deployment going green. Open the app — a
**Log** tab should now appear in the nav next to Validation.

---

## Step 3 — Speed up the gateway's own upload

This is the step that's easy to miss and quietly wastes everything else.

Your Ecowitt gateway uploads to Ecowitt's cloud on its own schedule. If
that's set to 5 minutes, polling every minute just re-reads the same
values five times — you get five identical rows, not five measurements.

In the **WSView Plus** app → your gateway → **Upload / Customized** (naming
varies by firmware) → set the upload interval to **60 seconds**.

**Check:** in the Ecowitt app, watch the reading timestamp update about
once a minute.

---

## Step 4 — Set up the 1-minute poller

[cron-job.org](https://cron-job.org) — free, allows up to 60 executions per
hour. Sign up, then **Create cronjob**:

| Field | Value |
|---|---|
| Title | PCIS sensor poll |
| URL | `https://YOUR-APP.vercel.app/api/cron/log-sensor` |
| Schedule | Every 1 minute |
| Request method | GET |

Then open **Advanced / Headers** and add:

```
Authorization: Bearer YOUR_CRON_SECRET
```

Same value as `CRON_SECRET` in your Vercel environment variables. Without
this header the endpoint returns 401 and logs nothing.

Save and enable.

**Check:** cron-job.org's execution history shows `200` responses. Click
one — the body should read something like:

```json
{"ok":true,"polled":1,"results":{"<farm-id>":"logged + advised (changed)"}}
```

`changed` or `steady` are both correct — `steady` means the decision was
identical to the previous minute, so the numeric row was written but the
8 kB explanation payload was skipped. That's the storage optimisation
working.

---

## Step 5 — Turn off the old pollers

You now have three schedulers pointed at the same endpoint. Leave them all
running and you'll get duplicate rows.

**Disable GitHub Actions:** repo → **Actions** tab → *Log sensor reading* →
**⋯** → **Disable workflow**.

**Leave the Vercel daily cron alone.** It's a once-a-day backstop that
costs nothing and proves the endpoint still works if cron-job.org ever
goes quiet.

---

## Step 6 — Watch it for ten minutes

Open the **Log** page in the app.

- Rows should appear about once a minute
- **Changes only** (the default) shows just the moments the recommendation
  moved — a steady ten minutes may legitimately be one line
- **Every minute** shows the raw stream
- The air-speed column reads `measured / calculated`

Then check the **Dashboard**: next to the humidity tile there's now a data
age badge — "just now", "3m ago" — green while fresh, amber past 25
minutes, red past 45.

---

## What to look for in the first day

**Fan count oscillating.** If the change log flags a change nearly every
minute — 10 fans, 11, 10, 11 — that isn't the log being noisy, it's the
engine hunting because conditions are sitting exactly on a rounding
boundary. Minute resolution makes this visible for the first time. If you
see it, tell me: the fix is hysteresis (require a margin before changing
the recommendation), and it matters because nobody should be told to
change fan count sixty times an hour.

**`ecowitt error:` in the cron response.** Ecowitt publishes no documented
rate limit for the cloud API. If they throttle at one call a minute you'll
see it here. Back the schedule off to 2 minutes; nothing is lost.

**Storage.** Expect roughly 26–61 MB per month against Supabase's 500 MB
free tier. Check in a week under **Database → Usage**. If it's tracking
much higher than that, the change-detection isn't working and it's worth
looking at before it becomes a problem.

**Render staying awake.** Minute-polling keeps the free-tier API from
sleeping, so no more 30-second cold starts. It lands at ~744 instance-hours
against the 750 free — just inside, but worth knowing it's close.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| cron-job.org shows 401 | Missing or wrong `Authorization` header | Must exactly match `CRON_SECRET` in Vercel |
| `"logged (no active flock)"` | House has no active flock | Dashboard → set up the current flock |
| `"logged (engine unreachable)"` | Render asleep or slow | Harmless — the reading was still saved. Should stop once polling keeps it warm |
| `"insert failed: ... log_recommendation_thin"` | Step 1a not run | Re-run `migration_sensor_log.sql` |
| Log page empty | No readings yet, or wrong house selected | Give it 2 minutes; check the house dropdown |
| Identical values every row | Gateway upload interval too slow | Step 3 |
| Duplicate rows each minute | Two schedulers running | Step 5 |
