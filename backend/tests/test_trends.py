from __future__ import annotations

from datetime import date
from datetime import timedelta

import pytest

from backend.core import trends
from backend.tests import conftest


def test_window_is_inclusive_of_today() -> None:
    """Unlike a baseline window: a trend chart should show today's point."""
    data = conftest.series([1.0, 2.0, 3.0])
    assert [v for _, v in trends.window(data, conftest.TODAY, 3)] == [1.0, 2.0, 3.0]


def test_mean_over_skips_nulls() -> None:
    assert trends.mean_over(conftest.series([2.0, None, 4.0]), conftest.TODAY, 3) == pytest.approx(3.0)


def test_mean_over_empty_is_none() -> None:
    assert trends.mean_over([], conftest.TODAY, 30) is None


def test_period_comparison_splits_two_windows() -> None:
    older = [(conftest.TODAY - timedelta(days=i), 400.0) for i in range(30, 60)]
    recent = [(conftest.TODAY - timedelta(days=i), 430.0) for i in range(30)]
    result = trends.period_comparison(older + recent, "sleep_duration_min", conftest.TODAY, window_days=30)
    assert result is not None
    assert result.current_mean == pytest.approx(430.0)
    assert result.previous_mean == pytest.approx(400.0)
    assert result.difference == pytest.approx(30.0)
    assert result.difference_percent == pytest.approx(7.5)


def test_period_comparison_needs_both_periods() -> None:
    assert trends.period_comparison(conftest.flat_series(430.0, 10), "x", conftest.TODAY, window_days=30) is None


def test_correlation_refuses_below_thirty_points() -> None:
    """At 40 data points correlation hunting manufactures findings, so the guard lives
    in the function rather than in a UI footnote."""
    a = conftest.series([float(i) for i in range(20)])
    b = conftest.series([float(i) * 2 for i in range(20)])
    assert trends.correlation(a, b, "a", "b") is None


def test_correlation_recovers_a_perfect_relationship() -> None:
    a = conftest.series([float(i) for i in range(40)])
    b = conftest.series([float(i) * 3 + 5 for i in range(40)])
    result = trends.correlation(a, b, "a", "b")
    assert result is not None
    assert result.r == pytest.approx(1.0)
    assert result.n == 40


def test_correlation_reports_negative_relationships() -> None:
    a = conftest.series([float(i) for i in range(40)])
    b = conftest.series([-float(i) for i in range(40)])
    result = trends.correlation(a, b, "a", "b")
    assert result is not None and result.r == pytest.approx(-1.0)


def test_correlation_only_uses_days_both_metrics_were_recorded() -> None:
    a: list[tuple[date, float | None]] = conftest.series([float(i) for i in range(40)])
    b: list[tuple[date, float | None]] = conftest.series(
        [None if i % 2 else float(i) for i in range(40)]
    )
    result = trends.correlation(a, b, "a", "b", min_n=10)
    assert result is not None
    assert result.n == 20


def test_correlation_of_a_constant_is_none() -> None:
    a = conftest.series([float(i) for i in range(40)])
    assert trends.correlation(a, conftest.flat_series(5.0, 40), "a", "flat") is None


def test_streak_counts_back_from_today() -> None:
    days = [(conftest.TODAY - timedelta(days=i), i < 5) for i in range(10)]
    assert trends.streak(days, conftest.TODAY) == 5


def test_a_missing_day_breaks_a_streak() -> None:
    """Absence is not evidence the condition was met."""
    days = [(conftest.TODAY, True), (conftest.TODAY - timedelta(days=2), True)]
    assert trends.streak(days, conftest.TODAY) == 1
