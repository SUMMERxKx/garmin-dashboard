/**
 * The wire format, mirrored in TypeScript.
 *
 * This is the other half of `backend/api/dashboard_json.py`. That module's docstring is
 * the contract; this file is the same contract expressed so the compiler can check it.
 *
 * Two rules from that docstring matter most when reading these types:
 *
 *   - `| null` is everywhere on purpose. A null means "no reading", NOT zero. A night
 *     with no HRV and a night with an HRV of zero are different facts, and averaging
 *     them together is how a dashboard quietly starts lying.
 *   - Numbers arrive raw and unformatted. Turning 412.5 into "6h 52m" is this app's
 *     job, done at the point of display.
 */

export type Energy = {
  total_kilocalories: number | null;
  active_kilocalories: number | null;
  resting_kilocalories: number | null;
  steps: number | null;
  distance_metres: number | null;
  moderate_intensity_minutes: number | null;
  vigorous_intensity_minutes: number | null;
};

export type Sleep = {
  total_minutes: number | null;
  score: number | null;
  deep_minutes: number | null;
  light_minutes: number | null;
  rem_minutes: number | null;
  awake_minutes: number | null;
};

export type Recovery = {
  hrv_last_night: number | null;
  hrv_weekly_average: number | null;
  hrv_baseline: number | null;
  resting_heart_rate: number | null;
  body_battery_charged: number | null;
  body_battery_drained: number | null;
  average_stress: number | null;
};

export type Body = {
  /** Garmin's own reading. Deliberately NOT called `weight_kilograms`: it is not a weigh-in. */
  garmin_weight_kilograms: number | null;
};

export type Weighing = {
  kilograms: number;
  recorded_at: string | null;
  source: string;
  /**
   * The scale's own body-fat estimate, if it gave one. NOT the same measurement as a
   * DEXA percentage: a scale infers composition from electrical resistance and moves
   * with hydration, so it is useful for its trend and not for its absolute value.
   */
  fat_percent: number | null;
};

export type Scan = {
  scan_date: string;
  provider: string | null;
  total_mass_kilograms: number | null;
  fat_mass_kilograms: number | null;
  lean_and_bone_kilograms: number | null;
  fat_percent: number | null;
  visceral_fat_grams: number | null;
  bone_mineral_density: number | null;
  bmd_t_score: number | null;
  bmd_z_score: number | null;
};

export type MacroTarget = {
  effective_from: string;
  goal: string;
  kilocalories: number;
  protein_grams: number;
  carbohydrate_grams: number;
  fat_grams: number;
};

export type Profile = {
  height_centimetres: number | null;
  birth_date: string | null;
};

export type FoodEntry = {
  food_id: string;
  food_name: string;
  servings: number;
  serving_basis: string;
  kilocalories: number;
  protein_grams: number;
  carbohydrate_grams: number;
  fat_grams: number;
  logged_at: string | null;
  meal_id: string | null;
};

export type FoodTotals = {
  kilocalories: number;
  protein_grams: number;
  carbohydrate_grams: number;
  fat_grams: number;
};

export type Food = {
  totals: FoodTotals;
  entries: FoodEntry[];
};

export type Activity = {
  name: string | null;
  type_key: string | null;
  started_at_local: string | null;
  duration_minutes: number | null;
  distance_metres: number | null;
  total_kilocalories: number | null;
  resting_kilocalories: number | null;
  /** Derived, not measured: total minus what resting would have cost anyway. */
  active_kilocalories: number | null;
  average_heart_rate: number | null;
  maximum_heart_rate: number | null;
  steps: number | null;
  aerobic_training_effect: number | null;
  anaerobic_training_effect: number | null;
};

/**
 * The one number a day's eating is scored on, and where it came from.
 *
 * `source` is the whole point of this block. "logged" is the food log's sum, "manual"
 * is a total typed in as one number, and "carried" is a figure inherited from the last
 * day that had one -- an assumption, not a measurement, and drawn differently for it.
 * `from_day` is the day the figure was actually recorded on.
 */
export type Intake = {
  kilocalories: number;
  source: "logged" | "manual" | "carried";
  from_day: string;
};

/** What normal looks like for one metric over one window, computed in Python. */
export type Baseline = {
  window_days: number;
  mean: number;
  standard_deviation: number;
  sample_size: number;
  oldest_day: string;
  newest_day: string;
};

export type MetricSummary = {
  latest_day: string | null;
  latest_value: number | null;
  /** Null when there were not enough readings to build one honestly. */
  window_7: Baseline | null;
  window_30: Baseline | null;
  /** "above", "below", "typical" -- or null. Positional, never good or bad. */
  position_vs_30: "above" | "below" | "typical" | null;
};

export type Baselines = {
  /** The last day with Garmin data; every window ends here. */
  as_of: string | null;
  metrics: Record<string, MetricSummary>;
};

export type Day = {
  /** ISO date, "2026-09-14". */
  day: string;
  energy: Energy;
  sleep: Sleep;
  recovery: Recovery;
  body: Body;
  /** The morning weigh-in, or null if there was not one. Never carried forward. */
  weight: Weighing | null;
  /** Null means the log was not kept that day -- not that nothing was eaten. */
  food: Food | null;
  /** The resolved calorie figure for the day. Null only before the first recorded day. */
  intake: Intake | null;
  /** Empty on a rest day. */
  activities: Activity[];
  /** How many Garmin fields this day actually has values for. 0 means nothing fetched yet. */
  fields_found: number;
};

export type DaysPayload = {
  schema_version: number;
  generated_at: string;
  first_day: string | null;
  last_day: string | null;
  /** Newest DEXA scan, or null. Not a daily reading -- it belongs to its own date. */
  latest_scan: Scan | null;
  /** The macro target in force on the last day of the span. */
  macro_target: MacroTarget | null;
  profile: Profile | null;
  /** Personal baselines for every metric on the dashboard. Absent from older exports. */
  baselines: Baselines | null;
  days: Day[];
};

/** Where the payload came from. The Log page can only write when it is the API. */
export type DataSource = "api" | "file";
