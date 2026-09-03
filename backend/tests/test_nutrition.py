from __future__ import annotations

from datetime import date

import pytest

from backend.core import nutrition
from backend.core.models import Food, GoalType, MacroTarget, MacroTotals, ServingBasis
from backend.core.reasons import ReasonCode
from backend.tests.conftest import make_entry


def test_implied_kcal_matches_the_real_target() -> None:
    # 180*4 + 260*4 + 65*9 = 720 + 1040 + 585 = 2345
    assert nutrition.implied_kcal(180.0, 260.0, 65.0) == pytest.approx(2345.0)


def test_the_real_target_is_internally_consistent(target: MacroTarget) -> None:
    assert abs(target.implied_kcal - target.kcal) < 10.0


def test_resolve_entry_scales_by_servings(chicken: Food) -> None:
    totals = nutrition.resolve_entry(chicken, 2.0)  # ~200 g
    assert totals.kcal == pytest.approx(330.0)
    assert totals.protein_g == pytest.approx(62.0)


def test_day_totals_sums_snapshots(chicken: Food) -> None:
    entries = [make_entry(date(2026, 9, 3), chicken, 2.0), make_entry(date(2026, 9, 3), chicken, 1.5)]
    assert nutrition.day_totals(entries).protein_g == pytest.approx(31.0 * 3.5)


def test_day_totals_of_nothing_is_zero_not_an_error() -> None:
    assert nutrition.day_totals([]).kcal == 0.0


def test_editing_a_food_cannot_rewrite_history(chicken: Food) -> None:
    """macros_snapshot is denormalised on write, so last month's dashboard stays true."""
    entry = make_entry(date(2026, 8, 1), chicken, 2.0)
    before = entry.macros_snapshot.protein_g
    chicken.protein_g = 99.0  # label corrected later
    assert entry.macros_snapshot.protein_g == before


def test_target_on_uses_the_target_in_force_that_day() -> None:
    august = MacroTarget(effective_from=date(2026, 8, 1), goal=GoalType.CUTTING,
                         kcal=2400.0, protein_g=180.0, carbs_g=260.0, fat_g=70.0)
    september = MacroTarget(effective_from=date(2026, 9, 3), goal=GoalType.CUTTING,
                            kcal=2350.0, protein_g=180.0, carbs_g=260.0, fat_g=65.0)
    targets = [september, august]  # deliberately unsorted
    assert nutrition.target_on(date(2026, 8, 15), targets) is august
    assert nutrition.target_on(date(2026, 9, 4), targets) is september
    assert nutrition.target_on(date(2026, 9, 3), targets) is september  # boundary is inclusive
    assert nutrition.target_on(date(2026, 7, 1), targets) is None  # before any target existed


def test_remaining_can_go_negative(target: MacroTarget) -> None:
    """Going over is information, not an error."""
    over = MacroTotals(kcal=2500.0, protein_g=200.0, carbs_g=280.0, fat_g=70.0)
    assert nutrition.remaining(over, target).kcal == pytest.approx(-150.0)


def test_remaining_plus_consumed_equals_target(target: MacroTarget) -> None:
    totals = MacroTotals(kcal=1930.0, protein_g=151.0, carbs_g=214.0, fat_g=61.0)
    left = nutrition.remaining(totals, target)
    assert totals.kcal + left.kcal == pytest.approx(target.kcal)
    assert totals.protein_g + left.protein_g == pytest.approx(target.protein_g)


def test_adherence_flags_protein_shortfall(target: MacroTarget) -> None:
    totals = MacroTotals(kcal=2140.0, protein_g=151.0, carbs_g=230.0, fat_g=68.0)
    result = nutrition.adherence(totals, target, entry_count=4)
    assert result.protein_target_met is False
    assert result.protein_percent == pytest.approx(151 / 180 * 100)
    codes = [r.code for r in result.reasons]
    assert ReasonCode.PROTEIN_UNDER_TARGET in codes
    assert ReasonCode.CALORIES_UNDER_TARGET in codes


def test_protein_met_within_tolerance(target: MacroTarget) -> None:
    totals = MacroTotals(kcal=2350.0, protein_g=176.0, carbs_g=260.0, fat_g=65.0)
    assert nutrition.adherence(totals, target).protein_target_met is True


def test_no_food_logged_is_its_own_reason(target: MacroTarget) -> None:
    result = nutrition.adherence(MacroTotals(), target, entry_count=0)
    assert next(r.code for r in result.reasons) is ReasonCode.NO_FOOD_LOGGED


def test_validate_food_accepts_a_real_label(chicken: Food) -> None:
    assert nutrition.validate_food(chicken) is True


def test_validate_food_catches_a_misplaced_decimal(chicken: Food) -> None:
    """The guard exists to catch 10x errors from a vision misread or a typo."""
    chicken.kcal = 1650.0
    assert nutrition.validate_food(chicken) is False


def test_serving_basis_travels_with_the_entry(chicken: Food) -> None:
    """The engine never converts raw<->cooked; the basis must survive to the UI."""
    entry = make_entry(date(2026, 9, 3), chicken, 2.0)
    assert entry.serving_basis is ServingBasis.RAW


def test_adherence_streak_uses_each_days_own_target() -> None:
    targets = [MacroTarget(effective_from=date(2026, 9, 1), goal=GoalType.CUTTING,
                           kcal=2350.0, protein_g=180.0, carbs_g=260.0, fat_g=65.0)]
    days = [
        (date(2026, 9, 1), MacroTotals(protein_g=185.0)),
        (date(2026, 9, 2), MacroTotals(protein_g=178.0)),  # within 5 g tolerance
        (date(2026, 9, 3), MacroTotals(protein_g=181.0)),
    ]
    assert nutrition.adherence_streak(days, targets) == 3

    days[1] = (date(2026, 9, 2), MacroTotals(protein_g=150.0))
    assert nutrition.adherence_streak(days, targets) == 1  # streak breaks going back
