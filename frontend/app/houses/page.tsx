"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";
import {
  getMyFarm, getHouses, createHouse, updateHouse, deleteHouse, type NewHouse,
} from "@/lib/db";
import { getCatalog } from "@/lib/api";
import Nav from "@/components/Nav";
import type { Farm, House, Catalog } from "@/lib/types";

const BLANK: NewHouse = {
  name: "",
  length_m: 120,
  width_m: 15,
  height_m: 3,
  insulation: "insulated",
  fan_index: 0,
  installed_fans: 10,
  static_pressure_pa: 30,
  has_cooling_pads: false,
  heater_kw: 0,
};

function toForm(h: House): NewHouse {
  return {
    name: h.name, length_m: h.length_m, width_m: h.width_m, height_m: h.height_m,
    insulation: h.insulation, fan_index: h.fan_index, installed_fans: h.installed_fans,
    static_pressure_pa: h.static_pressure_pa, has_cooling_pads: h.has_cooling_pads, heater_kw: h.heater_kw,
  };
}

export default function HousesPage() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [farm, setFarm] = useState<Farm | null>(null);
  const [houses, setHouses] = useState<House[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [form, setForm] = useState<NewHouse>(BLANK);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (!data.session) { router.replace("/login"); return; }
      setEmail(data.session.user.email ?? null);
      const f = await getMyFarm().catch(() => null);
      if (!f) { router.replace("/setup"); return; }
      setFarm(f);
      setHouses(await getHouses(f.id).catch(() => []));
      setCatalog(await getCatalog().catch(() => null));
      setLoading(false);
    })();
  }, [router]);

  function set<K extends keyof NewHouse>(k: K, v: NewHouse[K]) {
    setForm((prev) => ({ ...prev, [k]: v }));
  }

  function startNew() {
    setForm(BLANK); setEditingId(null); setError(""); setShowForm(true);
  }
  function startEdit(h: House) {
    setForm(toForm(h)); setEditingId(h.id); setError(""); setShowForm(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!farm) return;
    setBusy(true); setError("");
    try {
      if (editingId) await updateHouse(editingId, form);
      else await createHouse(farm.id, form);
      setHouses(await getHouses(farm.id));
      setForm(BLANK); setEditingId(null); setShowForm(false);
    } catch (err: any) {
      setError(err?.message ?? "Could not save house.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(h: House) {
    if (!farm) return;
    if (!window.confirm(`Delete "${h.name}"? Its flocks and history will be removed too.`)) return;
    try {
      await deleteHouse(h.id);
      setHouses(await getHouses(farm.id));
    } catch (err: any) {
      setError(err?.message ?? "Could not delete house.");
    }
  }

  if (loading) return <div className="auth-wrap"><div className="muted">Loading…</div></div>;

  return (
    <>
      <Nav email={email} />
      <div className="page">
        <h2>{farm?.name} — Houses</h2>
        <p className="muted">Add or edit each broiler house; the dashboard reads them to advise you.</p>

        {/* Form (create or edit) */}
        {showForm && (
          <div className="tile" style={{ maxWidth: 640, marginBottom: 20 }}>
            <h3 style={{ marginTop: 0 }}>{editingId ? "Edit house" : "New house"}</h3>
            <form onSubmit={submit}>
              <label>Name</label>
              <input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="House 02 - Broiler Shed" required />

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
                <div><label>Length (m)</label><input type="number" step="0.5" value={form.length_m} onChange={(e) => set("length_m", +e.target.value)} /></div>
                <div><label>Width (m)</label><input type="number" step="0.5" value={form.width_m} onChange={(e) => set("width_m", +e.target.value)} /></div>
                <div><label>Height (m)</label><input type="number" step="0.5" value={form.height_m} onChange={(e) => set("height_m", +e.target.value)} /></div>
              </div>

              <label>Insulation</label>
              <select value={form.insulation} onChange={(e) => set("insulation", e.target.value as NewHouse["insulation"])} style={selectStyle}>
                <option value="uninsulated">Uninsulated</option>
                <option value="insulated">Insulated (typical)</option>
                <option value="well_insulated">Well insulated</option>
              </select>

              <label>Fan model</label>
              <select value={form.fan_index} onChange={(e) => set("fan_index", +e.target.value)} style={selectStyle}>
                {(catalog?.fans ?? [{ index: 0, label: "Default fan" }]).map((f) => (
                  <option key={f.index} value={f.index}>{f.label}</option>
                ))}
              </select>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div><label>Fans installed</label><input type="number" value={form.installed_fans} onChange={(e) => set("installed_fans", +e.target.value)} /></div>
                <div><label>Static pressure (Pa)</label><input type="number" value={form.static_pressure_pa} onChange={(e) => set("static_pressure_pa", +e.target.value)} /></div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, alignItems: "end" }}>
                <div><label>Heater capacity (kW, 0 = none)</label><input type="number" value={form.heater_kw} onChange={(e) => set("heater_kw", +e.target.value)} /></div>
                <label style={{ display: "flex", alignItems: "center", gap: 8, margin: "0 0 11px" }}>
                  <input type="checkbox" style={{ width: "auto" }} checked={form.has_cooling_pads} onChange={(e) => set("has_cooling_pads", e.target.checked)} />
                  Cooling pads installed
                </label>
              </div>

              <div style={{ display: "flex", gap: 10 }}>
                <button className="primary" type="submit" disabled={busy} style={{ maxWidth: 200 }}>
                  {busy ? "Saving…" : editingId ? "Update house" : "Save house"}
                </button>
                <button type="button" className="ghost-btn" onClick={() => { setShowForm(false); setEditingId(null); }}>Cancel</button>
              </div>
            </form>
            {error && <div className="msg error">{error}</div>}
          </div>
        )}

        {/* House list */}
        <div className="grid">
          {houses.map((h) => (
            <div key={h.id} className="tile">
              <div className="cap">House</div>
              <div className="val" style={{ fontSize: 20 }}>{h.name}</div>
              <div className="muted" style={{ marginTop: 8 }}>
                {h.length_m}×{h.width_m}×{h.height_m} m · {h.installed_fans} fans · {h.insulation.replace("_", " ")}
                {h.has_cooling_pads ? " · pads" : ""}{h.heater_kw > 0 ? ` · ${h.heater_kw} kW heat` : ""}
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                <button className="ghost-btn" onClick={() => router.push(`/dashboard?house=${h.id}`)}>Open</button>
                <button className="ghost-btn" onClick={() => startEdit(h)}>Edit</button>
                <button className="ghost-btn" style={{ color: "var(--danger)" }} onClick={() => remove(h)}>Delete</button>
              </div>
            </div>
          ))}
          {houses.length === 0 && !showForm && (
            <div className="placeholder">No houses yet. Add your first one.</div>
          )}
        </div>

        {!showForm && (
          <div style={{ marginTop: 20 }}>
            <button className="primary" style={{ maxWidth: 220 }} onClick={startNew}>+ Add a house</button>
          </div>
        )}
      </div>
    </>
  );
}

const selectStyle: React.CSSProperties = {
  width: "100%", padding: "11px 12px", borderRadius: 9, background: "var(--surface-2)",
  border: "1px solid var(--line)", color: "var(--ink)", fontSize: 15,
};
