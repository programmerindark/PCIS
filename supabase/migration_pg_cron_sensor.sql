-- Sensor capture, moved OUT of the web layer and into Postgres.
--
-- History, because it explains every design choice below. Capture used to
-- run cron-job.org -> a Vercel route -> Supabase -> Ecowitt. That chain
-- returned HTTP 200 every minute while writing NOTHING for two and a half
-- days. Ecowitt was healthy throughout -- calling it directly from Postgres
-- returns `code 0, success` with a reading seconds old -- so the break was
-- inside the web layer, and it stayed invisible because no component
-- recorded its own outcome anywhere a human would look.
--
-- Two jobs, deliberately on different schedules:
--
--   poll_ecowitt_readings()   every 1 min   measurement capture
--   pair_recommendation()     every 5 min   engine prediction alongside it
--
-- Measurements are the irreplaceable half: a missed minute is gone forever,
-- whereas a missed recommendation can be recomputed later from the stored
-- reading. So the engine (Render free tier -- sleeps, slow to wake) is kept
-- OUT of the capture path entirely.
--
-- Depends on migration_sensor_log.sql (log_sensor_reading,
-- log_recommendation_thin, farms_with_ecowitt_keys).

create extension if not exists http with schema extensions;
create extension if not exists pg_cron;


-- ---------------------------------------------------------------------
-- Visibility
-- ---------------------------------------------------------------------
-- Every poll writes a row here, success or failure. This is the direct fix
-- for the blindness described above.
create table if not exists public.sensor_poll_log (
    id        bigserial primary key,
    ran_at    timestamptz not null default now(),
    farm_id   uuid,
    outcome   text not null,          -- logged | skipped | error
    detail    text
);

create index if not exists sensor_poll_log_ran_at_idx
    on public.sensor_poll_log (ran_at desc);

alter table public.sensor_poll_log enable row level security;

drop policy if exists "own poll log" on public.sensor_poll_log;
create policy "own poll log" on public.sensor_poll_log
    for select
    using (exists (select 1 from public.farms f
                    where f.id = sensor_poll_log.farm_id and f.owner = auth.uid()));


-- Where the engine lives. A public URL, not a secret -- it ships in the
-- browser bundle -- but held in a table so a Render hostname change needs
-- no migration.
create table if not exists public.app_settings (
    key   text primary key,
    value text not null
);
insert into public.app_settings(key, value)
values ('engine_url', 'https://pcis-api.onrender.com')
on conflict (key) do nothing;

alter table public.app_settings enable row level security;
-- No policy on purpose: only SECURITY DEFINER functions read this.


-- ---------------------------------------------------------------------
-- 1. Measurement capture  (every minute)
-- ---------------------------------------------------------------------
create or replace function public.poll_ecowitt_readings()
returns integer
language plpgsql
security definer
set search_path to 'public', 'extensions'
as $function$
declare
    f            record;
    resp         record;
    j            jsonb;
    indoor_blk   text;
    outdoor_blk  text;
    v_in_t       double precision;
    v_in_rh      double precision;
    v_out_t      double precision;
    v_out_rh     double precision;
    v_press      double precision;
    v_wind       double precision;
    mode         text;
    written      integer := 0;
begin
    for f in select * from public.farms_with_ecowitt_keys loop
        begin
            select * into resp from extensions.http_get(
                'https://api.ecowitt.net/api/v3/device/real_time'
                || '?application_key=' || f.ecowitt_application_key
                || '&api_key='         || f.ecowitt_api_key
                || '&mac='             || f.ecowitt_mac
                || '&call_back=all&temp_unitid=1&pressure_unitid=3'
            );

            if resp.status <> 200 then
                insert into public.sensor_poll_log(farm_id, outcome, detail)
                values (f.farm_id, 'error', 'ecowitt http ' || resp.status);
                continue;
            end if;

            j := resp.content::jsonb;
            if coalesce(j->>'code', '') <> '0' then
                insert into public.sensor_poll_log(farm_id, outcome, detail)
                values (f.farm_id, 'error',
                        'ecowitt code ' || coalesce(j->>'code','?')
                        || ': ' || coalesce(j->>'msg',''));
                continue;
            end if;

            -- Blocks are named by sensor TYPE, not placement. On this farm
            -- the WS90 array (Ecowitt's "outdoor" block) hangs INSIDE the
            -- house, so ecowitt_indoor_block = 'outdoor'. Reading it from
            -- the column rather than assuming is what keeps the moisture
            -- balance the right way round -- inverted, the app would advise
            -- fans that make the house wetter, and both values look
            -- perfectly plausible either way.
            indoor_blk  := coalesce(f.ecowitt_indoor_block, 'outdoor');
            outdoor_blk := case when indoor_blk = 'indoor' then 'outdoor' else 'indoor' end;

            v_in_t   := nullif(j->'data'->indoor_blk ->'temperature'->>'value','')::double precision;
            v_in_rh  := nullif(j->'data'->indoor_blk ->'humidity'   ->>'value','')::double precision;
            v_out_t  := nullif(j->'data'->outdoor_blk->'temperature'->>'value','')::double precision;
            v_out_rh := nullif(j->'data'->outdoor_blk->'humidity'   ->>'value','')::double precision;
            v_press  := coalesce(
                nullif(j->'data'->'pressure'->'absolute'->>'value','')::double precision,
                nullif(j->'data'->'pressure'->'relative'->>'value','')::double precision);
            -- Ecowitt reports wind in mph regardless of the unit flags we
            -- send, so the conversion is explicit rather than assumed.
            v_wind   := round((nullif(j->'data'->'wind'->'wind_speed'->>'value','')::double precision
                               * 0.44704)::numeric, 2);

            if v_in_t is null then
                insert into public.sensor_poll_log(farm_id, outcome, detail)
                values (f.farm_id, 'error', 'no temperature in block ' || indoor_blk);
                continue;
            end if;

            mode := public.log_sensor_reading(
                f.house_id, v_in_t, v_in_rh, v_out_t, v_out_rh, v_press, v_wind);

            insert into public.sensor_poll_log(farm_id, outcome, detail)
            values (f.farm_id, mode,
                    'in ' || v_in_t || 'C/' || coalesce(v_in_rh::text,'-') || '%  out '
                    || coalesce(v_out_t::text,'-') || 'C/' || coalesce(v_out_rh::text,'-') || '%');

            if mode = 'logged' then written := written + 1; end if;

        exception when others then
            -- One farm's failure must not abort the others, and the reason
            -- has to survive somewhere a human will look.
            insert into public.sensor_poll_log(farm_id, outcome, detail)
            values (f.farm_id, 'error', left(sqlerrm, 300));
        end;
    end loop;

    -- Keep the log small enough to stay on the free tier.
    delete from public.sensor_poll_log
     where id < (select max(id) - 2000 from public.sensor_poll_log);

    return written;
end;
$function$;


-- ---------------------------------------------------------------------
-- 2. Engine pairing  (every five minutes)
-- ---------------------------------------------------------------------
-- A reading alone records what the house DID. Only the PAIR can ever be
-- scored -- predicted humidity against measured humidity, computed air
-- speed against the anemometer -- which is the whole purpose of the
-- /validation page and the only route to replacing PCIS's assigned
-- confidence numbers with earned ones.
create or replace function public.pair_recommendation()
returns integer
language plpgsql
security definer
set search_path to 'public', 'extensions'
as $function$
declare
    f          record;
    r          record;
    engine     text;
    age_days   integer;
    live_birds integer;
    body       jsonb;
    resp       record;
    rec        jsonb;
    made       integer := 0;
begin
    select value into engine from public.app_settings where key = 'engine_url';
    if engine is null then return 0; end if;

    -- Render's free tier sleeps; allow for a cold start but do not hang
    -- the cron worker indefinitely.
    perform extensions.http_set_curlopt('CURLOPT_TIMEOUT_MS', '45000');

    for f in select * from public.farms_with_ecowitt_keys where flock_id is not null loop
        begin
            select * into r
              from public.readings
             where house_id = f.house_id and source = 'sensor'
             order by observed_at desc
             limit 1;

            if r is null or r.observed_at < now() - interval '10 minutes' then
                continue;                       -- nothing fresh to explain
            end if;
            if r.indoor_rh_pct is null or r.outdoor_t_c is null or r.outdoor_rh_pct is null then
                continue;                       -- engine needs all three
            end if;

            age_days := greatest(0, (current_date - f.placement_date));

            -- Lifted birds have physically left: they take their heat and
            -- moisture with them, so sizing ventilation for birds that are
            -- no longer there over-ventilates a half-empty house, which in
            -- cold weather chills the ones that remain.
            live_birds := greatest(1, coalesce(f.bird_count,0)
                                      - coalesce(f.cumulative_dead,0)
                                      - coalesce(f.cumulative_depleted,0));

            body := jsonb_build_object(
                'length_m', f.length_m, 'width_m', f.width_m, 'height_m', f.height_m,
                'insulation', f.insulation, 'fan_index', f.fan_index,
                'installed_fans', f.installed_fans,
                'static_pressure_pa', f.static_pressure_pa,
                'cooling_pads', f.has_cooling_pads, 'heater_kw', f.heater_kw,
                'bird_age_days', age_days, 'bird_count', live_birds,
                'indoor_rh_pct', r.indoor_rh_pct,
                'outdoor_t_c', r.outdoor_t_c, 'outdoor_rh_pct', r.outdoor_rh_pct)
                || case when r.pressure_hpa is null then '{}'::jsonb
                        else jsonb_build_object('pressure_hpa', r.pressure_hpa) end
                || case when r.measured_air_speed_mps is null then '{}'::jsonb
                        else jsonb_build_object('measured_air_speed_mps', r.measured_air_speed_mps) end;

            select * into resp from extensions.http_post(
                engine || '/recommend', body::text, 'application/json');

            if resp.status <> 200 then
                insert into public.sensor_poll_log(farm_id, outcome, detail)
                values (f.farm_id, 'error', 'engine http ' || resp.status);
                continue;
            end if;
            rec := resp.content::jsonb;

            perform public.log_recommendation_thin(
                f.house_id, f.flock_id,
                (rec->>'fans_on')::integer,
                (rec->>'pads_on')::boolean,
                (rec->>'heating_needed')::boolean,
                rec->>'governing_constraint',
                (rec->'bird_status'->>'comfort_score')::double precision,
                rec->'bird_status'->>'heat_stress_risk',
                (rec->>'air_speed_mps')::double precision,
                (rec->>'target_airspeed_mps')::double precision,
                (rec->>'vpd_kpa')::double precision,
                coalesce((rec->>'action_confidence')::double precision,
                         (rec->>'confidence_score')::double precision),
                rec);
            made := made + 1;

        exception when others then
            insert into public.sensor_poll_log(farm_id, outcome, detail)
            values (f.farm_id, 'error', 'pairing: ' || left(sqlerrm, 250));
        end;
    end loop;

    return made;
end;
$function$;


-- Neither function may be called from the web: both spend the farm's
-- Ecowitt/engine quota, and the cron worker runs as postgres anyway.
revoke all on function public.poll_ecowitt_readings() from public, anon, authenticated;
revoke all on function public.pair_recommendation()   from public, anon, authenticated;


-- ---------------------------------------------------------------------
-- Schedules
-- ---------------------------------------------------------------------
-- Re-running is safe: cron.schedule() upserts by job name.
select cron.schedule('pcis-sensor-poll', '* * * * *',
                     $$select public.poll_ecowitt_readings()$$);

select cron.schedule('pcis-pair-recommendation', '*/5 * * * *',
                     $$select public.pair_recommendation()$$);

-- Useful checks:
--   select * from cron.job;
--   select * from public.sensor_poll_log order by id desc limit 20;
--   select jobid, status, return_message, start_time
--     from cron.job_run_details order by start_time desc limit 20;
