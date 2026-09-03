from __future__ import annotations

from datetime import timedelta

import pytest

from backend.core import baselines
from backend.core.models import Status
from backend.tests.conftest import TODAY, flat_series, series


def test_window_excludes_the_current_day() -> None:
    """Otherwise a metric is partly compared against itself."""
    data = series([50.0] * 29 + [999.0])  # 999 lands on TODAY
    values = baselines.window_values(data, TODAY, 30)
    assert 999.0 not in values
    assert len(values) == 29


def test_window_drops_nulls_rather_than_zero_filling() -> None:
    # trailing 999.0 lands on TODAY and is excluded by the half-open window above
    data = series([50.0, None, 52.0, None, 54.0, 999.0])
    assert baselines.window_values(data, TODAY, 30) == [50.0, 52.0, 54.0]


def test_baseline_returns_none_below_minimum_readings() -> None:
    """Never a baseline built from four readings presented as if it means something."""
    assert baselines.baseline(flat_series(50.0, 5), "hrv_ms", 30, TODAY) is None


def test_baseline_computed_once_there_is_enough_data() -> None:
    base = baselines.baseline(flat_series(52.0, 30), "hrv_ms", 30, TODAY)
    assert base is not None
    assert base.mean == pytest.approx(52.0)
    assert base.n == 29  # today excluded
    assert base.sd == pytest.approx(0.0)


def test_default_min_n_scales_with_window() -> None:
    assert baselines.default_min_n(30) == 15
    assert baselines.default_min_n(7) == 3
    assert baselines.default_min_n(2) == 3  # floor


def test_baseline_building_reason_reports_progress() -> None:
    reason = baselines.baseline_building_reason(flat_series(52.0, 13), "hrv_ms", 30, TODAY)
    text = reason.render()
    assert "12 of 15" in text


def test_deviation_absolute_percent_and_z() -> None:
    data = series([50.0 + (i % 5) for i in range(30)])
    base = baselines.baseline(data, "hrv_ms", 30, TODAY)
    assert base is not None
    dev = baselines.deviation(40.0, base)
    assert dev is not None
    assert dev.difference == pytest.approx(40.0 - base.mean)
    assert dev.difference_percent < 0
    assert dev.z_score is not None
    assert dev.status is Status.BELOW


def test_deviation_is_none_without_inputs() -> None:
    assert baselines.deviation(None, None) is None
    assert baselines.deviation(50.0, None) is None


def test_band_never_tighter_than_three_percent() -> None:
    """A freakishly stable week must not flag every trivial wobble."""
    base = baselines.baseline(flat_series(100.0, 30), "x", 30, TODAY)
    assert base is not None
    assert base.sd == pytest.approx(0.0)
    assert baselines.band_for(base) == pytest.approx(3.0)
    assert baselines.status_of(101.0, base) is Status.NORMAL
    assert baselines.status_of(110.0, base) is Status.ABOVE


def test_consecutive_beyond_counts_a_real_run() -> None:
    data = series([53.0] * 26 + [45.0, 45.0, 45.0, 45.0])
    base = baselines.baseline(data, "hrv_ms", 30, TODAY)
    assert base is not None
    assert baselines.consecutive_beyond(data, base, direction=Status.BELOW, on=TODAY) == 4


def test_a_gap_breaks_the_run() -> None:
    """Five readings spread over three weeks is not a five-day streak."""
    data = [(TODAY, 45.0), (TODAY - timedelta(days=1), 45.0), (TODAY - timedelta(days=5), 45.0)]
    data += [(TODAY - timedelta(days=i), 53.0) for i in range(6, 32)]
    base = baselines.baseline(data, "hrv_ms", 30, TODAY)
    assert base is not None
    assert baselines.consecutive_beyond(data, base, direction=Status.BELOW, on=TODAY) == 2
