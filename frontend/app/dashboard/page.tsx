"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { supabase } from "@/lib/supabaseClient";
import {
  getMyFarm, getHouses, getActiveFlock, createFlock, updateFlock, endFlock, birdAgeDays,
  updateFarmLocation, saveRecommendation, getMortalitySummary, logMortality, type MortalitySummary,
} from "@/lib/db";
import { recommend, schedule, advise, mortality, getGrowthCurve } from "@/lib/api";
import { getCurrentWeather, getTodayProfile, type WxPoint } from "@/lib/weather";
import AppShell from "@/components/AppShell";
import Modal from "@/components/Modal";
import { ClimateTrend, GrowthCurve } from "@/components/Charts";
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

const daysAgoISO = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);

function deriveAlerts(r: RecommendResponse, house: House, sched: ScheduleResponse | null): Alert[] {
  const a: Alert[] = [];
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
  const [wxSource, setWxSource] = useState<"weather" | "manual">("manual");
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

  const [mort, setMort] = useState<MortalitySummary>({ cumulative_dead: 0, today_dead: 0 });
  const [mortAssess, setMortAssess] = useState<MortalityResponse | null>(null);
  const [deaths, setDeaths] = useState(0);
  const [growth, setGrowth] = useState<{ day: number; weight_kg: number }[]>([]);
  const [showConditions, setShowConditions] = useState(false);
  const [modal, setModal] = useState<null | "climate" | "growth" | "plan">(null);

  const [locBusy, setLocBusy] = useState(false);
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");

  const liveCount = flock ? Math.max(0, flock.bird_count - mort.cumulative_dead) : 0;
  const age = flock ? birdAgeDays(flock.placement_date) : 0;
  const density = house && liveCount ? liveCount / (house.length_m * house.width_m) : 0;

  const refreshWeather = useCallback(async (f: Farm) => {
    if (f.latitude == null || f.longitude == null) return;
    try {
      const wx = await getCurrentWeather(f.latitude, f.longitude);
      setOutT(wx.t_c); setOutRh(wx.rh_pct); setWxSource("weather");
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
      await refreshWeather(f);
      setLoading(false);
    })();
  }, [router, refreshWeather]);

  useEffect(() => {
    if (flock) getMortalitySummary(flock.id).then(setMort).catch(() => setMort({ cumulative_dead: 0, today_dead: 0 }));
    else setMort({ cumulative_dead: 0, today_dead: 0 });
  }, [flock]);

  useEffect(() => { getGrowthCurve().then((r) => setGrowth(r.points)).catch(() => setGrowth([])); }, []);

  const compute = useCallback(async () => {
    if (!house || !flock) return;
    setComputing(true); setError("");
    const live = Math.max(1, flock.bird_count - mort.cumulative_dead);
    const base = {
      length_m: house.length_m, width_m: house.width_m, height_m: house.height_m,
      insulation: house.insulation, fan_index: house.fan_index,
      installed_fans: house.installed_fans, static_pressure_pa: house.static_pressure_pa,
      cooling_pads: house.has_cooling_pads, heater_kw: house.heater_kw,
      bird_age_days: birdAgeDays(flock.placement_date), bird_count: live,
      indoor_rh_pct: inRh, outdoor_t_c: outT, outdoor_rh_pct: outRh,
    };
    try {
      const res = (await recommend(base)) as RecommendResponse;
      setResult(res);
      saveRecommendation(house.id, flock.id, res);
      setAdviceAck(false);
      advise(base).then((a) => setAdvice(a as AdviseResponse)).catch(() => setAdvice(null));
      mortality({ placed: flock.bird_count, cumulative_dead: mort.cumulative_dead, age_days: birdAgeDays(flock.placement_date), dead_today: mort.today_dead })
        .then((mm) => setMortAssess(mm as MortalityResponse)).catch(() => setMortAssess(null));
      if (profile?.length) setSched((await schedule({ ...base, profile, step_hours: 3 })) as ScheduleResponse);
    } catch (err: any) {
      setError(err?.message ?? "Could not reach the engine API. Is it running?");
    } finally { setComputing(false); }
  }, [house, flock, inRh, outT, outRh, profile, mort]);

  useEffect(() => { if (house && flock) compute(); /* eslint-disable-next-line */ }, [house, flock, profile, mort]);

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
    if (f) { setFlock(f); setEditingFlock(false); }
  }
  async function startNewFlock() {
    if (!flock || !window.confirm("End the current flock and place a new one?")) return;
    await endFlock(flock.id).catch(() => {});
    setFlock(null); setResult(null); setSched(null); setAdvice(null);
    setMort({ cumulative_dead: 0, today_dead: 0 }); setMortAssess(null);
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
  async function useMyLocation() {
    if (!farm || !navigator.geolocation) return;
    setLocBusy(true);
    navigator.geolocation.getCurrentPosition(async (pos) => {
      const la = +pos.coords.latitude.toFixed(4), lo = +pos.coords.longitude.toFixed(4);
      try { await updateFarmLocation(farm.id, la, lo); const nf = { ...farm, latitude: la, longitude: lo }; setFarm(nf); await refreshWeather(nf); }
      finally { setLocBusy(false); }
    }, () => { setLocBusy(false); setError("Location denied — enter manually."); });
  }
  async function saveManualLocation() {
    if (!farm) return;
    const la = parseFloat(lat), lo = parseFloat(lon);
    if (Number.isNaN(la) || Number.isNaN(lo)) { setError("Enter valid coordinates."); return; }
    setLocBusy(true);
    try { await updateFarmLocation(farm.id, la, lo); const nf = { ...farm, latitude: la, longitude: lo }; setFarm(nf); await refreshWeather(nf); }
    finally { setLocBusy(false); }
  }

  if (loading) return <div className="auth-wrap"><div className="muted">Loading…</div></div>;

  const bs = result?.bird_status;
  const hmx = result?.house_metrics;
  const alerts = result && house ? deriveAlerts(result, house, sched) : [];
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
      weather={wxSource === "weather" ? { t: outT, rh: outRh } : null}
      alertCount={alerts.length}
    >
      {houses.length === 0 && (
        <div className="placeholder">No houses yet. <Link href="/houses" style={{ color: "var(--accent)" }}>Add your first house</Link>.</div>
      )}

      {house && farm && farm.latitude == null && (
        <div className="tile" style={{ marginBottom: 16 }}>
          <div className="cap">Set farm location — enables automatic weather</div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "end", marginTop: 10 }}>
            <button className="primary" style={{ maxWidth: 210, margin: 0 }} onClick={useMyLocation} disabled={locBusy}>
              {locBusy ? "…" : "Use my current location"}
            </button>
            <span className="muted">or</span>
            <div><label style={{ marginTop: 0 }}>Latitude</label><input value={lat} onChange={(e) => setLat(e.target.value)} style={{ width: 120 }} placeholder="17.38" /></div>
            <div><label style={{ marginTop: 0 }}>Longitude</label><input value={lon} onChange={(e) => setLon(e.target.value)} style={{ width: 120 }} placeholder="78.48" /></div>
            <button className="ghost-btn" onClick={saveManualLocation} disabled={locBusy}>Save</button>
          </div>
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
                <div className="cap">Conditions {wxSource === "weather" ? "· auto from weather" : "· manual"}</div>
                <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "end", marginTop: 10 }}>
                  <div><label style={{ marginTop: 0 }}>Outdoor °C</label><input type="number" value={outT} onChange={(e) => { setOutT(+e.target.value); setWxSource("manual"); }} style={{ width: 110 }} /></div>
                  <div><label style={{ marginTop: 0 }}>Outdoor RH %</label><input type="number" value={outRh} onChange={(e) => { setOutRh(+e.target.value); setWxSource("manual"); }} style={{ width: 110 }} /></div>
                  <div><label style={{ marginTop: 0 }}>Indoor RH %</label><input type="number" value={inRh} onChange={(e) => setInRh(+e.target.value)} style={{ width: 110 }} /></div>
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
                  <label>Bird count</label>
                  <input type="number" value={flockCount} onChange={(e) => setFlockCount(+e.target.value)} />
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

            {/* metric cards */}
            <div className="metrics">
              <Metric icon="💚" label="Bird Comfort" color="var(--green)"
                value={bs ? `${bs.comfort_score}%` : "—"} sub={bs?.comfort_label ?? ""}
                pct={bs?.comfort_score ?? 0} />
              <Metric icon="🌡" label="Feel Temperature" color="var(--blue)"
                value={result?.effective_temp_c != null ? `${result.effective_temp_c.toFixed(1)}°` : "—"}
                sub={`Target ${result?.comfort.target_temp_c.toFixed(1) ?? "—"}°C`}
                pct={result?.effective_temp_c != null ? Math.min(100, (result.effective_temp_c / 40) * 100) : 0} />
              <Metric icon="🔥" label="Heat Stress" color={RISK_COLOR[bs?.heat_stress_risk ?? "Low"]}
                value={bs?.heat_stress_risk ?? "—"} sub={`Panting ${bs?.panting_index ?? "—"}`}
                pct={bs?.heat_stress_risk === "High" ? 100 : bs?.heat_stress_risk === "Moderate" ? 60 : 25} />
              <Metric icon="🌀" label="Fans Running" color={result && result.fans_on > house.installed_fans ? "var(--red)" : "var(--teal)"}
                value={result ? `${result.fans_on}/${house.installed_fans}` : "—"}
                sub={`${result?.pads_on ? "Pads ON" : "Pads off"}${result?.heating_needed ? " · Heat ON" : ""}`}
                pct={Math.min(100, ((result?.fans_on ?? 0) / Math.max(1, house.installed_fans)) * 100)} />
              <Metric icon="📉" label="Mortality" color={mortAssess && !mortAssess.within_target ? "var(--red)" : "var(--orange)"}
                value={mortAssess ? `${mortAssess.cumulative_pct}%` : "—"}
                sub={`Limit ${mortAssess?.acceptable_pct ?? "—"}% · ${mort.cumulative_dead.toLocaleString()} birds`}
                pct={Math.min(100, ((mortAssess?.cumulative_pct ?? 0) / Math.max(0.1, mortAssess?.acceptable_pct ?? 1)) * 100)} />
            </div>

            {/* stat strip */}
            <div className="stats">
              <div className="stat"><div className="k">Target Temp</div><div className="v">{result?.comfort.target_temp_c.toFixed(1) ?? "—"}<span className="u"> °C</span></div></div>
              <div className="stat"><div className="k">Indoor RH</div><div className="v">{inRh}<span className="u"> %</span></div></div>
              <div className="stat"><div className="k">Air Speed</div><div className="v">{result?.air_speed_mps?.toFixed(2) ?? "—"}<span className="u"> m/s</span></div></div>
              <div className="stat"><div className="k">Static Pressure</div><div className="v">{house.static_pressure_pa}<span className="u"> Pa</span></div></div>
              <div className="stat"><div className="k">VPD</div><div className="v">{result?.vpd_kpa ?? "—"}<span className="u"> kPa</span></div></div>
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
                <form onSubmit={submitDeaths} style={{ display: "flex", gap: 9, alignItems: "end", marginTop: 12 }}>
                  <div><label style={{ marginTop: 0 }}>Log deaths today</label><input type="number" min={0} value={deaths} onChange={(e) => setDeaths(+e.target.value)} style={{ width: 120 }} /></div>
                  <button className="primary" type="submit" style={{ maxWidth: 90, margin: 0 }} disabled={deaths <= 0}>Add</button>
                </form>
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
                    </div>
                    <Ring pct={advice.confidence} label="Confidence" />
                  </div>
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

            <div className="tile">
              <div className="tile-head"><span style={{ fontWeight: 700, fontSize: 14 }}>Quick Actions</span></div>
              <div className="qa-grid">
                <div className="qa" onClick={() => setShowConditions(true)}>🌡 Conditions</div>
                <div className="qa" onClick={() => compute()}>↻ Recalculate</div>
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
                  <Row k="Confidence" v={`${result.confidence_score}/100`} />
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

function Metric({ icon, label, value, sub, pct, color }: {
  icon: string; label: string; value: string; sub: string; pct: number; color: string;
}) {
  return (
    <div
      className="metric"
      style={{
        ["--mcol" as any]: `color-mix(in srgb, ${color} 45%, transparent)`,
        ["--mglow" as any]: `color-mix(in srgb, ${color} 26%, transparent)`,
      }}
    >
      <div className="metric-top">
        <span
          className="metric-icon"
          style={{
            background: `color-mix(in srgb, ${color} 20%, transparent)`,
            boxShadow: `0 0 16px color-mix(in srgb, ${color} 45%, transparent)`,
          }}
        >{icon}</span>
        <span className="metric-label">{label}</span>
      </div>
      <div className="metric-val" style={{ color }}>{value}</div>
      <div className="metric-sub muted">{sub}</div>
      <div className="bar">
        <i style={{ width: `${Math.max(0, Math.min(100, pct))}%`, background: color, boxShadow: `0 0 14px ${color}, 0 0 28px ${color}` }} />
      </div>
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
