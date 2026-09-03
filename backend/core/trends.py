"""Historical trends: series extraction, period comparison, correlation.

No analytics tier behind this. One user producing one snapshot a day is ~365 items a
year, so a single range query returns the whole history and these pure functions compute
over it in memory. See PLAN.md section 6 for the threshold where that stops being true.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, timedelta

from backend.core.models import CorrelationResult, PeriodComparison

Series = Sequence[tuple[date, float | None]]

#: Below this, correlation hunting manufactures findings. The guard lives here rather
#: than in a UI footnote, so no caller can accidentally skip it.
MIN_CORRELATION_N = 30


def window(series: Series, on: date, window_days: int) -> list[tuple[date, float]]:
    """Inclusive window ending at `on`, nulls dropped."""
    start = on - timedelta(days=window_days - 1)
    return [(d, v) for d, v in series if v is not None and start <= d <= on]


def mean_over(series: Series, on: date, window_days: int) -> float | None:
    values = [v for _, v in window(series, on, window_days)]
    return sum(values) / len(values) if values else None


def period_comparison(
    series: Series, metric: str, on: date, *, window_days: int = 30
) -> PeriodComparison | None:
    """Last N days against the N before them -- "compare this month with last month"."""
    current = window(series, on, window_days)
    previous = window(series, on - timedelta(days=window_days), window_days)
    if not current or not previous:
        return None
    current_mean = sum(v for _, v in current) / len(current)
    previous_mean = sum(v for _, v in previous) / len(previous)
    difference = current_mean - previous_mean
    return PeriodComparison(
        metric=metric,
        window_days=window_days,
        current_mean=current_mean,
        previous_mean=previous_mean,
        difference=difference,
        difference_percent=(difference / previous_mean * 100.0) if previous_mean else 0.0,
        current_n=len(current),
        previous_n=len(previous),
    )


def correlation(
    series_a: Series,
    series_b: Series,
    metric_a: str,
    metric_b: str,
    *,
    min_n: int = MIN_CORRELATION_N,
) -> CorrelationResult | None:
    """Pearson r over days where BOTH metrics were recorded.

    Returns None below `min_n`. Reporting n alongside r is not optional -- an r of 0.6
    on twelve days is noise wearing a number's clothes.
    """
    a = {d: v for d, v in series_a if v is not None}
    b = {d: v for d, v in series_b if v is not None}
    shared = sorted(set(a) & set(b))
    n = len(shared)
    if n < min_n:
        return None
    xs = [a[d] for d in shared]
    ys = [b[d] for d in shared]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    sxx = sum((x - mean_x) ** 2 for x in xs)
    syy = sum((y - mean_y) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return CorrelationResult(metric_a=metric_a, metric_b=metric_b, r=sxy / (sxx * syy) ** 0.5, n=n)


def streak(days: Sequence[tuple[date, bool]], on: date, *, max_lookback: int = 400) -> int:
    """Consecutive days ending at `on` where the predicate held.

    A missing day breaks the run -- it is not evidence the condition was met.
    """
    by_day = dict(days)
    count = 0
    for offset in range(max_lookback):
        day = on - timedelta(days=offset)
        if by_day.get(day) is not True:
            break
        count += 1
    return count


def build_series(
    snapshots: Sequence[object], extractor: Callable[[object], float | None], dates: Sequence[date]
) -> list[tuple[date, float | None]]:
    """Adapter helper: pull one metric out of a list of snapshots into a Series."""
    return [(d, extractor(s)) for d, s in zip(dates, snapshots, strict=True)]
