from __future__ import annotations

from datetime import timedelta

import pytest

from backend.core import calibration
from backend.core import reasons
from backend.tests import conftest


def weights(days: int, per_day: float, start: float = 80.0, every: int = 2) -> list[tuple]:
    return [
        (conftest.TODAY - timedelta(days=i), start + per_day * (days - 1 - i))
        for i in range(0, days, every)
    ]


def test_observed_maintenance_recovers_expenditure_from_intake_and_trend() -> None:
    """intake 2350/day while losing 0.35 kg/week implies maintenance ~2735."""
    intake = conftest.flat_series(2350.0, 42)
    result = calibration.observed_maintenance(intake, weights(42, -0.05), conftest.TODAY)
    assert result is not None
    assert result.kcal == pytest.approx(2735.0, abs=5.0)
    assert result.mean_intake_kcal == pytest.approx(2350.0)
    assert result.weight_slope_kg_per_week == pytest.approx(-0.35, abs=0.01)


def test_observed_maintenance_quantifies_the_garmin_overestimate() -> None:
    """This is how the resistance-training calorie bias becomes visible instead of
    being papered over with a fudge factor in tdee_estimate."""
    result = calibration.observed_maintenance(
        conftest.flat_series(2350.0, 42), weights(42, -0.05), conftest.TODAY,
        garmin_expenditure=conftest.flat_series(2900.0, 42),
    )
    assert result is not None
    assert result.difference_vs_garmin_kcal is not None
    assert result.difference_vs_garmin_kcal < -100  # Garmin runs high


def test_observed_maintenance_needs_enough_days() -> None:
    assert calibration.observed_maintenance(conftest.flat_series(2350.0, 10), weights(10, -0.05), conftest.TODAY) is None


def test_observed_maintenance_needs_enough_weigh_ins() -> None:
    """A maintenance figure from nine weigh-ins would be confidently wrong, and this
    number is meant to be trusted over Garmin's."""
    sparse = weights(42, -0.05, every=7)  # 6 weigh-ins
    assert calibration.observed_maintenance(conftest.flat_series(2350.0, 42), sparse, conftest.TODAY) is None


def test_observed_maintenance_with_no_data_at_all() -> None:
    assert calibration.observed_maintenance([], [], conftest.TODAY) is None


def test_flat_despite_deficit_is_flagged() -> None:
    flat = [(conftest.TODAY - timedelta(days=i), 79.0) for i in range(21)]
    reason = calibration.flat_despite_deficit(flat, conftest.flat_series(-450.0, 21), conftest.TODAY)
    assert reason is not None
    assert reason.code is reasons.ReasonCode.WEIGHT_TREND_FLAT_DESPITE_DEFICIT
    assert "450" in reason.render()


def test_not_flagged_when_weight_is_actually_falling() -> None:
    assert calibration.flat_despite_deficit(weights(21, -0.06, every=1), conftest.flat_series(-450.0, 21), conftest.TODAY) is None


def test_not_flagged_when_there_was_no_real_deficit() -> None:
    flat = [(conftest.TODAY - timedelta(days=i), 79.0) for i in range(21)]
    assert calibration.flat_despite_deficit(flat, conftest.flat_series(-20.0, 21), conftest.TODAY) is None


def test_lean_mass_guardrail_fires_on_elevated_loss() -> None:
    """The failure mode scale weight hides completely."""
    lean = [(conftest.TODAY - timedelta(days=i), 62.0 - 0.03 * (27 - i)) for i in range(28)]
    reason = calibration.lean_mass_guardrail(lean, conftest.TODAY)
    assert reason is not None
    assert reason.code is reasons.ReasonCode.LEAN_MASS_LOSS_ELEVATED
    assert "0.21" in reason.render()


def test_lean_mass_guardrail_quiet_when_lean_mass_holds() -> None:
    lean = [(conftest.TODAY - timedelta(days=i), 62.0) for i in range(28)]
    assert calibration.lean_mass_guardrail(lean, conftest.TODAY) is None


def test_lean_mass_guardrail_quiet_when_lean_mass_rises() -> None:
    lean = [(conftest.TODAY - timedelta(days=i), 62.0 + 0.02 * (27 - i)) for i in range(28)]
    assert calibration.lean_mass_guardrail(lean, conftest.TODAY) is None
