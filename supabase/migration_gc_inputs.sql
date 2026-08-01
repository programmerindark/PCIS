-- Inputs the GC payout formula needs and no sensor can supply.
--
-- Everything else on the dashboard is measured. Feed consumed and average
-- bird weight are not: someone weighs a sample and reads the feed slips.
-- That difference is why `entered_at` is stored and shown -- an entered
-- figure sitting next to live sensor readings looks equally current, and
-- a two-week-old weight priced against today's mortality is a plausible
-- wrong answer rather than an obvious one.
--
-- Sources: IB Group GC Policy, EC Shed (16 Oct 2025 - 15 Oct 2026), via
-- pcis.core.gc_policy. This file stores inputs only; no arithmetic here.

-- 1. Lift weight ------------------------------------------------------
--
-- `depletions` already records how many birds left. It did not record how
-- much they WEIGHED, and the GC formula cannot be evaluated without that:
-- the feed those birds ate is already in the crop's feed total, so
-- omitting their kilograms inflates FCR and grades the crop into a worse
-- slab. On this farm's numbers that is the difference between Rs 426,448
-- and Rs 0 -- see tests/test_gc_policy.py.
--
-- Nullable on purpose. Historic thins have no recorded weight and must
-- not be back-filled with a guess; gc_policy reports that it cannot price
-- the crop instead of inventing the missing kilograms.
alter table public.depletions
  add column if not exists weight_kg double precision;

comment on column public.depletions.weight_kg is
  'Total live weight lifted, kg, from the lifting slip. NULL means not '
  'recorded -- gc_policy refuses to price the crop rather than estimate it.';

-- 2. Feed and weight --------------------------------------------------
--
-- One row per entry rather than one mutable row per flock, so the crop
-- keeps a history. `feed_consumed_kg` is cumulative to date (that is how
-- the feed slips read); `avg_weight_kg` is the sample weighing.
create table if not exists public.crop_inputs (
    id                bigserial primary key,
    flock_id          uuid not null references public.flocks(id) on delete cascade,
    entered_at        timestamptz not null default now(),
    feed_consumed_kg  double precision not null check (feed_consumed_kg >= 0),
    avg_weight_kg     double precision not null check (avg_weight_kg > 0),
    -- Which contract column this crop is paid on. The same cFCR pays
    -- Rs 12.75 to Rs 14.75/kg across shed types -- a 16% spread -- so this
    -- cannot be defaulted silently to a guess.
    shed_type         text not null default 'other_ec'
                      check (shed_type in ('other_basic_ec','parivartan_basic_ec',
                                           'other_semi_ec','parivartan_semi_ec',
                                           'other_ec','parivartan_ec')),
    note              text,
    created_at        timestamptz not null default now()
);

create index if not exists crop_inputs_flock_entered_idx
    on public.crop_inputs (flock_id, entered_at desc);

alter table public.crop_inputs enable row level security;

-- Mirrors the `own depletions` policy exactly: reachable only through
-- flock -> house -> farm.owner.
drop policy if exists "own crop inputs" on public.crop_inputs;
create policy "own crop inputs" on public.crop_inputs
    for all
    using (exists (
        select 1 from public.flocks fl
          join public.houses h on h.id = fl.house_id
          join public.farms  f on f.id = h.farm_id
        where fl.id = crop_inputs.flock_id and f.owner = auth.uid()))
    with check (exists (
        select 1 from public.flocks fl
          join public.houses h on h.id = fl.house_id
          join public.farms  f on f.id = h.farm_id
        where fl.id = crop_inputs.flock_id and f.owner = auth.uid()));

-- 3. Latest position per flock ----------------------------------------
--
-- The dashboard needs the newest entry plus the lift totals in one read.
-- `lifted_weight_kg` deliberately returns NULL when ANY thin is missing
-- its weight, rather than summing the ones that have it: a partial total
-- understates delivered kilograms, which is the same failure as omitting
-- them entirely but harder to notice.
create or replace view public.crop_gc_inputs as
select
    fl.id                       as flock_id,
    fl.house_id,
    fl.bird_count               as chicks_housed,
    ci.feed_consumed_kg,
    ci.avg_weight_kg,
    ci.shed_type,
    ci.entered_at,
    coalesce(d.birds, 0)        as depleted_birds,
    case when d.any_missing_weight then null else d.weight_kg end
                                as depleted_weight_kg
from public.flocks fl
left join lateral (
    select feed_consumed_kg, avg_weight_kg, shed_type, entered_at
      from public.crop_inputs
     where flock_id = fl.id
     order by entered_at desc
     limit 1
) ci on true
left join lateral (
    select sum(birds)::int                      as birds,
           sum(coalesce(weight_kg, 0))          as weight_kg,
           bool_or(weight_kg is null)           as any_missing_weight
      from public.depletions
     where flock_id = fl.id
) d on true
where fl.active;

grant select on public.crop_gc_inputs to authenticated;
