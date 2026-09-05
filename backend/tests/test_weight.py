from __future__ import annotations

from datetime import date
from datetime import timedelta

import pytest

from backend.core import reasons
from backend.core import weight
from backend.tests import conftest


def declining(days: int = 28, start: float = 80.5, per_day: float = -0.06,
              noise: float = 0.0, end: date = conftest.TODAY) -> list[tuple[date, float]]:
    out = []
    for i in range(days):
        day = end - timedelta(days=days - 1 - i)
        wobble = noise if i % 2 == 0 else -noise
        out.append((day, start + per_day * i + wobble))
    return out


def test_ema_smooths_a_single_spike() -> None:
    """A single weigh-in is mostly water; the EMA must not follow it."""
    data = [(conftest.TODAY - timedelta(days=i), 80.0) for i in range(9, -1, -1)]
    data[-1] = (conftest.TODAY, 83.0)  # one bad morning
    value = weight.ema_on(data, conftest.TODAY)
    assert value is not None
    assert 80.0 < value < 80.5


def test_ema_is_time_weighted_so_gaps_count_more() -> None:
    """Manual entry means gaps. A reading after five days should move the average more
    than one taken the next morning."""
    tight = [(conftest.TODAY - timedelta(days=1), 80.0), (conftest.TODAY, 78.0)]
    loose = [(conftest.TODAY - timedelta(days=10), 80.0), (conftest.TODAY, 78.0)]
    tight_value = weight.ema_on(tight, conftest.TODAY)
    loose_value = weight.ema_on(loose, conftest.TODAY)
    assert tight_value is not None and loose_value is not None
    assert loose_value < tight_value  # the 10-day gap pulls harder toward 78


def test_ema_stays_inside_the_observed_range() -> None:
    data = declining(noise=0.5)
    values = [v for _, v in weight.ema(data)]
    assert min(v for _, v in data) <= min(values)
    assert max(values) <= max(v for _, v in data)


def test_ema_of_nothing_is_none() -> None:
    assert weight.ema_on([], conftest.TODAY) is None


def test_trend_recovers_a_known_slope() -> None:
    data = declining(days=28, per_day=-0.06)
    result = weight.trend(data, conftest.TODAY)
    assert result is not None
    assert result.slope_per_week == pytest.approx(-0.42, abs=0.01)
    assert result.r_squared == pytest.approx(1.0, abs=1e-6)
    assert result.n == 28


def test_trend_needs_three_points() -> None:
    assert weight.trend([(conftest.TODAY, 80.0), (conftest.TODAY - timedelta(days=1), 80.1)], conftest.TODAY) is None


def test_rate_of_change_is_kg_per_week() -> None:
    rate = weight.rate_of_change(declining(days=14, per_day=-0.07), conftest.TODAY)
    assert rate == pytest.approx(-0.49, abs=0.01)


def test_change_over_uses_smoothed_values() -> None:
    """Comparing two raw readings mostly measures hydration on two arbitrary mornings."""
    change = weight.change_over(declining(days=30, per_day=-0.05, noise=0.6), conftest.TODAY, 21)
    assert change is not None
    assert -1.6 < change < -0.6


def test_change_over_without_history_is_none() -> None:
    assert weight.change_over([(conftest.TODAY, 80.0)], conftest.TODAY, 30) is None


def test_flat_and_quiet_is_a_real_plateau() -> None:
    data = [(conftest.TODAY - timedelta(days=i), 79.0 + (0.05 if i % 2 else -0.05)) for i in range(21)]
    result = weight.plateau(data, conftest.TODAY)
    assert result is not None
    assert result.is_plateau is True
    assert result.reasons[0].code is reasons.ReasonCode.PLATEAU_DETECTED


def test_flat_but_noisy_declines_to_call_a_plateau() -> None:
    """Prevents the classic mistake of cutting calories during a fake stall."""
    data = [(conftest.TODAY - timedelta(days=i), 79.0 + (1.4 if i % 2 else -1.4)) for i in range(21)]
    result = weight.plateau(data, conftest.TODAY)
    assert result is not None
    assert result.is_plateau is False
    assert result.reasons[0].code is reasons.ReasonCode.LIKELY_WATER_FLUCTUATION


def test_a_clear_decline_is_not_a_plateau() -> None:
    result = weight.plateau(declining(days=21, per_day=-0.06), conftest.TODAY)
    assert result is not None
    assert result.is_plateau is False
    assert result.reasons[0].code is reasons.ReasonCode.WEIGHT_TREND_DOWN
    assert "down" in result.reasons[0].render()
