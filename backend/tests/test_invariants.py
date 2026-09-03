"""Property-based invariants: things that must hold for ANY input.

Table-driven tests check the cases I thought of. These check the ones I didn't.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.core import baselines, energy, nutrition, trends, weight
from backend.core.models import (
    BalanceState,
    Food,
    GoalType,
    MacroTarget,
    MacroTotals,
    Profile,
    ServingBasis,
    Sex,
)
from backend.core.units import kg_to_lb, lb_to_kg

TODAY = date(2026, 9, 3)

macros = st.builds(
    MacroTotals,
    kcal=st.floats(0, 10_000, allow_nan=False),
    protein_g=st.floats(0, 500, allow_nan=False),
    carbs_g=st.floats(0, 1000, allow_nan=False),
    fat_g=st.floats(0, 400, allow_nan=False),
)


@given(a=macros, b=macros)
def test_macro_addition_is_commutative(a: MacroTotals, b: MacroTotals) -> None:
    assert (a + b).kcal == pytest.approx((b + a).kcal)
    assert (a + b).protein_g == pytest.approx((b + a).protein_g)


@given(a=macros, b=macros, c=macros)
def test_macro_addition_is_associative(a: MacroTotals, b: MacroTotals, c: MacroTotals) -> None:
    assert ((a + b) + c).kcal == pytest.approx((a + (b + c)).kcal, rel=1e-9)


@given(a=macros)
def test_scaling_by_zero_empties(a: MacroTotals) -> None:
    assert a.scale(0.0).kcal == 0.0
    assert a.scale(0.0).protein_g == 0.0


@given(a=macros, f=st.floats(0.1, 10, allow_nan=False))
def test_scaling_is_linear(a: MacroTotals, f: float) -> None:
    assert a.scale(f).kcal == pytest.approx(a.kcal * f)


@given(
    consumed=macros,
    kcal=st.floats(1200, 4000, allow_nan=False),
    protein=st.floats(50, 300, allow_nan=False),
)
def test_remaining_always_reconstructs_the_target(
    consumed: MacroTotals, kcal: float, protein: float
) -> None:
    """The Nutrition screen shows consumed and remaining side by side; if they don't add
    back to the target, one of the two numbers on screen is lying."""
    target = MacroTarget(
        effective_from=TODAY, goal=GoalType.CUTTING,
        kcal=kcal, protein_g=protein, carbs_g=200.0, fat_g=60.0,
    )
    left = nutrition.remaining(consumed, target)
    assert consumed.kcal + left.kcal == pytest.approx(target.kcal, rel=1e-9)
    assert consumed.protein_g + left.protein_g == pytest.approx(target.protein_g, rel=1e-9)


@given(
    protein=st.floats(0, 400, allow_nan=False),
    carbs=st.floats(0, 800, allow_nan=False),
    fat=st.floats(0, 300, allow_nan=False),
)
def test_a_food_built_from_four_four_nine_always_validates(
    protein: float, carbs: float, fat: float
) -> None:
    food = Food(
        id="x", name="x", serving_desc="100 g", serving_basis=ServingBasis.AS_SOLD,
        kcal=nutrition.implied_kcal(protein, carbs, fat),
        protein_g=protein, carbs_g=carbs, fat_g=fat,
    )
    assert nutrition.validate_food(food) is True


@given(kg=st.floats(30, 250, allow_nan=False))
def test_weight_conversion_round_trips(kg: float) -> None:
    assert lb_to_kg(kg_to_lb(kg)) == pytest.approx(kg, rel=1e-12)


@given(
    burned=st.floats(800, 6000, allow_nan=False),
    consumed=st.floats(0, 6000, allow_nan=False),
)
def test_balance_sign_always_matches_its_state(burned: float, consumed: float) -> None:
    result = energy.energy_balance(burned, consumed)
    if result.state is BalanceState.DEFICIT:
        assert result.balance_kcal < 0
    elif result.state is BalanceState.SURPLUS:
        assert result.balance_kcal > 0
    assert result.balance_kcal == pytest.approx(consumed - burned)


@given(
    weight_kg=st.floats(40, 200, allow_nan=False),
    height_cm=st.floats(140, 220, allow_nan=False),
    sex=st.sampled_from(list(Sex)),
)
def test_bmr_is_always_a_plausible_positive_number(
    weight_kg: float, height_cm: float, sex: Sex
) -> None:
    profile = Profile(user_id="x", sex=sex, birth_date=date(2003, 5, 1), height_cm=height_cm)
    assert 400.0 < energy.bmr(profile, weight_kg, TODAY).kcal < 4000.0


@given(values=st.lists(st.floats(50, 120, allow_nan=False), min_size=1, max_size=60))
@settings(deadline=None)
def test_ema_never_leaves_the_observed_range(values: list[float]) -> None:
    """A smoothed weight outside the range of actual weigh-ins would be fabricated."""
    data = [(TODAY - timedelta(days=len(values) - 1 - i), v) for i, v in enumerate(values)]
    smoothed = [v for _, v in weight.ema(data)]
    assert min(values) - 1e-9 <= min(smoothed)
    assert max(smoothed) <= max(values) + 1e-9


@given(values=st.lists(st.floats(30, 90, allow_nan=False), min_size=0, max_size=40))
@settings(deadline=None)
def test_baseline_existence_depends_only_on_count(values: list[float]) -> None:
    """The None boundary must be exactly the documented minimum, never approximate."""
    data: list[tuple[date, float | None]] = [
        (TODAY - timedelta(days=len(values) - i), v) for i, v in enumerate(values)
    ]
    base = baselines.baseline(data, "hrv_ms", 30, TODAY)
    usable = len(baselines.window_values(data, TODAY, 30))
    assert (base is not None) == (usable >= baselines.default_min_n(30))


@given(n=st.integers(0, 29))
@settings(deadline=None)
def test_correlation_never_returns_below_its_minimum(n: int) -> None:
    a: list[tuple[date, float | None]] = [(TODAY - timedelta(days=i), float(i)) for i in range(n)]
    b: list[tuple[date, float | None]] = [(TODAY - timedelta(days=i), float(i) * 2) for i in range(n)]
    assert trends.correlation(a, b, "a", "b") is None
