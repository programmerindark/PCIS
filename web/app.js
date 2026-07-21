// PCIS web client.
//
// The engineering core runs UNMODIFIED in the browser via Pyodide --
// the same pcis/core and pcis/equipment .py files the desktop app and
// the test suite use. Nothing here reimplements a formula; this file
// only collects inputs, calls into Python, and renders what comes back.
// That is deliberate: a JavaScript reimplementation would be a second
// source of truth for the physics and the two would eventually drift.

let py = null;

const $ = (id) => document.getElementById(id);
const boot = (msg) => { const b = $("bootmsg"); if (b) b.textContent = msg; };

// Envelope surfaces match the desktop defaults. Kept here (rather than
// as editable fields) because they change rarely and are miserable to
// type on a phone -- see the setup note in index.html.
const SURFACES = [
  ["sidewalls", 0.6, 350.0],
  ["ceiling", 0.4, 1500.0],
];

async function init() {
  boot("Downloading Python runtime…");
  py = await loadPyodide({ indexURL: "https://cdn.jsdelivr.net/pyodide/v0.28.3/full/" });

  boot("Loading engineering core…");
  const buf = await (await fetch("pcis_core.zip")).arrayBuffer();
  py.unpackArchive(new Uint8Array(buf), "zip");
  py.runPython("import sys, os; sys.path.insert(0, os.getcwd())");

  boot("Ready");
  py.runPython(`
import json
from pcis.core import recommendation_engine as _re, heat_moisture_balance as _hmb
from pcis.core import growth_curve as _gc, digital_twin as _dt
from pcis.equipment.fan_curve import FAN_CATALOG
from pcis.equipment.cooling_pad import COOLING_PAD_CATALOG

def _surfaces(rows):
    return [_hmb.Surface(name=n, u_value=u, area_m2=a) for n, u, a in rows]

def catalogs():
    return json.dumps({
        "fans": [f"{f.manufacturer} {f.model}" for f in FAN_CATALOG],
        "pads": ["(no cooling pad installed)"] + [f"{p.manufacturer} {p.model}" for p in COOLING_PAD_CATALOG],
    })

def weight_for_age(age):
    try:
        return json.dumps({"kg": _gc.ross_308_body_weight_kg(float(age))})
    except ValueError as e:
        return json.dumps({"error": str(e)})

def recommend(payload):
    p = json.loads(payload)
    pad = None if p["pad"] == 0 else COOLING_PAD_CATALOG[p["pad"] - 1]
    r = _re.recommend(
        bird_count=int(p["birds"]), body_weight_kg=float(p["weight"]),
        indoor_t_c=float(p["it"]), indoor_rh_pct=float(p["irh"]),
        outdoor_t_c=float(p["ot"]), outdoor_rh_pct=float(p["orh"]),
        envelope_surfaces=_surfaces(p["surfaces"]),
        fan=FAN_CATALOG[int(p["fan"])],
        design_static_pressure_pa=float(p["sp"]),
        delta_t_c=float(p["dt"]), cooling_pad=pad,
    )
    return json.dumps({
        "fans_on": r.fans_on, "pads_on": r.pads_on,
        "airflow": r.required_airflow_m3_per_h,
        "governing": r.governing_constraint.replace("_", " "),
        "confidence": r.confidence_score,
        "unreachable": r.target_unreachable,
        "supply_t": r.supply_air_t_c,
        "target_t": r.comfort.target_temp_c,
        "thi": r.comfort.thi, "thi_class": r.comfort.thi_class,
        "comfort_index": r.comfort.comfort_index,
        "explanation": list(r.explanation),
    })

def schedule(payload):
    p = json.loads(payload)
    pad = None if p["pad"] == 0 else COOLING_PAD_CATALOG[p["pad"] - 1]
    inst = int(p["installed"])
    try:
        res = _dt.simulate_schedule(
            conditions=[_dt.OutdoorCondition(label=c[0], t_c=float(c[1]), rh_pct=float(c[2]))
                        for c in p["profile"]],
            age_days=float(p["age"]), bird_count=int(p["birds"]),
            envelope_surfaces=_surfaces(p["surfaces"]),
            fan=FAN_CATALOG[int(p["fan"])],
            design_static_pressure_pa=float(p["sp"]),
            delta_t_c=float(p["dt"]), indoor_rh_pct=float(p["irh"]),
            cooling_pad=pad, installed_fan_count=inst if inst > 0 else None,
        )
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({
        "steps": [{"label": s.label, "t": s.outdoor_t_c, "fans": s.fans_on,
                   "pads": s.pads_on, "unreachable": s.target_unreachable}
                  for s in res.steps],
        "blocks": [{"start": b.start_label, "end": b.end_label, "fans": b.fans_on,
                    "pads": b.pads_on, "n": b.n_steps} for b in res.blocks],
        "peak": res.peak_fans_on, "shortfall": res.shortfall_steps,
        "unreachable_steps": res.unreachable_steps,
        "notes": [n for n in res.notes if n.startswith("WARNING")],
    })
`);

  const cat = JSON.parse(py.globals.get("catalogs")());
  cat.fans.forEach((f, i) => $("fan").add(new Option(f, i)));
  cat.pads.forEach((p, i) => $("pad").add(new Option(p, i)));

  seedProfile();
  updateWeight();
  $("age").addEventListener("change", updateWeight);
  $("run").addEventListener("click", runRecommendation);
  $("runSched").addEventListener("click", runSchedule);
  $("boot").style.display = "none";
}

function pyCall(fn, obj) {
  return JSON.parse(py.globals.get(fn)(JSON.stringify(obj)));
}

let currentWeight = 2.296;

function updateWeight() {
  const r = JSON.parse(py.globals.get("weight_for_age")($("age").value));
  if (r.error) {
    $("wt").textContent = "Age outside the published Aviagen table (0–56 days) — "
      + "PCIS will not extrapolate a weight.";
    return;
  }
  currentWeight = r.kg;
  $("wt").textContent = `Body weight ${r.kg.toFixed(3)} kg, from the Aviagen Ross 308 `
    + `as-hatched growth curve.`;
}

function inputs() {
  return {
    birds: $("birds").value, weight: currentWeight,
    it: $("it").value, irh: $("irh").value,
    ot: $("ot").value, orh: $("orh").value,
    fan: $("fan").value, pad: Number($("pad").value),
    sp: $("sp").value, dt: $("dt").value,
    surfaces: SURFACES,
  };
}

function runRecommendation() {
  const r = pyCall("recommend", inputs());
  const cc = r.confidence >= 75 ? "var(--ok)" : r.confidence >= 50 ? "var(--warn)" : "var(--danger)";
  let html = `<div class="card"><h2>Result</h2><div class="metrics">
    <div class="metric"><div class="k">Fans on</div><div class="v">${r.fans_on}</div></div>
    <div class="metric"><div class="k">Cooling pads</div><div class="v">${r.pads_on ? "ON" : "off"}</div></div>
    <div class="metric"><div class="k">Airflow m³/h</div><div class="v" style="font-size:20px">${Math.round(r.airflow).toLocaleString()}</div></div>
    <div class="metric"><div class="k">Confidence</div><div class="v" style="color:${cc}">${r.confidence.toFixed(0)}<span style="font-size:15px">/100</span></div></div>
    <div class="metric wide"><div class="k">Governing constraint</div><div class="v">${r.governing}</div></div>
  </div>`;

  if (r.unreachable) {
    const gap = (r.supply_t - r.target_t).toFixed(1);
    html += `<div class="banner"><b>⚠ Target not reachable</b>
      Supply air is ${r.supply_t.toFixed(1)}°C but the target is ${r.target_t.toFixed(1)}°C
      (a ${gap}°C gap). Ventilation cannot cool the house below the air you feed it, so the
      fan count above will <b style="display:inline">not</b> achieve target — read it as
      “run what you have”. More fans will not close this gap; more evaporative cooling
      capacity, or accepting a warmer house, will.</div>`;
  }

  html += `<details><summary>Engineering explanation (${r.explanation.length} lines)</summary>
    <div class="expl">` + r.explanation.map(l => {
      const cls = l.includes("WARNING") ? "w" : (l.trim().startsWith("-") ? "d" : "");
      return `<div class="${cls}">${esc(l)}</div>`;
    }).join("") + `</div></details></div>`;
  $("out").innerHTML = html;
}

function seedProfile() {
  [["00:00", 24, 80], ["06:00", 21, 85], ["12:00", 34, 45],
   ["15:00", 37, 38], ["18:00", 34, 45], ["21:00", 28, 65]]
    .forEach(r => addRow(r[0], r[1], r[2]));
}

function addRow(label = "12:00", t = 30, rh = 50) {
  const d = document.createElement("div");
  d.className = "row prow";
  d.innerHTML = `<input value="${label}" aria-label="time">
    <input type="number" inputmode="decimal" value="${t}" aria-label="temp">
    <input type="number" inputmode="decimal" value="${rh}" aria-label="rh">
    <button class="ghost" style="width:44px;margin:0;padding:11px 0"
      onclick="this.parentElement.remove()">×</button>`;
  d.style.marginBottom = "8px";
  $("profile").appendChild(d);
}

function runSchedule() {
  const profile = [...document.querySelectorAll(".prow")].map(r => {
    const i = r.querySelectorAll("input");
    return [i[0].value, i[1].value, i[2].value];
  });
  if (!profile.length) { alert("Add at least one time row."); return; }

  const r = pyCall("schedule", { ...inputs(), profile, age: $("age").value,
                                 installed: $("installed").value });
  if (r.error) { $("schedOut").innerHTML = `<div class="card banner">${esc(r.error)}</div>`; return; }

  let html = `<div class="card"><h2>Schedule</h2><div class="sched"><table>`;
  r.blocks.forEach(b => {
    const span = b.n === 1 ? b.start : `${b.start} – ${b.end}`;
    html += `<tr><td>${span}</td><td><b>${b.fans}</b> fan(s)</td>
      <td>pads ${b.pads ? "ON" : "off"}</td></tr>`;
  });
  html += `</table></div><p class="hint">Peak requirement ${r.peak} fans.</p>`;
  r.notes.forEach(n => { html += `<div class="banner">${esc(n)}</div>`; });
  html += `<details><summary>Step detail</summary><div class="sched"><table>` +
    r.steps.map(s => `<tr class="${s.unreachable ? "u" : ""}"><td>${esc(s.label)}</td>
      <td>${s.t.toFixed(0)}°C</td><td>${s.fans} fan(s)</td>
      <td>${s.unreachable ? "unreachable" : ""}</td></tr>`).join("") +
    `</table></div></details></div>`;
  $("schedOut").innerHTML = html;
}

function showTab(which) {
  $("paneNow").classList.toggle("off", which !== "now");
  $("paneSched").classList.toggle("off", which !== "sched");
  $("tabNow").classList.toggle("on", which === "now");
  $("tabSched").classList.toggle("on", which === "sched");
}

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").then((reg) => {
    // A cached PWA will happily serve an old UI forever. Watch for a new
    // service worker taking over and tell the user to reload, rather than
    // leaving them looking at a version we already fixed.
    reg.addEventListener("updatefound", () => {
      const sw = reg.installing;
      if (!sw) return;
      sw.addEventListener("statechange", () => {
        if (sw.state === "installed" && navigator.serviceWorker.controller) {
          const b = document.getElementById("offlineBadge");
          b.textContent = "update ready - reload";
          b.style.cursor = "pointer";
          b.onclick = () => location.reload();
        }
      });
    });
  }).catch(() => {
    document.getElementById("offlineBadge").textContent = "online only";
  });
}

init().catch(e => boot("Failed to start: " + e));
