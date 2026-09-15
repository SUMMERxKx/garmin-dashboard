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
  days: Day[];
};
