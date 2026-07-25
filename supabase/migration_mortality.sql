-- PCIS migration — mortality log
-- =====================================================================
-- Run this in the Supabase SQL editor (after schema.sql). It adds a
-- daily mortality log per flock. Live bird count = placed - SUM(dead).
-- Owner-scoped via the flock -> house -> farm chain, same as the rest.
-- =====================================================================

create table if not exists public.mortality (
    id           bigint generated always as identity primary key,
    flock_id     uuid not null references public.flocks (id) on delete cascade,
    recorded_on  date not null default (now() at time zone 'utc')::date,
    dead         int  not null check (dead >= 0),
    note         text,
    created_at   timestamptz not null default now()
);
create index if not exists mortality_flock_date_idx
    on public.mortality (flock_id, recorded_on desc);

alter table public.mortality enable row level security;

create policy "own mortality" on public.mortality
    for all using (
        exists (
            select 1
            from public.flocks fl
            join public.houses h on h.id = fl.house_id
            join public.farms f on f.id = h.farm_id
            where fl.id = flock_id and f.owner = auth.uid()
        )
    ) with check (
        exists (
            select 1
            from public.flocks fl
            join public.houses h on h.id = fl.house_id
            join public.farms f on f.id = h.farm_id
            where fl.id = flock_id and f.owner = auth.uid()
        )
    );
