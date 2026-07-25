"use client";

import type { WxPoint } from "@/lib/weather";

const GRID = "#24314a";
const MUTED = "#93a1b5";
const TEMP = "#fb923c";   // orange
const RH = "#38bdf8";     // blue
const ACCENT = "#14b8a6"; // teal
const WARN = "#fbbf24";

const W = 620;
const H = 210;
const PADL = 38;
const PADR = 38;
const PADT = 14;
const PADB = 28;

function line(pts: [number, number][]): string {
  return pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
}

/** Today's outdoor climate: temperature (left axis) + humidity (right axis). */
export function ClimateTrend({ points }: { points: WxPoint[] }) {
  if (!points.length) return null;
  const temps = points.map((p) => p.t_c);
  const tmin = Math.min(...temps) - 2;
  const tmax = Math.max(...temps) + 2;
  const n = points.length;
  const x = (i: number) => PADL + (n === 1 ? 0 : (i / (n - 1)) * (W - PADL - PADR));
  const yT = (v: number) => H - PADB - ((v - tmin) / (tmax - tmin || 1)) * (H - PADT - PADB);
  const yR = (v: number) => H - PADB - (v / 100) * (H - PADT - PADB);

  const tempPts: [number, number][] = points.map((p, i) => [x(i), yT(p.t_c)]);
  const rhPts: [number, number][] = points.map((p, i) => [x(i), yR(p.rh_pct)]);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }}>
      {[0, 0.25, 0.5, 0.75, 1].map((f, i) => {
        const y = PADT + f * (H - PADT - PADB);
        const t = (tmax - f * (tmax - tmin)).toFixed(0);
        return (
          <g key={i}>
            <line x1={PADL} y1={y} x2={W - PADR} y2={y} stroke={GRID} strokeWidth={1} />
            <text x={PADL - 6} y={y + 4} fontSize="10" fill={MUTED} textAnchor="end">{t}°</text>
            <text x={W - PADR + 6} y={y + 4} fontSize="10" fill={MUTED} textAnchor="start">{Math.round((1 - f) * 100)}%</text>
          </g>
        );
      })}
      {points.map((p, i) => (i % 2 === 0 ? (
        <text key={i} x={x(i)} y={H - 8} fontSize="10" fill={MUTED} textAnchor="middle">{p.label}</text>
      ) : null))}
      <path d={line(rhPts)} fill="none" stroke={RH} strokeWidth={2} opacity={0.85} />
      <path d={line(tempPts)} fill="none" stroke={TEMP} strokeWidth={2.5} />
      <g fontSize="11">
        <circle cx={PADL} cy={6} r={4} fill={TEMP} /><text x={PADL + 8} y={9} fill={MUTED}>Temp °C</text>
        <circle cx={PADL + 78} cy={6} r={4} fill={RH} /><text x={PADL + 86} y={9} fill={MUTED}>Humidity %</text>
      </g>
    </svg>
  );
}

/** Aviagen Ross-308 target body weight across the grow-out, marker at today. */
export function GrowthCurve({
  points,
  currentDay,
}: {
  points: { day: number; weight_kg: number }[];
  currentDay: number;
}) {
  if (!points.length) return null;
  const ws = points.map((p) => p.weight_kg);
  const wmax = Math.max(...ws) * 1.05;
  const dmin = points[0].day;
  const dmax = points[points.length - 1].day;
  const x = (d: number) => PADL + ((d - dmin) / (dmax - dmin || 1)) * (W - PADL - PADR);
  const y = (w: number) => H - PADB - (w / (wmax || 1)) * (H - PADT - PADB);
  const curve: [number, number][] = points.map((p) => [x(p.day), y(p.weight_kg)]);
  const cur = points.find((p) => p.day === currentDay) ?? points[Math.min(currentDay, points.length - 1)];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }}>
      {[0, 0.25, 0.5, 0.75, 1].map((f, i) => {
        const yy = PADT + f * (H - PADT - PADB);
        const wv = (wmax - f * wmax).toFixed(1);
        return (
          <g key={i}>
            <line x1={PADL} y1={yy} x2={W - PADR} y2={yy} stroke={GRID} strokeWidth={1} />
            <text x={PADL - 6} y={yy + 4} fontSize="10" fill={MUTED} textAnchor="end">{wv}</text>
          </g>
        );
      })}
      {points.filter((p) => p.day % 7 === 0).map((p) => (
        <text key={p.day} x={x(p.day)} y={H - 8} fontSize="10" fill={MUTED} textAnchor="middle">{p.day}</text>
      ))}
      <text x={(PADL + W - PADR) / 2} y={H - 0.5} fontSize="10" fill={MUTED} textAnchor="middle">bird age (days)</text>
      <path d={line(curve)} fill="none" stroke={ACCENT} strokeWidth={2.5} />
      {cur && (
        <g>
          <line x1={x(cur.day)} y1={PADT} x2={x(cur.day)} y2={H - PADB} stroke={WARN} strokeWidth={1} strokeDasharray="4 3" />
          <circle cx={x(cur.day)} cy={y(cur.weight_kg)} r={4.5} fill={WARN} />
          <text x={Math.min(x(cur.day) + 8, W - PADR - 60)} y={y(cur.weight_kg) - 8} fontSize="11" fill="#e7edf3">
            day {cur.day}: {cur.weight_kg.toFixed(2)} kg
          </text>
        </g>
      )}
    </svg>
  );
}
