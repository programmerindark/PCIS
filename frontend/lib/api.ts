// Client for the PCIS engine API (FastAPI). Base URL comes from the
// environment so it points at localhost in dev and the deployed API in
// production. The engine is the ONLY source of climate numbers.

// Trimmed and de-slashed: pasted values carry stray whitespace, and a
// trailing slash would produce "//recommend" on every call.
const BASE = (process.env.NEXT_PUBLIC_PCIS_API_URL ?? "http://127.0.0.1:8000")
  .trim()
  .replace(/\/+$/, "");

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`PCIS API ${path} failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function getCatalog() {
  const res = await fetch(`${BASE}/catalog`);
  if (!res.ok) throw new Error("Failed to load catalog");
  return res.json();
}

export async function getGrowthCurve(): Promise<{ points: { day: number; weight_kg: number }[] }> {
  const res = await fetch(`${BASE}/growth-curve`);
  if (!res.ok) throw new Error("Failed to load growth curve");
  return res.json();
}

export function recommend(input: Record<string, unknown>) {
  return post<Record<string, any>>("/recommend", input);
}

export function schedule(input: Record<string, unknown>) {
  return post<Record<string, any>>("/schedule", input);
}

export function advise(input: Record<string, unknown>) {
  return post<Record<string, any>>("/advise", input);
}

export function mortality(input: Record<string, unknown>) {
  return post<Record<string, any>>("/mortality", input);
}

export type EcowittReading = {
  ok: boolean;
  error: string | null;
  indoor_t_c: number | null;
  indoor_rh_pct: number | null;
  source_block: string | null;
  available_blocks: string[];
  blocks: Record<string, { temperature_c?: number; humidity_pct?: number }>;
  // A two-module install measures ambient as well as house conditions, so
  // the outdoor figures below come from hardware rather than a forecast.
  outdoor_t_c: number | null;
  outdoor_rh_pct: number | null;
  outdoor_source_block: string | null;
  outdoor_measured: boolean;
  // Barometric pressure: PCIS psychrometrics assume sea level unless this
  // is supplied, which understates humidity ratio and overstates how much
  // heat each cubic metre of fan air can carry.
  pressure_hpa: number | null;
  // Ecowitt's own derived values, kept as independent cross-checks and
  // never substituted for the engine's psychrometrics.
  cross_checks: {
    outdoor_dew_point_c?: number;
    indoor_dew_point_c?: number;
    wind_speed_mps?: number;
    measured_air_speed_mps?: number;
  } | null;
};

export function readEcowittCloud(input: {
  application_key: string; api_key: string; mac: string;
  indoor_block?: string; outdoor_block?: string | null;
}) {
  return post<EcowittReading>("/sensor/ecowitt/cloud", input);
}

export function readEcowittLocal(input: { gateway_ip: string; indoor_block?: string }) {
  return post<EcowittReading>("/sensor/ecowitt/local", input);
}

export type EcowittDevice = { name: string; mac: string; type?: string; last_update?: string };

export function listEcowittDevices(input: { application_key: string; api_key: string }) {
  return post<{ devices: EcowittDevice[]; message: string }>("/sensor/ecowitt/devices", input);
}

export type GCPosition = {
  /** When set, PCIS is declining to price the crop. Render THIS and not
   *  the money — the other fields are computed from incomplete inputs. */
  incomplete_reason: string | null;
  mortality_pct: number;
  birds_delivered: number;
  avg_weight_kg: number;
  total_weight_kg: number;
  fcr: number;
  cbw_kg: number;
  cfcr: number;
  cbw_penalised: boolean;
  rate_per_kg: number;
  rearing_charge: number;
  shed_type: string;
  mortality_threshold_pct: number;
  slab: {
    next_better_cfcr: number | null;
    next_better_rate: number | null;
    gain_per_kg: number | null;
    margin_to_worse_cfcr: number | null;
    next_worse_rate: number | null;
    loss_per_kg: number | null;
  };
  notes: string[];
};

/** Where the crop sits against the IB Group slab tables today.
 *
 * A position, not a forecast — see pcis/core/gc_policy.py. */
export function gcPosition(input: Record<string, unknown>) {
  return post<GCPosition>("/gc-position", input);
}
