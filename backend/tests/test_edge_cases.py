"""Edge cases and guard branches.

Split into its own file because these are not about the main behaviour of any module --
they are the "what if" paths: a zero denominator, an explicit override, a value that is
exactly on a boundary. Several were found by coverage after a readability refactor, which
is exactly what coverage is useful for.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta

import pytest

from backend.core import baselines
from backend.core import body_composition
from backend.core import calibration
from backend.core import models
from backend.core import nutrition
from backend.core import reasons
from backend.core import recovery
from backend.core import trends
from backend.core import weight
from backend.tests import conftest

# --- Profile.age_on --------------------------------------------------------


def test_age_is_lower_before_the_birthday_has_happened() -> None:
    """Born 1 May 2003. In April 2026 he is still 22; from 1 May he is 23.

    Subtracting the years alone would say 23 on both dates. This is the reason the
    profile stores a birth date rather than an age in the first place.
    """
    profile = models.Profile(user_id="x", sex=models.Sex.MALE, birth_date=date(2003, 5, 1), height_cm=180.0)
    assert profile.age_on(date(2026, 4, 30)) == 22
    assert profile.age_on(date(2026, 5, 1)) == 23      # the birthday itself counts
    assert profile.age_on(date(2026, 9, 3)) == 23


def test_age_handles_a_birthday_later_in_the_month() -> None:
    profile = models.Profile(user_id="x", sex=models.Sex.MALE, birth_date=date(2003, 5, 20), height_cm=180.0)
    assert profile.age_on(date(2026, 5, 19)) == 22
    assert profile.age_on(date(2026, 5, 20)) == 23


# --- MacroTotals -----------------------------------------------------------


def test_scaling_carries_optional_fields_when_they_are_present() -> None:
    totals = models.MacroTotals(kcal=100.0, protein_g=10.0, fiber_g=3.0, sodium_mg=200.0)
    doubled = totals.scale(2.0)
    assert doubled.fiber_g == 6.0
    assert doubled.sodium_mg == 400.0


def test_scaling_leaves_unknown_optional_fields_unknown() -> None:
    """None means "we do not know", and multiplying an unknown keeps it unknown."""
    totals = models.MacroTotals(kcal=100.0, fiber_g=None, sodium_mg=None)
    doubled = totals.scale(2.0)
    assert doubled.fiber_g is None
    assert doubled.sodium_mg is None


# --- baselines -------------------------------------------------------------


def test_an_explicit_minimum_overrides_the_default() -> None:
    """Useful for a metric that needs more history than the default rule allows."""
    data = conftest.flat_series(52.0, 20)
    assert baselines.baseline(data, "hrv_ms", 30, conftest.TODAY) is not None       # default is 15
    assert baselines.baseline(data, "hrv_ms", 30, conftest.TODAY, min_n=25) is None


def test_baseline_building_reason_respects_an_explicit_minimum() -> None:
    reason = baselines.baseline_building_reason(conftest.flat_series(52.0, 20), "hrv_ms", 30, conftest.TODAY, min_n=25)
    assert reason.detail["required"] == 25


def test_deviation_percent_is_zero_when_the_baseline_average_is_zero() -> None:
    """Guards against dividing by zero. No real metric averages exactly zero, but the
    branch has to do something defined."""
    zero_baseline = models.Baseline(metric="x", mean=0.0, sd=1.0, n=20, window_days=30, computed_on=conftest.TODAY)
    result = baselines.deviation(5.0, zero_baseline)
    assert result is not None
    assert result.difference_percent == 0.0
    assert result.difference == 5.0


def test_consecutive_beyond_counts_upward_runs_too() -> None:
    """The same helper serves resting heart rate, where ABOVE baseline is the bad
    direction, not below."""
    data = conftest.series([53.0] * 26 + [61.0, 61.0, 61.0])
    base = baselines.baseline(data, "resting_hr", 30, conftest.TODAY)
    assert base is not None
    assert baselines.consecutive_beyond(data, base, direction=models.Status.ABOVE, on=conftest.TODAY) == 3
    assert baselines.consecutive_beyond(data, base, direction=models.Status.BELOW, on=conftest.TODAY) == 0


# --- body composition ------------------------------------------------------


def test_estimate_with_zero_weight_does_not_divide_by_zero() -> None:
    anchor = models.DexaScan(
        date=date(2026, 10, 1), total_mass_kg=80.0, fat_mass_kg=15.2,
        lean_mass_kg=61.5, bone_mass_kg=3.2, body_fat_pct=19.0,
    )
    result = body_composition.estimate(0.0, date(2026, 11, 1), anchor)
    assert result.body_fat_pct == 0.0


# --- nutrition -------------------------------------------------------------


def test_adherence_against_a_zero_target_does_not_divide_by_zero(target: models.MacroTarget) -> None:
    zero_target = models.MacroTarget(
        effective_from=conftest.TODAY, goal=models.GoalType.MAINTAINING,
        kcal=0.0, protein_g=0.0, carbs_g=0.0, fat_g=0.0,
    )
    result = nutrition.adherence(models.MacroTotals(kcal=100.0), zero_target)
    assert result.kcal_percent == 0.0


def test_eating_over_the_calorie_target_is_reported(target: models.MacroTarget) -> None:
    over = models.MacroTotals(kcal=2800.0, protein_g=185.0, carbs_g=300.0, fat_g=80.0)
    codes = [reason.code for reason in nutrition.adherence(over, target).reasons]
    assert reasons.ReasonCode.CALORIES_OVER_TARGET in codes


def test_a_small_calorie_gap_is_not_worth_mentioning(target: models.MacroTarget) -> None:
    """Being 20 kcal off a 2,350 target is noise, not information."""
    close_enough = models.MacroTotals(kcal=2330.0, protein_g=185.0, carbs_g=260.0, fat_g=65.0)
    codes = [reason.code for reason in nutrition.adherence(close_enough, target).reasons]
    assert reasons.ReasonCode.CALORIES_OVER_TARGET not in codes
    assert reasons.ReasonCode.CALORIES_UNDER_TARGET not in codes


def test_adherence_streak_stops_at_a_day_with_no_target() -> None:
    """Days before any target existed cannot be scored, so the streak ends there."""
    targets = [
        models.MacroTarget(effective_from=date(2026, 9, 2), goal=models.GoalType.CUTTING,
                    kcal=2350.0, protein_g=180.0, carbs_g=260.0, fat_g=65.0)
    ]
    days = [
        (date(2026, 9, 1), models.MacroTotals(protein_g=200.0)),   # before any target
        (date(2026, 9, 2), models.MacroTotals(protein_g=200.0)),
        (date(2026, 9, 3), models.MacroTotals(protein_g=200.0)),
    ]
    assert nutrition.adherence_streak(days, targets) == 2


# --- reasons ---------------------------------------------------------------


def test_missing_optional_fields_render_as_blanks_not_the_word_none() -> None:
    reason = reasons.Reason(code=reasons.ReasonCode.NO_WEIGH_IN, metric="weight_kg")
    rendered = reason.render()
    assert "None" not in rendered
    assert "{" not in rendered


# --- recovery --------------------------------------------------------------


@pytest.mark.parametrize(
    ("average_vote", "expected_score"),
    [(-1.0, 0.0), (-0.5, 25.0), (0.0, 50.0), (0.5, 75.0), (1.0, 100.0)],
)
def test_vote_to_score_mapping(average_vote: float, expected_score: float) -> None:
    assert recovery.score_from_average_vote(average_vote) == expected_score


def test_score_is_clamped_to_the_zero_to_hundred_range() -> None:
    """Votes should never exceed +/-1, but a score of 104 would still be a bug worth
    preventing rather than displaying."""
    assert recovery.score_from_average_vote(-2.0) == 0.0
    assert recovery.score_from_average_vote(2.0) == 100.0


def test_sleep_debt_skips_nights_with_no_recording() -> None:
    nights = conftest.series([420.0, None, 420.0, None, 420.0, None, 420.0])
    debt = recovery.sleep_debt(nights, conftest.TODAY, target_hours=8.0)
    assert debt is not None
    # 4 nights were recorded (indices 0, 2, 4, 6), each 420 min = 7h against an 8h
    # target, so 4 x 1 hour short. Unlike a baseline window, this one includes today.
    assert debt == pytest.approx(4.0)


def test_sleep_consistency_measures_bedtime_spread() -> None:
    steady = [(conftest.TODAY - timedelta(days=i), 23.0) for i in range(7)]
    erratic = [(conftest.TODAY - timedelta(days=i), 21.0 + (4.0 if i % 2 else 0.0)) for i in range(7)]

    steady_spread = recovery.sleep_consistency(steady, conftest.TODAY)
    erratic_spread = recovery.sleep_consistency(erratic, conftest.TODAY)

    assert steady_spread == pytest.approx(0.0)
    assert erratic_spread is not None
    assert erratic_spread > 1.5


# --- trends ----------------------------------------------------------------


def test_period_comparison_needs_the_earlier_period_too() -> None:
    """Thirty days of data cannot be compared against the thirty days before it."""
    only_recent = conftest.flat_series(430.0, 30)
    assert trends.period_comparison(only_recent, "sleep", conftest.TODAY, window_days=30) is None


def test_streak_of_a_false_day_is_zero() -> None:
    days = [(conftest.TODAY, False), (conftest.TODAY - timedelta(days=1), True)]
    assert trends.streak(days, conftest.TODAY) == 0


def test_build_series_pulls_one_field_out_of_snapshots() -> None:
    class FakeSnapshot:
        def __init__(self, value: float | None) -> None:
            self.value = value

    snapshots = [FakeSnapshot(1.0), FakeSnapshot(None), FakeSnapshot(3.0)]
    dates = [conftest.TODAY - timedelta(days=2), conftest.TODAY - timedelta(days=1), conftest.TODAY]

    built = trends.build_series(snapshots, lambda snapshot: snapshot.value, dates)

    assert built == [(dates[0], 1.0), (dates[1], None), (dates[2], 3.0)]


# --- weight ----------------------------------------------------------------


def test_rolling_mean_without_readings_is_none() -> None:
    assert weight.rolling_mean([], conftest.TODAY, 7) is None


def test_rolling_mean_averages_the_window() -> None:
    readings = [(conftest.TODAY - timedelta(days=i), 80.0 + i) for i in range(3)]
    assert weight.rolling_mean(readings, conftest.TODAY, 3) == pytest.approx(81.0)


def test_trend_is_none_when_every_reading_is_on_the_same_day() -> None:
    """Three readings but no time axis to fit a line against."""
    same_day = [(conftest.TODAY, 80.0), (conftest.TODAY, 80.5), (conftest.TODAY, 79.5)]
    assert weight.trend(same_day, conftest.TODAY) is None


def test_standard_deviation_of_fewer_than_two_values_is_zero() -> None:
    assert weight.standard_deviation([]) == 0.0
    assert weight.standard_deviation([80.0]) == 0.0


def test_standard_deviation_of_a_known_set() -> None:
    # values 2, 4, 4, 4, 5, 5, 7, 9 -> sample standard deviation is about 2.14
    assert weight.standard_deviation([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(2.138, abs=0.01)


def test_plateau_reports_an_upward_trend() -> None:
    gaining = [(conftest.TODAY - timedelta(days=i), 79.0 + 0.05 * (20 - i)) for i in range(21)]
    result = weight.plateau(gaining, conftest.TODAY)
    assert result is not None
    assert result.is_plateau is False
    assert result.reasons[0].code is reasons.ReasonCode.WEIGHT_TREND_UP


def test_exponential_weight_grows_with_the_gap() -> None:
    """The property that makes the average handle skipped weigh-ins correctly."""
    one_day = weight.exponential_weight_for_gap(1.0, 7.0)
    seven_days = weight.exponential_weight_for_gap(7.0, 7.0)
    fourteen_days = weight.exponential_weight_for_gap(14.0, 7.0)

    assert one_day < seven_days < fourteen_days
    assert seven_days == pytest.approx(0.5)      # one halflife = move halfway


# --- calibration -----------------------------------------------------------


def test_observed_maintenance_skips_days_with_no_intake_recorded() -> None:
    intake: list[tuple[date, float | None]] = []
    for days_back in range(42):
        day = conftest.TODAY - timedelta(days=days_back)
        if days_back % 5 == 0:
            intake.append((day, None))       # a day that was never logged
        else:
            intake.append((day, 2350.0))

    weigh_ins = [(conftest.TODAY - timedelta(days=i), 80.0 - 0.05 * (41 - i)) for i in range(0, 42, 2)]

    result = calibration.observed_maintenance(intake, weigh_ins, conftest.TODAY)
    assert result is not None
    # days_back 0, 5, 10, ... 40 are unlogged -- that is 9 days out of 42.
    assert result.days_used == 33
    assert result.mean_intake_kcal == pytest.approx(2350.0)


def test_observed_maintenance_is_none_when_all_weigh_ins_are_on_one_day() -> None:
    """Enough readings to pass the count check, but no time axis to fit a trend to."""
    intake = conftest.flat_series(2350.0, 42)
    weigh_ins = [(conftest.TODAY, 80.0 + i * 0.01) for i in range(15)]
    assert calibration.observed_maintenance(intake, weigh_ins, conftest.TODAY) is None


def test_observed_maintenance_ignores_garmin_days_outside_the_window() -> None:
    intake = conftest.flat_series(2350.0, 42)
    weigh_ins = [(conftest.TODAY - timedelta(days=i), 80.0 - 0.05 * (41 - i)) for i in range(0, 42, 2)]
    garmin: list[tuple[date, float | None]] = [(conftest.TODAY - timedelta(days=400), 9999.0)]

    result = calibration.observed_maintenance(intake, weigh_ins, conftest.TODAY, garmin_expenditure=garmin)
    assert result is not None
    assert result.garmin_mean_expenditure_kcal is None      # nothing inside the window


def test_flat_despite_deficit_needs_logged_balances() -> None:
    flat = [(conftest.TODAY - timedelta(days=i), 79.0) for i in range(21)]
    assert calibration.flat_despite_deficit(flat, [], conftest.TODAY) is None


def test_flat_despite_deficit_skips_unlogged_days() -> None:
    flat = [(conftest.TODAY - timedelta(days=i), 79.0) for i in range(21)]
    balances = conftest.series([None if i % 2 else -450.0 for i in range(21)])
    reason = calibration.flat_despite_deficit(flat, balances, conftest.TODAY)
    assert reason is not None
    assert reason.code is reasons.ReasonCode.WEIGHT_TREND_FLAT_DESPITE_DEFICIT


# --- final guard branches --------------------------------------------------


def test_period_comparison_percent_is_zero_when_the_earlier_period_averaged_zero() -> None:
    """Guards a division by zero. Only reachable for a metric that can legitimately be
    zero for a whole period, such as workout minutes during a rest week."""
    earlier_zero: list[tuple[date, float | None]] = []
    for days_back in range(30, 60):
        earlier_zero.append((conftest.TODAY - timedelta(days=days_back), 0.0))

    recent: list[tuple[date, float | None]] = []
    for days_back in range(30):
        recent.append((conftest.TODAY - timedelta(days=days_back), 45.0))

    result = trends.period_comparison(earlier_zero + recent, "workout_minutes", conftest.TODAY, window_days=30)
    assert result is not None
    assert result.difference_percent == 0.0
    assert result.difference == pytest.approx(45.0)


def test_correlation_is_none_when_the_second_metric_never_changes() -> None:
    """Symmetric with the flat-first-metric case: if either side never moved, "do they
    move together?" has no answer."""
    varying = conftest.series([float(i) for i in range(40)])
    constant = conftest.flat_series(5.0, 40)
    assert trends.correlation(constant, varying, "flat", "varying") is None
    assert trends.correlation(varying, constant, "varying", "flat") is None


def test_observed_maintenance_skips_garmin_days_with_no_reading() -> None:
    intake = conftest.flat_series(2350.0, 42)
    weigh_ins = [(conftest.TODAY - timedelta(days=i), 80.0 - 0.05 * (41 - i)) for i in range(0, 42, 2)]

    garmin: list[tuple[date, float | None]] = []
    for days_back in range(42):
        day = conftest.TODAY - timedelta(days=days_back)
        if days_back % 3 == 0:
            garmin.append((day, None))      # watch not worn
        else:
            garmin.append((day, 2900.0))

    result = calibration.observed_maintenance(intake, weigh_ins, conftest.TODAY, garmin_expenditure=garmin)
    assert result is not None
    assert result.garmin_mean_expenditure_kcal == pytest.approx(2900.0)
