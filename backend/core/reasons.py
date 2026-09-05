"""Reason traces: the structured explanation behind every derived number.

Two consumers, one object:
  1. the UI's "Why?" affordance (Phase 4)
  2. the LLM analysis layer (Phase 7) -- its ONLY input

Because the trace is the LLM's only input, it cannot invent a reason that never fired.
Every code carries a templated English string, so the app is fully readable with the
LLM switched off.

Codes are a closed enum. Adding free-text reasons anywhere defeats the purpose.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel
from pydantic import ConfigDict


class ReasonCode(StrEnum):
    """Closed vocabulary. Never build a reason from a free-text string."""

    # --- recovery -----------------------------------------------------------
    SLEEP_BELOW_BASELINE = "SLEEP_BELOW_BASELINE"
    SLEEP_ABOVE_BASELINE = "SLEEP_ABOVE_BASELINE"
    SLEEP_SCORE_BELOW_BASELINE = "SLEEP_SCORE_BELOW_BASELINE"
    HRV_BELOW_BASELINE = "HRV_BELOW_BASELINE"
    HRV_ABOVE_BASELINE = "HRV_ABOVE_BASELINE"
    HRV_SUPPRESSED_CONSECUTIVE = "HRV_SUPPRESSED_CONSECUTIVE"
    RHR_ABOVE_BASELINE = "RHR_ABOVE_BASELINE"
    BODY_BATTERY_BELOW_BASELINE = "BODY_BATTERY_BELOW_BASELINE"
    STRESS_ABOVE_BASELINE = "STRESS_ABOVE_BASELINE"

    # --- energy -------------------------------------------------------------
    ENERGY_DEFICIT = "ENERGY_DEFICIT"
    ENERGY_MAINTENANCE = "ENERGY_MAINTENANCE"
    ENERGY_SURPLUS = "ENERGY_SURPLUS"
    EXPENDITURE_ABOVE_BASELINE = "EXPENDITURE_ABOVE_BASELINE"
    RESISTANCE_CALORIES_UNRELIABLE = "RESISTANCE_CALORIES_UNRELIABLE"

    # --- nutrition ----------------------------------------------------------
    PROTEIN_UNDER_TARGET = "PROTEIN_UNDER_TARGET"
    PROTEIN_TARGET_MET = "PROTEIN_TARGET_MET"
    CALORIES_UNDER_TARGET = "CALORIES_UNDER_TARGET"
    CALORIES_OVER_TARGET = "CALORIES_OVER_TARGET"
    NO_FOOD_LOGGED = "NO_FOOD_LOGGED"

    # --- weight / body ------------------------------------------------------
    WEIGHT_TREND_DOWN = "WEIGHT_TREND_DOWN"
    WEIGHT_TREND_UP = "WEIGHT_TREND_UP"
    WEIGHT_TREND_FLAT = "WEIGHT_TREND_FLAT"
    WEIGHT_TREND_FLAT_DESPITE_DEFICIT = "WEIGHT_TREND_FLAT_DESPITE_DEFICIT"
    PLATEAU_DETECTED = "PLATEAU_DETECTED"
    LIKELY_WATER_FLUCTUATION = "LIKELY_WATER_FLUCTUATION"
    LEAN_MASS_LOSS_ELEVATED = "LEAN_MASS_LOSS_ELEVATED"

    # --- formula / provenance ----------------------------------------------
    BMR_FORMULA_KATCH_MCARDLE = "BMR_FORMULA_KATCH_MCARDLE"
    BMR_FORMULA_MIFFLIN_ST_JEOR = "BMR_FORMULA_MIFFLIN_ST_JEOR"
    COMPOSITION_ESTIMATED = "COMPOSITION_ESTIMATED"
    COMPOSITION_MEASURED = "COMPOSITION_MEASURED"

    # --- data quality -------------------------------------------------------
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NO_WEIGH_IN = "NO_WEIGH_IN"
    METRIC_MISSING = "METRIC_MISSING"
    BASELINE_BUILDING = "BASELINE_BUILDING"


#: Templated English for every code. The app must be fully readable without the LLM.
TEMPLATES: dict[ReasonCode, str] = {
    ReasonCode.SLEEP_BELOW_BASELINE: "Sleep was {current} {unit}, {abs_pct}% below your {window}-day average of {baseline}.",
    ReasonCode.SLEEP_ABOVE_BASELINE: "Sleep was {current} {unit}, {abs_pct}% above your {window}-day average of {baseline}.",
    ReasonCode.SLEEP_SCORE_BELOW_BASELINE: "Sleep score was {current}, below your {window}-day average of {baseline}.",
    ReasonCode.HRV_BELOW_BASELINE: "HRV was {current} {unit}, {abs_pct}% below your {window}-day baseline of {baseline}.",
    ReasonCode.HRV_ABOVE_BASELINE: "HRV was {current} {unit}, {abs_pct}% above your {window}-day baseline of {baseline}.",
    ReasonCode.HRV_SUPPRESSED_CONSECUTIVE: "HRV has been below baseline for {consecutive_days} consecutive days.",
    ReasonCode.RHR_ABOVE_BASELINE: "Resting heart rate was {current} {unit}, {difference} above your baseline of {baseline}.",
    ReasonCode.BODY_BATTERY_BELOW_BASELINE: "Body Battery was {current}, {abs_pct}% below your {window}-day average of {baseline}.",
    ReasonCode.STRESS_ABOVE_BASELINE: "Average stress was {current}, above your {window}-day average of {baseline}.",
    ReasonCode.ENERGY_DEFICIT: "You are in an estimated {abs_balance} kcal deficit ({consumed} eaten against {burned} burned).",
    ReasonCode.ENERGY_MAINTENANCE: "You are close to maintenance ({consumed} eaten against {burned} burned).",
    ReasonCode.ENERGY_SURPLUS: "You are in an estimated {abs_balance} kcal surplus ({consumed} eaten against {burned} burned).",
    ReasonCode.EXPENDITURE_ABOVE_BASELINE: "Expenditure was {current} kcal, {abs_pct}% above your {window}-day average.",
    ReasonCode.RESISTANCE_CALORIES_UNRELIABLE: "Expenditure includes {minutes} min of resistance training, where Garmin's heart-rate-based estimate tends to run high.",
    ReasonCode.PROTEIN_UNDER_TARGET: "Protein is {difference} g below your target of {target} g.",
    ReasonCode.PROTEIN_TARGET_MET: "Protein target met ({current} g of {target} g).",
    ReasonCode.CALORIES_UNDER_TARGET: "Calories are {difference} kcal below your target of {target}.",
    ReasonCode.CALORIES_OVER_TARGET: "Calories are {difference} kcal above your target of {target}.",
    ReasonCode.NO_FOOD_LOGGED: "No food logged for this day.",
    ReasonCode.WEIGHT_TREND_DOWN: "Weight trend is down {rate} kg/week over the last {window} days.",
    ReasonCode.WEIGHT_TREND_UP: "Weight trend is +{rate} kg/week over the last {window} days.",
    ReasonCode.WEIGHT_TREND_FLAT: "Weight trend is flat over the last {window} days.",
    ReasonCode.WEIGHT_TREND_FLAT_DESPITE_DEFICIT: "Weight has been flat for {window} days despite an average deficit of {avg_deficit} kcal/day.",
    ReasonCode.PLATEAU_DETECTED: "Weight has been flat with low variation for {window} days -- this looks like a real plateau rather than water fluctuation.",
    ReasonCode.LIKELY_WATER_FLUCTUATION: "Day-to-day variation is high, so this change is more likely water than tissue.",
    ReasonCode.LEAN_MASS_LOSS_ELEVATED: "Estimated lean mass is falling at {rate} kg/week, faster than the {threshold} kg/week guideline.",
    ReasonCode.BMR_FORMULA_KATCH_MCARDLE: "BMR estimated with Katch-McArdle, because lean body mass is known from a DEXA scan.",
    ReasonCode.BMR_FORMULA_MIFFLIN_ST_JEOR: "BMR estimated with Mifflin-St Jeor, because no body-composition measurement is available.",
    ReasonCode.COMPOSITION_ESTIMATED: "Body composition is an estimate, projected from your {anchor_date} scan using a fat/lean split of {p_fat}.",
    ReasonCode.COMPOSITION_MEASURED: "Body composition is measured, from the DEXA scan on {anchor_date}.",
    ReasonCode.INSUFFICIENT_DATA: "Not enough data to compute {metric} ({n} of {required} readings).",
    ReasonCode.NO_WEIGH_IN: "No weigh-in recorded for this day.",
    ReasonCode.METRIC_MISSING: "{metric} was not reported -- the watch may not have been worn.",
    ReasonCode.BASELINE_BUILDING: "Still building your {metric} baseline ({n} of {required} days).",
}


class Reason(BaseModel):
    """One structured explanation. Carries its own numbers so nothing downstream recomputes."""

    model_config = ConfigDict(frozen=True)

    code: ReasonCode
    metric: str | None = None
    current: float | None = None
    baseline: float | None = None
    unit: str | None = None
    difference: float | None = None
    difference_percent: float | None = None
    window_days: int | None = None
    n: int | None = None
    #: Extra structured context for codes that need it (target, consecutive_days, p_fat, ...).
    detail: dict[str, float | int | str] = {}

    def render(self) -> str:
        """Turn this reason into a plain English sentence.

        Uses the template table above -- no LLM involved. The app has to be completely
        readable with the AI layer switched off; the AI's job later is to write it
        *better*, never to make it possible.
        """
        template = TEMPLATES.get(self.code)

        # Every code is supposed to have a template, and a test enforces that. This is
        # only a safety net so a missing one degrades to a readable code rather than
        # crashing the dashboard.
        if template is None:  # pragma: no cover - guarded by test_every_code_has_a_template
            return self.code.value

        # Build the values the template can refer to by name. Anything missing becomes
        # an empty string rather than the word "None" appearing in a sentence.
        values: dict[str, object] = {}

        values["metric"] = self.metric or "this metric"
        values["unit"] = self.unit or ""
        values["current"] = format_number(self.current)
        values["baseline"] = format_number(self.baseline)
        values["difference_percent"] = format_number(self.difference_percent)

        # Differences are stored with a sign, because the direction matters elsewhere.
        # But the templates already say "below" or "above" in words, so they want the
        # size without the sign -- otherwise you get "11% below" rendered as "-11% below".
        if self.difference is None:
            values["difference"] = ""
        else:
            values["difference"] = format_number(abs(self.difference))

        if self.difference_percent is None:
            values["abs_pct"] = ""
        else:
            values["abs_pct"] = format_number(abs(self.difference_percent))

        if self.window_days is None:
            values["window"] = ""
        else:
            values["window"] = self.window_days

        if self.n is None:
            values["n"] = ""
        else:
            values["n"] = self.n

        # `detail` carries the extras that only some codes need, such as a target value
        # or a number of consecutive days. It is applied last so a code can override a
        # standard field if it needs to.
        values.update(self.detail)

        try:
            return template.format(**values)
        except KeyError:  # pragma: no cover - guarded by test_every_template_renders
            # A template asked for a placeholder nobody supplied. A test covers this
            # for every code, so reaching here means a template was just edited.
            return self.code.value


def format_number(value: float | None) -> str:
    """Format a number for a sentence, without floating-point noise.

    Two things this fixes:

      52.20000000000001  ->  "52.2"    (rounded to one decimal place)
      47.0               ->  "47"      (a whole number does not need ".0")

    The second one matters more than it looks: "HRV was 47 ms" reads like something a
    person wrote, and "HRV was 47.0 ms" reads like something a machine printed.
    """
    if value is None:
        return ""

    rounded = round(value, 1)

    # `rounded == int(rounded)` is true for whole numbers like 47.0 but not for 52.2.
    if rounded == int(rounded):
        return str(int(rounded))

    return str(rounded)
