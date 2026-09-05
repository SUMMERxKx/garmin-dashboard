"""Things the system learns about you from your own data.

Both are OBSERVATIONS, never controls. They tell you what your body appears to be doing;
changing a target stays an explicit act by you. This matters especially because Garmin's
expenditure estimate runs high on resistance-training days -- the fix is not a fudge
factor in `energy.tdee_estimate`, it is measuring the bias here against actual weight
trend and reporting it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from datetime import timedelta

from backend.core import models
from backend.core import reasons
from backend.core import weight

#: Energy density of body fat. The standard approximation; genuinely mixed-tissue loss
#: runs lower, which is one reason the estimate below is reported with its inputs.
KCAL_PER_KG_FAT = 7700.0

MIN_DAYS = 28
MIN_WEIGH_INS = 12

#: Losing lean mass faster than this while cutting is worth flagging.
LEAN_LOSS_THRESHOLD_KG_PER_WEEK = 0.1

#: A logged deficit smaller than this is within the error of any calorie estimate, so
#: "flat weight despite a deficit" is not a meaningful observation below it.
MINIMUM_DEFICIT_WORTH_FLAGGING = 100.0


def observed_maintenance(
    intake: Sequence[tuple[date, float | None]],
    weights: Sequence[tuple[date, float]],
    on: date,
    *,
    window_days: int = 42,
    garmin_expenditure: Sequence[tuple[date, float | None]] | None = None,
    min_days: int = MIN_DAYS,
    min_weigh_ins: int = MIN_WEIGH_INS,
) -> models.MaintenanceEstimate | None:
    """What your maintenance calories appear to actually be.

        maintenance = mean_intake - weight_slope_kg_per_day * 7700

    Returns None on thin data rather than guessing: a maintenance figure derived from
    nine weigh-ins would be confidently wrong, and this number is meant to be trusted
    over Garmin's.
    """
    first_day_in_window = on - timedelta(days=window_days - 1)

    # Collect the days we have intake for.
    intake_values: list[float] = []
    for day, calories in intake:
        if calories is None:
            continue
        if first_day_in_window <= day <= on:
            intake_values.append(calories)

    # Collect the weigh-ins in the same window.
    weigh_ins: list[tuple[date, float]] = []
    for day, weight_kg in weights:
        if first_day_in_window <= day <= on:
            weigh_ins.append((day, weight_kg))

    # Refuse rather than guess. This number is meant to be trusted over Garmin's own
    # estimate, so producing one from nine weigh-ins would be worse than saying nothing.
    if len(intake_values) < min_days:
        return None
    if len(weigh_ins) < min_weigh_ins:
        return None

    result = weight.trend(weigh_ins, on, window_days=window_days)
    if result is None:
        return None

    mean_intake = sum(intake_values) / len(intake_values)
    maintenance = mean_intake - result.slope_per_day * KCAL_PER_KG_FAT

    # If we were given Garmin's own expenditure figures, compare against them. The gap
    # is the interesting part: it is how the device's overestimate of resistance
    # training becomes a measured number instead of an assumption.
    garmin_mean: float | None = None
    difference: float | None = None

    if garmin_expenditure:
        garmin_values: list[float] = []
        for day, calories in garmin_expenditure:
            if calories is None:
                continue
            if first_day_in_window <= day <= on:
                garmin_values.append(calories)

        if garmin_values:
            garmin_mean = sum(garmin_values) / len(garmin_values)
            difference = maintenance - garmin_mean

    return models.MaintenanceEstimate(
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
) -> reasons.Reason | None:
    """Weight flat while the logged balance says deficit.

    Usually means the intake or expenditure input is off rather than that physics broke --
    which is exactly the sort of thing worth surfacing instead of quietly averaging away.
    """
    result = weight.trend(weights, on, window_days=window_days)
    if result is None or abs(result.slope_per_week) >= flat_slope_kg_per_week:
        return None
    first_day_in_window = on - timedelta(days=window_days - 1)

    balances_in_window: list[float] = []
    for day, balance in balances:
        if balance is None:
            continue
        if first_day_in_window <= day <= on:
            balances_in_window.append(balance)

    if not balances_in_window:
        return None

    average = sum(balances_in_window) / len(balances_in_window)

    # Only worth flagging if there was a real deficit to begin with. A logged average
    # of -20 kcal is inside the noise of any calorie estimate.
    if average >= -MINIMUM_DEFICIT_WORTH_FLAGGING:
        return None
    return reasons.Reason(
        code=reasons.ReasonCode.WEIGHT_TREND_FLAT_DESPITE_DEFICIT,
        metric="weight_kg",
        window_days=window_days,
        n=len(balances_in_window),
        detail={"avg_deficit": round(abs(average)), "window": window_days},
    )


def lean_mass_guardrail(
    lean_masses: Sequence[tuple[date, float]],
    on: date,
    *,
    window_days: int = 28,
    threshold: float = LEAN_LOSS_THRESHOLD_KG_PER_WEEK,
) -> reasons.Reason | None:
    """Flag lean mass falling faster than the guideline.

    The point is not caution for its own sake: this is the failure mode scale weight
    hides completely, and it is the reason body composition is a first-class feature.
    """
    result = weight.trend(lean_masses, on, window_days=window_days)
    if result is None:
        return None

    # `slope_per_week` is negative when lean mass is falling, so a loss faster than the
    # threshold means the slope is BELOW minus-threshold.
    losing_faster_than_the_guideline = result.slope_per_week < -threshold
    if not losing_faster_than_the_guideline:
        return None

    if lean_masses:
        most_recent_lean_mass = lean_masses[-1][1]
    else:  # pragma: no cover - unreachable: `trend` already returned None if empty
        most_recent_lean_mass = None

    return reasons.Reason(
        code=reasons.ReasonCode.LEAN_MASS_LOSS_ELEVATED,
        metric="lean_mass_kg",
        current=most_recent_lean_mass,
        window_days=window_days,
        n=result.n,
        detail={"rate": round(abs(result.slope_per_week), 2), "threshold": threshold},
    )
