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

/** Bird age in days from the placement date, clamped to the engine's
 *  published Ross-308 range [0, 56]. */
export function birdAgeDays(placementDate: string): number {
  const placed = new Date(placementDate + "T00:00:00");
  const now = new Date();
  const days = Math.floor((now.getTime() - placed.getTime()) / 86_400_000);
  return Math.max(0, Math.min(56, days));
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
