# Database setup

Run these **in order**. They are not numbered and several depend on objects
created by earlier ones, so the order below is the ordering — there is no
migration tool inferring it for you.

Paste each into the Supabase SQL editor (Project → SQL Editor → New query),
or apply with `supabase db push` if you use the CLI.

| # | File | Creates | Depends on |
|---|------|---------|-----------|
| 1 | `schema.sql` | `profiles`, `farms`, `houses`, `flocks`, `recommendations`, RLS | — |
| 2 | `migration_mortality.sql` | `mortality` | 1 |
| 3 | `migration_sensors.sql` | Ecowitt columns on `farms` | 1 |
| 4 | `migration_sensor_log.sql` | `readings`, `log_sensor_reading`, `log_recommendation_thin`, `farms_with_ecowitt_keys` | 1, 3 |
| 5 | `migration_depletion.sql` | `depletions`, updated `farms_with_ecowitt_keys` | 1, 4 |
| 6 | `migration_gc_inputs.sql` | `crop_inputs`, `depletions.weight_kg`, `crop_gc_inputs` | 5 |
| 7 | `migration_pg_cron_sensor.sql` | `sensor_poll_log`, `app_settings`, the two cron jobs | 4, 5 |

Step 7 also enables the `http` and `pg_cron` extensions and schedules the
polling. Skip it if you would rather drive the sensor from somewhere else —
everything above it works without it.

## What step 7 turns on

Two scheduled jobs run **inside Postgres**, not in the web app:

```
poll_ecowitt_readings()   every 1 min   fetches the sensor, appends a reading
pair_recommendation()     every 5 min   asks the engine what it advises
```

They are separate on purpose. A missed measurement is gone forever; a missed
recommendation can be recomputed later from the stored reading. So the engine
— which may be on a free tier that sleeps — is kept out of the capture path.

This replaced an external scheduler calling a serverless route. That chain
returned HTTP 200 every minute while writing nothing for two and a half days,
because no component recorded its own outcome anywhere durable. Hence
`sensor_poll_log`: one row per farm per run, success or failure.

## After setup, check it works

```sql
-- Are the jobs registered?
select jobname, schedule, active from cron.job;

-- Is anything landing? Expect roughly one row a minute.
select ran_at, outcome, detail
  from public.sensor_poll_log order by id desc limit 20;

-- Did a scheduled run itself fail?
select jobid, status, return_message, start_time
  from cron.job_run_details order by start_time desc limit 20;
```

## One setting you must get right

`farms.ecowitt_indoor_block` names which Ecowitt block is **physically inside
the house**, and Ecowitt names its blocks by sensor TYPE, not by placement.

If your WS90 array hangs inside the shed and the console sits outside — a
common install — then Ecowitt's `"outdoor"` block is your indoor reading, and
this column must be set to `'outdoor'`.

Get it backwards and the moisture balance inverts: the app will recommend
fans that make the house wetter. **Nothing can detect this automatically**,
because both readings look perfectly plausible either way. Check it against a
thermometer you trust before relying on any advice.

## Environment variables

| Where | Variable | Notes |
|---|---|---|
| Frontend | `NEXT_PUBLIC_SUPABASE_URL` | public |
| Frontend | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | public, RLS-protected |
| Frontend | `NEXT_PUBLIC_PCIS_API_URL` | your engine deployment |
| Database | `app_settings.engine_url` | row in the table, set by step 7 |

There is deliberately **no service-role key** in the running system any more.
The cron jobs are `SECURITY DEFINER` functions owned by `postgres`, so nothing
needs a key that bypasses RLS. If you find yourself adding one, check first
whether a narrow definer function would do instead.
