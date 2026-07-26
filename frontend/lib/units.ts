"use client";

import { useEffect, useState } from "react";

// Display-unit preference. SI is ALWAYS what is stored in the database
// and sent to the engine; this only affects what the operator sees and
// types, matching the desktop app's rule.

export type UnitSystem = "metric" | "imperial";

const KEY = "pcis.units";
const M_PER_FT = 0.3048;

export function metresToDisplay(m: number, u: UnitSystem): number {
  return u === "imperial" ? m / M_PER_FT : m;
}
export function displayToMetres(v: number, u: UnitSystem): number {
  return u === "imperial" ? v * M_PER_FT : v;
}
export function lengthSuffix(u: UnitSystem): string {
  return u === "imperial" ? "ft" : "m";
}

export function cToDisplay(c: number, u: UnitSystem): number {
  return u === "imperial" ? c * 9 / 5 + 32 : c;
}
export function displayToC(v: number, u: UnitSystem): number {
  return u === "imperial" ? (v - 32) * 5 / 9 : v;
}
export function tempSuffix(u: UnitSystem): string {
  return u === "imperial" ? "°F" : "°C";
}

export function speedToDisplay(mps: number, u: UnitSystem): number {
  return u === "imperial" ? mps * 196.85 : mps;   // m/s -> ft/min
}
export function speedSuffix(u: UnitSystem): string {
  return u === "imperial" ? "ft/min" : "m/s";
}

/** Shared unit preference, persisted in localStorage and synced across
 *  components in the same tab via a custom event. */
export function useUnits(): [UnitSystem, (u: UnitSystem) => void] {
  const [units, setUnitsState] = useState<UnitSystem>("metric");

  useEffect(() => {
    const stored = (typeof window !== "undefined" && localStorage.getItem(KEY)) as UnitSystem | null;
    if (stored === "metric" || stored === "imperial") setUnitsState(stored);
    const onChange = (e: Event) => {
      const detail = (e as CustomEvent<UnitSystem>).detail;
      if (detail) setUnitsState(detail);
    };
    window.addEventListener("pcis-units", onChange);
    return () => window.removeEventListener("pcis-units", onChange);
  }, []);

  const setUnits = (u: UnitSystem) => {
    setUnitsState(u);
    try {
      localStorage.setItem(KEY, u);
      window.dispatchEvent(new CustomEvent("pcis-units", { detail: u }));
    } catch { /* storage unavailable */ }
  };

  return [units, setUnits];
}
