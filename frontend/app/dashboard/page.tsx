"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { supabase } from "@/lib/supabaseClient";
import {
  getMyFarm, getHouses, getActiveFlock, createFlock, updateFlock, endFlock, birdAgeDays,
  updateFarmLocation, updateFarmSensor, saveRecommendation, getMortalitySummary, logMortality, logDepletion, setLiveCount, type MortalitySummary,
  getSensorHistory, type SensorHistoryPoint,
} from "@/lib/db";
import { getSensorAgeMinutes } from "@/lib/validation";
import { downsample } from "@/lib/activity";
import { recommend, schedule, advise, mortality, getGrowthCurve, readEcowittCloud, listEcowittDevices, type EcowittReading, type EcowittDevice } from "@/lib/api";
import { getCurrentWeather, getTodayProfile, type WxPoint } from "@/lib/weather";
import AppShell from "@/components/AppShell";
import Modal from "@/components/Modal";
import { ClimateTrend, GrowthCurve, Sparkline } from "@/components/Charts";
import LocationPicker from "@/components/LocationPicker";
import { useUnits, cToDisplay, displayToC, tempSuffix, speedToDisplay, speedSuffix } from "@/lib/units";
import type {
  Farm, House, Flock, RecommendResponse, ScheduleResponse, Alert, AdviseResponse, MortalityResponse,
} from "@/lib/types";

const House3D = dynamic(() => import("@/components/House3D"), {
  ssr: false,
  loading: () => <div style={{ height: 340, display: "grid", placeItems: "center", color: "var(--ink-muted)" }}>Loading house view…</div>,
});

const RISK_COLOR: Record<string, string> = { Low: "var(--ok)", Moderate: "var(--warn)", High: "var(--danger)" };
const SEV: Record<string, { c: string; bg: string; ico: string }> = {
  info: { c: "var(--blue)", bg: "rgba(56,189,248,0.13)", ico: "ℹ" },
  warning: { c: "var(--warn)", bg: "rgba(251,191,36,0.13)", ico: "⚠" },
  critical: { c: "var(--danger)", bg: "rgba(248,113,113,0.13)", ico: "🔥" },
};

/** Minutes of sensor silence before PCIS stops trusting the reading.
 *
 * A power cut at the farm kills the Ecowitt gateway and the router along
 * with the fans, so the cloud simply stops hearing anything. Silence is
 * therefore the signature of the emergency, and a dashboard that keeps
 * showing the last good reading is actively reassuring at the worst
 * possible moment.
 *
 * Set well above the 10-minute poll interval so ordinary jitter or one
 * missed upload does not cry wolf, but low enough to matter: with fans
 * off, a full house gains heat fast (see the power-failure note in the
 * UI), so the useful unit here is minutes.
 */
const SENSOR_STALE_MIN = 25;
const SENSOR_DEAD_MIN = 45;

const daysAgoISO = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);

function deriveAlerts(
  r: RecommendResponse, house: House, sched: ScheduleResponse | null,
  sensorAgeMin: number | null,
): Alert[] {
  const a: Alert[] = [];
  // Listed first: if the sensor has gone quiet, every other number on this
  // screen is describing a house we can no longer see.
  if (sensorAgeMin != null && sensorAgeMin >= SENSOR_DEAD_MIN) {
    a.push({
      severity: "critical",
      title: "Sensor silent — check the house NOW",
      message: `No reading for ${Math.round(sensorAgeMin)} minutes. A power cut takes the sensor and router down with the fans, so silence often means the ventilation has stopped. Everything below is from the last reading and may no longer be true.`,
    });
  } else if (sensorAgeMin != null && sensorAgeMin >= SENSOR_STALE_MIN) {
    a.push({
      severity: "warning",
      title: "Sensor reading is stale",
      message: `Last reading ${Math.round(sensorAgeMin)} minutes ago. Readings below may be out of date.`,
    });
  }
  if (r.bird_status.heat_stress_risk === "High")
    a.push({ severity: "critical", title: "High heat-stress risk", message: "Birds are in the high heat-stress band right now." });
  if (r.fans_on > house.installed_fans)
    a.push({ severity: "warning", title: "Fan shortfall", message: `Needs ${r.fans_on} fans, only ${house.installed_fans} installed.` });
  if (r.target_unreachable)
    a.push({ severity: "warning", title: "Target not reachable", message: "Ventilation alone can't hold target — add cooling." });
  if (sched && sched.shortfall_steps > 0 && r.fans_on <= house.installed_fans)
    a.push({ severity: "warning", title: "Fans short later today", message: `${sched.shortfall_steps} step(s) today exceed installed fans.` });
  if (r.heating_needed)
    a.push({ severity: "info", title: "Heating needed", message: `Supplemental heat ~${r.heat_deficit_kw} kW to hold target.` });
  return a;
}

function Ring({ pct, label }: { pct: number; label: string }) {
  const R = 30, C = 2 * Math.PI * R;
  const off = C - (Math.max(0, Math.min(100, pct)) / 100) * C;
  return (
    <svg width="76" height="76" viewBox="0 0 76 76" style={{ flex: "none" }}>
      <circle cx="38" cy="38" r={R} fill="none" stroke="var(--surface-3)" strokeWidth="7" />
      <circle cx="38" cy="38" r={R} fill="none" stroke="var(--ok)" strokeWidth="7" strokeLinecap="round"
        strokeDasharray={C} strokeDashoffset={off} transform="rotate(-90 38 38)" />
      <text x="38" y="36" textAnchor="middle" fontSize="16" fontWeight="800" fill="var(--ink)">{Math.round(pct)}%</text>
      <text x="38" y="49" textAnchor="middle" fontSize="8" fill="var(--ink-muted)">{label}</text>
    </svg>
  );
}


/** A failed sensor read, shaped like a real one.
 *
 * Kept as a helper rather than an inline literal in three places: the
 * reading type grows every time the gateway turns out to expose something
 * useful (pressure, measured outdoor, air speed), and duplicated literals
 * meant each addition broke the build in several spots at once.
 */
function sensorError(error: string): EcowittReading {
  return {
    ok: false, error,
    indoor_t_c: null, indoor_rh_pct: null,
    source_block: null, available_blocks: [], blocks: {},
    outdoor_t_c: null, outdoor_rh_pct: null,
    outdoor_source_block: null, outdoor_measured: false,
    pressure_hpa: null, cross_checks: null,
  };
}

export default function DashboardPage() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [farm, setFarm] = useState<Farm | null>(null);
  const [houses, setHouses] = useState<House[]>([]);
  const [house, setHouse] = useState<House | null>(null);
  const [flock, setFlock] = useState<Flock | null>(null);
  const [loading, setLoading] = useState(true);

  const [outT, setOutT] = useState(32);
  const [outRh, setOutRh] = useState(60);
  const [inRh, setInRh] = useState(60);
  const [wxSource, setWxSource] = useState<"sensor" | "forecast" | "manual">("manual");
  const [profile, setProfile] = useState<WxPoint[] | null>(null);

  const [result, setResult] = useState<RecommendResponse | null>(null);
  const [sched, setSched] = useState<ScheduleResponse | null>(null);
  const [advice, setAdvice] = useState<AdviseResponse | null>(null);
  const [adviceAck, setAdviceAck] = useState(false);
  const [computing, setComputing] = useState(false);
  const [error, setError] = useState("");

  const [flockCount, setFlockCount] = useState(20000);
  const [flockDate, setFlockDate] = useState(daysAgoISO(28));
  const [editingFlock, setEditingFlock] = useState(false);

  const [mort, setMort] = useState<MortalitySummary>({ cumulative_dead: 0, today_dead: 0, cumulative_depleted: 0 });
  const [mortAssess, setMortAssess] = useState<MortalityResponse | null>(null);
  const [deaths, setDeaths] = useState(0);
  const [lifted, setLifted] = useState(0);
  const [growth, setGrowth] = useState<{ day: number; weight_kg: number }[]>([]);
  const [sensorHistory, setSensorHistory] = useState<SensorHistoryPoint[]>([]);
  const [sensorAgeMin, setSensorAgeMin] = useState<number | null>(null);
  // Incremented once a minute to drive a live re-read + recompute. Without
  // it the dashboard showed whatever was true when the page loaded: a
  // screen left open on the wall would still be reporting the morning's
  // conditions at dusk, while the staleness badge — which reads the
  // background log, not the screen — cheerfully said "just now".
  const [autoTick, setAutoTick] = useState(0);
  const [showConditions, setShowConditions] = useState(false);
  const [modal, setModal] = useState<null | "climate" | "growth" | "plan" | "sensorHistory">(null);

  const [showLocation, setShowLocation] = useState(false);
  const [showSensor, setShowSensor] = useState(false);
  const [sensor, setSensor] = useState<EcowittReading | null>(null);
  const [sensorBusy, setSensorBusy] = useState(false);
  const [devices, setDevices] = useState<EcowittDevice[] | null>(null);
  const [ecoKeys, setEcoKeys] = useState({ application_key: "", api_key: "", mac: "", indoor_block: "outdoor" });
  const [liveInput, setLiveInput] = useState<number | null>(null);
  const [units] = useUnits();
  const T = (c: number) => +cToDisplay(c, units).toFixed(1);
  const ts = tempSuffix(units);

  // Lifted birds have left the house: they carry their heat, moisture and
  // CO2 out with them, so ventilation must size for who is still inside.
  const liveCount = flock
    ? Math.max(0, flock.bird_count - mort.cumulative_dead - (mort.cumulative_depleted ?? 0))
    : 0;
  const age = flock ? birdAgeDays(flock.placement_date) : 0;
  const density = house && liveCount ? liveCount / (house.length_m * house.width_m) : 0;

  const refreshWeather = useCallback(async (f: Farm) => {
    if (f.latitude == null || f.longitude == null) return;
    try {
      const wx = await getCurrentWeather(f.latitude, f.longitude);
      setOutT(wx.t_c); setOutRh(wx.rh_pct); setWxSource("forecast");
      setProfile(await getTodayProfile(f.latitude, f.longitude));
    } catch { /* keep manual */ }
  }, []);

  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (!data.session) { router.replace("/login"); return; }
      setEmail(data.session.user.email ?? null);
      const f = await getMyFarm().catch(() => null);
      if (!f) { router.replace("/setup"); return; }
      setFarm(f);
      const hs = await getHouses(f.id).catch(() => []);
      setHouses(hs);
      if (hs.length) {
        const wanted = new URLSearchParams(window.location.search).get("house");
        const chosen = hs.find((h) => h.id === wanted) ?? hs[0];
        setHouse(chosen);
        setFlock(await getActiveFlock(chosen.id).catch(() => null));
      }
      if (f.ecowitt_application_key && f.ecowitt_api_key && f.ecowitt_mac) {
        const k = {
          application_key: f.ecowitt_application_key,
          api_key: f.ecowitt_api_key,
          mac: f.ecowitt_mac,
          indoor_block: f.ecowitt_indoor_block || "outdoor",
        };
        setEcoKeys(k);
        readEcowittCloud(k).then((r) => {
          setSensor(r);
          if (r.ok && r.indoor_rh_pct != null) setInRh(r.indoor_rh_pct);
          // A two-module install measures ambient too. Measured beats
          // forecast for conditions right now, so it overrides the
          // Open-Meteo values that refreshWeather() filled in.
          if (r.ok && r.outdoor_measured) {
            if (r.outdoor_t_c != null) setOutT(r.outdoor_t_c);
            if (r.outdoor_rh_pct != null) setOutRh(r.outdoor_rh_pct);
            setWxSource("sensor");
          }
        }).catch(() => {});
      }
      await refreshWeather(f);
      setLoading(false);
    })();
  }, [router, refreshWeather]);

  useEffect(() => {
    if (flock) getMortalitySummary(flock.id).then(setMort).catch(() => setMort({ cumulative_dead: 0, today_dead: 0, cumulative_depleted: 0 }));
    else setMort({ cumulative_dead: 0, today_dead: 0, cumulative_depleted: 0 });
  }, [flock]);

  useEffect(() => { getGrowthCurve().then((r) => setGrowth(r.points)).catch(() => setGrowth([])); }, []);

  // Logged sensor history (from /api/cron/log-sensor, not the one-off
  // "Test read"). Empty on a fresh farm until the cron has run at least
  // once — that's expected, not a bug.
  useEffect(() => {
    if (!house) { setSensorHistory([]); return; }
    getSensorHistory(house.id, 48).then(setSensorHistory).catch(() => setSensorHistory([]));
    // Re-checked on a timer, not just on load: a dashboard left open on a
    // wall display must notice the sensor going quiet, which is what a
    // power cut at the farm actually looks like from here.
    const check = () => getSensorAgeMinutes(house.id).then(setSensorAgeMin).catch(() => setSensorAgeMin(null));
    check();
    const timer = setInterval(check, 60_000);
    return () => clearInterval(timer);
  }, [house]);

  const compute = useCallback(async () => {
    if (!house || !flock) return;
    setComputing(true); setError("");
    const live = Math.max(1, flock.bird_count - mort.cumulative_dead - (mort.cumulative_depleted ?? 0));
    const base = {
      length_m: house.length_m, width_m: house.width_m, height_m: house.height_m,
      insulation: house.insulation, fan_index: house.fan_index,
      installed_fans: house.installed_fans, static_pressure_pa: house.static_pressure_pa,
      cooling_pads: house.has_cooling_pads, heater_kw: house.heater_kw,
      bird_age_days: birdAgeDays(flock.placement_date), bird_count: live,
      indoor_rh_pct: inRh, outdoor_t_c: outT, outdoor_rh_pct: outRh,
      // Measured extras. Both are optional: omitted, the engine falls back
      // to sea-level pressure and skips the air-speed cross-check, which is
      // exactly the pre-sensor behaviour.
      pressure_hpa: sensor?.ok ? sensor.pressure_hpa ?? undefined : undefined,
      measured_air_speed_mps: sensor?.ok
        ? sensor.cross_checks?.measured_air_speed_mps ?? undefined
        : undefined,
    };
    try {
      const res = (await recommend(base)) as RecommendResponse;
      setResult(res);
      saveRecommendation(house.id, flock.id, res);
      setAdviceAck(false);
      advise(base).then((a) => setAdvice(a as AdviseResponse)).catch(() => setAdvice(null));
      mortality({ placed: flock.bird_count, cumulative_dead: mort.cumulative_dead, age_days: birdAgeDays(flock.placement_date), dead_today: mort.today_dead, depleted: mort.cumulative_depleted ?? 0 })
        .then((mm) => setMortAssess(mm as MortalityResponse)).catch(() => setMortAssess(null));
      if (profile?.length) setSched((await schedule({ ...base, profile, step_hours: 3 })) as ScheduleResponse);
    } catch (err: any) {
      setError(err?.message ?? "Could not reach the engine API. Is it running?");
    } finally { setComputing(false); }
  }, [house, flock, inRh, outT, outRh, profile, mort, sensor]);

  useEffect(() => { if (house && flock) compute(); /* eslint-disable-next-line */ }, [house, flock, profile, mort, autoTick]);

  // Live refresh, matching the once-a-minute poll rate.
  //
  // The background cron already logs a reading and a recommendation every
  // minute, but that is a database record — it is not what the screen
  // shows. The dashboard used to read the sensor once on mount and then
  // hold that snapshot indefinitely, so the fan count your dad reads at
  // 4pm could have been computed at 9am. Re-reading here means the number
  // on screen is the number for right now.
  useEffect(() => {
    if (!farm?.ecowitt_application_key || !ecoKeys.mac) return;
    const timer = setInterval(async () => {
      try {
        const r = await readEcowittCloud(ecoKeys);
        setSensor(r);
        if (r.ok && r.indoor_rh_pct != null) setInRh(r.indoor_rh_pct);
        if (r.ok && r.outdoor_measured) {
          if (r.outdoor_t_c != null) setOutT(r.outdoor_t_c);
          if (r.outdoor_rh_pct != null) setOutRh(r.outdoor_rh_pct);
          setWxSource("sensor");
        }
      } catch {
        // A failed read must not stop the loop — the next minute may work,
        // and the staleness badge already reports the gap.
      }
      // Advance last, so the recompute above runs against the new state.
      setAutoTick((t) => t + 1);
    }, 60_000);
    return () => clearInterval(timer);
  }, [farm, ecoKeys]);

  async function addFlock(e: React.FormEvent) {
    e.preventDefault();
    if (!house) return;
    const f = await createFlock(house.id, { name: "Flock", placement_date: flockDate, bird_count: flockCount })
      .catch((err) => { setError(err?.message ?? "Could not create flock."); return null; });
    if (f) setFlock(f);
  }
  function startEditFlock() { if (flock) { setFlockDate(flock.placement_date); setFlockCount(flock.bird_count); setEditingFlock(true); } }
  async function saveFlockEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!flock) return;
    const f = await updateFlock(flock.id, { placement_date: flockDate, bird_count: flockCount }).catch(() => null);
    if (f) {
      if (liveInput != null && liveInput !== flock.bird_count - mort.cumulative_dead) {
        await setLiveCount(f.id, flockCount, liveInput).catch(() => {});
        const s2 = await getMortalitySummary(f.id).catch(() => null);
        if (s2) setMort(s2);
      }
      setFlock(f);
      setEditingFlock(false);
    }
  }
  async function startNewFlock() {
    if (!flock || !window.confirm("End the current flock and place a new one?")) return;
    await endFlock(flock.id).catch(() => {});
    setFlock(null); setResult(null); setSched(null); setAdvice(null);
    setMort({ cumulative_dead: 0, today_dead: 0, cumulative_depleted: 0 }); setMortAssess(null);
    setFlockDate(daysAgoISO(0)); setFlockCount(20000);
  }
  async function submitDeaths(e: React.FormEvent) {
    e.preventDefault();
    if (!flock || deaths <= 0) return;
    await logMortality(flock.id, Math.round(deaths)).catch((err) => setError(err?.message ?? "Could not log."));
    setDeaths(0);
    const s = await getMortalitySummary(flock.id).catch(() => null);
    if (s) setMort(s);
  }
  async function submitLift(e: React.FormEvent) {
    e.preventDefault();
    if (!flock || lifted <= 0) return;
    // Separate table, separate meaning: these birds left alive.
    await logDepletion(flock.id, Math.round(lifted), "lift / thinning")
      .catch((err) => setError(err?.message ?? "Could not record the lift."));
    setLifted(0);
    const s = await getMortalitySummary(flock.id).catch(() => null);
    if (s) setMort(s);
  }
  async function findDevices() {
    setSensorBusy(true);
    try {
      const r = await listEcowittDevices({
        application_key: ecoKeys.application_key, api_key: ecoKeys.api_key,
      });
      setDevices(r.devices);
      if (r.devices.length === 1) setEcoKeys((k) => ({ ...k, mac: r.devices[0].mac }));
      if (r.devices.length === 0)
        setSensor(sensorError(r.message || "No devices on this account."));
    } catch (e: any) {
      setSensor(sensorError(e?.message ?? "Device lookup failed"));
    } finally { setSensorBusy(false); }
  }

  async function readSensor(save: boolean) {
    setSensorBusy(true);
    try {
      const r = await readEcowittCloud(ecoKeys);
      setSensor(r);
      if (r.ok && r.indoor_rh_pct != null) setInRh(r.indoor_rh_pct);
      if (save && farm && r.ok) {
        await updateFarmSensor(farm.id, {
          ecowitt_application_key: ecoKeys.application_key,
          ecowitt_api_key: ecoKeys.api_key,
          ecowitt_mac: ecoKeys.mac,
          ecowitt_indoor_block: ecoKeys.indoor_block,
        });
        setFarm({ ...farm, ...{
          ecowitt_application_key: ecoKeys.application_key,
          ecowitt_api_key: ecoKeys.api_key,
          ecowitt_mac: ecoKeys.mac,
          ecowitt_indoor_block: ecoKeys.indoor_block,
        } });
        setShowSensor(false);
      }
    } catch (e: any) {
      setSensor(sensorError(e?.message ?? "Sensor read failed"));
    } finally { setSensorBusy(false); }
  }

  /** Set the FARM's location (search / device / coordinates). Weather is
   *  always fetched for the farm, so it stays right when you're away. */
  async function pickLocation(la: number, lo: number) {
    if (!farm) return;
    await updateFarmLocation(farm.id, la, lo);
    const nf = { ...farm, latitude: la, longitude: lo };
    setFarm(nf);
    setShowLocation(false);
    await refreshWeather(nf);
  }

  if (loading) return <div className="auth-wrap"><div className="muted">Loading…</div></div>;

  const bs = result?.bird_status;
  const hmx = result?.house_metrics;
  const series = sched?.series ?? [];
  const ph = result?.predicted_humidity ?? null;
  const tg = result?.tunnel_geometry ?? null;
  const alerts = result && house ? deriveAlerts(result, house, sched, sensorAgeMin) : [];
  if (hmx && !hmx.density_within_limit)
    alerts.push({ severity: "warning", title: "Stocking density over limit", message: hmx.note });
  if (hmx && !hmx.co2_within_guideline)
    alerts.push({ severity: "warning", title: "CO₂ above guideline", message: `Estimated ${hmx.estimated_co2_ppm} ppm (guide ≤3000). Increase minimum ventilation.` });
  if (mortAssess && !mortAssess.within_target) alerts.push({ severity: "critical", title: "Mortality above limit", message: mortAssess.note });
  else if (mortAssess?.elevated_today) alerts.push({ severity: "warning", title: "Elevated mortality today", message: mortAssess.note });

  const overall = !result ? "—" : alerts.some((a) => a.severity === "critical") ? "Attention"
    : alerts.length ? "Watch" : "Optimal";
  const overallCls = overall === "Optimal" ? "chip" : overall === "Watch" ? "chip warn" : "chip danger";

  const selectors = (
    <>
      <div className="selector"><span className="ico">🏢</span><span style={{ fontWeight: 600 }}>{farm?.name}</span></div>
      {houses.length > 0 && (
        <div className="selector">
          <span className="ico">🏠</span>
          <select value={house?.id} onChange={async (e) => {
            const h = houses.find((x) => x.id === e.target.value) ?? null;
            setHouse(h); setResult(null); setSched(null); setAdvice(null);
            setFlock(h ? await getActiveFlock(h.id).catch(() => null) : null);
          }}>
            {houses.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
          </select>
        </div>
      )}
      {flock && <div className="selector"><span className="ico">🐤</span><span style={{ fontWeight: 600 }}>Day {age} · {liveCount.toLocaleString()} birds</span></div>}
    </>
  );

  return (
    <AppShell
      email={email}
      selectors={selectors}
      weather={{ t: outT, rh: outRh, source: wxSource, ageMin: sensorAgeMin }}
      alertCount={alerts.length}
      live={sensorAgeMin == null ? null : sensorAgeMin < SENSOR_STALE_MIN}
    >
      {houses.length === 0 && (
        <div className="placeholder">No houses yet. <Link href="/houses" style={{ color: "var(--accent)" }}>Add your first house</Link>.</div>
      )}

      {house && farm && (farm.latitude == null || showLocation) && (
        <div className="tile" style={{ marginBottom: 16, maxWidth: 620 }}>
          <div className="tile-head">
            <span className="tile-title">
              {farm.latitude == null ? "Set farm location" : "Change farm location"}
            </span>
            {farm.latitude != null && (
              <span className="muted" style={{ fontSize: 11.5 }}>
                now {farm.latitude.toFixed(2)}, {farm.longitude?.toFixed(2)}
              </span>
            )}
          </div>
          <LocationPicker
            currentLat={farm.latitude}
            currentLon={farm.longitude}
            onPick={pickLocation}
            onClose={farm.latitude != null ? () => setShowLocation(false) : undefined}
          />
        </div>
      )}

      {house && showSensor && (
        <div className="tile" style={{ marginBottom: 16, maxWidth: 620 }}>
          <div className="tile-head">
            <span className="tile-title">Ecowitt sensor</span>
            <button className="ghost-btn" onClick={() => setShowSensor(false)}>Close</button>
          </div>
          <p className="muted" style={{ fontSize: 12.5, marginTop: 0, lineHeight: 1.5 }}>
            Reads MEASURED house conditions from your gateway. Get the Application Key,
            API Key and device MAC from your ecowitt.net account (profile → API).
            A WittBoy array reports under the <b>outdoor</b> block even when mounted inside,
            so leave that selected unless your readings look wrong.
          </p>
          <label>Application key</label>
          <input value={ecoKeys.application_key} onChange={(e) => setEcoKeys({ ...ecoKeys, application_key: e.target.value })} />
          <label>API key</label>
          <input value={ecoKeys.api_key} onChange={(e) => setEcoKeys({ ...ecoKeys, api_key: e.target.value })} />
          <label>Device MAC</label>
          <div style={{ display: "flex", gap: 8 }}>
            <input value={ecoKeys.mac} onChange={(e) => setEcoKeys({ ...ecoKeys, mac: e.target.value })} placeholder="XX:XX:XX:XX:XX:XX" />
            <button className="ghost-btn" onClick={findDevices}
              disabled={sensorBusy || ecoKeys.application_key.length < 8 || ecoKeys.api_key.length < 8}>
              Find my devices
            </button>
          </div>
          {devices && devices.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
              {devices.map((d) => (
                <button key={d.mac} className="ghost-btn" style={{ textAlign: "left" }}
                  onClick={() => setEcoKeys({ ...ecoKeys, mac: d.mac })}>
                  <b>{d.name}</b> <span className="muted">{d.type ? `· ${d.type}` : ""}</span>
                  <span className="muted" style={{ float: "right", fontSize: 11 }}>{d.mac}</span>
                </button>
              ))}
            </div>
          )}
          <label>House reading comes from</label>
          <select value={ecoKeys.indoor_block} onChange={(e) => setEcoKeys({ ...ecoKeys, indoor_block: e.target.value })}
            style={{ padding: "11px 13px", borderRadius: 10, background: "rgba(118,118,128,0.24)", border: "1px solid transparent", color: "var(--ink)", width: "100%" }}>
            <option value="outdoor">outdoor block (WittBoy / WS90 array)</option>
            <option value="indoor">indoor block (gateway built-in probe)</option>
            {(sensor?.available_blocks ?? []).filter((b) => b.startsWith("temp_and_humidity")).map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
          <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
            <button className="primary" style={{ maxWidth: 150, margin: 0 }} onClick={() => readSensor(false)} disabled={sensorBusy}>
              {sensorBusy ? "Reading…" : "Test read"}
            </button>
            <button className="ghost-btn" onClick={() => readSensor(true)} disabled={sensorBusy}>Save &amp; use</button>
          </div>
          {sensor && (
            <div className="msg" style={{ color: sensor.ok ? "var(--green-bright)" : "var(--red)", fontSize: 13 }}>
              {sensor.ok
                ? `✓ ${sensor.indoor_t_c}°C · ${sensor.indoor_rh_pct}% RH from "${sensor.source_block}" (blocks seen: ${sensor.available_blocks.join(", ") || "none"})`
                : `⚠ ${sensor.error ?? "No reading"}${sensor.available_blocks.length ? ` — blocks seen: ${sensor.available_blocks.join(", ")}` : ""}`}
            </div>
          )}

          {/* Everything the gateway sends beyond temperature/RH. Shown so
              the operator can see WHICH inputs are measured rather than
              assumed — the difference matters when judging a
              recommendation, and it was previously silently discarded. */}
          {sensor?.ok && (
            <div style={{ marginTop: 10, display: "grid", gap: 6, fontSize: 12.5, opacity: 0.85 }}>
              {sensor.outdoor_measured && (
                <div>
                  <b>Outdoor measured</b> — {sensor.outdoor_t_c}°C · {sensor.outdoor_rh_pct}% RH
                  {" "}from &quot;{sensor.outdoor_source_block}&quot;. Using this instead of the forecast.
                </div>
              )}
              {sensor.pressure_hpa != null && (
                <div>
                  <b>Pressure</b> — {sensor.pressure_hpa} hPa
                  {sensor.pressure_hpa < 1000
                    ? " (above sea level; humidity and fan mass-flow corrected for it)"
                    : ""}
                </div>
              )}
              {sensor.cross_checks?.measured_air_speed_mps != null && (
                <div>
                  <b>In-house air speed</b> — {sensor.cross_checks.measured_air_speed_mps} m/s measured
                  {result?.air_speed_mps != null && (
                    <> vs {result.air_speed_mps} m/s computed
                      {result.air_speed_agreement === "agree"
                        ? " ✓ agrees"
                        : result.air_speed_agreement
                          ? ` ⚠ ${result.air_speed_divergence_pct}% apart`
                          : ""}
                    </>
                  )}
                </div>
              )}
              {sensor.cross_checks?.outdoor_dew_point_c != null && (
                <div><b>Dew point</b> — {sensor.cross_checks.outdoor_dew_point_c}°C (sensor&apos;s own figure, cross-check only)</div>
              )}
            </div>
          )}
        </div>
      )}

      {house && !flock && (
        <div className="tile" style={{ maxWidth: 460 }}>
          <h3 style={{ marginTop: 0 }}>Place a flock in {house.name}</h3>
          <form onSubmit={addFlock}>
            <label>Placement date</label>
            <input type="date" value={flockDate} onChange={(e) => setFlockDate(e.target.value)} />
            <label>Bird count</label>
            <input type="number" value={flockCount} onChange={(e) => setFlockCount(+e.target.value)} />
            <button className="primary" type="submit" style={{ maxWidth: 200 }}>Place flock</button>
          </form>
        </div>
      )}

      {house && flock && (
        <>
          {/* ============ HEADER ============ */}
          <div className="hero-head">
              <span className="hero-title">{house.name}</span>
              <span className={overallCls}>{overall}</span>
              <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                <button className="ghost-btn" onClick={() => setShowConditions((s) => !s)}>⚙ Conditions</button>
                <button className="ghost-btn" onClick={startEditFlock}>Edit flock</button>
                <button className="ghost-btn" onClick={startNewFlock}>New flock</button>
              </div>
            </div>
            <div className="meta-row">
              <span>Age: <b>{age} days</b></span>
              <span>Birds: <b>{liveCount.toLocaleString()}</b></span>
              <span>Weight: <b>{result?.body_weight_kg?.toFixed(2) ?? "—"} kg</b></span>
              <span>Target temp: <b>{result?.comfort.target_temp_c.toFixed(1) ?? "—"}°C</b></span>
              <span>Density: <b>{density ? density.toFixed(1) : "—"} birds/m²</b></span>
            </div>

            {showConditions && (
              <div className="tile" style={{ marginTop: 14 }}>
                <div className="cap">
                  Conditions ·{" "}
                  {wxSource === "sensor" ? "measured at the farm"
                    : wxSource === "forecast" ? "auto from forecast"
                    : "manual"}
                </div>
                <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "end", marginTop: 10 }}>
                  <div><label style={{ marginTop: 0 }}>Outdoor °C</label><input type="number" value={outT} onChange={(e) => { setOutT(+e.target.value); setWxSource("manual"); }} style={{ width: 110 }} /></div>
                  <div><label style={{ marginTop: 0 }}>Outdoor RH %</label><input type="number" value={outRh} onChange={(e) => { setOutRh(+e.target.value); setWxSource("manual"); }} style={{ width: 110 }} /></div>
                  <div><label style={{ marginTop: 0 }}>Indoor RH % (measured)</label><input type="number" value={inRh} onChange={(e) => setInRh(+e.target.value)} style={{ width: 110 }} /></div>
                  <button className="primary" style={{ maxWidth: 130, margin: 0 }} onClick={compute} disabled={computing}>{computing ? "…" : "Update"}</button>
                  {farm?.latitude != null && <button className="ghost-btn" onClick={() => farm && refreshWeather(farm)}>↻ Weather</button>}
                </div>
              </div>
            )}

            {editingFlock && (
              <div className="tile" style={{ marginTop: 14, maxWidth: 460 }}>
                <div className="cap">Edit flock</div>
                <form onSubmit={saveFlockEdit}>
                  <label>Placement date</label>
                  <input type="date" value={flockDate} onChange={(e) => setFlockDate(e.target.value)} />
                  <p className="muted" style={{ fontSize: 12 }}>Age today would be day {birdAgeDays(flockDate)}.</p>
                  <label>Birds placed (at day 0)</label>
                  <input type="number" value={flockCount} onChange={(e) => setFlockCount(+e.target.value)} />
                  <label>Birds alive now</label>
                  <input type="number" value={liveInput ?? ""} onChange={(e) => setLiveInput(+e.target.value)} />
                  <p className="muted" style={{ fontSize: 11.5, lineHeight: 1.5, marginBottom: 0 }}>
                    Enter today's count — PCIS derives cumulative mortality
                    ({Math.max(0, flockCount - (liveInput ?? flockCount)).toLocaleString()} birds ·{" "}
                    {flockCount > 0
                      ? (100 * Math.max(0, flockCount - (liveInput ?? flockCount)) / flockCount).toFixed(1)
                      : "0"}%)
                    and uses the live count for all ventilation maths.
                  </p>
                  <div style={{ display: "flex", gap: 10 }}>
                    <button className="primary" type="submit" style={{ maxWidth: 140, margin: "14px 0 0" }}>Save</button>
                    <button type="button" className="ghost-btn" style={{ marginTop: 14 }} onClick={() => setEditingFlock(false)}>Cancel</button>
                  </div>
                </form>
              </div>
            )}

            {error && <div className="msg error" style={{ marginTop: 12 }}>{error}</div>}

          <div className="dash-grid" style={{ marginTop: 16 }}>
            {/* ============ LEFT COLUMN ============ */}
            <div>
            {/* metric cards */}
            <div className="metrics">
              <Metric icon="💚" label="Bird Comfort" color="var(--green)"
                value={result?.felt_comfort_index != null ? `${result.felt_comfort_index}%` : (bs ? `${bs.comfort_score}%` : "—")}
                sub={result?.felt_comfort_index != null
                  ? `as felt · ${bs?.comfort_score ?? "—"}% dry-bulb`
                  : (bs?.comfort_label ?? "")}
                pct={result?.felt_comfort_index ?? bs?.comfort_score ?? 0} />
              <Metric icon="🌡" label="Feel Temperature" color="var(--blue)"
                value={result?.effective_temp_c != null ? `${result.effective_temp_c.toFixed(1)}°` : "—"}
                sub={result && result.effective_temp_c != null && result.achievable_indoor_t_c != null
                  ? `house ${result.achievable_indoor_t_c.toFixed(1)}° · target ${result.comfort.target_temp_c.toFixed(1)}°`
                  : `Target ${result?.comfort.target_temp_c.toFixed(1) ?? "—"}°C`}
                pct={result?.effective_temp_c != null ? Math.min(100, (result.effective_temp_c / 40) * 100) : 0}
                spark={series.map((s) => s.effective_temp_c)} />
              <Metric icon="🔥" label="Heat Stress" color={RISK_COLOR[bs?.heat_stress_risk ?? "Low"]}
                value={bs?.heat_stress_risk ?? "—"} sub={`Panting ${bs?.panting_index ?? "—"}`}
                pct={bs?.heat_stress_risk === "High" ? 100 : bs?.heat_stress_risk === "Moderate" ? 60 : 25} />
              <Metric icon="🌀" label="Fans Running" color={result && result.fans_on > house.installed_fans ? "var(--red)" : "var(--teal)"}
                value={result ? `${result.fans_on}/${house.installed_fans}` : "—"}
                sub={`${result?.pads_on ? "Pads ON" : "Pads off"}${result?.heating_needed ? " · Heat ON" : ""}`}
                pct={Math.min(100, ((result?.fans_on ?? 0) / Math.max(1, house.installed_fans)) * 100)}
                spark={series.map((s) => s.fans_on)} />
              <Metric icon="📉" label="Mortality" color={mortAssess && !mortAssess.within_target ? "var(--red)" : "var(--orange)"}
                value={mortAssess ? `${mortAssess.cumulative_pct}%` : "—"}
                sub={`Limit ${mortAssess?.acceptable_pct ?? "—"}% · ${mort.cumulative_dead.toLocaleString()} birds`}
                pct={Math.min(100, ((mortAssess?.cumulative_pct ?? 0) / Math.max(0.1, mortAssess?.acceptable_pct ?? 1)) * 100)} />
            </div>

          {/* ============ 3D — centre stage ============ */}
          <div className="hero3d">
            <div className="hero3d-head">
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span className="live-dot" />
                <span style={{ fontWeight: 600, fontSize: 16, letterSpacing: "-0.3px" }}>Live House Simulation</span>
              </div>
              <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 12.5 }}>
                <span className="muted">Fans <b style={{ color: "var(--teal)" }}>{result?.fans_on ?? 0}/{house.installed_fans}</b></span>
                <span className="muted">Pads <b style={{ color: result?.pads_on ? "var(--orange)" : "var(--ink-dim)" }}>{result?.pads_on ? "ON" : "off"}</b></span>
                <span className="muted">Airflow <b style={{ color: "var(--blue)" }}>{result?.air_speed_mps?.toFixed(2) ?? "—"} m/s</b></span>
                <span className="muted">{result?.governing_constraint?.replace("_", " ")} governing</span>
              </div>
            </div>
            <House3D
              fansOn={result?.fans_on ?? 0}
              installedFans={house.installed_fans}
              padsOn={!!result?.pads_on}
              airSpeed={result?.air_speed_mps ?? null}
              risk={bs?.heat_stress_risk ?? "Low"}
              feelTempC={result?.effective_temp_c ?? null}
              targetTempC={result?.comfort.target_temp_c ?? null}
            />
          </div>

            {/* stat strip */}
            <div className="stats">
              <div className="stat">
                <div className="k">Target Temp</div>
                <div className="v">{result?.comfort.target_temp_c.toFixed(1) ?? "—"}<span className="u"> °C</span></div>
                <Sparkline values={series.map((s) => s.target_t_c)} color="var(--orange)" />
              </div>
              <div className="stat">
                <div className="k">Outdoor RH</div>
                <div className="v">{outRh}<span className="u"> %</span></div>
                <Sparkline values={series.map((s) => s.outdoor_rh_pct)} color="var(--teal)" />
              </div>
              <div className="stat">
                <div className="k">Indoor RH</div>
                <div className="v" style={{ color: ph && Math.abs(ph.indoor_rh_pct - inRh) > 10 ? "var(--warn)" : undefined }}>
                  {inRh}<span className="u"> % meas.</span>
                </div>
                <div className="u" style={{ fontSize: 10.5 }}>predicted {ph ? `${ph.indoor_rh_pct}%` : "—"}</div>
              </div>
              <div className="stat">
                <div className="k">Air Speed</div>
                <div className="v">{result?.air_speed_mps?.toFixed(2) ?? "—"}<span className="u"> m/s</span></div>
                <Sparkline values={series.map((s) => s.air_speed_mps)} color="var(--blue)" />
              </div>
              <div className="stat">
                <div className="k">Fans</div>
                <div className="v">{result?.fans_on ?? "—"}<span className="u"> running</span></div>
                <Sparkline values={series.map((s) => s.fans_on)} color="var(--green-bright)" />
              </div>
              <div className="stat">
                <div className="k">VPD</div>
                <div className="v">{result?.vpd_kpa ?? "—"}<span className="u"> kPa</span></div>
                <Sparkline values={series.map((s) => s.vpd_kpa)} color="var(--purple)" />
              </div>
              <div className="stat">
                <div className="k">Stocking density</div>
                <div className="v" style={{ color: hmx && !hmx.density_within_limit ? "var(--red)" : undefined }}>
                  {hmx?.stocking_density_kg_m2 ?? "—"}<span className="u"> kg/m²</span>
                </div>
                <div className="u" style={{ fontSize: 10.5 }}>limit {hmx?.density_limit_kg_m2 ?? "—"} · {hmx?.density_pct_of_limit ?? "—"}%</div>
              </div>
              <div className="stat">
                <div className="k">CO₂ (est.)</div>
                <div className="v" style={{ color: hmx && !hmx.co2_within_guideline ? "var(--red)" : undefined }}>
                  {hmx?.estimated_co2_ppm ?? "—"}<span className="u"> ppm</span>
                </div>
                <div className="u" style={{ fontSize: 10.5 }}>guide ≤3000</div>
              </div>
              <div className="stat">
                <div className="k">Air changes</div>
                <div className="v">{hmx?.air_changes_per_hour ?? "—"}<span className="u"> /h</span></div>
                <div className="u" style={{ fontSize: 10.5 }}>{hmx?.airflow_per_bird_m3_h ?? "—"} m³/h per bird</div>
              </div>
              <div className="stat"><div className="k">Water intake</div><div className="v">{bs ? `${bs.water_intake_multiplier}×` : "—"}<span className="u"> est.</span></div></div>
            </div>

            {/* bottom row */}
            <div className="bottom-grid">
              {profile?.length ? (
                <div className="tile expandable" onClick={() => setModal("climate")}>
                  <div className="tile-head"><span className="tile-title">Climate Trend</span><span className="expand-hint">Today · tap to expand ⤢</span></div>
                  <ClimateTrend points={profile} />
                </div>
              ) : null}
              {sensorHistory.length >= 2 && (
                <div className="tile expandable" onClick={() => setModal("sensorHistory")}>
                  <div className="tile-head">
                    <span className="tile-title">📡 Measured House History</span>
                    <span className="expand-hint">Last 48h · sensor · tap to expand ⤢</span>
                  </div>
                  {/* Downsampled: 48h at one reading a minute is 2,880
                      points, which a 620px chart cannot render as anything
                      but a smear. */}
                  <ClimateTrend
                    points={downsample(
                      sensorHistory.filter((p) => p.indoor_t_c != null && p.indoor_rh_pct != null),
                      240
                    ).map((p) => ({
                      t_c: p.indoor_t_c as number,
                      rh_pct: p.indoor_rh_pct as number,
                      label: new Date(p.observed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
                    }))}
                  />
                </div>
              )}
              {growth.length > 0 && (
                <div className="tile expandable" onClick={() => setModal("growth")}>
                  <div className="tile-head"><span className="tile-title">Bird Weight Progress</span><span className="chip">Day {age}</span></div>
                  <GrowthCurve points={growth} currentDay={age} />
                </div>
              )}
              {sched && (
                <div className="tile expandable" onClick={() => setModal("plan")}>
                  <div className="tile-head"><span className="tile-title">Today's Plan</span><span className="expand-hint">peak {sched.peak_fans_on} fans ⤢</span></div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {sched.blocks.map((b, i) => (
                      <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "9px 11px", background: "var(--surface-2)", borderRadius: 9, fontSize: 12.5 }}>
                        <span style={{ fontWeight: 600 }}>{b.start === b.end ? b.start : `${b.start}–${b.end}`}</span>
                        <span className="muted">{b.fans_on} fans · pads {b.pads_on ? "ON" : "off"} · heat {b.heating_needed ? "ON" : "off"}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div className="tile">
                <div className="tile-head"><span style={{ fontWeight: 700 }}>Flock Health</span></div>
                <div className="qa-grid" style={{ marginTop: 0 }}>
                  <div><div className="k muted" style={{ fontSize: 11 }}>Live birds</div><div style={{ fontWeight: 800, fontSize: 17 }}>{liveCount.toLocaleString()}</div></div>
                  <div><div className="k muted" style={{ fontSize: 11 }}>Placed</div><div style={{ fontWeight: 800, fontSize: 17 }}>{flock.bird_count.toLocaleString()}</div></div>
                </div>
                {mortAssess && (
                  <div style={{ marginTop: 10, fontSize: 12, color: mortAssess.within_target ? "var(--ok)" : "var(--danger)" }}>
                    {mortAssess.within_target ? "✓" : "⚠"} {mortAssess.cumulative_pct}% cumulative (limit {mortAssess.acceptable_pct}%)
                  </div>
                )}
                {(mort.cumulative_depleted ?? 0) > 0 && (
                  <div style={{ marginTop: 8, fontSize: 12, color: "var(--blue)" }}>
                    🚚 {mort.cumulative_depleted.toLocaleString()} lifted (sold) — not counted as deaths
                  </div>
                )}
                <form onSubmit={submitDeaths} style={{ display: "flex", gap: 9, alignItems: "end", marginTop: 12 }}>
                  <div><label style={{ marginTop: 0 }}>Log deaths today</label><input type="number" min={0} value={deaths} onChange={(e) => setDeaths(+e.target.value)} style={{ width: 120 }} /></div>
                  <button className="primary" type="submit" style={{ maxWidth: 90, margin: 0 }} disabled={deaths <= 0}>Add</button>
                </form>
                {/* Deliberately a SEPARATE form from deaths, not a dropdown on
                    one field. Birds sold and birds dead look similar in a
                    database and mean opposite things to a welfare figure —
                    the EU ceiling is ~3% of the flock and a lift is 20-40%,
                    so one mis-click would report a disaster that never
                    happened. Two buttons make the choice explicit. */}
                <form onSubmit={submitLift} style={{ display: "flex", gap: 9, alignItems: "end", marginTop: 10 }}>
                  <div>
                    <label style={{ marginTop: 0 }}>Birds lifted (sold)</label>
                    <input type="number" min={0} value={lifted} onChange={(e) => setLifted(+e.target.value)} style={{ width: 120 }} />
                  </div>
                  <button className="ghost-btn" type="submit" style={{ margin: 0 }} disabled={lifted <= 0}>Record lift</button>
                </form>
                <div className="muted" style={{ fontSize: 10.5, marginTop: 6, lineHeight: 1.45 }}>
                  Use <b>Record lift</b> when birds leave alive for slaughter. They drop out
                  of the ventilation load but never count as mortality.
                </div>
              </div>
            </div>
          </div>

          {/* ============ RIGHT RAIL ============ */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {advice && (
              <div className="advisor">
                <div className="advisor-head">
                  <span style={{ fontSize: 19 }}>✦</span>
                  <div>
                    <div style={{ fontWeight: 800, fontSize: 15 }}>AI Advisor</div>
                    <div className="muted" style={{ fontSize: 10.5 }}>Powered by the PCIS engine</div>
                  </div>
                  <span className="advisor-badge">PCIS AI</span>
                </div>

                <div className="action-box">
                  <div className="action-title">💡 Action recommended</div>
                  <div style={{ fontSize: 17, fontWeight: 800, marginTop: 7, lineHeight: 1.25 }}>{advice.headline}</div>
                  <div className="muted" style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.5 }}>{advice.detail}</div>
                </div>

                <div style={{ marginTop: 13 }}>
                  <div className="cap" style={{ color: "var(--warn)" }}>Expected result</div>
                  <div className="ring-wrap">
                    <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6, fontSize: 12.5 }}>
                      {advice.feel_before_c != null && advice.feel_after_c != null && (
                        <div>🌡 Feel temp: <b style={{ color: advice.feel_after_c < advice.feel_before_c ? "var(--ok)" : "var(--ink)" }}>
                          {advice.feel_before_c}° → {advice.feel_after_c}°</b></div>
                      )}
                      <div>💚 Comfort: <b>{advice.comfort_score}%</b></div>
                      <div>📈 Heat stress: <b style={{ color: RISK_COLOR[advice.heat_stress_risk] }}>{advice.heat_stress_risk}</b></div>
                      <div>😮‍💨 Panting: <b>{advice.panting_before} → {advice.panting_after}</b></div>
                      {/* Two different questions, two different numbers.
                          The ring shows confidence in the ACTION (how many
                          fans), which is geometry-driven and well sourced.
                          The felt-temp and comfort figures above lean on
                          humidity inputs and are softer — saying so is more
                          useful than averaging them into one vague score. */}
                      {advice.metric_confidence != null &&
                        advice.metric_confidence < advice.confidence && (
                        <div className="muted" style={{ fontSize: 11 }}>
                          Comfort figures above: {advice.metric_confidence}% confidence
                        </div>
                      )}
                    </div>
                    <Ring pct={advice.confidence} label="Action confidence" />
                  </div>
                  {advice.confidence_basis && (
                    <div className="muted" style={{ fontSize: 10.5, marginTop: 8, lineHeight: 1.45 }}>
                      Based on: {advice.confidence_basis}
                    </div>
                  )}
                </div>

                <button className="primary" style={{ marginTop: 14 }} onClick={() => setAdviceAck(true)} disabled={adviceAck}>
                  {adviceAck ? "✓ Noted" : "▶ Apply recommendation"}
                </button>
                <div className="muted" style={{ fontSize: 10.5, marginTop: 7, lineHeight: 1.45 }}>
                  Advice only — v1 doesn’t control equipment. {advice.why}
                </div>
              </div>
            )}

            <div className="tile">
              <div className="tile-head">
                <span style={{ fontWeight: 700, fontSize: 14 }}>Active Alerts <span style={{ color: "var(--danger)" }}>({alerts.length})</span></span>
              </div>
              {alerts.length === 0 && <div className="muted" style={{ fontSize: 12.5 }}>No alerts — all systems normal.</div>}
              {alerts.map((a, i) => {
                const s = SEV[a.severity];
                return (
                  <div key={i} className="alert-row">
                    <div className="alert-ico" style={{ background: s.bg, color: s.c }}>{s.ico}</div>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 700, fontSize: 12.5 }}>{a.title}</div>
                      <div className="muted" style={{ fontSize: 11.5, lineHeight: 1.45 }}>{a.message}</div>
                    </div>
                  </div>
                );
              })}
            </div>

            {tg && (
              <div className="tile">
                <div className="tile-head">
                  <span className="tile-title">Tunnel geometry</span>
                  <span className={tg.meets_target ? "chip" : "chip warn"}>
                    {tg.current_velocity_mps} m/s
                  </span>
                </div>
                <div className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>{tg.note}</div>

                {!tg.meets_target && tg.required_ceiling_height_m != null && (
                  <div style={{ display: "flex", gap: 12, marginTop: 12 }}>
                    <div style={{ flex: 1, background: "rgba(34,197,94,0.10)", border: "1px solid rgba(34,197,94,0.3)", borderRadius: 12, padding: 11 }}>
                      <div className="cap" style={{ color: "var(--green-bright)" }}>Drop ceiling</div>
                      <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>{tg.required_ceiling_height_m} m</div>
                      <div className="muted" style={{ fontSize: 11 }}>from {tg.current_ceiling_height_m} m · uses current fans</div>
                    </div>
                    <div style={{ flex: 1, background: "rgba(251,146,60,0.10)", border: "1px solid rgba(251,146,60,0.3)", borderRadius: 12, padding: 11 }}>
                      <div className="cap" style={{ color: "var(--orange)" }}>Or add fans</div>
                      <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>{tg.fans_needed_instead}</div>
                      <div className="muted" style={{ fontSize: 11 }}>vs {house.installed_fans} installed</div>
                    </div>
                  </div>
                )}

                <table style={{ width: "100%", marginTop: 12, fontSize: 12, borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ color: "var(--ink-muted)" }}>
                      <th style={{ textAlign: "left", fontWeight: 500, paddingBottom: 5 }}>Ceiling</th>
                      <th style={{ textAlign: "right", fontWeight: 500 }}>Velocity</th>
                      <th style={{ textAlign: "right", fontWeight: 500 }}>ft/min</th>
                      <th style={{ textAlign: "right", fontWeight: 500 }}>Target</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tg.options.map((o, i) => (
                      <tr key={i} style={{ borderTop: "1px solid var(--line)" }}>
                        <td style={{ padding: "5px 0" }}>{o.ceiling_height_m} m</td>
                        <td style={{ textAlign: "right", fontWeight: 600 }}>{o.velocity_mps}</td>
                        <td style={{ textAlign: "right", color: "var(--ink-muted)" }}>{o.velocity_fpm}</td>
                        <td style={{ textAlign: "right", color: o.meets_tunnel_target ? "var(--green-bright)" : o.windchill_effective ? "var(--orange)" : "var(--ink-dim)" }}>
                          {o.meets_tunnel_target ? "✓ 3.0" : o.windchill_effective ? "~2.5" : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {ph && (
              <div className="tile">
                <div className="tile-head">
                  <span className="tile-title">Humidity check</span>
                  {Math.abs(ph.indoor_rh_pct - inRh) > 10 && <span className="chip warn">gap {Math.abs(ph.indoor_rh_pct - inRh).toFixed(0)}%</span>}
                </div>
                <div style={{ display: "flex", gap: 18 }}>
                  <div>
                    <div className="cap">
                      {sensor?.ok ? "Sensor" : "Measured"}
                      {sensorAgeMin != null && (
                        <span style={{
                          marginLeft: 6,
                          color: sensorAgeMin >= SENSOR_DEAD_MIN ? "var(--danger)"
                               : sensorAgeMin >= SENSOR_STALE_MIN ? "var(--warn)"
                               : "var(--ok)",
                        }}>
                          {sensorAgeMin < 1 ? "just now" : `${Math.round(sensorAgeMin)}m ago`}
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: sensor?.ok ? "var(--green-bright)" : undefined }}>{inRh}%</div>
                    {sensor?.ok && <div className="muted" style={{ fontSize: 10.5 }}>Ecowitt live</div>}
                  </div>
                  <div><div className="cap">Predicted</div><div style={{ fontSize: 22, fontWeight: 700, color: "var(--blue)" }}>{ph.indoor_rh_pct}%</div></div>
                </div>
                <div className="muted" style={{ fontSize: 11.5, marginTop: 10, lineHeight: 1.5 }}>{ph.note}</div>
              </div>
            )}

            <div className="tile">
              <div className="tile-head"><span style={{ fontWeight: 700, fontSize: 14 }}>Quick Actions</span></div>
              <div className="qa-grid">
                <div className="qa" onClick={() => setShowConditions(true)}>🌡 Conditions</div>
                <div className="qa" onClick={() => compute()}>↻ Recalculate</div>
                <div className="qa" onClick={() => setShowLocation(true)}>📍 Location</div>
                <div className="qa" onClick={() => setShowSensor(true)}>📡 Sensor</div>
                <div className="qa" onClick={() => router.push("/houses")}>🏠 Houses</div>
                <div className="qa" onClick={startEditFlock}>🐤 Edit flock</div>
              </div>
            </div>

            {result && (
              <div className="tile">
                <div className="tile-head"><span style={{ fontWeight: 700, fontSize: 14 }}>Engine detail</span></div>
                <div style={{ display: "grid", gap: 8, fontSize: 12.5 }}>
                  <Row k="Governing constraint" v={result.governing_constraint.replace("_", " ")} />
                  <Row k="Required airflow" v={`${result.required_airflow_m3_per_h.toLocaleString()} m³/h`} />
                  <Row k="Target air speed" v={result.target_airspeed_mps ? `${result.target_airspeed_mps} m/s` : "—"} />
                  <Row k="Heating" v={result.heating_needed ? `${result.heat_deficit_kw} kW` : "off"} />
                  {result.measured_air_speed_mps != null && (
                    <Row
                      k="Air speed (measured)"
                      v={`${result.measured_air_speed_mps} m/s${
                        result.air_speed_agreement === "agree"
                          ? " ✓"
                          : result.air_speed_divergence_pct != null
                            ? ` ⚠ ${result.air_speed_divergence_pct > 0 ? "+" : ""}${result.air_speed_divergence_pct}%`
                            : ""
                      }`}
                    />
                  )}
                  {result.moisture_control_limited && result.outdoor_rh_for_drying_pct != null && (
                    <Row k="Drying resumes below" v={`${result.outdoor_rh_for_drying_pct}% outdoor RH`} />
                  )}
                  <Row k="Action confidence" v={`${result.action_confidence}/100`} />
                  <Row k="Metric confidence" v={`${result.confidence_score}/100`} />
                </div>
              </div>
            )}
          </div>
        </div>
        </>
      )}

      {/* ============ EXPANDED CHART MODALS ============ */}
      {modal === "climate" && profile && (
        <Modal title="Climate Trend" subtitle="Outdoor temperature and humidity across today, from your farm's location" onClose={() => setModal(null)}>
          <div style={{ background: "rgba(0,0,0,0.3)", borderRadius: 16, padding: 16 }}>
            <ClimateTrend points={profile} />
          </div>
          <div className="stats" style={{ marginTop: 16 }}>
            <div className="stat"><div className="k">Peak temp</div><div className="v">{Math.max(...profile.map((p) => p.t_c)).toFixed(1)}<span className="u"> °C</span></div></div>
            <div className="stat"><div className="k">Low temp</div><div className="v">{Math.min(...profile.map((p) => p.t_c)).toFixed(1)}<span className="u"> °C</span></div></div>
            <div className="stat"><div className="k">Peak RH</div><div className="v">{Math.max(...profile.map((p) => p.rh_pct))}<span className="u"> %</span></div></div>
            <div className="stat"><div className="k">Points</div><div className="v">{profile.length}<span className="u"> · 3-hourly</span></div></div>
          </div>
        </Modal>
      )}

      {modal === "sensorHistory" && sensorHistory.length >= 2 && (() => {
        const pts = downsample(
          sensorHistory.filter((p) => p.indoor_t_c != null && p.indoor_rh_pct != null), 300)
          .map((p) => ({
            t_c: p.indoor_t_c as number,
            rh_pct: p.indoor_rh_pct as number,
            label: new Date(p.observed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          }));
        const pressures = sensorHistory.map((p) => p.pressure_hpa).filter((v): v is number => v != null);
        const speeds = sensorHistory.map((p) => p.measured_air_speed_mps).filter((v): v is number => v != null);
        return (
          <Modal title="Measured House History" subtitle="Actual sensor readings inside the house — logged automatically every 10 minutes, not estimates" onClose={() => setModal(null)}>
            <div style={{ background: "rgba(0,0,0,0.3)", borderRadius: 16, padding: 16 }}>
              <ClimateTrend points={pts} />
            </div>
            <div className="stats" style={{ marginTop: 16 }}>
              <div className="stat"><div className="k">Peak temp</div><div className="v">{Math.max(...pts.map((p) => p.t_c)).toFixed(1)}<span className="u"> °C</span></div></div>
              <div className="stat"><div className="k">Low temp</div><div className="v">{Math.min(...pts.map((p) => p.t_c)).toFixed(1)}<span className="u"> °C</span></div></div>
              <div className="stat"><div className="k">Peak RH</div><div className="v">{Math.max(...pts.map((p) => p.rh_pct))}<span className="u"> %</span></div></div>
              {pressures.length > 0 && (
                <div className="stat"><div className="k">Pressure</div><div className="v">{pressures[pressures.length - 1]}<span className="u"> hPa</span></div></div>
              )}
              {speeds.length > 0 && (
                <div className="stat"><div className="k">Air speed (latest)</div><div className="v">{speeds[speeds.length - 1]}<span className="u"> m/s</span></div></div>
              )}
              <div className="stat"><div className="k">Readings</div><div className="v">{sensorHistory.length}<span className="u"> · ~10 min apart</span></div></div>
            </div>
          </Modal>
        );
      })()}

      {modal === "growth" && growth.length > 0 && (
        <Modal title="Bird Weight Progress" subtitle="Aviagen Ross 308 as-hatched target curve, days 0–56" onClose={() => setModal(null)}>
          <div style={{ background: "rgba(0,0,0,0.3)", borderRadius: 16, padding: 16 }}>
            <GrowthCurve points={growth} currentDay={age} />
          </div>
          <div className="stats" style={{ marginTop: 16 }}>
            <div className="stat"><div className="k">Today (day {age})</div><div className="v">{result?.body_weight_kg?.toFixed(3) ?? "—"}<span className="u"> kg</span></div></div>
            <div className="stat"><div className="k">Day 42 target</div><div className="v">{growth.find((g) => g.day === 42)?.weight_kg.toFixed(2) ?? "—"}<span className="u"> kg</span></div></div>
            <div className="stat"><div className="k">Day 56 target</div><div className="v">{growth.find((g) => g.day === 56)?.weight_kg.toFixed(2) ?? "—"}<span className="u"> kg</span></div></div>
            <div className="stat"><div className="k">Total live weight</div><div className="v">{result ? ((result.body_weight_kg * liveCount) / 1000).toFixed(1) : "—"}<span className="u"> t</span></div></div>
          </div>
        </Modal>
      )}

      {modal === "plan" && sched && (
        <Modal title="Today's Operating Plan" subtitle="Engine-computed fan, pad and heater schedule from today's forecast" onClose={() => setModal(null)}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {sched.blocks.map((b, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 16px", background: "rgba(118,118,128,0.16)", borderRadius: 14 }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 15 }}>{b.start === b.end ? b.start : `${b.start} – ${b.end}`}</div>
                  <div className="muted" style={{ fontSize: 12 }}>{b.hours} hours</div>
                </div>
                <div style={{ display: "flex", gap: 18, fontSize: 13 }}>
                  <span>🌀 <b style={{ color: "var(--teal)" }}>{b.fans_on}</b> fans</span>
                  <span style={{ color: b.pads_on ? "var(--orange)" : "var(--ink-dim)" }}>💧 pads {b.pads_on ? "ON" : "off"}</span>
                  <span style={{ color: b.heating_needed ? "var(--red)" : "var(--ink-dim)" }}>🔥 heat {b.heating_needed ? "ON" : "off"}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="stats" style={{ marginTop: 16 }}>
            <div className="stat"><div className="k">Peak fans</div><div className="v">{sched.peak_fans_on}</div></div>
            <div className="stat"><div className="k">Fan-hours</div><div className="v">{sched.fan_hours}</div></div>
            <div className="stat"><div className="k">Heating steps</div><div className="v">{sched.heating_steps}</div></div>
            <div className="stat"><div className="k">Shortfall steps</div><div className="v" style={{ color: sched.shortfall_steps ? "var(--red)" : undefined }}>{sched.shortfall_steps}</div></div>
          </div>
          {sched.notes?.filter((n) => n.startsWith("WARNING")).map((n, i) => (
            <div key={i} className="msg error" style={{ fontSize: 12.5, lineHeight: 1.5 }}>⚠ {n}</div>
          ))}
        </Modal>
      )}
    </AppShell>
  );
}

function Metric({ icon, label, value, sub, pct, color, spark }: {
  icon: string; label: string; value: string; sub: string; pct: number; color: string;
  spark?: (number | null)[];
}) {
  return (
    <div
      className="metric"
      style={{
        ["--mtint" as any]: `color-mix(in srgb, ${color} 16%, transparent)`,
        ["--mcol" as any]: `color-mix(in srgb, ${color} 28%, transparent)`,
      }}
    >
      <div className="metric-top">
        <span className="metric-icon">{icon}</span>
        <span className="metric-label">{label}</span>
      </div>
      <div className="metric-val" style={{ color }}>{value}</div>
      <div className="metric-sub muted">{sub}</div>
      {spark && spark.length > 1 ? (
        <Sparkline values={spark} color={color} />
      ) : (
        <div className="bar"><i style={{ width: `${Math.max(0, Math.min(100, pct))}%`, background: color }} /></div>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
      <span className="muted">{k}</span>
      <span style={{ fontWeight: 600, textAlign: "right" }}>{v}</span>
    </div>
  );
}
