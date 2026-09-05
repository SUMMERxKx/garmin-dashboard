"""Trends over time: averages, comparing one period against another, and correlations.

There is no data warehouse behind this. One person recording one snapshot a day is
about 365 records a year -- a few hundred kilobytes. A single database query can return
the entire history, and these plain functions work through it in memory in well under a
millisecond. Adding a query engine and an ETL pipeline for that amount of data would be
building infrastructure for a problem we do not have.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence
from datetime import date
from datetime import timedelta

from backend.core import models

# A list of (day, value) pairs. None means "not recorded that day".
Series = Sequence[tuple[date, float | None]]

# Below this many overlapping days we refuse to report a correlation at all.
# See `correlation` for the reasoning.
MIN_CORRELATION_N = 30


def window(series: Series, on: date, window_days: int) -> list[tuple[date, float]]:
    """The (day, value) pairs inside the window ending on `on`, with gaps dropped.

    Note this window INCLUDES `on`, unlike the baseline window in `baselines.py`. A
    chart of the last 30 days should obviously show today's point; a baseline that
    today is going to be compared against should not.
    """
    first_day_in_window = on - timedelta(days=window_days - 1)

    pairs: list[tuple[date, float]] = []

    for day, value in series:
        if value is None:
            continue
        if first_day_in_window <= day <= on:
            pairs.append((day, value))

    return pairs


def mean_over(series: Series, on: date, window_days: int) -> float | None:
    """The average value across the window, or None if nothing was recorded."""
    pairs = window(series, on, window_days)

    if not pairs:
        return None

    values = [value for _day, value in pairs]
    return sum(values) / len(values)


def period_comparison(
    series: Series,
    metric: str,
    on: date,
    *,
    window_days: int = 30,
) -> models.PeriodComparison | None:
    """Compare the last N days against the N days before them.

    This is the "how does this month compare with last month?" calculation. Both
    period sizes are reported so a thin period is visible rather than hidden -- an
    average of three days looks identical to an average of thirty otherwise.
    """
    current_period = window(series, on, window_days)

    # Step the window back by its own length to get the period before it.
    day_before_current_period = on - timedelta(days=window_days)
    previous_period = window(series, day_before_current_period, window_days)

    if not current_period:
        return None
    if not previous_period:
        return None

    current_values = [value for _day, value in current_period]
    previous_values = [value for _day, value in previous_period]

    current_average = sum(current_values) / len(current_values)
    previous_average = sum(previous_values) / len(previous_values)

    difference = current_average - previous_average

    if previous_average != 0:
        difference_percent = (difference / previous_average) * 100.0
    else:
        difference_percent = 0.0

    return models.PeriodComparison(
        metric=metric,
        window_days=window_days,
        current_mean=current_average,
        previous_mean=previous_average,
        difference=difference,
        difference_percent=difference_percent,
        current_n=len(current_period),
        previous_n=len(previous_period),
    )


def correlation(
    series_a: Series,
    series_b: Series,
    metric_a: str,
    metric_b: str,
    *,
    min_n: int = MIN_CORRELATION_N,
) -> models.CorrelationResult | None:
    """Measure whether two metrics tend to move together.

    Returns Pearson's r, which runs from -1 to +1:

        +1   they move up and down in perfect lockstep
         0   no relationship at all
        -1   when one goes up, the other reliably goes down

    Only days where BOTH metrics were recorded are used -- you cannot compare a day's
    sleep against a weight you never measured.

    THE MINIMUM SAMPLE SIZE IS THE IMPORTANT PART. Given forty days of data and enough
    metrics to pair up, you will find impressive-looking correlations that are pure
    coincidence. An r of 0.6 across twelve days is noise wearing a number's clothes. The
    check lives inside this function rather than as a warning in the UI, so that no
    caller -- including the future LLM query layer, which is the caller most likely to
    ask for a correlation over almost no data -- can skip it.
    """
    # Build lookups so we can find the days the two metrics have in common.
    values_a: dict[date, float] = {}
    for day, value in series_a:
        if value is not None:
            values_a[day] = value

    values_b: dict[date, float] = {}
    for day, value in series_b:
        if value is not None:
            values_b[day] = value

    days_with_both = sorted(set(values_a.keys()) & set(values_b.keys()))
    number_of_days = len(days_with_both)

    if number_of_days < min_n:
        return None

    a_values: list[float] = []
    b_values: list[float] = []
    for day in days_with_both:
        a_values.append(values_a[day])
        b_values.append(values_b[day])

    average_a = sum(a_values) / number_of_days
    average_b = sum(b_values) / number_of_days

    # Pearson's r needs three running totals, each measuring how far values sit from
    # their own average:
    #
    #   spread_a       how much metric A varies on its own
    #   spread_b       how much metric B varies on its own
    #   joint_spread   whether they vary together (the part that carries the answer)
    spread_a = 0.0
    spread_b = 0.0
    joint_spread = 0.0

    for a_value, b_value in zip(a_values, b_values, strict=True):
        a_difference = a_value - average_a
        b_difference = b_value - average_b

        spread_a += a_difference * a_difference
        spread_b += b_difference * b_difference
        joint_spread += a_difference * b_difference

    # If either metric never changed, "do they move together?" has no answer -- one of
    # them did not move at all.
    if spread_a == 0:
        return None
    if spread_b == 0:
        return None

    r = joint_spread / ((spread_a * spread_b) ** 0.5)

    return models.CorrelationResult(metric_a=metric_a, metric_b=metric_b, r=r, n=number_of_days)


def streak(
    days: Sequence[tuple[date, bool]],
    on: date,
    *,
    max_lookback: int = 400,
) -> int:
    """Count how many days in a row, ending on `on`, something was true.

    A MISSING DAY BREAKS THE STREAK. Not having a record for a day is not evidence that
    the condition was met -- most likely nothing was logged at all.
    """
    was_true_on_day = dict(days)

    days_in_a_row = 0

    for days_back in range(max_lookback):
        day_being_checked = on - timedelta(days=days_back)

        # `.get` returns None for a day with no record, which is not True, so the
        # streak ends there just as a False would end it.
        if was_true_on_day.get(day_being_checked) is not True:
            break

        days_in_a_row += 1

    return days_in_a_row


def build_series(
    snapshots: Sequence[object],
    extractor: Callable[[object], float | None],
    dates: Sequence[date],
) -> list[tuple[date, float | None]]:
    """Pull one metric out of a list of snapshots into the (day, value) shape used here.

    `extractor` is a small function saying which field to read, for example
    `lambda snapshot: snapshot.measured.heart.hrv_ms`.
    """
    pairs: list[tuple[date, float | None]] = []

    for day, snapshot in zip(dates, snapshots, strict=True):
        pairs.append((day, extractor(snapshot)))

    return pairs
