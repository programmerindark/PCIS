"use client";

// Predicted-vs-measured over time, with the gap between them shaded.
//
// Deliberately plotted as two lines on one axis rather than as a
// scatter of predicted against measured. A scatter shows correlation but
// hides WHEN the model drifted; on a farm, "it was wrong all Tuesday
// afternoon" is more actionable than "R² = 0.87", because Tuesday
// afternoon is something the operator can go and explain.

const GRID = "#24314a";
const MUTED = "#93a1b5";
const PREDICTED = "#a78bfa"; // violet
const MEASURED = "#34d399";  // green
const GAP = "#f87171";       // red, for the error band

const W = 620;
const H = 210;
const PADL = 42;
const PADR = 16;
const PADT = 14;
const PADB = 28;

export type Series = {
  t: string;
  predicted: number | null;
  measured: number | null;
};

function path(pts: [number, number][]): string {
  return pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
}

export function ValidationChart({
  series,
  unit,
  label,
}: {
  series: Series[];
  unit: string;
  label: string;
}) {
  const usable = series.filter((s) => s.predicted != null || s.measured != null);
  if (usable.length < 2) {
    return (
      <div style={{ height: 140, display: "grid", placeItems: "center", color: MUTED, fontSize: 13 }}>
        Not enough paired data yet — needs at least two logged readings.
      </div>
    );
  }

  const vals = usable.flatMap((s) => [s.predicted, s.measured]).filter((v): v is number => v != null);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const pad = (hi - lo) * 0.15 || 1;
  const min = lo - pad;
  const max = hi + pad;

  const n = usable.length;
  const x = (i: number) => PADL + (n === 1 ? 0 : (i / (n - 1)) * (W - PADL - PADR));
  const y = (v: number) => H - PADB - ((v - min) / (max - min || 1)) * (H - PADT - PADB);

  const predPts: [number, number][] = [];
  const measPts: [number, number][] = [];
  usable.forEach((s, i) => {
    if (s.predicted != null) predPts.push([x(i), y(s.predicted)]);
    if (s.measured != null) measPts.push([x(i), y(s.measured)]);
  });

  // Shaded band between the two lines, drawn only where both exist, so
  // the size of the disagreement is visible at a glance rather than
  // something the eye has to measure between two lines.
  const bothIdx = usable
    .map((s, i) => (s.predicted != null && s.measured != null ? i : -1))
    .filter((i) => i >= 0);
  const bandPath =
    bothIdx.length >= 2
      ? `${path(bothIdx.map((i) => [x(i), y(usable[i].predicted as number)]))} ` +
        `L${bothIdx
          .slice()
          .reverse()
          .map((i) => `${x(i).toFixed(1)},${y(usable[i].measured as number).toFixed(1)}`)
          .join(" L")} Z`
      : "";

  const tick = (v: number) => (Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(2));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }}>
      {[0, 0.25, 0.5, 0.75, 1].map((f, i) => {
        const yy = PADT + f * (H - PADT - PADB);
        return (
          <g key={i}>
            <line x1={PADL} y1={yy} x2={W - PADR} y2={yy} stroke={GRID} strokeWidth={1} />
            <text x={PADL - 6} y={yy + 4} fontSize="10" fill={MUTED} textAnchor="end">
              {tick(max - f * (max - min))}
            </text>
          </g>
        );
      })}

      {bandPath && <path d={bandPath} fill={GAP} opacity={0.16} />}
      <path d={path(predPts)} fill="none" stroke={PREDICTED} strokeWidth={2} strokeDasharray="5 3" />
      <path d={path(measPts)} fill="none" stroke={MEASURED} strokeWidth={2.5} />

      {usable.map((s, i) =>
        i % Math.max(1, Math.floor(n / 6)) === 0 ? (
          <text key={i} x={x(i)} y={H - 8} fontSize="9.5" fill={MUTED} textAnchor="middle">
            {new Date(s.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </text>
        ) : null
      )}

      <g fontSize="11">
        <line x1={PADL} y1={6} x2={PADL + 16} y2={6} stroke={PREDICTED} strokeWidth={2} strokeDasharray="5 3" />
        <text x={PADL + 22} y={9} fill={MUTED}>PCIS predicted</text>
        <line x1={PADL + 122} y1={6} x2={PADL + 138} y2={6} stroke={MEASURED} strokeWidth={2.5} />
        <text x={PADL + 144} y={9} fill={MUTED}>Sensor measured {unit ? `(${unit})` : ""}</text>
      </g>
      <title>{label}</title>
    </svg>
  );
}
