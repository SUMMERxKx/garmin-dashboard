from __future__ import annotations

from datetime import date

import pytest

from backend.core import energy
from backend.core.models import (
    Activity,
    ActivityKind,
    BalanceState,
    BmrFormula,
    Profile,
    Sex,
)
from backend.core.reasons import ReasonCode


def test_mifflin_st_jeor_matches_hand_calculation(profile: Profile) -> None:
    # 10*80 + 6.25*180 - 5*23 + 5 = 800 + 1125 - 115 + 5 = 1815
    result = energy.bmr(profile, 80.0, date(2026, 9, 3))
    assert result.kcal == pytest.approx(1815.0)
    assert result.formula is BmrFormula.MIFFLIN_ST_JEOR


def test_mifflin_female_offset() -> None:
    p = Profile(user_id="x", sex=Sex.FEMALE, birth_date=date(2003, 5, 1), height_cm=180.0)
    # same inputs, -161 instead of +5 -> 166 kcal lower
    assert energy.bmr(p, 80.0, date(2026, 9, 3)).kcal == pytest.approx(1649.0)


def test_katch_mcardle_used_when_lean_mass_known(profile: Profile) -> None:
    # 370 + 21.6 * 64.8 = 1769.68
    result = energy.bmr(profile, 80.0, date(2026, 9, 3), lean_mass_kg=64.8)
    assert result.kcal == pytest.approx(1769.68)
    assert result.formula is BmrFormula.KATCH_MCARDLE


def test_the_two_formulas_agree_within_a_few_percent(profile: Profile) -> None:
    """Not a coincidence -- the agreement is the sanity check that neither is wildly off."""
    mifflin = energy.bmr(profile, 80.0, date(2026, 9, 3)).kcal
    katch = energy.bmr(profile, 80.0, date(2026, 9, 3), lean_mass_kg=80.0 * 0.82).kcal
    assert abs(mifflin - katch) / mifflin < 0.03


def test_formula_choice_is_always_explained(profile: Profile) -> None:
    """A step change in the target must never be mysterious."""
    assert energy.bmr(profile, 80.0, date(2026, 9, 3)).reasons[0].code is ReasonCode.BMR_FORMULA_MIFFLIN_ST_JEOR
    assert energy.bmr(profile, 80.0, date(2026, 9, 3), lean_mass_kg=64.8).reasons[0].code is ReasonCode.BMR_FORMULA_KATCH_MCARDLE


def test_bmr_tracks_weight_not_a_stale_age(profile: Profile) -> None:
    """Birth date, not age: the same profile must give a lower BMR as he ages."""
    young = energy.bmr(profile, 80.0, date(2026, 9, 3)).kcal
    older = energy.bmr(profile, 80.0, date(2036, 9, 3)).kcal
    assert older == pytest.approx(young - 50.0)  # 10 years * 5 kcal


def test_tef_is_ten_percent() -> None:
    assert energy.tef(2350.0) == pytest.approx(235.0)


def test_tdee_sums_components() -> None:
    assert energy.tdee_estimate(1815.0, 617.0, 2350.0) == pytest.approx(1815 + 617 + 235)
    assert energy.tdee_estimate(1815.0, None, None) == pytest.approx(1815.0)


@pytest.mark.parametrize(
    ("burned", "consumed", "state"),
    [
        (2760.0, 2250.0, BalanceState.DEFICIT),
        (2400.0, 2650.0, BalanceState.SURPLUS),
        (2400.0, 2420.0, BalanceState.MAINTENANCE),
    ],
)
def test_balance_states(burned: float, consumed: float, state: BalanceState) -> None:
    result = energy.energy_balance(burned, consumed)
    assert result.state is state
    assert result.balance_kcal == pytest.approx(consumed - burned)


def test_rest_day_reads_as_maintenance_on_a_fixed_target() -> None:
    """A fixed 2350 target against a ~2400 rest-day TDEE is near maintenance, and the
    dashboard must say so rather than claiming a deficit."""
    assert energy.energy_balance(2400.0, 2350.0).state is BalanceState.MAINTENANCE


def test_resistance_training_caveat_is_surfaced() -> None:
    lifting = Activity(provider_id="1", kind=ActivityKind.RESISTANCE, type_raw="strength_training", duration_min=58.0)
    codes = [r.code for r in energy.energy_balance(2760.0, 2250.0, activities=[lifting]).reasons]
    assert ReasonCode.RESISTANCE_CALORIES_UNRELIABLE in codes


def test_no_caveat_for_a_run() -> None:
    run = Activity(provider_id="2", kind=ActivityKind.RUNNING, type_raw="running", duration_min=52.0)
    codes = [r.code for r in energy.energy_balance(3100.0, 2350.0, activities=[run]).reasons]
    assert ReasonCode.RESISTANCE_CALORIES_UNRELIABLE not in codes


def test_cumulative_balance_accumulates() -> None:
    assert energy.cumulative_balance([-500.0, -400.0, 100.0]) == [-500.0, -900.0, -800.0]
