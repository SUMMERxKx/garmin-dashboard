"""Every function's answer to "I don't have that".

This is where health dashboards actually break: the watch was on the charger, the weigh-in
was skipped, the user is three days old, there is no DEXA. None of it is an error state,
and none of it may produce a fabricated number.
"""

from __future__ import annotations

from datetime import date

from backend.core import (
    baselines,
    body_composition,
    calibration,
    energy,
    nutrition,
    recovery,
    trends,
    weight,
)
from backend.core.models import (
    BalanceState,
    DailyHealthSnapshot,
    MacroTotals,
    Status,
)
from backend.tests.conftest import TODAY, flat_series


def test_an_empty_snapshot_is_valid() -> None:
    """A watch left on the charger is a normal Tuesday, not an exception."""
    snapshot = DailyHealthSnapshot(date=TODAY)
    assert snapshot.measured.energy.total_kcal is None
    assert snapshot.measured.sleep.has_stages is False
    assert snapshot.nutrition.entry_count == 0
    assert snapshot.derived.recovery_status is None


def test_no_food_logged_gives_zero_totals_not_an_error() -> None:
    assert nutrition.day_totals([]) == MacroTotals()


def test_no_target_yet_returns_none() -> None:
    assert nutrition.target_on(TODAY, []) is None


def test_balance_with_no_intake_is_the_full_expenditure() -> None:
    result = energy.energy_balance(2400.0, 0.0)
    assert result.state is BalanceState.DEFICIT
    assert result.balance_kcal == -2400.0


def test_tdee_survives_a_missing_activity_figure() -> None:
    assert energy.tdee_estimate(1815.0, None, None) == 1815.0


def test_brand_new_user_gets_no_baselines() -> None:
    three_days = flat_series(52.0, 3)
    assert baselines.baseline(three_days, "hrv_ms", 30, TODAY) is None
    assert baselines.baseline(three_days, "hrv_ms", 7, TODAY) is None


def test_brand_new_user_gets_unknown_recovery_not_a_score() -> None:
    result = recovery.recovery_status({"hrv_ms": 50.0}, {"hrv_ms": flat_series(52.0, 3)}, TODAY)
    assert result.status is Status.UNKNOWN
    assert result.score is None


def test_no_weigh_ins_at_all() -> None:
    assert weight.ema_on([], TODAY) is None
    assert weight.trend([], TODAY) is None
    assert weight.plateau([], TODAY) is None
    assert weight.rate_of_change([], TODAY) is None
    assert weight.rolling_mean([], TODAY, 7) is None


def test_a_single_weigh_in_gives_a_value_but_no_trend() -> None:
    one = [(TODAY, 80.0)]
    assert weight.ema_on(one, TODAY) == 80.0
    assert weight.trend(one, TODAY) is None


def test_no_dexa_means_no_composition() -> None:
    assert body_composition.composition_on(80.0, TODAY, []) is None
    assert body_composition.latest_scan_before([], TODAY) is None


def test_trends_of_nothing() -> None:
    assert trends.mean_over([], TODAY, 30) is None
    assert trends.period_comparison([], "x", TODAY) is None
    assert trends.correlation([], [], "a", "b") is None
    assert trends.streak([], TODAY) == 0
    assert trends.window([], TODAY, 30) == []


def test_calibration_of_nothing() -> None:
    assert calibration.observed_maintenance([], [], TODAY) is None
    assert calibration.flat_despite_deficit([], [], TODAY) is None
    assert calibration.lean_mass_guardrail([], TODAY) is None


def test_sleep_helpers_of_nothing() -> None:
    assert recovery.sleep_debt([], TODAY) is None
    assert recovery.sleep_consistency([], TODAY) is None


def test_a_day_before_any_history_exists() -> None:
    """Backfill will ask about dates with nothing on either side."""
    ancient = date(2020, 1, 1)
    assert baselines.baseline(flat_series(52.0, 30), "hrv_ms", 30, ancient) is None
    assert weight.ema_on([(TODAY, 80.0)], ancient) is None
