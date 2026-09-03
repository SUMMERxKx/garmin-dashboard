"""Personal baselines -- the module everything else leans on.

`HRV = 48` is not information. `HRV 48, 30-day baseline 56, -14%` is. Almost every
question this product answers reduces to "compared to my normal", which is why baselines
are a dependency of the Today screen rather than a feature of the Trends screen.

Commitments:
  * rolling, not calendar ("last 30 days from today", not "this month")
  * personal, never population
  * excludes the current day, or a metric is partly compared against itself
  * insufficient data returns None -- never a baseline built from four readings
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, timedelta

from backend.core.models import Baseline, Deviation, Status
from backend.core.reasons import Reason, ReasonCode

#: (day, value) pairs. `None` values mean "not reported" and are skipped, not zero-filled.
Series = Sequence[tuple[date, float | None]]


def default_min_n(window_days: int) -> int:
    """Half the window, floor of 3. A 30-day baseline needs 15 readings; a 7-day needs 3."""
    return max(3, window_days // 2)


def window_values(
    series: Series,
    on: date,
    window_days: int,
    *,
    exclude_on: bool = True,
) -> list[float]:
    """Non-null values inside [on - window_days, on) -- half-open, so `on` is excluded."""
    start = on - timedelta(days=window_days)
    out: list[float] = []
    for day, value in series:
        if value is None:
            continue
        if day < start:
            continue
        if day > on or (exclude_on and day >= on):
            continue
        out.append(value)
    return out


def baseline(
    series: Series,
    metric: str,
    window_days: int,
    on: date,
    *,
    min_n: int | None = None,
) -> Baseline | None:
    """Rolling mean and SD, or None when there isn't enough data to mean anything."""
    values = window_values(series, on, window_days)
    required = default_min_n(window_days) if min_n is None else min_n
    if len(values) < required:
        return None
    mean = sum(values) / len(values)
    if len(values) > 1:
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        sd = math.sqrt(variance)
    else:  # pragma: no cover - required >= 3 makes this unreachable in practice
        sd = 0.0
    return Baseline(
        metric=metric, mean=mean, sd=sd, n=len(values), window_days=window_days, computed_on=on
    )


def baseline_building_reason(
    series: Series, metric: str, window_days: int, on: date, *, min_n: int | None = None
) -> Reason:
    """The honest alternative to a fabricated baseline: say how far along we are."""
    values = window_values(series, on, window_days)
    required = default_min_n(window_days) if min_n is None else min_n
    return Reason(
        code=ReasonCode.BASELINE_BUILDING,
        metric=metric,
        n=len(values),
        window_days=window_days,
        detail={"required": required},
    )


def band_for(base: Baseline, *, min_relative: float = 0.03) -> float:
    """Half-width of the 'normal' band.

    One SD, but never tighter than 3% of the mean -- a metric with an unusually stable
    week would otherwise flag every trivial wobble as a deviation.
    """
    return max(base.sd, abs(base.mean) * min_relative)


def status_of(current: float, base: Baseline, *, min_relative: float = 0.03) -> Status:
    """Direction only. Whether 'above' is good or bad is the caller's business --
    higher HRV is good, higher resting HR is not."""
    band = band_for(base, min_relative=min_relative)
    if current > base.mean + band:
        return Status.ABOVE
    if current < base.mean - band:
        return Status.BELOW
    return Status.NORMAL


def deviation(current: float | None, base: Baseline | None, *, min_relative: float = 0.03) -> Deviation | None:
    """Absolute difference, percent, and z-score against a baseline."""
    if current is None or base is None:
        return None
    difference = current - base.mean
    percent = (difference / base.mean * 100.0) if base.mean else 0.0
    z = (difference / base.sd) if base.sd > 0 else None
    return Deviation(
        metric=base.metric,
        current=current,
        baseline=base.mean,
        difference=difference,
        difference_percent=percent,
        z_score=z,
        status=status_of(current, base, min_relative=min_relative),
        window_days=base.window_days,
        n=base.n,
    )


def consecutive_beyond(
    series: Series,
    base: Baseline,
    *,
    direction: Status,
    on: date,
    max_lookback: int = 30,
    min_relative: float = 0.03,
) -> int:
    """How many consecutive days ending at `on` sit beyond the baseline band.

    Missing days break the run rather than being skipped: five readings spread over
    three weeks is not a five-day streak.
    """
    by_day = {day: value for day, value in series if value is not None}
    band = band_for(base, min_relative=min_relative)
    count = 0
    for offset in range(max_lookback):
        day = on - timedelta(days=offset)
        value = by_day.get(day)
        if value is None:
            break
        beyond = (
            value < base.mean - band if direction is Status.BELOW else value > base.mean + band
        )
        if not beyond:
            break
        count += 1
    return count
