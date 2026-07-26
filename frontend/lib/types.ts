// Shared types mirroring the Supabase schema and the PCIS API contract.

export type Farm = {
  id: string;
  name: string;
  location: string | null;
  latitude: number | null;
  longitude: number | null;
  ecowitt_application_key?: string | null;
  ecowitt_api_key?: string | null;
  ecowitt_mac?: string | null;
  ecowitt_indoor_block?: string | null;
  ecowitt_gateway_ip?: string | null;
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

export type HouseMetrics = {
  stocking_density_kg_m2: number;
  density_limit_kg_m2: number;
  density_pct_of_limit: number;
  density_within_limit: boolean;
  estimated_co2_ppm: number | null;
  co2_within_guideline: boolean;
  air_changes_per_hour: number | null;
  airflow_per_bird_m3_h: number | null;
  note: string;
};

export type PredictedHumidity = {
  indoor_rh_pct: number;
  indoor_humidity_ratio_g_per_kg: number;
  supply_humidity_ratio_g_per_kg: number;
  moisture_added_g_per_kg: number;
  saturated: boolean;
  note: string;
};

export type CeilingOption = {
  ceiling_height_m: number;
  cross_section_m2: number;
  velocity_mps: number;
  velocity_fpm: number;
  meets_tunnel_target: boolean;
  windchill_effective: boolean;
};

export type TunnelGeometry = {
  current_velocity_mps: number;
  target_velocity_mps: number;
  meets_target: boolean;
  required_cross_section_m2: number;
  required_ceiling_height_m: number | null;
  current_ceiling_height_m: number | null;
  ceiling_drop_m: number | null;
  fans_needed_instead: number | null;
  note: string;
  options: CeilingOption[];
};

export type RecommendResponse = {
  house_metrics?: HouseMetrics;
  predicted_humidity?: PredictedHumidity | null;
  tunnel_geometry?: TunnelGeometry;
  fans_on: number;
  pads_on: boolean;
  governing_constraint: string;
  required_airflow_m3_per_h: number;
  air_speed_mps: number | null;
  target_airspeed_mps: number | null;
  effective_temp_c: number | null;
  vpd_kpa: number;
  achievable_indoor_t_c: number | null;
  felt_comfort_index: number | null;
  moisture_control_limited: boolean;
  /** Outdoor RH below which ventilation starts drying the house again. */
  outdoor_rh_for_drying_pct: number | null;
  /** Anemometer reading from inside the house, when a sensor supplies one. */
  measured_air_speed_mps: number | null;
  /** "agree" | "measured_lower" | "measured_higher" */
  air_speed_agreement: string | null;
  air_speed_divergence_pct: number | null;
  heating_needed: boolean;
  heat_deficit_kw: number;
  target_unreachable: boolean;
  /** Confidence in the METRICS (felt temp, comfort). */
  confidence_score: number;
  /** Confidence in the ACTION (how many fans to run) — usually higher. */
  action_confidence: number;
  action_basis: string;
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

export type ScheduleStep = {
  label: string;
  outdoor_t_c: number;
  outdoor_rh_pct: number;
  target_t_c: number;
  fans_on: number;
  air_speed_mps: number | null;
  effective_temp_c: number | null;
  vpd_kpa: number;
};

export type ScheduleResponse = {
  blocks: ScheduleBlock[];
  series?: ScheduleStep[];
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

export type MortalityResponse = {
  live_count: number;
  cumulative_dead: number;
  cumulative_pct: number;
  acceptable_pct: number;
  within_target: boolean;
  elevated_today: boolean;
  daily_pct: number;
  note: string;
};

export type AdviseResponse = {
  category: string;
  headline: string;
  detail: string;
  why: string;
  /** Confidence in the recommended ACTION — what the headline number means. */
  confidence: number;
  /** Confidence in the felt-temperature / comfort figures shown alongside. */
  metric_confidence: number;
  confidence_basis: string;
  feel_before_c: number | null;
  feel_after_c: number | null;
  panting_before: string;
  panting_after: string;
  comfort_score: number;
  heat_stress_risk: string;
};
