"""Weight: trend over individual readings, always.

A single weigh-in is mostly water. Manual entry means gaps are expected, so every
function here tolerates them and returns None rather than interpolating fake data.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from backend.core.models import PlateauResult, TrendResult
from backend.core.reasons import Reason, ReasonCode

Series = Sequence[tuple[date, float]]

#: Flatter than this reads as "no trend".
FLAT_SLOPE_KG_PER_WEEK = 0.1
#: Day-to-day scatter above this means water noise dominates and we can't call a plateau.
NOISY_SD_KG = 0.8


def ema(series: Series, *, halflife_days: float = 7.0) -> list[tuple[date, float]]:
    """Time-weighted EMA, so irregular weigh-ins are handled correctly.

    A plain EMA assumes even spacing. With manual entry the gap matters: a reading after
    five days should move the average more than one taken the next morning. The weight
    for a gap of `d` days is `1 - 0.5**(d/halflife)`.
    """
    ordered = sorted(series, key=lambda p: p[0])
    out: list[tuple[date, float]] = []
    current: float | None = None
    previous_day: date | None = None
    for day, value in ordered:
        if current is None or previous_day is None:
            current = value
        else:
            gap = max((day - previous_day).days, 1)
            alpha = 1.0 - 0.5 ** (gap / halflife_days)
            current = current + alpha * (value - current)
        previous_day = day
        out.append((day, current))
    return out


def ema_on(series: Series, on: date, *, halflife_days: float = 7.0) -> float | None:
    """The EMA value as of a given day, using only readings up to and including it."""
    upto = [(d, v) for d, v in series if d <= on]
    if not upto:
        return None
    return ema(upto, halflife_days=halflife_days)[-1][1]


def rolling_mean(series: Series, on: date, window_days: int) -> float | None:
    start = on - timedelta(days=window_days - 1)
    values = [v for d, v in series if start <= d <= on]
    return sum(values) / len(values) if values else None


def change_over(series: Series, on: date, days: int) -> float | None:
    """Change in the smoothed value, not in two raw readings -- comparing raw endpoints
    mostly measures hydration on two arbitrary mornings."""
    now = ema_on(series, on)
    then = ema_on(series, on - timedelta(days=days))
    if now is None or then is None:
        return None
    return now - then


def trend(series: Series, on: date, *, window_days: int = 28) -> TrendResult | None:
    """Least-squares slope over the window. r-squared reports how much to trust it."""
    start = on - timedelta(days=window_days - 1)
    points = sorted(((d, v) for d, v in series if start <= d <= on), key=lambda p: p[0])
    n = len(points)
    if n < 3:
        return None
    xs = [float((d - points[0][0]).days) for d, _ in points]
    ys = [v for _, v in points]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx
    syy = sum((y - mean_y) ** 2 for y in ys)
    r_squared = (sxy**2 / (sxx * syy)) if syy > 0 else 0.0
    return TrendResult(
        slope_per_day=slope,
        slope_per_week=slope * 7.0,
        r_squared=r_squared,
        n=n,
        window_days=window_days,
    )


def rate_of_change(series: Series, on: date, *, window_days: int = 14) -> float | None:
    """kg per week."""
    result = trend(series, on, window_days=window_days)
    return None if result is None else result.slope_per_week


def _sd(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return (sum((v - mean) ** 2 for v in values) / (n - 1)) ** 0.5


def plateau(
    series: Series,
    on: date,
    *,
    window_days: int = 21,
    flat_slope: float = FLAT_SLOPE_KG_PER_WEEK,
    noisy_sd: float = NOISY_SD_KG,
) -> PlateauResult | None:
    """Distinguish a real stall from water retention.

    Flat *and* low-variance is a genuine plateau. Flat with high day-to-day scatter means
    the noise is bigger than the signal, so we decline to call it -- which prevents the
    classic mistake of cutting calories during a fake stall.
    """
    result = trend(series, on, window_days=window_days)
    if result is None:
        return None
    start = on - timedelta(days=window_days - 1)
    values = [v for d, v in series if start <= d <= on]
    sd = _sd(values)
    flat = abs(result.slope_per_week) < flat_slope
    is_plateau = flat and sd <= noisy_sd

    reasons: list[Reason] = []
    if is_plateau:
        reasons.append(
            Reason(code=ReasonCode.PLATEAU_DETECTED, metric="weight_kg", window_days=window_days, n=len(values))
        )
    elif flat and sd > noisy_sd:
        reasons.append(
            Reason(code=ReasonCode.LIKELY_WATER_FLUCTUATION, metric="weight_kg", window_days=window_days, n=len(values))
        )
    else:
        code = ReasonCode.WEIGHT_TREND_DOWN if result.slope_per_week < 0 else ReasonCode.WEIGHT_TREND_UP
        reasons.append(
            Reason(
                code=code,
                metric="weight_kg",
                window_days=window_days,
                n=len(values),
                detail={"rate": round(abs(result.slope_per_week), 2), "window": window_days},
            )
        )
    return PlateauResult(
        is_plateau=is_plateau,
        window_days=window_days,
        slope_per_week=result.slope_per_week,
        sd=sd,
        n=len(values),
        reasons=reasons,
    )
