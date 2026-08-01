// Supabase data helpers. All queries run as the logged-in user, so
// Row Level Security automatically limits results to their own farm.

import { supabase } from "./supabaseClient";
import type { Farm, House, Flock, Insulation } from "./types";

export async function getMyFarm(): Promise<Farm | null> {
  const { data, error } = await supabase
    .from("farms")
    .select("*")
    .order("created_at", { ascending: true })
    .limit(1)
    .maybeSingle();
  if (error) throw error;
  return data as Farm | null;
}

export async function createFarm(name: string, location: string): Promise<Farm> {
  const { data: userData } = await supabase.auth.getUser();
  const uid = userData.user?.id;
  if (!uid) throw new Error("Not signed in.");
  const { data, error } = await supabase
    .from("farms")
    .insert({ owner: uid, name, location: location || null })
    .select()
    .single();
  if (error) throw error;
  return data as Farm;
}

export async function getHouses(farmId: string): Promise<House[]> {
  const { data, error } = await supabase
    .from("houses")
    .select("*")
    .eq("farm_id", farmId)
    .order("created_at", { ascending: true });
  if (error) throw error;
  return (data ?? []) as House[];
}

export type NewHouse = {
  name: string;
  length_m: number;
  width_m: number;
  height_m: number;
  insulation: Insulation;
  fan_index: number;
  installed_fans: number;
  static_pressure_pa: number;
  has_cooling_pads: boolean;
  heater_kw: number;
};

export async function createHouse(farmId: string, h: NewHouse): Promise<House> {
  const { data, error } = await supabase
    .from("houses")
    .insert({ farm_id: farmId, ...h })
    .select()
    .single();
  if (error) throw error;
  return data as House;
}

export async function updateHouse(houseId: string, h: NewHouse): Promise<House> {
  const { data, error } = await supabase
    .from("houses")
    .update(h)
    .eq("id", houseId)
    .select()
    .single();
  if (error) throw error;
  return data as House;
}

export async function deleteHouse(houseId: string): Promise<void> {
  const { error } = await supabase.from("houses").delete().eq("id", houseId);
  if (error) throw error;
}

export async function getActiveFlock(houseId: string): Promise<Flock | null> {
  const { data, error } = await supabase
    .from("flocks")
    .select("*")
    .eq("house_id", houseId)
    .eq("active", true)
    .order("placement_date", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw error;
  return data as Flock | null;
}

export type NewFlock = {
  name: string;
  placement_date: string;
  bird_count: number;
};

export async function createFlock(houseId: string, f: NewFlock): Promise<Flock> {
  const { data, error } = await supabase
    .from("flocks")
    .insert({ house_id: houseId, ...f, strain: "Ross 308", active: true })
    .select()
    .single();
  if (error) throw error;
  return data as Flock;
}

export async function updateFlock(
  flockId: string,
  fields: { placement_date?: string; bird_count?: number }
): Promise<Flock> {
  const { data, error } = await supabase
    .from("flocks")
    .update(fields)
    .eq("id", flockId)
    .select()
    .single();
  if (error) throw error;
  return data as Flock;
}

/** Retire the current flock (mark inactive) so a new one can be placed. */
export async function endFlock(flockId: string): Promise<void> {
  const { error } = await supabase.from("flocks").update({ active: false }).eq("id", flockId);
  if (error) throw error;
}

export type MortalitySummary = {
  cumulative_dead: number;
  today_dead: number;
  /** Birds removed ALIVE (lifting / thinning). Never mortality. */
  cumulative_depleted: number;
};

export async function getMortalitySummary(flockId: string): Promise<MortalitySummary> {
  const { data, error } = await supabase
    .from("mortality")
    .select("recorded_on, dead")
    .eq("flock_id", flockId);
  if (error) throw error;
  const today = new Date().toISOString().slice(0, 10);
  let cumulative_dead = 0;
  let today_dead = 0;
  for (const r of (data ?? []) as { recorded_on: string; dead: number }[]) {
    cumulative_dead += r.dead;
    if (r.recorded_on === today) today_dead += r.dead;
  }
  const { data: dep, error: depErr } = await supabase
    .from("depletions")
    .select("birds")
    .eq("flock_id", flockId);
  // A missing depletions table (migration not yet run) must not break the
  // dashboard — treat it as "nothing lifted yet" rather than failing hard.
  const cumulative_depleted = depErr
    ? 0
    : ((dep ?? []) as { birds: number }[]).reduce((a, r) => a + r.birds, 0);

  return { cumulative_dead, today_dead, cumulative_depleted };
}

/** Record birds caught and sent to slaughter — a lift / thin.
 *
 * Deliberately a separate call from logMortality(). These birds leave the
 * house, so ventilation must size for the smaller flock, but they are
 * alive and must never reach the mortality figure: a thin is 20-40% of
 * the flock against an EU ceiling of ~3%, so mixing them up reports a
 * catastrophic welfare breach on a routine harvest day.
 */
export async function logDepletion(
  flockId: string,
  birds: number,
  note?: string
): Promise<void> {
  if (birds <= 0) return;
  const { error } = await supabase
    .from("depletions")
    .insert({ flock_id: flockId, birds: Math.round(birds), note: note ?? null });
  if (error) throw error;
}

export async function logMortality(flockId: string, dead: number, note?: string): Promise<void> {
  const { error } = await supabase.from("mortality").insert({ flock_id: flockId, dead, note });
  if (error) throw error;
}

/** Set the CURRENT live bird count directly.
 *
 * Farmers often know how many birds are alive right now but not the
 * running total of losses (e.g. taking over a flock mid-cycle). This
 * reconciles by writing one adjustment row so that
 * placed - depleted - sum(mortality) == the live count entered.
 *
 * IMPORTANT: any birds already recorded as lifted are held aside, so
 * lowering the live count after a harvest does not re-book those birds as
 * deaths. Use logDepletion() for a lift; this is only for correcting the
 * count of birds that are actually still in the house. */
export async function setLiveCount(
  flockId: string,
  placed: number,
  liveNow: number
): Promise<void> {
  const { cumulative_dead, cumulative_depleted } = await getMortalitySummary(flockId);
  // Birds that have left alive are not available to be counted as dead.
  const inHouseCapacity = Math.max(0, placed - cumulative_depleted);
  const live = Math.max(0, Math.min(inHouseCapacity, Math.round(liveNow)));
  const targetDead = inHouseCapacity - live;
  const delta = targetDead - cumulative_dead;
  if (delta === 0) return;
  if (delta > 0) {
    await logMortality(flockId, delta, "adjustment: live count set by operator");
  } else {
    // Live count is HIGHER than our records imply -> previous losses were
    // over-recorded. Store a negative-offset row is not allowed (dead >= 0),
    // so clear the log and write the reconciled total instead.
    const { error } = await supabase.from("mortality").delete().eq("flock_id", flockId);
    if (error) throw error;
    if (targetDead > 0) {
      await logMortality(flockId, targetDead, "adjustment: live count set by operator");
    }
  }
}

/** Bird age in days from the placement date, clamped to the engine's
 *  published Ross-308 range [0, 56]. */
export function birdAgeDays(placementDate: string): number {
  const placed = new Date(placementDate + "T00:00:00");
  const now = new Date();
  const days = Math.floor((now.getTime() - placed.getTime()) / 86_400_000);
  return Math.max(0, Math.min(56, days));
}

export async function updateFarmSensor(
  farmId: string,
  fields: {
    ecowitt_application_key?: string | null;
    ecowitt_api_key?: string | null;
    ecowitt_mac?: string | null;
    ecowitt_indoor_block?: string | null;
  }
): Promise<void> {
  const { error } = await supabase.from("farms").update(fields).eq("id", farmId);
  if (error) throw error;
}

export async function updateFarmLocation(
  farmId: string,
  latitude: number,
  longitude: number
): Promise<void> {
  const { error } = await supabase
    .from("farms")
    .update({ latitude, longitude })
    .eq("id", farmId);
  if (error) throw error;
}

/** Log an engine result to history (best-effort; never blocks the UI). */
export async function saveRecommendation(
  houseId: string,
  flockId: string | null,
  r: any
): Promise<void> {
  try {
    await supabase.from("recommendations").insert({
      house_id: houseId,
      flock_id: flockId,
      fans_on: r.fans_on,
      pads_on: r.pads_on,
      heating_needed: r.heating_needed,
      governing_constraint: r.governing_constraint,
      comfort_index: r.bird_status?.comfort_score ?? null,
      heat_stress_risk: r.bird_status?.heat_stress_risk ?? null,
      air_speed_mps: r.air_speed_mps,
      target_airspeed_mps: r.target_airspeed_mps,
      vpd_kpa: r.vpd_kpa,
      confidence: r.confidence_score,
      payload: r,
    });
  } catch {
    // History logging is non-critical; ignore failures.
  }
}

export type SensorHistoryPoint = {
  observed_at: string;
  indoor_t_c: number | null;
  indoor_rh_pct: number | null;
  outdoor_t_c: number | null;
  outdoor_rh_pct: number | null;
  pressure_hpa: number | null;
  measured_air_speed_mps: number | null;
};

/** Logged sensor readings for a house, most recent last.
 *
 * These come only from /api/cron/log-sensor (source = 'sensor'), so this
 * is real measured history, distinct from the one-off "Test read" the
 * sensor card also supports. Empty until the cron has run at least once
 * with valid Ecowitt keys on the farm — that's expected on a fresh farm,
 * not an error.
 */
export async function getSensorHistory(
  houseId: string,
  hours = 48
): Promise<SensorHistoryPoint[]> {
  const since = new Date(Date.now() - hours * 3_600_000).toISOString();
  const { data, error } = await supabase
    .from("readings")
    .select("observed_at, indoor_t_c, indoor_rh_pct, outdoor_t_c, outdoor_rh_pct, pressure_hpa, measured_air_speed_mps")
    .eq("house_id", houseId)
    .eq("source", "sensor")
    .gte("observed_at", since)
    .order("observed_at", { ascending: true });
  if (error) throw error;
  return (data ?? []) as SensorHistoryPoint[];
}

// ---------------------------------------------------------------------------
// Growing-charge inputs
// ---------------------------------------------------------------------------
//
// Everything else the dashboard shows is measured by a sensor once a
// minute. These two numbers are typed in by a person, so `entered_at`
// travels with them everywhere and the UI is expected to show it. A
// fortnight-old weight rendered next to a live temperature looks exactly
// as current as the temperature, and prices the crop wrongly without
// looking wrong.

export type CropGCInputs = {
  flock_id: string;
  chicks_housed: number;
  feed_consumed_kg: number | null;
  avg_weight_kg: number | null;
  shed_type: string | null;
  entered_at: string | null;
  depleted_birds: number;
  /** NULL when ANY lift is missing its weight — a partial sum understates
   *  delivered kilograms, which is the same error as omitting them but
   *  harder to spot. The engine refuses to price the crop in that case. */
  depleted_weight_kg: number | null;
};

export async function getCropGCInputs(flockId: string): Promise<CropGCInputs | null> {
  const { data, error } = await supabase
    .from("crop_gc_inputs")
    .select("*")
    .eq("flock_id", flockId)
    .maybeSingle();
  // Migration not yet applied — the GC card simply does not render.
  if (error) return null;
  return (data as CropGCInputs) ?? null;
}

export async function saveCropInputs(
  flockId: string,
  feedConsumedKg: number,
  avgWeightKg: number,
  shedType: string,
  note?: string
): Promise<void> {
  const { error } = await supabase.from("crop_inputs").insert({
    flock_id: flockId,
    feed_consumed_kg: feedConsumedKg,
    avg_weight_kg: avgWeightKg,
    shed_type: shedType,
    note: note ?? null,
  });
  if (error) throw error;
}

/** Record the weight of a lift that was logged without one.
 *
 * Kept separate from logDepletion() because the bird count is known at the
 * moment of catching while the weight comes back later on the slip. */
export async function setDepletionWeight(
  depletionId: number,
  weightKg: number
): Promise<void> {
  const { error } = await supabase
    .from("depletions")
    .update({ weight_kg: weightKg })
    .eq("id", depletionId);
  if (error) throw error;
}

export type DepletionRow = {
  id: number;
  removed_on: string;
  birds: number;
  weight_kg: number | null;
  note: string | null;
};

export async function getDepletions(flockId: string): Promise<DepletionRow[]> {
  const { data, error } = await supabase
    .from("depletions")
    .select("id, removed_on, birds, weight_kg, note")
    .eq("flock_id", flockId)
    .order("removed_on", { ascending: false });
  if (error) return [];
  return (data ?? []) as DepletionRow[];
}
