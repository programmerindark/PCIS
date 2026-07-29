// The minute-by-minute record: what the sensor saw and what PCIS decided.
//
// At one poll a minute a day is 1,440 rows, so the design problem is not
// fetching the data but presenting it without drowning the reader. Two
// different questions need two different answers:
//
//   * "What is happening right now?" -> the raw stream, newest first.
//   * "What happened today?"         -> only the moments the decision
//                                       CHANGED. Ninety-nine rows saying
//                                       "10 fans, target airspeed" are one
//                                       fact, not ninety-nine.
//
// The second view is the one worth reading, which is why the change log is
// the default. It also lines up with how the data is stored: the full
// engine payload is kept only on change (see log_recommendation_thin), so
// the interesting rows are exactly the detailed ones.

import { supabase } from "./supabaseClient";

export type ActivityRow = {
  t: string;
  indoorT: number | null;
  indoorRh: number | null;
  outdoorT: number | null;
  measuredSpeed: number | null;
  // From the paired recommendation, when one exists for this minute.
  fansOn: number | null;
  governing: string | null;
  computedSpeed: number | null;
  comfort: number | null;
  heatRisk: string | null;
  /** True when this row's decision differs from the row before it. */
  changed: boolean;
};

const PAIR_TOLERANCE_MS = 90 * 1000;

type ReadingRow = {
  observed_at: string;
  indoor_t_c: number | null;
  indoor_rh_pct: number | null;
  outdoor_t_c: number | null;
  measured_air_speed_mps: number | null;
};

type RecRow = {
  created_at: string;
  fans_on: number | null;
  governing_constraint: string | null;
  air_speed_mps: number | null;
  comfort_index: number | null;
  heat_stress_risk: string | null;
};

/** Recent activity for a house, newest first.
 *
 * `hours` bounds the query; `cap` bounds what is returned, because a week
 * at minute resolution is 10,080 rows and no one is reading that.
 */
export async function getRecentActivity(
  houseId: string,
  hours = 6,
  cap = 720
): Promise<ActivityRow[]> {
  const since = new Date(Date.now() - hours * 3_600_000).toISOString();

  const [rRes, cRes] = await Promise.all([
    supabase
      .from("readings")
      .select("observed_at, indoor_t_c, indoor_rh_pct, outdoor_t_c, measured_air_speed_mps")
      .eq("house_id", houseId)
      .eq("source", "sensor")
      .gte("observed_at", since)
      .order("observed_at", { ascending: false })
      .limit(cap),
    supabase
      .from("recommendations")
      .select("created_at, fans_on, governing_constraint, air_speed_mps, comfort_index, heat_stress_risk")
      .eq("house_id", houseId)
      .gte("created_at", since)
      .order("created_at", { ascending: false })
      .limit(cap),
  ]);

  if (rRes.error) throw rRes.error;
  if (cRes.error) throw cRes.error;

  const readings = (rRes.data ?? []) as ReadingRow[];
  const recs = (cRes.data ?? []) as RecRow[];

  // Both lists are newest-first and roughly aligned in time, so one
  // forward scan pairs them without comparing every row to every other.
  const rows: ActivityRow[] = [];
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
    const rec =
      recs.length && Math.abs(new Date(recs[j].created_at).getTime() - rt) <= PAIR_TOLERANCE_MS
        ? recs[j]
        : null;

    rows.push({
      t: r.observed_at,
      indoorT: r.indoor_t_c,
      indoorRh: r.indoor_rh_pct,
      outdoorT: r.outdoor_t_c,
      measuredSpeed: r.measured_air_speed_mps,
      fansOn: rec?.fans_on ?? null,
      governing: rec?.governing_constraint ?? null,
      computedSpeed: rec?.air_speed_mps ?? null,
      comfort: rec?.comfort_index ?? null,
      heatRisk: rec?.heat_stress_risk ?? null,
      changed: false,
    });
  }

  // Mark the rows where the decision moved. Walk oldest -> newest so
  // "changed" means "differs from the minute before", which is the way a
  // person reads a log.
  for (let i = rows.length - 2; i >= 0; i--) {
    const cur = rows[i];
    const prev = rows[i + 1];
    cur.changed =
      cur.fansOn !== prev.fansOn ||
      cur.governing !== prev.governing ||
      cur.heatRisk !== prev.heatRisk;
  }
  return rows;
}

/** Thin a dense series down to at most `maxPoints` for charting.
 *
 * A 620px-wide chart cannot show 2,880 points; drawing them anyway costs
 * render time and produces a solid smear. Takes evenly spaced samples and
 * always keeps the newest point, so the right-hand edge of the chart is
 * the current value rather than whatever the sampling stride happened to
 * land on.
 */
export function downsample<T>(series: T[], maxPoints = 240): T[] {
  if (series.length <= maxPoints) return series;
  const stride = Math.ceil(series.length / maxPoints);
  const out: T[] = [];
  for (let i = 0; i < series.length; i += stride) out.push(series[i]);
  const last = series[series.length - 1];
  if (out[out.length - 1] !== last) out.push(last);
  return out;
}
