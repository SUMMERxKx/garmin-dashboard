from __future__ import annotations

from datetime import timedelta

import pytest

from backend.core import models
from backend.core import reasons
from backend.core import recovery
from backend.tests import conftest


def history(**metrics: float) -> dict[str, list[tuple]]:
    return {name: conftest.flat_series(value, 30) for name, value in metrics.items()}


def test_all_inputs_at_baseline_reads_normal() -> None:
    current = {"hrv_ms": 52.0, "sleep_duration_min": 430.0, "resting_hr": 53.0, "body_battery_high": 72.0}
    result = recovery.recovery_status(current, history(**current), conftest.TODAY)
    assert result.status is models.Status.NORMAL
    assert len(result.inputs_used) == 4


def test_suppressed_hrv_and_short_sleep_reads_below() -> None:
    hist = history(hrv_ms=52.0, sleep_duration_min=430.0, resting_hr=53.0, body_battery_high=72.0)
    current = {"hrv_ms": 44.0, "sleep_duration_min": 380.0, "resting_hr": 58.0, "body_battery_high": 55.0}
    result = recovery.recovery_status(current, hist, conftest.TODAY)
    assert result.status is models.Status.BELOW
    assert result.score is not None and result.score < 20
    codes = {r.code for r in result.reasons}
    assert reasons.ReasonCode.HRV_BELOW_BASELINE in codes
    assert reasons.ReasonCode.SLEEP_BELOW_BASELINE in codes
    assert reasons.ReasonCode.RHR_ABOVE_BASELINE in codes


def test_direction_is_metric_aware() -> None:
    """Higher HRV is good; higher resting HR is not. Same 'ABOVE' status, opposite meaning."""
    hist = history(hrv_ms=52.0, resting_hr=53.0)
    good = recovery.recovery_status({"hrv_ms": 62.0, "resting_hr": 53.0}, hist, conftest.TODAY)
    bad = recovery.recovery_status({"hrv_ms": 52.0, "resting_hr": 62.0}, hist, conftest.TODAY)
    assert good.score is not None and bad.score is not None
    assert good.score > bad.score


def test_degrades_to_the_subset_that_has_baselines() -> None:
    """The FR165 may not report everything -- a missing metric must reduce confidence,
    not silently count as neutral."""
    hist = history(hrv_ms=52.0, sleep_duration_min=430.0)
    result = recovery.recovery_status(
        {"hrv_ms": 44.0, "sleep_duration_min": 380.0, "body_battery_high": None}, hist, conftest.TODAY
    )
    assert result.inputs_used == ["sleep_duration_min", "hrv_ms"]
    assert result.status is models.Status.BELOW


def test_unknown_when_no_baselines_exist_yet() -> None:
    """A brand-new user gets an honest 'building baseline', not a fabricated score."""
    result = recovery.recovery_status(
        {"hrv_ms": 44.0, "sleep_duration_min": 380.0}, {"hrv_ms": conftest.flat_series(52.0, 4)}, conftest.TODAY
    )
    assert result.status is models.Status.UNKNOWN
    assert result.score is None
    assert reasons.ReasonCode.BASELINE_BUILDING in {r.code for r in result.reasons}


def test_watch_not_worn_is_reported_not_guessed() -> None:
    hist = history(hrv_ms=52.0, sleep_duration_min=430.0)
    result = recovery.recovery_status({"hrv_ms": None, "sleep_duration_min": None}, hist, conftest.TODAY)
    assert result.status is models.Status.UNKNOWN
    assert reasons.ReasonCode.METRIC_MISSING in {r.code for r in result.reasons}


def test_consecutive_hrv_suppression_is_flagged() -> None:
    hrv = [(conftest.TODAY - timedelta(days=i), 52.0 if i >= 4 else 43.0) for i in range(30)]
    result = recovery.recovery_status({"hrv_ms": 43.0}, {"hrv_ms": hrv}, conftest.TODAY)
    flagged = [r for r in result.reasons if r.code is reasons.ReasonCode.HRV_SUPPRESSED_CONSECUTIVE]
    assert flagged and flagged[0].detail["consecutive_days"] == 4


def test_sleep_debt_accumulates() -> None:
    debt = recovery.sleep_debt(conftest.flat_series(420.0, 7), conftest.TODAY, target_hours=8.0)
    assert debt is not None
    assert debt == pytest.approx(7.0)  # 7 nights x 1h short


def test_sleep_debt_of_nothing_is_none() -> None:
    assert recovery.sleep_debt([], conftest.TODAY) is None


def test_sleep_consistency_needs_three_nights() -> None:
    assert recovery.sleep_consistency([(conftest.TODAY, 23.0)], conftest.TODAY) is None
