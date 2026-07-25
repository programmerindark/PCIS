-- PCIS v1 — Supabase / Postgres schema
-- =====================================================================
-- Paste into the Supabase SQL editor and run. Designed for Supabase Auth
-- (auth.users) with Row Level Security so each grower only sees their own
-- farms. Every data-bearing table hangs off a farm; ownership is checked
-- back to farms.owner = auth.uid().
--
-- Tables:
--   profiles         one row per auth user (display name, role)
--   farms            a grower's farm (owner = auth user)
--   houses           a broiler house within a farm (its geometry + kit)
--   flocks           a placement of birds in a house
--   readings         a climate observation (manual / weather / sensor)
--   recommendations  a logged engine result (for history + future ML)
--   alerts           a surfaced warning for the operator
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- profiles
-- ---------------------------------------------------------------------
create table if not exists public.profiles (
    id          uuid primary key references auth.users (id) on delete cascade,
    full_name   text,
    role        text not null default 'grower',   -- grower | admin
    created_at  timestamptz not null default now()
);

-- Auto-create a profile row when a new auth user signs up.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
    insert into public.profiles (id, full_name)
    values (new.id, coalesce(new.raw_user_meta_data ->> 'full_name', ''))
    on conflict (id) do nothing;
    return new;
end; $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------
-- farms
-- ---------------------------------------------------------------------
create table if not exists public.farms (
    id          uuid primary key default gen_random_uuid(),
    owner       uuid not null references auth.users (id) on delete cascade,
    name        text not null,
    location    text,
    latitude    double precision,   -- for the weather API
    longitude   double precision,
    created_at  timestamptz not null default now()
);
create index if not exists farms_owner_idx on public.farms (owner);

-- ---------------------------------------------------------------------
-- houses  (geometry + installed equipment; matches the engine inputs)
-- ---------------------------------------------------------------------
create table if not exists public.houses (
    id                 uuid primary key default gen_random_uuid(),
    farm_id            uuid not null references public.farms (id) on delete cascade,
    name               text not null,
    length_m           double precision not null default 120,
    width_m            double precision not null default 15,
    height_m           double precision not null default 3,
    insulation         text not null default 'insulated',   -- uninsulated|insulated|well_insulated
    fan_index          int  not null default 0,             -- index into the engine fan catalog
    installed_fans     int  not null default 10,
    static_pressure_pa double precision not null default 30,
    has_cooling_pads   boolean not null default false,
    heater_kw          double precision not null default 0,
    created_at         timestamptz not null default now()
);
create index if not exists houses_farm_idx on public.houses (farm_id);

-- ---------------------------------------------------------------------
-- flocks
-- ---------------------------------------------------------------------
create table if not exists public.flocks (
    id             uuid primary key default gen_random_uuid(),
    house_id       uuid not null references public.houses (id) on delete cascade,
    name           text,
    strain         text not null default 'Ross 308',
    placement_date date not null,
    bird_count     int  not null,
    active         boolean not null default true,
    created_at     timestamptz not null default now()
);
create index if not exists flocks_house_idx on public.flocks (house_id);

-- ---------------------------------------------------------------------
-- readings  (a point-in-time climate observation)
-- ---------------------------------------------------------------------
create table if not exists public.readings (
    id             bigint generated always as identity primary key,
    house_id       uuid not null references public.houses (id) on delete cascade,
    observed_at    timestamptz not null default now(),
    indoor_t_c     double precision,
    indoor_rh_pct  double precision,
    outdoor_t_c    double precision,
    outdoor_rh_pct double precision,
    source         text not null default 'manual'   -- manual | weather | sensor
);
create index if not exists readings_house_time_idx on public.readings (house_id, observed_at desc);

-- ---------------------------------------------------------------------
-- recommendations  (logged engine output; history + future calibration)
-- ---------------------------------------------------------------------
create table if not exists public.recommendations (
    id                   bigint generated always as identity primary key,
    house_id             uuid not null references public.houses (id) on delete cascade,
    flock_id             uuid references public.flocks (id) on delete set null,
    created_at           timestamptz not null default now(),
    fans_on              int,
    pads_on              boolean,
    heating_needed       boolean,
    governing_constraint text,
    comfort_index        double precision,
    heat_stress_risk     text,
    air_speed_mps        double precision,
    target_airspeed_mps  double precision,
    vpd_kpa              double precision,
    confidence           double precision,
    payload              jsonb           -- full engine response, for replay/ML
);
create index if not exists recommendations_house_time_idx on public.recommendations (house_id, created_at desc);

-- ---------------------------------------------------------------------
-- alerts
-- ---------------------------------------------------------------------
create table if not exists public.alerts (
    id          bigint generated always as identity primary key,
    house_id    uuid not null references public.houses (id) on delete cascade,
    created_at  timestamptz not null default now(),
    severity    text not null default 'info',   -- info | warning | critical
    kind        text not null,                  -- e.g. heat_stress | fan_shortfall | high_humidity
    title       text not null,
    message     text,
    resolved    boolean not null default false
);
create index if not exists alerts_house_time_idx on public.alerts (house_id, created_at desc);

-- =====================================================================
-- Row Level Security
-- =====================================================================
alter table public.profiles        enable row level security;
alter table public.farms           enable row level security;
alter table public.houses          enable row level security;
alter table public.flocks          enable row level security;
alter table public.readings        enable row level security;
alter table public.recommendations enable row level security;
alter table public.alerts          enable row level security;

-- profiles: a user sees/edits only their own profile row.
create policy "own profile" on public.profiles
    for all using (id = auth.uid()) with check (id = auth.uid());

-- farms: owner-scoped.
create policy "own farms" on public.farms
    for all using (owner = auth.uid()) with check (owner = auth.uid());

-- Helper predicate reused below: a house belongs to the current user
-- when its farm is owned by them.
create policy "own houses" on public.houses
    for all using (
        exists (select 1 from public.farms f where f.id = farm_id and f.owner = auth.uid())
    ) with check (
        exists (select 1 from public.farms f where f.id = farm_id and f.owner = auth.uid())
    );

create policy "own flocks" on public.flocks
    for all using (
        exists (
            select 1 from public.houses h join public.farms f on f.id = h.farm_id
            where h.id = house_id and f.owner = auth.uid()
        )
    ) with check (
        exists (
            select 1 from public.houses h join public.farms f on f.id = h.farm_id
            where h.id = house_id and f.owner = auth.uid()
        )
    );

create policy "own readings" on public.readings
    for all using (
        exists (
            select 1 from public.houses h join public.farms f on f.id = h.farm_id
            where h.id = house_id and f.owner = auth.uid()
        )
    ) with check (
        exists (
            select 1 from public.houses h join public.farms f on f.id = h.farm_id
            where h.id = house_id and f.owner = auth.uid()
        )
    );

create policy "own recommendations" on public.recommendations
    for all using (
        exists (
            select 1 from public.houses h join public.farms f on f.id = h.farm_id
            where h.id = house_id and f.owner = auth.uid()
        )
    ) with check (
        exists (
            select 1 from public.houses h join public.farms f on f.id = h.farm_id
            where h.id = house_id and f.owner = auth.uid()
        )
    );

create policy "own alerts" on public.alerts
    for all using (
        exists (
            select 1 from public.houses h join public.farms f on f.id = h.farm_id
            where h.id = house_id and f.owner = auth.uid()
        )
    ) with check (
        exists (
            select 1 from public.houses h join public.farms f on f.id = h.farm_id
            where h.id = house_id and f.owner = auth.uid()
        )
    );
