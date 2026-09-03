"""Things the system learns about you from your own data.

Both are OBSERVATIONS, never controls. They tell you what your body appears to be doing;
changing a target stays an explicit act by you. This matters especially because Garmin's
expenditure estimate runs high on resistance-training days -- the fix is not a fudge
factor in `energy.tdee_estimate`, it is measuring the bias here against actual weight
trend and reporting it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from backend.core.models import MaintenanceEstimate
from backend.core.reasons import Reason, ReasonCode
from backend.core.weight import trend

#: Energy density of body fat. The standard approximation; genuinely mixed-tissue loss
#: runs lower, which is one reason the estimate below is reported with its inputs.
KCAL_PER_KG_FAT = 7700.0

MIN_DAYS = 28
MIN_WEIGH_INS = 12

#: Losing lean mass faster than this while cutting is worth flagging.
LEAN_LOSS_THRESHOLD_KG_PER_WEEK = 0.1


def observed_maintenance(
    intake: Sequence[tuple[date, float | None]],
    weights: Sequence[tuple[date, float]],
    on: date,
    *,
    window_days: int = 42,
    garmin_expenditure: Sequence[tuple[date, float | None]] | None = None,
    min_days: int = MIN_DAYS,
    min_weigh_ins: int = MIN_WEIGH_INS,
) -> MaintenanceEstimate | None:
    """What your maintenance calories appear to actually be.

        maintenance = mean_intake - weight_slope_kg_per_day * 7700

    Returns None on thin data rather than guessing: a maintenance figure derived from
    nine weigh-ins would be confidently wrong, and this number is meant to be trusted
    over Garmin's.
    """
    start = on - timedelta(days=window_days - 1)
    intake_values = [v for d, v in intake if v is not None and start <= d <= on]
    weigh_ins = [(d, v) for d, v in weights if start <= d <= on]

    if len(intake_values) < min_days or len(weigh_ins) < min_weigh_ins:
        return None

    result = trend(weigh_ins, on, window_days=window_days)
    if result is None:
        return None

    mean_intake = sum(intake_values) / len(intake_values)
    maintenance = mean_intake - result.slope_per_day * KCAL_PER_KG_FAT

    garmin_mean: float | None = None
    difference: float | None = None
    if garmin_expenditure:
        garmin_values = [v for d, v in garmin_expenditure if v is not None and start <= d <= on]
        if garmin_values:
            garmin_mean = sum(garmin_values) / len(garmin_values)
            difference = maintenance - garmin_mean

    return MaintenanceEstimate(
        kcal=maintenance,
        days_used=len(intake_values),
        mean_intake_kcal=mean_intake,
        weight_slope_kg_per_week=result.slope_per_week,
        garmin_mean_expenditure_kcal=garmin_mean,
        difference_vs_garmin_kcal=difference,
        reasons=[],
    )


def flat_despite_deficit(
    weights: Sequence[tuple[date, float]],
    balances: Sequence[tuple[date, float | None]],
    on: date,
    *,
    window_days: int = 21,
    flat_slope_kg_per_week: float = 0.1,
) -> Reason | None:
    """Weight flat while the logged balance says deficit.

    Usually means the intake or expenditure input is off rather than that physics broke --
    which is exactly the sort of thing worth surfacing instead of quietly averaging away.
    """
    result = trend(weights, on, window_days=window_days)
    if result is None or abs(result.slope_per_week) >= flat_slope_kg_per_week:
        return None
    start = on - timedelta(days=window_days - 1)
    values = [v for d, v in balances if v is not None and start <= d <= on]
    if not values:
        return None
    average = sum(values) / len(values)
    if average >= -100.0:
        return None
    return Reason(
        code=ReasonCode.WEIGHT_TREND_FLAT_DESPITE_DEFICIT,
        metric="weight_kg",
        window_days=window_days,
        n=len(values),
        detail={"avg_deficit": round(abs(average)), "window": window_days},
    )


def lean_mass_guardrail(
    lean_masses: Sequence[tuple[date, float]],
    on: date,
    *,
    window_days: int = 28,
    threshold: float = LEAN_LOSS_THRESHOLD_KG_PER_WEEK,
) -> Reason | None:
    """Flag lean mass falling faster than the guideline.

    The point is not caution for its own sake: this is the failure mode scale weight
    hides completely, and it is the reason body composition is a first-class feature.
    """
    result = trend(lean_masses, on, window_days=window_days)
    if result is None or result.slope_per_week >= -threshold:
        return None
    return Reason(
        code=ReasonCode.LEAN_MASS_LOSS_ELEVATED,
        metric="lean_mass_kg",
        current=lean_masses[-1][1] if lean_masses else None,
        window_days=window_days,
        n=result.n,
        detail={"rate": round(abs(result.slope_per_week), 2), "threshold": threshold},
    )
