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

from pydantic import BaseModel, ConfigDict


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
    ReasonCode.WEIGHT_TREND_DOWN: "Weight trend is {rate} kg/week over the last {window} days.",
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
        """Templated English. Never call an LLM to produce baseline readability."""
        template = TEMPLATES.get(self.code)
        if template is None:  # pragma: no cover - guarded by test_all_codes_have_templates
            return self.code.value
        values: dict[str, object] = {
            "metric": self.metric or "this metric",
            "current": _fmt(self.current),
            "baseline": _fmt(self.baseline),
            "unit": self.unit or "",
            "difference": _fmt(abs(self.difference)) if self.difference is not None else "",
            "difference_percent": _fmt(self.difference_percent),
            "abs_pct": _fmt(abs(self.difference_percent)) if self.difference_percent is not None else "",
            "window": self.window_days if self.window_days is not None else "",
            "n": self.n if self.n is not None else "",
        }
        values.update(self.detail)
        try:
            return template.format(**values)
        except KeyError:  # pragma: no cover - guarded by test_templates_render
            return self.code.value


def _fmt(value: float | None) -> str:
    """Render a number without trailing noise: 6.4 not 6.400000000000001."""
    if value is None:
        return ""
    rounded = round(value, 1)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded)
