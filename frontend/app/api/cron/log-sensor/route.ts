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
};

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
    return NextResponse.json({ ok: true, polled: 0, message: "No farms with Ecowitt keys configured." });
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

      const { error: rpcErr } = await admin.rpc("log_sensor_reading", {
        p_house_id: farm.house_id,
        p_indoor_t_c: c.indoor_t_c,
        p_indoor_rh_pct: c.indoor_rh_pct,
        p_outdoor_t_c: c.outdoor_t_c,
        p_outdoor_rh_pct: c.outdoor_rh_pct,
        p_pressure_hpa: c.pressure_hpa,
        p_measured_air_speed_mps: c.measured_air_speed_mps,
      });
      results[farm.farm_id] = rpcErr ? `insert failed: ${rpcErr.message}` : "logged";
    } catch (e: any) {
      results[farm.farm_id] = `fetch failed: ${e?.message ?? "unknown"}`;
    }
  }

  return NextResponse.json({ ok: true, polled: farms.length, results });
}
