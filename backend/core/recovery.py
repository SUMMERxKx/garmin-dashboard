"""Recovery status -- OURS, not Garmin's.

The Forerunner 165 has no Training Readiness or Training Status; those start at the 265.
It does report every input, so we compute a composite against personal baselines and
label it as derived everywhere it appears (never dressed up as a Garmin metric).

Degrades gracefully by design: it uses whatever subset of inputs actually has a baseline,
reports which ones it used, and returns UNKNOWN rather than guessing when none do.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from backend.core.baselines import Series, baseline, deviation
from backend.core.models import Baseline, RecoveryResult, Status
from backend.core.reasons import Reason, ReasonCode

#: metric -> (higher_is_better, reason code when it moves the wrong way)
_INPUTS: dict[str, tuple[bool, ReasonCode]] = {
    "sleep_duration_min": (True, ReasonCode.SLEEP_BELOW_BASELINE),
    "sleep_score": (True, ReasonCode.SLEEP_SCORE_BELOW_BASELINE),
    "hrv_ms": (True, ReasonCode.HRV_BELOW_BASELINE),
    "resting_hr": (False, ReasonCode.RHR_ABOVE_BASELINE),
    "body_battery_high": (True, ReasonCode.BODY_BATTERY_BELOW_BASELINE),
    "stress_avg": (False, ReasonCode.STRESS_ABOVE_BASELINE),
}

_UNITS = {
    "sleep_duration_min": "min",
    "hrv_ms": "ms",
    "resting_hr": "bpm",
}


def recovery_status(
    current: dict[str, float | None],
    history: dict[str, Series],
    on: date,
    *,
    window_days: int = 30,
) -> RecoveryResult:
    """Composite recovery against personal baselines.

    Each available input votes -1 (worse than normal), 0 (normal) or +1 (better). The
    score is the mean vote mapped onto 0-100, so a missing metric reduces confidence
    rather than silently counting as neutral.
    """
    votes: list[float] = []
    reasons: list[Reason] = []
    used: list[str] = []
    baselines: dict[str, Baseline] = {}

    for metric, (higher_is_better, bad_code) in _INPUTS.items():
        value = current.get(metric)
        series = history.get(metric, [])
        if value is None:
            if metric in ("sleep_duration_min", "hrv_ms"):
                reasons.append(Reason(code=ReasonCode.METRIC_MISSING, metric=metric))
            continue
        base = baseline(series, metric, window_days, on)
        if base is None:
            reasons.append(
                Reason(
                    code=ReasonCode.BASELINE_BUILDING,
                    metric=metric,
                    window_days=window_days,
                    n=len([v for _, v in series if v is not None]),
                    detail={"required": max(3, window_days // 2)},
                )
            )
            continue

        dev = deviation(value, base)
        assert dev is not None  # value and base are both non-None here
        baselines[metric] = base
        used.append(metric)

        if dev.status is Status.NORMAL:
            votes.append(0.0)
            continue
        moved_up = dev.status is Status.ABOVE
        good = moved_up if higher_is_better else not moved_up
        votes.append(1.0 if good else -1.0)
        if not good:
            reasons.append(
                Reason(
                    code=bad_code,
                    metric=metric,
                    current=value,
                    baseline=base.mean,
                    unit=_UNITS.get(metric),
                    difference=dev.difference,
                    difference_percent=dev.difference_percent,
                    window_days=window_days,
                    n=base.n,
                )
            )

    if not votes:
        return RecoveryResult(status=Status.UNKNOWN, score=None, inputs_used=[], reasons=reasons)

    net = sum(votes) / len(votes)
    score = max(0.0, min(100.0, 50.0 + 50.0 * net))
    if net <= -0.34:
        status = Status.BELOW
    elif net >= 0.34:
        status = Status.ABOVE
    else:
        status = Status.NORMAL

    hrv_series = history.get("hrv_ms", [])
    hrv_base = baselines.get("hrv_ms")
    if hrv_base is not None:
        from backend.core.baselines import consecutive_beyond

        streak = consecutive_beyond(hrv_series, hrv_base, direction=Status.BELOW, on=on)
        if streak >= 3:
            reasons.append(
                Reason(
                    code=ReasonCode.HRV_SUPPRESSED_CONSECUTIVE,
                    metric="hrv_ms",
                    detail={"consecutive_days": streak},
                )
            )

    return RecoveryResult(status=status, score=score, inputs_used=used, reasons=reasons)


def sleep_debt(series: Series, on: date, target_hours: float = 8.0, *, window: int = 7) -> float | None:
    """Cumulative shortfall in hours over the window. None when nothing was recorded."""
    start = on - timedelta(days=window - 1)
    values = [v for d, v in series if start <= d <= on and v is not None]
    if not values:
        return None
    return sum(target_hours - (v / 60.0) for v in values)


def sleep_consistency(starts: Sequence[tuple[date, float]], on: date, *, window: int = 14) -> float | None:
    """SD in hours of sleep-onset clock time. Lower is more consistent."""
    start = on - timedelta(days=window - 1)
    values = [v for d, v in starts if start <= d <= on]
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5
