"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { supabase } from "@/lib/supabaseClient";
import {
  getMyFarm, getHouses, getActiveFlock, createFlock, updateFlock, endFlock, birdAgeDays,
  updateFarmLocation, saveRecommendation, getMortalitySummary, logMortality, type MortalitySummary,
} from "@/lib/db";
import { recommend, schedule, advise, mortality, getGrowthCurve } from "@/lib/api";
import { getCurrentWeather, getTodayProfile, type WxPoint } from "@/lib/weather";
import AppShell from "@/components/AppShell";
import { ClimateTrend, GrowthCurve } from "@/components/Charts";
import dynamic from "next/dynamic";

// 3D house is client-only (WebGL) — never render it on the server.
const House3D = dynamic(() => import("@/components/House3D"), {
  ssr: false,
  loading: () => <div style={{ height: 320, display: "grid", placeItems: "center", color: "var(--ink-muted)" }}>Loading house view…</div>,
});
import type {
  Farm, House, Flock, RecommendResponse, ScheduleResponse, Alert, AdviseResponse, MortalityResponse,
} from "@/lib/types";

const RISK_COLOR: Record<string, string> = { Low: "var(--ok)", Moderate: "var(--warn)", High: "var(--danger)" };
const SEV_COLOR: Record<string, string> = { info: "var(--accent)", warning: "var(--warn)", critical: "var(--danger)" };

function daysAgoISO(n: number) {
  return new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);
}

function deriveAlerts(r: RecommendResponse, house: House, sched: ScheduleResponse | null): Alert[] {
  const a: Alert[] = [];
  if (r.bird_status.heat_stress_risk === "High")
    a.push({ severity: "critical", title: "High heat-stress risk", message: "Birds are in the high heat-stress band right now." });
  if (r.fans_on > house.installed_fans)
    a.push({ severity: "warning", title: "Fan shortfall", message: `Needs ${r.fans_on} fans but only ${house.installed_fans} installed.` });
  if (r.target_unreachable)
    a.push({ severity: "warning", title: "Target not reachable", message: "Ventilation alone can't hold target — add cooling or accept a warmer house." });
  if (sched && sched.shortfall_steps > 0 && r.fans_on <= house.installed_fans)
    a.push({ severity: "warning", title: "Fans short later today", message: `${sched.shortfall_steps} time(s) today need more fans than installed.` });
  if (r.heating_needed)
    a.push({ severity: "info", title: "Heating needed", message: `Supplemental heat ~${r.heat_deficit_kw} kW to hold target.` });
  return a;
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
  const [deaths, setDeaths] = useState<number>(0);
  const [growth, setGrowth] = useState<{ day: number; weight_kg: number }[]>([]);

  const liveCount = flock ? Math.max(0, flock.bird_count - mort.cumulative_dead) : 0;

  const [locBusy, setLocBusy] = useState(false);
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");

  const refreshWeather = useCallback(async (f: Farm) => {
    if (f.latitude == null || f.longitude == null) return;
    try {
      const wx = await getCurrentWeather(f.latitude, f.longitude);
      setOutT(wx.t_c);
      setOutRh(wx.rh_pct);
      setWxSource("weather");
      setProfile(await getTodayProfile(f.latitude, f.longitude));
    } catch {
      // leave manual values if weather is unreachable
    }
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
      if (hs.length > 0) {
        const wanted = new URLSearchParams(window.location.search).get("house");
        const chosen = hs.find((h) => h.id === wanted) ?? hs[0];
        setHouse(chosen);
        setFlock(await getActiveFlock(chosen.id).catch(() => null));
      }
      await refreshWeather(f);
      setLoading(false);
    })();
  }, [router, refreshWeather]);

  const compute = useCallback(async () => {
    if (!house || !flock) return;
    setComputing(true);
    setError("");
    const age = birdAgeDays(flock.placement_date);
    const live = Math.max(0, flock.bird_count - mort.cumulative_dead);
    const base = {
      length_m: house.length_m, width_m: house.width_m, height_m: house.height_m,
      insulation: house.insulation, fan_index: house.fan_index,
      installed_fans: house.installed_fans, static_pressure_pa: house.static_pressure_pa,
      cooling_pads: house.has_cooling_pads, heater_kw: house.heater_kw,
      bird_age_days: age, bird_count: Math.max(1, live),
      indoor_rh_pct: inRh, outdoor_t_c: outT, outdoor_rh_pct: outRh,
    };
    try {
      const res = (await recommend(base)) as RecommendResponse;
      setResult(res);
      saveRecommendation(house.id, flock.id, res);
      setAdviceAck(false);
      advise(base).then((a) => setAdvice(a as AdviseResponse)).catch(() => setAdvice(null));
      mortality({
        placed: flock.bird_count, cumulative_dead: mort.cumulative_dead,
        age_days: age, dead_today: mort.today_dead,
      }).then((mm) => setMortAssess(mm as MortalityResponse)).catch(() => setMortAssess(null));
      if (profile && profile.length > 0) {
        const s = (await schedule({ ...base, profile, step_hours: 3 })) as ScheduleResponse;
        setSched(s);
      }
    } catch (err: any) {
      setError(err?.message ?? "Could not reach the engine API. Is it running (window 1)?");
    } finally {
      setComputing(false);
    }
  }, [house, flock, inRh, outT, outRh, profile, mort]);

  useEffect(() => {
    if (flock) getMortalitySummary(flock.id).then(setMort).catch(() => setMort({ cumulative_dead: 0, today_dead: 0 }));
    else setMort({ cumulative_dead: 0, today_dead: 0 });
  }, [flock]);

  useEffect(() => {
    getGrowthCurve().then((r) => setGrowth(r.points)).catch(() => setGrowth([]));
  }, []);

  useEffect(() => {
    if (house && flock) compute();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [house, flock, profile, mort]);

  async function addFlock(e: React.FormEvent) {
    e.preventDefault();
    if (!house) return;
    const f = await createFlock(house.id, { name: "Flock", placement_date: flockDate, bird_count: flockCount })
      .catch((err) => { setError(err?.message ?? "Could not create flock."); return null; });
    if (f) setFlock(f);
  }

  function startEditFlock() {
    if (!flock) return;
    setFlockDate(flock.placement_date);
    setFlockCount(flock.bird_count);
    setEditingFlock(true);
  }

  async function saveFlockEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!flock) return;
    const f = await updateFlock(flock.id, { placement_date: flockDate, bird_count: flockCount })
      .catch((err) => { setError(err?.message ?? "Could not update flock."); return null; });
    if (f) { setFlock(f); setEditingFlock(false); }
  }

  async function startNewFlock() {
    if (!flock) return;
    if (!window.confirm("End the current flock and place a new one? The old flock's history is kept.")) return;
    await endFlock(flock.id).catch(() => {});
    setFlock(null); setResult(null); setSched(null); setAdvice(null);
    setMort({ cumulative_dead: 0, today_dead: 0 }); setMortAssess(null);
    setFlockDate(daysAgoISO(0)); setFlockCount(20000);
  }

  async function submitDeaths(e: React.FormEvent) {
    e.preventDefault();
    if (!flock || deaths <= 0) return;
    await logMortality(flock.id, Math.round(deaths)).catch((err) => setError(err?.message ?? "Could not log mortality."));
    setDeaths(0);
    const s = await getMortalitySummary(flock.id).catch(() => null);
    if (s) setMort(s); // triggers recompute with the new live count
  }

  async function useMyLocation() {
    if (!farm || !navigator.geolocation) return;
    setLocBusy(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const la = +pos.coords.latitude.toFixed(4);
        const lo = +pos.coords.longitude.toFixed(4);
        try {
          await updateFarmLocation(farm.id, la, lo);
          const nf = { ...farm, latitude: la, longitude: lo };
          setFarm(nf);
          await refreshWeather(nf);
        } finally { setLocBusy(false); }
      },
      () => { setLocBusy(false); setError("Location permission denied — enter it manually."); }
    );
  }

  async function saveManualLocation() {
    if (!farm) return;
    const la = parseFloat(lat), lo = parseFloat(lon);
    if (Number.isNaN(la) || Number.isNaN(lo)) { setError("Enter valid latitude and longitude."); return; }
    setLocBusy(true);
    try {
      await updateFarmLocation(farm.id, la, lo);
      const nf = { ...farm, latitude: la, longitude: lo };
      setFarm(nf);
      await refreshWeather(nf);
    } finally { setLocBusy(false); }
  }

  if (loading) return <div className="auth-wrap"><div className="muted">Loading…</div></div>;

  const bs = result?.bird_status;
  const alerts = result && house ? deriveAlerts(result, house, sched) : [];
  if (mortAssess && !mortAssess.within_target)
    alerts.push({ severity: "critical", title: "Mortality above acceptable limit", message: mortAssess.note });
  else if (mortAssess && mortAssess.elevated_today)
    alerts.push({ severity: "warning", title: "Elevated mortality today", message: mortAssess.note });

  return (
    <AppShell
      email={email}
      title={farm?.name ?? "Dashboard"}
      right={
        farm?.latitude != null && wxSource === "weather" ? (
          <span className="pill">☁ {outT}°C · {outRh}% RH</span>
        ) : null
      }
    >
      <div className="page-inner">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
          <div>
            <h2 style={{ marginBottom: 2 }}>{house ? house.name : "Dashboard"}</h2>
            <p className="muted">
              {farm?.name}
              {flock ? ` · ${flock.bird_count.toLocaleString()} birds · day ${birdAgeDays(flock.placement_date)}` : ""}
            </p>
            {flock && (
              <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                <button className="ghost-btn" style={{ padding: "5px 10px", fontSize: 13 }} onClick={startEditFlock}>Edit flock</button>
                <button className="ghost-btn" style={{ padding: "5px 10px", fontSize: 13 }} onClick={startNewFlock}>New flock</button>
              </div>
            )}
          </div>
          {houses.length > 1 && (
            <select value={house?.id} onChange={async (e) => {
              const h = houses.find((x) => x.id === e.target.value) ?? null;
              setHouse(h); setResult(null); setSched(null);
              setFlock(h ? await getActiveFlock(h.id).catch(() => null) : null);
            }} style={selectStyle}>
              {houses.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
            </select>
          )}
        </div>

        {houses.length === 0 && (
          <div className="placeholder" style={{ marginTop: 16 }}>
            No houses yet. <Link href="/houses">Add your first house</Link> to begin.
          </div>
        )}

        {/* Edit flock */}
        {flock && editingFlock && (
          <div className="tile" style={{ maxWidth: 480, marginTop: 16 }}>
            <h3 style={{ marginTop: 0 }}>Edit flock</h3>
            <form onSubmit={saveFlockEdit}>
              <label>Placement date</label>
              <input type="date" value={flockDate} onChange={(e) => setFlockDate(e.target.value)} style={{ padding: "10px 12px", borderRadius: 9, background: "var(--surface-2)", border: "1px solid var(--line)", color: "var(--ink)", fontSize: 15, width: "100%" }} />
              <p className="muted" style={{ marginTop: 6, fontSize: 13 }}>
                Age today would be day {birdAgeDays(flockDate)}.
              </p>
              <label>Bird count</label>
              <input type="number" value={flockCount} onChange={(e) => setFlockCount(+e.target.value)} />
              <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
                <button className="primary" type="submit" style={{ maxWidth: 160, margin: 0 }}>Save</button>
                <button type="button" className="ghost-btn" onClick={() => setEditingFlock(false)}>Cancel</button>
              </div>
            </form>
          </div>
        )}

        {/* Location setup (only when the farm has no coordinates yet) */}
        {house && farm && farm.latitude == null && (
          <div className="tile" style={{ marginTop: 16, maxWidth: 640 }}>
            <div className="cap">Set farm location — for automatic weather</div>
            <p className="muted" style={{ marginTop: 6 }}>
              PCIS can pull today's outdoor temperature and humidity for you.
            </p>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "end" }}>
              <button className="primary" style={{ maxWidth: 220, margin: 0 }} onClick={useMyLocation} disabled={locBusy}>
                {locBusy ? "…" : "Use my current location"}
              </button>
              <span className="muted">or enter manually:</span>
              <div><label style={{ marginTop: 0 }}>Latitude</label><input value={lat} onChange={(e) => setLat(e.target.value)} style={{ width: 120 }} placeholder="17.38" /></div>
              <div><label style={{ marginTop: 0 }}>Longitude</label><input value={lon} onChange={(e) => setLon(e.target.value)} style={{ width: 120 }} placeholder="78.48" /></div>
              <button className="ghost-btn" onClick={saveManualLocation} disabled={locBusy}>Save</button>
            </div>
          </div>
        )}

        {house && !flock && (
          <div className="tile" style={{ maxWidth: 480, marginTop: 16 }}>
            <h3 style={{ marginTop: 0 }}>Place a flock in {house.name}</h3>
            <form onSubmit={addFlock}>
              <label>Placement date</label>
              <input type="date" value={flockDate} onChange={(e) => setFlockDate(e.target.value)} style={selectStyle} />
              <label>Bird count</label>
              <input type="number" value={flockCount} onChange={(e) => setFlockCount(+e.target.value)} />
              <button className="primary" type="submit" style={{ maxWidth: 200 }}>Place flock</button>
            </form>
          </div>
        )}

        {house && flock && (
          <>
            {/* Conditions */}
            <div className="tile" style={{ marginTop: 16 }}>
              <div className="cap">
                Current conditions {wxSource === "weather" ? "· auto from weather" : "· manual"}
              </div>
              <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "end", marginTop: 10 }}>
                <Field label="Outdoor °C" value={outT} onChange={(v) => { setOutT(v); setWxSource("manual"); }} />
                <Field label="Outdoor RH %" value={outRh} onChange={(v) => { setOutRh(v); setWxSource("manual"); }} />
                <Field label="Indoor target RH %" value={inRh} onChange={setInRh} />
                <button className="primary" style={{ maxWidth: 140, margin: 0 }} onClick={compute} disabled={computing}>
                  {computing ? "…" : "Update"}
                </button>
                {farm?.latitude != null && (
                  <button className="ghost-btn" onClick={() => farm && refreshWeather(farm)}>↻ Weather</button>
                )}
              </div>
            </div>

            {error && <div className="msg error" style={{ marginTop: 12 }}>{error}</div>}

            {/* AI Advisor */}
            {advice && (
              <div className="tile" style={{ marginTop: 16, borderColor: "var(--accent)", background: "var(--surface)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
                  <div className="cap" style={{ color: "var(--accent-text, var(--accent))" }}>✦ AI Advisor · action recommended</div>
                  <div className="cap">Confidence {advice.confidence}/100</div>
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, marginTop: 8 }}>{advice.headline}</div>
                <p className="muted" style={{ marginTop: 4 }}>{advice.detail}</p>

                <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginTop: 12 }}>
                  {advice.feel_before_c != null && advice.feel_after_c != null && (
                    <Expected label="Feel temperature"
                      text={`${advice.feel_before_c}°C → ${advice.feel_after_c}°C`}
                      good={advice.feel_after_c < advice.feel_before_c} />
                  )}
                  <Expected label="Panting (est.)"
                    text={`${advice.panting_before} → ${advice.panting_after}`}
                    good={advice.panting_after !== advice.panting_before} />
                  <Expected label="Heat-stress" text={advice.heat_stress_risk}
                    good={advice.heat_stress_risk === "Low"} />
                </div>

                <p className="muted" style={{ marginTop: 12, fontSize: 13 }}>{advice.why}</p>

                <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 12 }}>
                  <button className="primary" style={{ maxWidth: 220, margin: 0 }}
                    onClick={() => setAdviceAck(true)} disabled={adviceAck}>
                    {adviceAck ? "Noted ✓" : "Apply recommendation"}
                  </button>
                  <span className="muted" style={{ fontSize: 12 }}>
                    Advice only — v1 doesn’t control your equipment; apply it on your controller.
                  </span>
                </div>
              </div>
            )}

            {/* Live 3D house view */}
            <div className="tile" style={{ marginTop: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                <div className="cap">Live house view</div>
                <div className="muted" style={{ fontSize: 12 }}>
                  Tunnel fans {result?.fans_on ?? 0}/{house.installed_fans} · pads {result?.pads_on ? "ON" : "off"}
                  {result?.air_speed_mps != null ? ` · ${result.air_speed_mps} m/s` : ""}
                </div>
              </div>
              <div style={{ marginTop: 8, borderRadius: 12, overflow: "hidden", background: "#0b1220" }}>
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
            </div>

            {/* Alerts */}
            {alerts.length > 0 && (
              <div className="tile" style={{ marginTop: 16 }}>
                <div className="cap">Active alerts ({alerts.length})</div>
                <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 10 }}>
                  {alerts.map((a, i) => (
                    <div key={i} style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                      <span style={{ color: SEV_COLOR[a.severity], fontWeight: 800 }}>●</span>
                      <div>
                        <div style={{ fontWeight: 700 }}>{a.title}</div>
                        <div className="muted">{a.message}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Tiles */}
            <div className="grid" style={{ marginTop: 16 }}>
              <Tile cap="Bird comfort" val={bs ? `${bs.comfort_score}%` : "—"} sub={bs?.comfort_label}
                color={bs ? (bs.comfort_label === "Good" ? "var(--ok)" : bs.comfort_label === "Fair" ? "var(--warn)" : "var(--danger)") : undefined} />
              <Tile cap="Feel temperature" val={result?.effective_temp_c != null ? `${result.effective_temp_c.toFixed(1)}°C` : "—"}
                sub={result ? `target ${result.comfort.target_temp_c.toFixed(1)}°C` : undefined} />
              <Tile cap="Heat-stress risk" val={bs?.heat_stress_risk ?? "—"} color={bs ? RISK_COLOR[bs.heat_stress_risk] : undefined} />
              <Tile cap="Fans running" val={result ? `${result.fans_on} / ${house.installed_fans}` : "—"}
                color={result && result.fans_on > house.installed_fans ? "var(--danger)" : undefined} />
            </div>

            {/* Flock health / mortality */}
            <div className="tile" style={{ marginTop: 16 }}>
              <div className="cap">Flock health · live birds & mortality</div>
              <div className="grid" style={{ marginTop: 10 }}>
                <KV k="Live birds" v={`${liveCount.toLocaleString()} / ${flock.bird_count.toLocaleString()}`} />
                <KV k="Cumulative loss" v={mortAssess ? `${mort.cumulative_dead.toLocaleString()} (${mortAssess.cumulative_pct}%)` : `${mort.cumulative_dead.toLocaleString()}`} />
                <KV k="Acceptable ≤" v={mortAssess ? `${mortAssess.acceptable_pct}%` : "—"} />
                <KV k="Today" v={`${mort.today_dead.toLocaleString()}`} />
              </div>
              {mortAssess && (
                <div className="msg" style={{ marginTop: 10, color: mortAssess.within_target ? "var(--ok)" : "var(--danger)" }}>
                  {mortAssess.within_target ? "✓ " : "⚠ "}{mortAssess.note}
                </div>
              )}
              <form onSubmit={submitDeaths} style={{ display: "flex", gap: 10, alignItems: "end", marginTop: 12 }}>
                <div>
                  <label style={{ marginTop: 0 }}>Log deaths today</label>
                  <input type="number" min={0} value={deaths} onChange={(e) => setDeaths(+e.target.value)} style={{ width: 140 }} />
                </div>
                <button className="primary" type="submit" style={{ maxWidth: 120, margin: 0 }} disabled={deaths <= 0}>Add</button>
                <span className="muted" style={{ fontSize: 12 }}>Live count feeds the engine — fewer birds, less ventilation needed.</span>
              </form>
            </div>

            {/* Day plan */}
            {sched && (
              <div className="tile" style={{ marginTop: 16 }}>
                <div className="cap">Today's plan · peak {sched.peak_fans_on} fans · {sched.fan_hours} fan-hours</div>
                <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
                  {sched.blocks.map((b, i) => (
                    <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", background: "var(--surface-2)", borderRadius: 8 }}>
                      <span style={{ fontWeight: 600 }}>{b.start === b.end ? b.start : `${b.start} – ${b.end}`} <span className="muted">({b.hours} h)</span></span>
                      <span>{b.fans_on} fans · pads {b.pads_on ? "ON" : "off"} · heat {b.heating_needed ? "ON" : "off"}</span>
                    </div>
                  ))}
                </div>
                {sched.notes?.some((n) => n.startsWith("WARNING")) && (
                  <p className="muted" style={{ marginTop: 10 }}>
                    {sched.notes.filter((n) => n.startsWith("WARNING"))[0]}
                  </p>
                )}
              </div>
            )}

            {/* Charts */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16, marginTop: 16 }}>
              {profile && profile.length > 0 && (
                <div className="tile">
                  <div className="cap">Climate trend · today</div>
                  <div style={{ marginTop: 8 }}><ClimateTrend points={profile} /></div>
                </div>
              )}
              {growth.length > 0 && (
                <div className="tile">
                  <div className="cap">Bird weight vs Aviagen Ross-308 target</div>
                  <div style={{ marginTop: 8 }}><GrowthCurve points={growth} currentDay={birdAgeDays(flock.placement_date)} /></div>
                </div>
              )}
            </div>

            {/* Recommendation detail */}
            {result && (
              <div className="tile" style={{ marginTop: 16 }}>
                <div className="cap">Recommendation detail</div>
                <div className="grid" style={{ marginTop: 10 }}>
                  <KV k="Cooling pads" v={result.pads_on ? "ON" : "OFF"} />
                  <KV k="Heating" v={result.heating_needed ? `${result.heat_deficit_kw} kW` : "OFF"} />
                  <KV k="Target air speed" v={result.target_airspeed_mps ? `${result.target_airspeed_mps} m/s` : "—"} />
                  <KV k="Predicted air speed" v={result.air_speed_mps != null ? `${result.air_speed_mps} m/s` : "—"} />
                  <KV k="VPD" v={`${result.vpd_kpa} kPa`} />
                  <KV k="Panting (est.)" v={bs?.panting_index ?? "—"} />
                  <KV k="Water (est.)" v={bs ? `~${bs.water_intake_multiplier}× normal` : "—"} />
                  <KV k="Governing" v={result.governing_constraint.replace("_", " ")} />
                  <KV k="Confidence" v={`${result.confidence_score}/100`} />
                </div>
                {result.explanation?.[0] && <p className="muted" style={{ marginTop: 12 }}>{result.explanation[0]}</p>}
              </div>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}

function Field({ label, value, onChange }: { label: string; value: number; onChange: (n: number) => void }) {
  return (
    <div>
      <label style={{ marginTop: 0 }}>{label}</label>
      <input type="number" value={value} onChange={(e) => onChange(+e.target.value)} style={{ width: 130 }} />
    </div>
  );
}
function Expected({ label, text, good }: { label: string; text: string; good: boolean }) {
  return (
    <div>
      <div className="cap">{label}</div>
      <div style={{ fontWeight: 700, fontSize: 16, marginTop: 4, color: good ? "var(--ok)" : "var(--ink)" }}>{text}</div>
    </div>
  );
}
function Tile({ cap, val, sub, color }: { cap: string; val: string; sub?: string; color?: string }) {
  return (
    <div className="tile">
      <div className="cap">{cap}</div>
      <div className="val" style={color ? { color } : {}}>{val}</div>
      {sub && <div className="muted" style={{ marginTop: 4 }}>{sub}</div>}
    </div>
  );
}
function KV({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="cap">{k}</div>
      <div style={{ fontWeight: 700, fontSize: 17, marginTop: 4 }}>{v}</div>
    </div>
  );
}
const selectStyle: React.CSSProperties = {
  padding: "10px 12px", borderRadius: 9, background: "var(--surface-2)",
  border: "1px solid var(--line)", color: "var(--ink)", fontSize: 15,
};
