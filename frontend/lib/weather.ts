// Weather via Open-Meteo (free, no API key, CORS-enabled) so the
// dashboard auto-fills outdoor conditions from the farm's location.

export type CurrentWx = { t_c: number; rh_pct: number };
export type WxPoint = { label: string; t_c: number; rh_pct: number };

const BASE = "https://api.open-meteo.com/v1/forecast";

export type Place = {
  name: string;
  admin1?: string;
  country?: string;
  latitude: number;
  longitude: number;
};

/** Search places by name (Open-Meteo geocoding — free, no key).
 *  Lets an operator set the FARM's location while away from it. */
export async function searchPlaces(query: string): Promise<Place[]> {
  const q = query.trim();
  if (q.length < 2) return [];
  const url = `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=6&language=en&format=json`;
  const r = await fetch(url);
  if (!r.ok) throw new Error("Place search failed");
  const j = await r.json();
  return (j.results ?? []).map((p: any) => ({
    name: p.name,
    admin1: p.admin1,
    country: p.country,
    latitude: p.latitude,
    longitude: p.longitude,
  }));
}

export async function getCurrentWeather(lat: number, lon: number): Promise<CurrentWx> {
  const url = `${BASE}?latitude=${lat}&longitude=${lon}&current=temperature_2m,relative_humidity_2m`;
  const r = await fetch(url);
  if (!r.ok) throw new Error("Weather lookup failed");
  const j = await r.json();
  return {
    t_c: Math.round(j.current.temperature_2m * 10) / 10,
    rh_pct: Math.round(j.current.relative_humidity_2m),
  };
}

// Today's outdoor curve, sampled every 3 hours, ready to feed /schedule.
export async function getTodayProfile(lat: number, lon: number): Promise<WxPoint[]> {
  const url =
    `${BASE}?latitude=${lat}&longitude=${lon}` +
    `&hourly=temperature_2m,relative_humidity_2m&forecast_days=1&timezone=auto`;
  const r = await fetch(url);
  if (!r.ok) throw new Error("Weather forecast failed");
  const j = await r.json();
  const times: string[] = j.hourly.time;
  const temps: number[] = j.hourly.temperature_2m;
  const rhs: number[] = j.hourly.relative_humidity_2m;
  const pts: WxPoint[] = [];
  for (let h = 0; h < 24 && h < times.length; h += 3) {
    pts.push({
      label: times[h].slice(11, 16), // "HH:MM"
      t_c: Math.round(temps[h] * 10) / 10,
      rh_pct: Math.round(rhs[h]),
    });
  }
  return pts;
}
