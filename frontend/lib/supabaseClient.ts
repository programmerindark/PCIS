"use client";

import { createClient } from "@supabase/supabase-js";

// Browser Supabase client (client-side auth for v1). The URL and anon
// key are public-safe values read from .env.local. Never put the
// service_role key here.
// Trimmed, because a value pasted into a hosting dashboard very often
// arrives with a trailing newline. A URL with "\n" on the end still looks
// correct in every UI that displays it, but the newline lands in the middle
// of the request line and in any header built from it. That is precisely
// what silently broke the sensor cron for two and a half days: it ran,
// returned 200, and wrote nothing.
const url = (process.env.NEXT_PUBLIC_SUPABASE_URL ?? "").trim();
const anonKey = (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "").trim();

if (!url || !anonKey) {
  // Helpful error during dev if .env.local isn't set up yet.
  // eslint-disable-next-line no-console
  console.warn(
    "Supabase env vars missing. Copy .env.local.example to .env.local and fill in your Project URL + anon key."
  );
}

export const supabase = createClient(url ?? "", anonKey ?? "");
