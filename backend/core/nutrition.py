"""Nutrition: totals, dated targets, remaining, adherence.

Every number the Nutrition screen shows comes from here. No LLM involvement anywhere in
this module -- macro arithmetic is exactly the kind of thing code must own.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from backend.core import models
from backend.core import reasons

#: A label whose stated kcal misses 4/4/9 by more than this is rejected. The goal is
#: catching a misread decimal point (a 10x error), not policing label rounding.
KCAL_TOLERANCE_PCT = 0.10
KCAL_TOLERANCE_FLOOR = 15.0

#: Protein within this many grams of target counts as met.
PROTEIN_MET_TOLERANCE_G = 5.0

#: Calorie gaps smaller than this are not worth putting on screen.
CALORIE_GAP_WORTH_MENTIONING = 50.0


def implied_kcal(protein_g: float, carbs_g: float, fat_g: float) -> float:
    return protein_g * 4.0 + carbs_g * 4.0 + fat_g * 9.0


def validate_food(food: models.Food) -> bool:
    """kcal should reconcile with 4/4/9. Applies equally to typed entry and to anything
    extracted from a label by vision -- same guard catches a model misread and a typo."""
    expected = implied_kcal(food.protein_g, food.carbs_g, food.fat_g)
    tolerance = max(KCAL_TOLERANCE_FLOOR, expected * KCAL_TOLERANCE_PCT)
    return abs(food.kcal - expected) <= tolerance


def resolve_entry(food: models.Food, servings: float) -> models.MacroTotals:
    """servings x per-serving macros.

    The engine never converts between raw and cooked weight. A raw-basis food logged from
    a cooked weight is a data-entry error, not a math problem, and silent conversion would
    make it undetectable. `serving_basis` travels with the entry so the UI can show it.
    """
    return food.per_serving.scale(servings)


def day_totals(entries: Sequence[models.LogEntry]) -> models.MacroTotals:
    total = models.MacroTotals()
    for entry in entries:
        total = total + entry.macros_snapshot
    return total


def target_on(on: date, targets: Sequence[models.MacroTarget]) -> models.MacroTarget | None:
    """The target in force on a given day.

    Targets are append-only and effective-dated, so a dashboard for 15 August is scored
    against August's target rather than today's.
    """
    applicable = [t for t in targets if t.effective_from <= on]
    if not applicable:
        return None
    return max(applicable, key=lambda t: t.effective_from)


def remaining(totals: models.MacroTotals, target: models.MacroTarget) -> models.MacroTotals:
    """May be negative -- going over is information, not an error."""
    return models.MacroTotals(
        kcal=target.kcal - totals.kcal,
        protein_g=target.protein_g - totals.protein_g,
        carbs_g=target.carbs_g - totals.carbs_g,
        fat_g=target.fat_g - totals.fat_g,
    )


def adherence(totals: models.MacroTotals, target: models.MacroTarget, *, entry_count: int | None = None) -> models.AdherenceResult:
    def percent_of_target(consumed: float, goal: float) -> float:
        """How much of a target has been eaten, as a percentage.

        A target of zero would divide by zero, so that returns 0.0. No real target is
        zero, but guarding costs one line.
        """
        if goal == 0:
            return 0.0
        return (consumed / goal) * 100.0

    protein_met = totals.protein_g >= target.protein_g - PROTEIN_MET_TOLERANCE_G
    adherence_reasons: list[reasons.Reason] = []

    if entry_count == 0:
        adherence_reasons.append(reasons.Reason(code=reasons.ReasonCode.NO_FOOD_LOGGED, metric="nutrition"))
    elif protein_met:
        adherence_reasons.append(
            reasons.Reason(
                code=reasons.ReasonCode.PROTEIN_TARGET_MET,
                metric="protein_g",
                current=totals.protein_g,
                unit="g",
                detail={"target": round(target.protein_g)},
            )
        )
    else:
        adherence_reasons.append(
            reasons.Reason(
                code=reasons.ReasonCode.PROTEIN_UNDER_TARGET,
                metric="protein_g",
                current=totals.protein_g,
                unit="g",
                difference=totals.protein_g - target.protein_g,
                detail={"target": round(target.protein_g)},
            )
        )

    # Only mention calories when the gap is big enough to act on. Being 20 kcal off a
    # 2,350 target is not information, it is noise.
    kcal_diff = totals.kcal - target.kcal

    if abs(kcal_diff) > CALORIE_GAP_WORTH_MENTIONING:
        if kcal_diff > 0:
            calorie_code = reasons.ReasonCode.CALORIES_OVER_TARGET
        else:
            calorie_code = reasons.ReasonCode.CALORIES_UNDER_TARGET

        adherence_reasons.append(
            reasons.Reason(
                code=calorie_code,
                metric="kcal",
                current=totals.kcal,
                unit="kcal",
                difference=kcal_diff,
                detail={"target": round(target.kcal)},
            )
        )

    return models.AdherenceResult(
        kcal_percent=percent_of_target(totals.kcal, target.kcal),
        protein_percent=percent_of_target(totals.protein_g, target.protein_g),
        carbs_percent=percent_of_target(totals.carbs_g, target.carbs_g),
        fat_percent=percent_of_target(totals.fat_g, target.fat_g),
        protein_target_met=protein_met,
        reasons=adherence_reasons,
    )


def adherence_streak(
    days: Sequence[tuple[date, models.MacroTotals]],
    targets: Sequence[models.MacroTarget],
    *,
    metric: str = "protein_g",
) -> int:
    """Consecutive days ending at the most recent, meeting that day's own target."""
    streak = 0
    for _day, totals in sorted(days, key=lambda d: d[0], reverse=True):
        target = target_on(_day, targets)
        if target is None:
            break
        if metric == "protein_g":
            met = totals.protein_g >= target.protein_g - PROTEIN_MET_TOLERANCE_G
        else:  # pragma: no cover - only protein is used today
            met = getattr(totals, metric) >= getattr(target, metric)
        if not met:
            break
        streak += 1
    return streak
