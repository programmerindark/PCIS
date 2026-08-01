/**
 * Continuous sensor logging.
 *
 * Called on a schedule (see vercel.json `crons`) rather than only when an
 * operator happens to have the dashboard open. Every registered Ecowitt
 * gateway gets polled and one row is appended to `readings` per farm, so
 * the felt-temp/comfort/moisture picture PCIS shows can eventually be
 * checked against what the house actually did over hours and days, not
 * just the single live snapshot the dashboard's "Test read" button gives.
 *
 * Runs server-side ONLY. It uses the Supabase service_role key (server
 * env var `SUPABASE_SERVICE_ROLE_KEY`, never `NEXT_PUBLIC_*`) because the
 * cron trigger carries no user session, and it calls two narrow
 * SECURITY DEFINER database functions (see
 * supabase/migration_sensor_log.sql) rather than querying `farms`
 * directly, so the credential surface this route can reach is limited to
 * exactly "list Ecowitt keys" and "insert one reading" — not arbitrary
 * table access.
 *
 * Security note: this route checks a shared secret
 * (`CRON_SECRET`) on every call so it cannot be triggered by a stranger
 * who finds the URL and used to poll every farm's Ecowitt account on
 * demand. Vercel Cron sends this automatically when `CRON_SECRET` is
 * set; set the same value in the Vercel dashboard.
 */
import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

const ECOWITT_CLOUD_URL = "https://api.ecowitt.net/api/v3/device/real_time";

type FarmRow = {
  farm_id: string;
  house_id: string;
  ecowitt_application_key: string;
  ecowitt_api_key: string;
  ecowitt_mac: string;
  ecowitt_indoor_block: string | null;
  // House geometry + equipment, so the engine can be run unattended.
  length_m: number;
  width_m: number;
  height_m: number;
  insulation: string;
  fan_index: number;
  installed_fans: number;
  static_pressure_pa: number;
  has_cooling_pads: boolean;
  heater_kw: number;
  // Active flock; null between crops.
  flock_id: string | null;
  placement_date: string | null;
  bird_count: number | null;
  cumulative_dead: number;
  cumulative_depleted: number;
};

/** Whole days since placement — mirrors lib/db.ts::birdAgeDays. */
function birdAgeDays(placementDate: string): number {
  const ms = Date.now() - new Date(placementDate + "T00:00:00").getTime();
  return Math.max(0, Math.floor(ms / 86_400_000));
}

function num(v: unknown): number | null {
  if (v == null) return null;
  if (typeof v === "object" && v !== null && "value" in (v as any)) v = (v as any).value;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** Mirrors backend/app/ecowitt.py::select_house_conditions, kept in sync
 * by hand since this route intentionally does not call the Python
 * engine (it only logs raw measurements — no engineering judgment is
 * applied here, so there is nothing for the cited engine to own). */
function pickConditions(data: any, indoorBlock: string) {
  const blocks: Record<string, any> = {};
  for (const name of ["indoor", "outdoor"]) if (data?.[name]) blocks[name] = data[name];
  const others = Object.keys(blocks).filter((b) => b !== indoorBlock);
  const outdoorBlock = others.length === 1 ? others[0] : null;

  const inside = blocks[indoorBlock] ?? {};
  const outside = outdoorBlock ? blocks[outdoorBlock] ?? {} : {};
  const press = data?.pressure ?? {};

  return {
    indoor_t_c: num(inside.temperature),
    indoor_rh_pct: num(inside.humidity),
    outdoor_t_c: num(outside.temperature),
    outdoor_rh_pct: num(outside.humidity),
    pressure_hpa: num(press.absolute) ?? num(press.relative),
    measured_air_speed_mps: num(data?.wind?.wind_speed) != null
      ? Number(((num(data?.wind?.wind_speed) as number) * 0.44704).toFixed(2))
      : null,
  };
}

export async function GET(req: Request) {
  const auth = req.headers.get("authorization");
  if (process.env.CRON_SECRET && auth !== `Bearer ${process.env.CRON_SECRET}`) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !serviceKey) {
    return NextResponse.json({ error: "Supabase server env not configured" }, { status: 500 });
  }
  const admin = createClient(url, serviceKey);

  const { data: farms, error: farmsErr } = await admin
    .from("farms_with_ecowitt_keys")
    .select("*") as { data: FarmRow[] | null; error: any };

  if (farmsErr) {
    return NextResponse.json({ error: farmsErr.message }, { status: 500 });
  }
  if (!farms || farms.length === 0) {
    return NextResponse.json(
      { ok: false, polled: 0, message: "No farms with Ecowitt keys configured." },
      { status: 502 },
    );
  }

  const results: Record<string, string> = {};

  for (const farm of farms) {
    try {
      const params = new URLSearchParams({
        application_key: farm.ecowitt_application_key,
        api_key: farm.ecowitt_api_key,
        mac: farm.ecowitt_mac,
        call_back: "all",
        temp_unitid: "1",
        pressure_unitid: "3",
      });
      const res = await fetch(`${ECOWITT_CLOUD_URL}?${params.toString()}`, {
        signal: AbortSignal.timeout(12_000),
      });
      const payload = await res.json();
      if (payload.code !== 0 && payload.code !== "0") {
        results[farm.farm_id] = `ecowitt error: ${payload.msg ?? "rejected"}`;
        continue;
      }
      const c = pickConditions(payload.data, farm.ecowitt_indoor_block || "outdoor");
      if (c.indoor_t_c == null) {
        results[farm.farm_id] = "no indoor reading in response";
        continue;
      }

      const { data: logMode, error: rpcErr } = await admin.rpc("log_sensor_reading", {
        p_house_id: farm.house_id,
        p_indoor_t_c: c.indoor_t_c,
        p_indoor_rh_pct: c.indoor_rh_pct,
        p_outdoor_t_c: c.outdoor_t_c,
        p_outdoor_rh_pct: c.outdoor_rh_pct,
        p_pressure_hpa: c.pressure_hpa,
        p_measured_air_speed_mps: c.measured_air_speed_mps,
      });
      if (rpcErr) {
        results[farm.farm_id] = `insert failed: ${rpcErr.message}`;
        continue;
      }
      // Another scheduler already logged this minute. Stop here rather than
      // running the engine again: a second recommendation for the same
      // reading is not extra information, and duplicate rows within one
      // minute make a stable engine look like it is oscillating.
      if (logMode === "skipped") {
        results[farm.farm_id] = "skipped (already logged this minute)";
        continue;
      }

      // ---- Run the engine on what was just measured -------------------
      // A reading on its own records what the house did. Pairing it with
      // the engine's output records what PCIS BELIEVED at that moment --
      // and only the pair can later be scored (predicted humidity vs
      // measured humidity, computed air speed vs measured air speed).
      //
      // Skipped when the house is empty: no birds means no heat load and
      // nothing to advise, so a recommendation would be noise in the
      // dataset rather than a data point.
      const canAdvise =
        farm.flock_id && farm.placement_date && farm.bird_count != null &&
        c.indoor_rh_pct != null && c.outdoor_t_c != null && c.outdoor_rh_pct != null;

      if (!canAdvise) {
        results[farm.farm_id] = farm.flock_id ? "logged (incomplete reading)" : "logged (no active flock)";
        continue;
      }

      const apiBase = process.env.NEXT_PUBLIC_PCIS_API_URL;
      if (!apiBase) {
        results[farm.farm_id] = "logged (engine URL not configured)";
        continue;
      }

      try {
        // Lifted birds have physically left the house, so they take their heat
        // and moisture with them. Sizing ventilation for birds that are no
        // longer there would over-ventilate a half-empty house — which in
        // cold weather chills the ones that remain.
        const liveBirds = Math.max(
          1,
          (farm.bird_count as number) - (farm.cumulative_dead ?? 0) - (farm.cumulative_depleted ?? 0)
        );
        const recRes = await fetch(`${apiBase.replace(/\/$/, "")}/recommend`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: AbortSignal.timeout(30_000),
          body: JSON.stringify({
            length_m: farm.length_m,
            width_m: farm.width_m,
            height_m: farm.height_m,
            insulation: farm.insulation,
            fan_index: farm.fan_index,
            installed_fans: farm.installed_fans,
            static_pressure_pa: farm.static_pressure_pa,
            cooling_pads: farm.has_cooling_pads,
            heater_kw: farm.heater_kw,
            bird_age_days: birdAgeDays(farm.placement_date as string),
            bird_count: liveBirds,
            // Measured, not typed. This is the whole point.
            indoor_rh_pct: c.indoor_rh_pct,
            outdoor_t_c: c.outdoor_t_c,
            outdoor_rh_pct: c.outdoor_rh_pct,
            pressure_hpa: c.pressure_hpa ?? undefined,
            measured_air_speed_mps: c.measured_air_speed_mps ?? undefined,
          }),
        });

        if (!recRes.ok) {
          results[farm.farm_id] = `logged (engine ${recRes.status})`;
          continue;
        }
        const rec = await recRes.json();

        const { data: recMode, error: recErr } = await admin.rpc("log_recommendation_thin", {
          p_house_id: farm.house_id,
          p_flock_id: farm.flock_id,
          p_fans_on: rec.fans_on ?? null,
          p_pads_on: rec.pads_on ?? null,
          p_heating_needed: rec.heating_needed ?? null,
          p_governing_constraint: rec.governing_constraint ?? null,
          p_comfort_index: rec.bird_status?.comfort_score ?? null,
          p_heat_stress_risk: rec.bird_status?.heat_stress_risk ?? null,
          p_air_speed_mps: rec.air_speed_mps ?? null,
          p_target_airspeed_mps: rec.target_airspeed_mps ?? null,
          p_vpd_kpa: rec.vpd_kpa ?? null,
          p_confidence: rec.action_confidence ?? rec.confidence_score ?? null,
          p_payload: rec,
        });
        // "steady" means the decision was identical to the previous tick,
        // so the numeric row was written but the 8 kB explanation payload
        // was not — see log_recommendation_thin in the migration.
        results[farm.farm_id] = recErr
          ? `logged (recommendation not saved: ${recErr.message})`
          : `logged + advised (${recMode ?? "ok"})`;
      } catch (e: any) {
        // The reading is already safely stored; a slow or sleeping engine
        // must not cost us the measurement.
        results[farm.farm_id] = `logged (engine unreachable: ${e?.message ?? "timeout"})`;
      }
    } catch (e: any) {
      results[farm.farm_id] = `fetch failed: ${e?.message ?? "unknown"}`;
    }
  }

  // Status must reflect whether anything was actually WRITTEN.
  //
  // This route used to return 200 unconditionally, with per-farm outcomes
  // buried in the body. An external monitor therefore saw an unbroken wall
  // of green while the Ecowitt call failed for two and a half days and not
  // one reading reached the database. A health endpoint that cannot report
  // failure is not a health endpoint.
  const outcomes = Object.values(results);
  const wrote = outcomes.filter((r) => r.startsWith("logged")).length;
  const skipped = outcomes.filter((r) => r.startsWith("skipped")).length;
  const ok = wrote > 0 || skipped > 0;

  return NextResponse.json(
    {
      ok,
      polled: farms.length,
      wrote,
      skipped,
      failed: outcomes.length - wrote - skipped,
      results,
    },
    // 502: the route itself is healthy, but every upstream attempt failed.
    { status: ok ? 200 : 502 },
  );
}
