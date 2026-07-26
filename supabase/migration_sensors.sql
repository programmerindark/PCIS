-- PCIS migration — Ecowitt sensor configuration
-- =====================================================================
-- Run in the Supabase SQL editor (after schema.sql and
-- migration_mortality.sql). Stores the farm's Ecowitt credentials so the
-- dashboard can read MEASURED house conditions instead of typed ones.
--
-- Security: these columns live on `farms`, which is already protected by
-- the owner-scoped RLS policy, so a grower can only ever read/write
-- their own keys. They are Ecowitt account keys (read-only weather
-- data), not payment or identity credentials.
-- =====================================================================

alter table public.farms
    add column if not exists ecowitt_application_key text,
    add column if not exists ecowitt_api_key         text,
    add column if not exists ecowitt_mac             text,
    -- Ecowitt names blocks after the SENSOR TYPE, not placement: a
    -- WittBoy/WS90 array reports under "outdoor" even when mounted
    -- inside the house. This records which block is the house reading.
    add column if not exists ecowitt_indoor_block    text default 'outdoor',
    add column if not exists ecowitt_gateway_ip      text;

-- Readings already exist (see schema.sql). Widen the source check so
-- sensor-sourced rows are clearly labelled.
comment on column public.readings.source is
    'manual | weather | sensor  — where the reading came from';
