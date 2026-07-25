// Client for the PCIS engine API (FastAPI). Base URL comes from the
// environment so it points at localhost in dev and the deployed API in
// production. The engine is the ONLY source of climate numbers.

const BASE = process.env.NEXT_PUBLIC_PCIS_API_URL ?? "http://127.0.0.1:8000";

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

export function recommend(input: Record<string, unknown>) {
  return post<Record<string, any>>("/recommend", input);
}

export function schedule(input: Record<string, unknown>) {
  return post<Record<string, any>>("/schedule", input);
}
