-- PCIS migration — continuous sensor logging
-- =====================================================================
-- Run in the Supabase SQL editor (after schema.sql, migration_mortality.sql
-- and migration_sensors.sql).
--
-- `readings` already exists in schema.sql (source: manual | weather |
-- sensor) but nothing has ever written a 'sensor' row — every reading so
-- far has been a one-off manual test. This migration:
--
--   1. Widens `readings` with the two extra fields the Ecowitt integration
--      exposes (pressure, measured air speed) so a logged row carries
--      everything /api/cron/log-sensor captures, not just temp/RH.
--   2. Adds an RLS policy so the service-role cron job (which does not
--      carry a user session) can insert on behalf of a house's owner via
--      a SECURITY DEFINER function rather than a blanket "service role
--      bypasses RLS" assumption — kept explicit so it's auditable here
--      rather than implicit in how the Supabase client is invoked.
-- =====================================================================

alter table public.readings
    add column if not exists pressure_hpa            double precision,
    add column if not exists measured_air_speed_mps   double precision;

-- ---------------------------------------------------------------------
-- log_sensor_reading: the only way the cron job writes to `readings`.
--
-- SECURITY DEFINER so it can insert regardless of who calls it, but it
-- takes a house_id and does nothing else -- it cannot read or modify any
-- other table, and the cron route is the only caller (see
-- frontend/app/api/cron/log-sensor/route.ts). This is narrower than
-- handing the cron job a service-role key with blanket table access.
-- ---------------------------------------------------------------------
--
-- DEDUPLICATION. Returns 'logged' or 'skipped'.
--
-- Several schedulers can end up pointed at the same endpoint -- a
-- cron-job.org minute poll, a GitHub Actions workflow, Vercel's own cron,
-- plus manual test hits while debugging. Live data showed 15 minutes out of
-- 98 carrying two to seven rows each.
--
-- The damage is not just wasted rows. Duplicates within one minute get
-- compared against each other by the change-detection logic, so a stable
-- engine looks like it is oscillating: the raw count showed 32 fan changes
-- in 200 rows, while deduplicating to one row per minute revealed only 2
-- real changes in 102 minutes. A guard here is more robust than trying to
-- keep every external scheduler disciplined, because it holds no matter
-- how many callers appear later.
--
-- 40 seconds rather than 60: a poll running slightly early must not be
-- rejected, but a genuine second poll within the same minute must be.
create or replace function public.log_sensor_reading(
    p_house_id        uuid,
    p_indoor_t_c       double precision,
    p_indoor_rh_pct    double precision,
    p_outdoor_t_c      double precision,
    p_outdoor_rh_pct   double precision,
    p_pressure_hpa     double precision,
    p_measured_air_speed_mps double precision
) returns text
language plpgsql
security definer
set search_path = public
as $$
begin
    if exists (
        select 1 from public.readings
         where house_id = p_house_id
           and source = 'sensor'
           and observed_at > now() - interval '40 seconds'
    ) then
        return 'skipped';
    end if;

    insert into public.readings
        (house_id, indoor_t_c, indoor_rh_pct, outdoor_t_c, outdoor_rh_pct,
         pressure_hpa, measured_air_speed_mps, source)
    values
        (p_house_id, p_indoor_t_c, p_indoor_rh_pct, p_outdoor_t_c, p_outdoor_rh_pct,
         p_pressure_hpa, p_measured_air_speed_mps, 'sensor');
    return 'logged';
end;
$$;

-- Deliberately service_role ONLY, not anon or authenticated. The cron
-- route runs server-side in a Vercel serverless function with the
-- service_role key in a server-only env var (never NEXT_PUBLIC_*, never
-- shipped to the browser). Granting this to anon would let anyone with
-- the public anon key -- which is, by design, embedded in the frontend
-- bundle -- write arbitrary rows into any house's reading history.
grant execute on function public.log_sensor_reading to service_role;

-- ---------------------------------------------------------------------
-- farms_with_ecowitt_keys: what the cron job needs to poll every farm.
--
-- Same reasoning as above: this returns Ecowitt credentials, so it is
-- service_role only. It exists as a narrow, named view of exactly the
-- columns the poller needs, rather than having the cron route select
-- straight from `farms` with the service-role key -- so the credential
-- surface a compromised cron route could read is scoped to this, not to
-- every column on every table.
-- ---------------------------------------------------------------------
-- One Ecowitt gateway is a farm-level piece of hardware, but `readings`
-- is keyed by house. `distinct on` picks the farm's FIRST-created house
-- so a poll logs one row, not one per house -- multi-house farms with a
-- single sensor would otherwise get the same reading duplicated against
-- every house, silently inflating that house's apparent data density.
create or replace view public.farms_with_ecowitt_keys as
    select distinct on (f.id)
        f.id            as farm_id,
        h.id            as house_id,
        f.ecowitt_application_key,
        f.ecowitt_api_key,
        f.ecowitt_mac,
        f.ecowitt_indoor_block,
        -- House geometry + equipment: everything /recommend needs, so the
        -- cron can run the ENGINE on the measured conditions rather than
        -- only filing away raw numbers. Without this the database would
        -- accumulate a record of what the house did but no record of what
        -- PCIS would have said about it -- and a prediction that was never
        -- written down cannot later be scored against the outcome.
        h.length_m, h.width_m, h.height_m, h.insulation,
        h.fan_index, h.installed_fans, h.static_pressure_pa,
        h.has_cooling_pads, h.heater_kw,
        -- Active flock, for bird age and count. Null when the house is
        -- empty between crops, in which case the poller logs the reading
        -- but skips the recommendation (no birds, nothing to advise).
        fl.id            as flock_id,
        fl.placement_date,
        fl.bird_count,
        coalesce((
            select sum(m.dead) from public.mortality m where m.flock_id = fl.id
        ), 0)::int       as cumulative_dead
    from public.farms f
    join public.houses h on h.farm_id = f.id
    left join public.flocks fl on fl.house_id = h.id and fl.active
    where f.ecowitt_application_key is not null
      and f.ecowitt_api_key is not null
      and f.ecowitt_mac is not null
    order by f.id, h.created_at asc;

revoke all on public.farms_with_ecowitt_keys from anon, authenticated;
grant select on public.farms_with_ecowitt_keys to service_role;

-- ---------------------------------------------------------------------
-- log_recommendation: the cron job's counterpart to log_sensor_reading.
--
-- Storing the engine's output next to the measurement it was computed
-- from is the entire point of unattended logging. A `readings` row says
-- what the house was doing; the matching `recommendations` row says what
-- PCIS believed about it at that moment -- what it predicted the indoor
-- humidity would be, how fast it computed the air to be moving, how many
-- fans it would have run.
--
-- Once both exist on the same timeline, claims the engine currently makes
-- on the strength of cited literature and engineering judgment become
-- checkable against this specific house: predicted vs measured humidity,
-- computed vs measured air speed. That is the difference between a
-- confidence score someone assigned and one the data earned.
-- ---------------------------------------------------------------------
create or replace function public.log_recommendation(
    p_house_id             uuid,
    p_flock_id             uuid,
    p_fans_on              int,
    p_pads_on              boolean,
    p_heating_needed       boolean,
    p_governing_constraint text,
    p_comfort_index        double precision,
    p_heat_stress_risk     text,
    p_air_speed_mps        double precision,
    p_target_airspeed_mps  double precision,
    p_vpd_kpa              double precision,
    p_confidence           double precision,
    p_payload              jsonb
) returns void
language sql
security definer
set search_path = public
as $$
    insert into public.recommendations
        (house_id, flock_id, fans_on, pads_on, heating_needed,
         governing_constraint, comfort_index, heat_stress_risk,
         air_speed_mps, target_airspeed_mps, vpd_kpa, confidence, payload)
    values
        (p_house_id, p_flock_id, p_fans_on, p_pads_on, p_heating_needed,
         p_governing_constraint, p_comfort_index, p_heat_stress_risk,
         p_air_speed_mps, p_target_airspeed_mps, p_vpd_kpa, p_confidence,
         p_payload);
$$;

grant execute on function public.log_recommendation to service_role;

-- ---------------------------------------------------------------------
-- log_recommendation_thin: minute-resolution logging without the bloat.
--
-- The full engine response is ~8 kB, over half of it human-readable
-- explanation strings that are byte-identical from one minute to the next
-- while conditions hold steady. Storing it every minute costs ~354 MB a
-- month against a 500 MB free-tier database -- the writes would start
-- failing about six weeks in, which on this farm means mid-crop.
--
-- So: the numeric columns are written EVERY tick, giving an unbroken
-- minute-by-minute record of what the house was doing and what PCIS
-- decided. The fat jsonb payload is written only when the decision
-- actually changed -- a different fan count, a different governing
-- constraint, pads or heating switching state.
--
-- That keeps full forensic detail at exactly the moments something
-- happened, which is when anyone would ever go looking, and spends
-- nothing on the long stretches where the answer was the same as the
-- minute before.
-- ---------------------------------------------------------------------
create or replace function public.log_recommendation_thin(
    p_house_id             uuid,
    p_flock_id             uuid,
    p_fans_on              int,
    p_pads_on              boolean,
    p_heating_needed       boolean,
    p_governing_constraint text,
    p_comfort_index        double precision,
    p_heat_stress_risk     text,
    p_air_speed_mps        double precision,
    p_target_airspeed_mps  double precision,
    p_vpd_kpa              double precision,
    p_confidence           double precision,
    p_payload              jsonb
) returns text
language plpgsql
security definer
set search_path = public
as $$
declare
    prev record;
    changed boolean := true;
begin
    select fans_on, pads_on, heating_needed, governing_constraint, heat_stress_risk
      into prev
      from public.recommendations
     where house_id = p_house_id
     order by created_at desc
     limit 1;

    if found then
        changed := (prev.fans_on              is distinct from p_fans_on)
                or (prev.pads_on              is distinct from p_pads_on)
                or (prev.heating_needed       is distinct from p_heating_needed)
                or (prev.governing_constraint is distinct from p_governing_constraint)
                or (prev.heat_stress_risk     is distinct from p_heat_stress_risk);
    end if;

    insert into public.recommendations
        (house_id, flock_id, fans_on, pads_on, heating_needed,
         governing_constraint, comfort_index, heat_stress_risk,
         air_speed_mps, target_airspeed_mps, vpd_kpa, confidence, payload)
    values
        (p_house_id, p_flock_id, p_fans_on, p_pads_on, p_heating_needed,
         p_governing_constraint, p_comfort_index, p_heat_stress_risk,
         p_air_speed_mps, p_target_airspeed_mps, p_vpd_kpa, p_confidence,
         case when changed then p_payload else null end);

    return case when changed then 'changed' else 'steady' end;
end;
$$;

grant execute on function public.log_recommendation_thin to service_role;
