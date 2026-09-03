"""Nutrition: totals, dated targets, remaining, adherence.

Every number the Nutrition screen shows comes from here. No LLM involvement anywhere in
this module -- macro arithmetic is exactly the kind of thing code must own.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from backend.core.models import (
    AdherenceResult,
    Food,
    LogEntry,
    MacroTarget,
    MacroTotals,
)
from backend.core.reasons import Reason, ReasonCode

#: A label whose stated kcal misses 4/4/9 by more than this is rejected. The goal is
#: catching a misread decimal point (a 10x error), not policing label rounding.
KCAL_TOLERANCE_PCT = 0.10
KCAL_TOLERANCE_FLOOR = 15.0

#: Protein within this many grams of target counts as met.
PROTEIN_MET_TOLERANCE_G = 5.0


def implied_kcal(protein_g: float, carbs_g: float, fat_g: float) -> float:
    return protein_g * 4.0 + carbs_g * 4.0 + fat_g * 9.0


def validate_food(food: Food) -> bool:
    """kcal should reconcile with 4/4/9. Applies equally to typed entry and to anything
    extracted from a label by vision -- same guard catches a model misread and a typo."""
    expected = implied_kcal(food.protein_g, food.carbs_g, food.fat_g)
    tolerance = max(KCAL_TOLERANCE_FLOOR, expected * KCAL_TOLERANCE_PCT)
    return abs(food.kcal - expected) <= tolerance


def resolve_entry(food: Food, servings: float) -> MacroTotals:
    """servings x per-serving macros.

    The engine never converts between raw and cooked weight. A raw-basis food logged from
    a cooked weight is a data-entry error, not a math problem, and silent conversion would
    make it undetectable. `serving_basis` travels with the entry so the UI can show it.
    """
    return food.per_serving.scale(servings)


def day_totals(entries: Sequence[LogEntry]) -> MacroTotals:
    total = MacroTotals()
    for entry in entries:
        total = total + entry.macros_snapshot
    return total


def target_on(on: date, targets: Sequence[MacroTarget]) -> MacroTarget | None:
    """The target in force on a given day.

    Targets are append-only and effective-dated, so a dashboard for 15 August is scored
    against August's target rather than today's.
    """
    applicable = [t for t in targets if t.effective_from <= on]
    if not applicable:
        return None
    return max(applicable, key=lambda t: t.effective_from)


def remaining(totals: MacroTotals, target: MacroTarget) -> MacroTotals:
    """May be negative -- going over is information, not an error."""
    return MacroTotals(
        kcal=target.kcal - totals.kcal,
        protein_g=target.protein_g - totals.protein_g,
        carbs_g=target.carbs_g - totals.carbs_g,
        fat_g=target.fat_g - totals.fat_g,
    )


def adherence(totals: MacroTotals, target: MacroTarget, *, entry_count: int | None = None) -> AdherenceResult:
    def pct(consumed: float, goal: float) -> float:
        return (consumed / goal * 100.0) if goal else 0.0

    protein_met = totals.protein_g >= target.protein_g - PROTEIN_MET_TOLERANCE_G
    reasons: list[Reason] = []

    if entry_count == 0:
        reasons.append(Reason(code=ReasonCode.NO_FOOD_LOGGED, metric="nutrition"))
    elif protein_met:
        reasons.append(
            Reason(
                code=ReasonCode.PROTEIN_TARGET_MET,
                metric="protein_g",
                current=totals.protein_g,
                unit="g",
                detail={"target": round(target.protein_g)},
            )
        )
    else:
        reasons.append(
            Reason(
                code=ReasonCode.PROTEIN_UNDER_TARGET,
                metric="protein_g",
                current=totals.protein_g,
                unit="g",
                difference=totals.protein_g - target.protein_g,
                detail={"target": round(target.protein_g)},
            )
        )

    kcal_diff = totals.kcal - target.kcal
    if abs(kcal_diff) > 50:
        reasons.append(
            Reason(
                code=ReasonCode.CALORIES_OVER_TARGET if kcal_diff > 0 else ReasonCode.CALORIES_UNDER_TARGET,
                metric="kcal",
                current=totals.kcal,
                unit="kcal",
                difference=kcal_diff,
                detail={"target": round(target.kcal)},
            )
        )

    return AdherenceResult(
        kcal_percent=pct(totals.kcal, target.kcal),
        protein_percent=pct(totals.protein_g, target.protein_g),
        carbs_percent=pct(totals.carbs_g, target.carbs_g),
        fat_percent=pct(totals.fat_g, target.fat_g),
        protein_target_met=protein_met,
        reasons=reasons,
    )


def adherence_streak(
    days: Sequence[tuple[date, MacroTotals]],
    targets: Sequence[MacroTarget],
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
