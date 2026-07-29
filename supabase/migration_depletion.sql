-- PCIS migration — depletion (thinning / lifting / partial harvest)
-- =====================================================================
-- Run in the Supabase SQL editor, after the other migrations.
--
-- WHY THIS EXISTS
--
-- Broiler flocks are routinely thinned: part of the flock is caught and
-- sent to slaughter days before the rest. On this farm it is called
-- "lifting".
--
-- Until now the only way to tell PCIS the house had emptied was to lower
-- the live-bird count, which wrote the difference into the MORTALITY log.
-- The EU 2007/43/EC ceiling is roughly 3% at market age, while a thin
-- removes 20-40% of the flock in a single morning. So a routine harvest
-- did not nudge the mortality figure -- it detonated it, reporting a
-- catastrophic welfare breach on a day when nothing had gone wrong, and
-- corrupting the very outcome history the logged data exists to build.
--
-- Depleted birds leave the house, so they leave the heat, moisture and
-- CO2 load and the ventilation calculation must see the reduced count.
-- But they are alive. They are not mortality. Two different tables.
-- =====================================================================

create table if not exists public.depletions (
    id           bigint generated always as identity primary key,
    flock_id     uuid not null references public.flocks (id) on delete cascade,
    removed_on   date not null default (now() at time zone 'utc')::date,
    birds        int  not null check (birds > 0),
    note         text,
    created_at   timestamptz not null default now()
);
create index if not exists depletions_flock_idx on public.depletions (flock_id, removed_on desc);

alter table public.depletions enable row level security;

-- Same owner-scoped rule as every other table: a grower reaches their own
-- flocks only, through the farm they own.
create policy "own depletions" on public.depletions
    for all using (
        exists (
            select 1
            from public.flocks fl
            join public.houses h on h.id = fl.house_id
            join public.farms f  on f.id = h.farm_id
            where fl.id = depletions.flock_id
              and f.owner = auth.uid()
        )
    ) with check (
        exists (
            select 1
            from public.flocks fl
            join public.houses h on h.id = fl.house_id
            join public.farms f  on f.id = h.farm_id
            where fl.id = depletions.flock_id
              and f.owner = auth.uid()
        )
    );

-- ---------------------------------------------------------------------
-- Teach the unattended poller about depletion.
--
-- Without this the cron job would keep sizing ventilation for a full
-- house after a thin. That error is not symmetric: over-ventilating a
-- half-empty house in cold weather chills the birds that are left, and
-- the engine would have no way of knowing it was wrong.
-- ---------------------------------------------------------------------
create or replace view public.farms_with_ecowitt_keys as
    select distinct on (f.id)
        f.id            as farm_id,
        h.id            as house_id,
        f.ecowitt_application_key,
        f.ecowitt_api_key,
        f.ecowitt_mac,
        f.ecowitt_indoor_block,
        h.length_m, h.width_m, h.height_m, h.insulation,
        h.fan_index, h.installed_fans, h.static_pressure_pa,
        h.has_cooling_pads, h.heater_kw,
        fl.id            as flock_id,
        fl.placement_date,
        fl.bird_count,
        coalesce((
            select sum(m.dead) from public.mortality m where m.flock_id = fl.id
        ), 0)::int       as cumulative_dead,
        coalesce((
            select sum(d.birds) from public.depletions d where d.flock_id = fl.id
        ), 0)::int       as cumulative_depleted
    from public.farms f
    join public.houses h on h.farm_id = f.id
    left join public.flocks fl on fl.house_id = h.id and fl.active
    where f.ecowitt_application_key is not null
      and f.ecowitt_api_key is not null
      and f.ecowitt_mac is not null
    order by f.id, h.created_at asc;

revoke all on public.farms_with_ecowitt_keys from anon, authenticated;
grant select on public.farms_with_ecowitt_keys to service_role;
