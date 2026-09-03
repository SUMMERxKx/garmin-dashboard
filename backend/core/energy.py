"""Energy: BMR, expenditure, and the balance that the whole product turns on."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from backend.core.models import (
    Activity,
    ActivityKind,
    BalanceResult,
    BalanceState,
    BmrFormula,
    BmrResult,
    Profile,
)
from backend.core.reasons import Reason, ReasonCode

#: |balance| within this many kcal reads as maintenance rather than a real deficit/surplus.
MAINTENANCE_BAND_KCAL = 100.0

#: Thermic effect of food, as a fraction of intake. Protein is highest; a flat 10% is a
#: fine approximation at a normal mixed diet.
TEF_FACTOR = 0.10


def bmr(
    profile: Profile,
    weight_kg: float,
    on: date,
    *,
    lean_mass_kg: float | None = None,
) -> BmrResult:
    """Basal metabolic rate, with the formula chosen by what data exists.

    Katch-McArdle when lean mass is known (more accurate, and sex-independent);
    Mifflin-St Jeor otherwise. The result records which formula ran and why -- a step
    change in the target must be explainable rather than mysterious.
    """
    if lean_mass_kg is not None:
        kcal = 370.0 + 21.6 * lean_mass_kg
        return BmrResult(
            kcal=kcal,
            formula=BmrFormula.KATCH_MCARDLE,
            reasons=[Reason(code=ReasonCode.BMR_FORMULA_KATCH_MCARDLE, metric="bmr", current=kcal)],
        )
    age = profile.age_on(on)
    offset = 5.0 if profile.sex == "male" else -161.0
    kcal = 10.0 * weight_kg + 6.25 * profile.height_cm - 5.0 * age + offset
    return BmrResult(
        kcal=kcal,
        formula=BmrFormula.MIFFLIN_ST_JEOR,
        reasons=[Reason(code=ReasonCode.BMR_FORMULA_MIFFLIN_ST_JEOR, metric="bmr", current=kcal)],
    )


def tef(consumed_kcal: float, factor: float = TEF_FACTOR) -> float:
    return consumed_kcal * factor


def tdee_estimate(
    bmr_kcal: float,
    active_kcal: float | None,
    consumed_kcal: float | None = None,
    *,
    include_tef: bool = True,
) -> float:
    """BMR + activity + TEF.

    NOTE: `active_kcal` from Garmin is heart-rate-derived and overstates resistance
    training -- HR stays elevated between sets without matching oxygen cost. Do NOT
    apply a fudge factor here; that would hide the bias. calibration.observed_maintenance
    measures it instead, by anchoring to actual weight trend.
    """
    total = bmr_kcal + (active_kcal or 0.0)
    if include_tef and consumed_kcal:
        total += tef(consumed_kcal)
    return total


def resistance_minutes(activities: Sequence[Activity]) -> float:
    return sum(
        a.duration_min or 0.0 for a in activities if a.kind is ActivityKind.RESISTANCE
    )


def energy_balance(
    burned_kcal: float,
    consumed_kcal: float,
    *,
    activities: Sequence[Activity] = (),
    maintenance_band_kcal: float = MAINTENANCE_BAND_KCAL,
) -> BalanceResult:
    """Consumed minus burned. Negative is a deficit.

    Surfaces the resistance-training caveat when relevant rather than hiding it: on
    push/pull/legs days the expenditure input is the least trustworthy number on screen.
    """
    balance = consumed_kcal - burned_kcal
    if balance < -maintenance_band_kcal:
        state, code = BalanceState.DEFICIT, ReasonCode.ENERGY_DEFICIT
    elif balance > maintenance_band_kcal:
        state, code = BalanceState.SURPLUS, ReasonCode.ENERGY_SURPLUS
    else:
        state, code = BalanceState.MAINTENANCE, ReasonCode.ENERGY_MAINTENANCE

    reasons = [
        Reason(
            code=code,
            metric="energy_balance",
            current=balance,
            unit="kcal",
            detail={
                "abs_balance": round(abs(balance)),
                "burned": round(burned_kcal),
                "consumed": round(consumed_kcal),
            },
        )
    ]
    lifting = resistance_minutes(activities)
    if lifting > 0:
        reasons.append(
            Reason(
                code=ReasonCode.RESISTANCE_CALORIES_UNRELIABLE,
                metric="active_kcal",
                detail={"minutes": round(lifting)},
            )
        )
    return BalanceResult(
        burned_kcal=burned_kcal,
        consumed_kcal=consumed_kcal,
        balance_kcal=balance,
        state=state,
        reasons=reasons,
    )


def cumulative_balance(balances: Sequence[float]) -> list[float]:
    total = 0.0
    out: list[float] = []
    for b in balances:
        total += b
        out.append(total)
    return out
