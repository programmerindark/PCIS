// Model validation: scoring what PCIS predicted against what the sensor
// measured.
//
// Every cron tick writes two rows a few seconds apart — a `readings` row
// (what the house was doing) and a `recommendations` row (what PCIS
// believed about it). Pairing them on the timeline turns the engine's
// claims into something checkable on THIS house, rather than something
// resting purely on cited literature and my engineering judgment.
//
// A note on evidential strength, because the two comparisons here are NOT
// equally meaningful and presenting them as if they were would be
// misleading:
//
//   * AIR SPEED is an independent check. The computed figure comes from
//     the fan curve and the house cross-section via continuity; the
//     anemometer knows nothing about either. Agreement is real evidence.
//
//   * HUMIDITY is a partially circular check. The measured indoor RH is
//     fed INTO the engine, where it influences the ventilation rate that
//     the moisture balance then uses to predict indoor RH. The prediction
//     can still diverge from the measurement (and the size of that gap is
//     informative), but it is not independent, and a small error here is
//     weaker evidence than a small error in air speed.
//
// Both are reported, labelled for what they are.

import { supabase } from "./supabaseClient";

/** Rows written within this many milliseconds are treated as the same
 *  observation. The cron writes both within a second or two; 5 minutes is
 *  loose enough to survive a slow engine call without ever pairing two
 *  different 10-minute ticks. */
const PAIR_TOLERANCE_MS = 5 * 60 * 1000;

export type ValidationPair = {
  t: string;                       // ISO timestamp of the reading
  measuredRh: number | null;
  predictedRh: number | null;
  measuredSpeed: number | null;
  computedSpeed: number | null;
};

export type ErrorStats = {
  n: number;
  /** Mean signed error (predicted - measured). Sign matters: it separates
   *  a model that is noisy from one that is consistently biased. */
  bias: number;
  /** Mean absolute error — typical size of a miss, regardless of sign. */
  mae: number;
  /** Worst single miss, so a good average can't hide a bad excursion. */
  worst: number;
};

export function errorStats(
  pairs: ValidationPair[],
  pick: (p: ValidationPair) => [number | null, number | null]
): ErrorStats | null {
  const errs: number[] = [];
  for (const p of pairs) {
    const [predicted, measured] = pick(p);
    if (predicted == null || measured == null) continue;
    errs.push(predicted - measured);
  }
  if (errs.length === 0) return null;
  const bias = errs.reduce((a, b) => a + b, 0) / errs.length;
  const mae = errs.reduce((a, b) => a + Math.abs(b), 0) / errs.length;
  const worst = errs.reduce((a, b) => (Math.abs(b) > Math.abs(a) ? b : a), 0);
  return { n: errs.length, bias, mae, worst };
}

type ReadingRow = {
  observed_at: string;
  indoor_rh_pct: number | null;
  measured_air_speed_mps: number | null;
};

type RecommendationRow = {
  created_at: string;
  air_speed_mps: number | null;
  payload: any;
};

/** Fetch logged readings and recommendations and pair them by time.
 *
 * Returns oldest-first. Pairs with neither comparison available are
 * dropped, so an empty result means "nothing to score yet" rather than
 * "the model is perfect".
 */
export async function getValidationHistory(
  houseId: string,
  hours = 168
): Promise<ValidationPair[]> {
  const since = new Date(Date.now() - hours * 3_600_000).toISOString();

  const [readingsRes, recsRes] = await Promise.all([
    supabase
      .from("readings")
      .select("observed_at, indoor_rh_pct, measured_air_speed_mps")
      .eq("house_id", houseId)
      .eq("source", "sensor")
      .gte("observed_at", since)
      .order("observed_at", { ascending: true }),
    supabase
      .from("recommendations")
      .select("created_at, air_speed_mps, payload")
      .eq("house_id", houseId)
      .gte("created_at", since)
      .order("created_at", { ascending: true }),
  ]);

  if (readingsRes.error) throw readingsRes.error;
  if (recsRes.error) throw recsRes.error;

  const readings = (readingsRes.data ?? []) as ReadingRow[];
  const recs = (recsRes.data ?? []) as RecommendationRow[];
  if (recs.length === 0) return [];

  // Two sorted lists, so a single forward scan finds each reading's
  // nearest recommendation without an O(n*m) comparison of every pair.
  const pairs: ValidationPair[] = [];
  let j = 0;
  for (const r of readings) {
    const rt = new Date(r.observed_at).getTime();
    while (
      j + 1 < recs.length &&
      Math.abs(new Date(recs[j + 1].created_at).getTime() - rt) <=
        Math.abs(new Date(recs[j].created_at).getTime() - rt)
    ) {
      j++;
    }
    const rec = recs[j];
    if (Math.abs(new Date(rec.created_at).getTime() - rt) > PAIR_TOLERANCE_MS) continue;

    const predictedRh = rec.payload?.predicted_humidity?.indoor_rh_pct ?? null;
    // Prefer the measurement echoed back inside the engine payload, since
    // that is provably the value the engine actually saw; fall back to the
    // readings row for older recommendations logged before that was wired.
    const measuredSpeed =
      rec.payload?.measured_air_speed_mps ?? r.measured_air_speed_mps ?? null;

    if (
      (predictedRh == null || r.indoor_rh_pct == null) &&
      (rec.air_speed_mps == null || measuredSpeed == null)
    ) {
      continue;
    }

    pairs.push({
      t: r.observed_at,
      measuredRh: r.indoor_rh_pct,
      predictedRh,
      measuredSpeed,
      computedSpeed: rec.air_speed_mps,
    });
  }
  return pairs;
}
