from __future__ import annotations

from datetime import timedelta

import pytest

from backend.core import recovery
from backend.core.models import Status
from backend.core.reasons import ReasonCode
from backend.tests.conftest import TODAY, flat_series


def history(**metrics: float) -> dict[str, list[tuple]]:
    return {name: flat_series(value, 30) for name, value in metrics.items()}


def test_all_inputs_at_baseline_reads_normal() -> None:
    current = {"hrv_ms": 52.0, "sleep_duration_min": 430.0, "resting_hr": 53.0, "body_battery_high": 72.0}
    result = recovery.recovery_status(current, history(**current), TODAY)
    assert result.status is Status.NORMAL
    assert len(result.inputs_used) == 4


def test_suppressed_hrv_and_short_sleep_reads_below() -> None:
    hist = history(hrv_ms=52.0, sleep_duration_min=430.0, resting_hr=53.0, body_battery_high=72.0)
    current = {"hrv_ms": 44.0, "sleep_duration_min": 380.0, "resting_hr": 58.0, "body_battery_high": 55.0}
    result = recovery.recovery_status(current, hist, TODAY)
    assert result.status is Status.BELOW
    assert result.score is not None and result.score < 20
    codes = {r.code for r in result.reasons}
    assert ReasonCode.HRV_BELOW_BASELINE in codes
    assert ReasonCode.SLEEP_BELOW_BASELINE in codes
    assert ReasonCode.RHR_ABOVE_BASELINE in codes


def test_direction_is_metric_aware() -> None:
    """Higher HRV is good; higher resting HR is not. Same 'ABOVE' status, opposite meaning."""
    hist = history(hrv_ms=52.0, resting_hr=53.0)
    good = recovery.recovery_status({"hrv_ms": 62.0, "resting_hr": 53.0}, hist, TODAY)
    bad = recovery.recovery_status({"hrv_ms": 52.0, "resting_hr": 62.0}, hist, TODAY)
    assert good.score is not None and bad.score is not None
    assert good.score > bad.score


def test_degrades_to_the_subset_that_has_baselines() -> None:
    """The FR165 may not report everything -- a missing metric must reduce confidence,
    not silently count as neutral."""
    hist = history(hrv_ms=52.0, sleep_duration_min=430.0)
    result = recovery.recovery_status(
        {"hrv_ms": 44.0, "sleep_duration_min": 380.0, "body_battery_high": None}, hist, TODAY
    )
    assert result.inputs_used == ["sleep_duration_min", "hrv_ms"]
    assert result.status is Status.BELOW


def test_unknown_when_no_baselines_exist_yet() -> None:
    """A brand-new user gets an honest 'building baseline', not a fabricated score."""
    result = recovery.recovery_status(
        {"hrv_ms": 44.0, "sleep_duration_min": 380.0}, {"hrv_ms": flat_series(52.0, 4)}, TODAY
    )
    assert result.status is Status.UNKNOWN
    assert result.score is None
    assert ReasonCode.BASELINE_BUILDING in {r.code for r in result.reasons}


def test_watch_not_worn_is_reported_not_guessed() -> None:
    hist = history(hrv_ms=52.0, sleep_duration_min=430.0)
    result = recovery.recovery_status({"hrv_ms": None, "sleep_duration_min": None}, hist, TODAY)
    assert result.status is Status.UNKNOWN
    assert ReasonCode.METRIC_MISSING in {r.code for r in result.reasons}


def test_consecutive_hrv_suppression_is_flagged() -> None:
    hrv = [(TODAY - timedelta(days=i), 52.0 if i >= 4 else 43.0) for i in range(30)]
    result = recovery.recovery_status({"hrv_ms": 43.0}, {"hrv_ms": hrv}, TODAY)
    flagged = [r for r in result.reasons if r.code is ReasonCode.HRV_SUPPRESSED_CONSECUTIVE]
    assert flagged and flagged[0].detail["consecutive_days"] == 4


def test_sleep_debt_accumulates() -> None:
    debt = recovery.sleep_debt(flat_series(420.0, 7), TODAY, target_hours=8.0)
    assert debt is not None
    assert debt == pytest.approx(7.0)  # 7 nights x 1h short


def test_sleep_debt_of_nothing_is_none() -> None:
    assert recovery.sleep_debt([], TODAY) is None


def test_sleep_consistency_needs_three_nights() -> None:
    assert recovery.sleep_consistency([(TODAY, 23.0)], TODAY) is None
