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
create or replace function public.log_sensor_reading(
    p_house_id        uuid,
    p_indoor_t_c       double precision,
    p_indoor_rh_pct    double precision,
    p_outdoor_t_c      double precision,
    p_outdoor_rh_pct   double precision,
    p_pressure_hpa     double precision,
    p_measured_air_speed_mps double precision
) returns void
language sql
security definer
set search_path = public
as $$
    insert into public.readings
        (house_id, indoor_t_c, indoor_rh_pct, outdoor_t_c, outdoor_rh_pct,
         pressure_hpa, measured_air_speed_mps, source)
    values
        (p_house_id, p_indoor_t_c, p_indoor_rh_pct, p_outdoor_t_c, p_outdoor_rh_pct,
         p_pressure_hpa, p_measured_air_speed_mps, 'sensor');
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
        f.ecowitt_indoor_block
    from public.farms f
    join public.houses h on h.farm_id = f.id
    where f.ecowitt_application_key is not null
      and f.ecowitt_api_key is not null
      and f.ecowitt_mac is not null
    order by f.id, h.created_at asc;

revoke all on public.farms_with_ecowitt_keys from anon, authenticated;
grant select on public.farms_with_ecowitt_keys to service_role;
