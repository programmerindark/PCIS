// Shared types mirroring the Supabase schema and the PCIS API contract.

export type Farm = {
  id: string;
  name: string;
  location: string | null;
  latitude: number | null;
  longitude: number | null;
};

export type Insulation = "uninsulated" | "insulated" | "well_insulated";

export type House = {
  id: string;
  farm_id: string;
  name: string;
  length_m: number;
  width_m: number;
  height_m: number;
  insulation: Insulation;
  fan_index: number;
  installed_fans: number;
  static_pressure_pa: number;
  has_cooling_pads: boolean;
  heater_kw: number;
};

export type Flock = {
  id: string;
  house_id: string;
  name: string | null;
  strain: string;
  placement_date: string; // ISO date
  bird_count: number;
  active: boolean;
};

export type BirdStatus = {
  comfort_score: number;
  comfort_label: string;
  heat_stress_risk: string;
  effective_bird_temp_c: number | null;
  panting_index: string;
  water_intake_multiplier: number;
};

export type Comfort = {
  target_temp_c: number;
  deviation_c: number;
  thi: number;
  thi_class: string;
  comfort_index: number;
};

export type RecommendResponse = {
  fans_on: number;
  pads_on: boolean;
  governing_constraint: string;
  required_airflow_m3_per_h: number;
  air_speed_mps: number | null;
  target_airspeed_mps: number | null;
  effective_temp_c: number | null;
  vpd_kpa: number;
  heating_needed: boolean;
  heat_deficit_kw: number;
  target_unreachable: boolean;
  confidence_score: number;
  comfort: Comfort;
  bird_status: BirdStatus;
  explanation: string[];
  body_weight_kg: number;
};

export type CatalogFan = { index: number; label: string };
export type Catalog = {
  fans: CatalogFan[];
  pads: { index: number; label: string }[];
  insulation: { key: string; wall_u: number; ceiling_u: number }[];
};

export type ScheduleBlock = {
  start: string;
  end: string;
  hours: number;
  fans_on: number;
  pads_on: boolean;
  heating_needed: boolean;
};

export type ScheduleResponse = {
  blocks: ScheduleBlock[];
  peak_fans_on: number;
  fan_hours: number;
  heating_steps: number;
  shortfall_steps: number;
  unreachable_steps: number;
  notes: string[];
  body_weight_kg: number;
};

export type Severity = "info" | "warning" | "critical";
export type Alert = { severity: Severity; title: string; message: string };
