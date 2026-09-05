"""Personal baselines -- the idea the whole dashboard is built on.

"HRV = 48" tells you nothing. "HRV 48, which is 14% below your 30-day average of 56"
tells you something. Almost every question this app answers is really the question
"compared to my own normal?", which is why baselines are needed by the main screen and
not just by the charts.

Four rules this module sticks to:

  * ROLLING, not calendar. "The last 30 days from today", not "this month".
  * PERSONAL, never population. Your baseline is yours. Comparing you to other
    23-year-olds would be a different product.
  * TODAY IS EXCLUDED from its own baseline. Otherwise you are partly comparing today
    against itself, which flattens out any deviation.
  * NOT ENOUGH DATA IS AN ANSWER. If there are too few readings we return None, which
    the screen shows as "still building your baseline (12 of 15 days)". A baseline
    calculated from four readings would look authoritative and mean nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from datetime import timedelta

from backend.core import models
from backend.core import reasons

# A list of (day, value) pairs. A value of None means "not reported that day" -- those
# are skipped rather than counted as zero, which would drag the average down.
Series = Sequence[tuple[date, float | None]]

# The "normal" band is never allowed to be narrower than this fraction of the average.
# See `band_for` for why.
MINIMUM_RELATIVE_BAND = 0.03


def default_min_n(window_days: int) -> int:
    """How many readings a window needs before its baseline is trustworthy.

    Half the window length, but never fewer than 3. So a 30-day baseline needs 15
    readings, and a 7-day baseline needs 3.

    Half is a judgement call, not a statistical law: it is enough that a couple of odd
    days cannot dominate, while not making you wait a full month before the screen
    shows anything useful.
    """
    minimum = window_days // 2

    if minimum < 3:
        return 3

    return minimum


def window_values(
    series: Series,
    on: date,
    window_days: int,
    *,
    exclude_on: bool = True,
) -> list[float]:
    """Collect the values inside the baseline window.

    The window covers the `window_days` days leading up to `on`. By default `on` itself
    is left out, because a baseline should be something to compare today against, not
    something today has already influenced.

    Days with no reading are skipped entirely.
    """
    earliest_day_wanted = on - timedelta(days=window_days)

    values: list[float] = []

    for day, value in series:
        # No reading that day -- skip it rather than treating it as zero.
        if value is None:
            continue

        # Too far in the past to be in the window.
        if day < earliest_day_wanted:
            continue

        # In the future relative to the day we are asking about.
        if day > on:
            continue

        # `on` itself: included only if the caller explicitly asked for it.
        if day == on and exclude_on:
            continue

        values.append(value)

    return values


def baseline(
    series: Series,
    metric: str,
    window_days: int,
    on: date,
    *,
    min_n: int | None = None,
) -> models.Baseline | None:
    """Work out this person's normal for one metric, or return None if we cannot yet.

    Returns the average, the spread (standard deviation), and how many readings went
    into it -- so anything downstream can say how solid the comparison is.
    """
    values = window_values(series, on, window_days)

    if min_n is None:
        readings_required = default_min_n(window_days)
    else:
        readings_required = min_n

    if len(values) < readings_required:
        return None

    average = sum(values) / len(values)

    # Standard deviation: how spread out the readings are around their average.
    if len(values) > 1:
        total_squared_distance = 0.0
        for value in values:
            distance_from_average = value - average
            total_squared_distance += distance_from_average * distance_from_average

        # (n - 1) rather than n is the standard correction when measuring the spread of
        # a sample rather than an entire population.
        variance = total_squared_distance / (len(values) - 1)
        spread = variance**0.5
    else:  # pragma: no cover - unreachable: `readings_required` is never below 3
        # Kept so the branch is defined rather than implied, in case the minimum is
        # ever lowered for a metric that needs less history.
        spread = 0.0

    return models.Baseline(
        metric=metric,
        mean=average,
        sd=spread,
        n=len(values),
        window_days=window_days,
        computed_on=on,
    )


def baseline_building_reason(
    series: Series,
    metric: str,
    window_days: int,
    on: date,
    *,
    min_n: int | None = None,
) -> reasons.Reason:
    """Explain that a baseline is not ready yet, and how far along it is.

    This is the honest alternative to making one up. The screen shows something like
    "still building your HRV baseline (12 of 15 days)".
    """
    values = window_values(series, on, window_days)

    if min_n is None:
        readings_required = default_min_n(window_days)
    else:
        readings_required = min_n

    return reasons.Reason(
        code=reasons.ReasonCode.BASELINE_BUILDING,
        metric=metric,
        n=len(values),
        window_days=window_days,
        detail={"required": readings_required},
    )


def band_for(base: models.Baseline, *, min_relative: float = MINIMUM_RELATIVE_BAND) -> float:
    """How far from the average still counts as "normal".

    Normally one standard deviation. But there is a floor of 3% of the average, and
    that floor is doing real work: if you happened to have an unusually consistent
    fortnight, the standard deviation could be almost zero, and then every trivial
    wobble would be flagged as a meaningful deviation.
    """
    one_standard_deviation = base.sd
    three_percent_of_average = abs(base.mean) * min_relative

    if one_standard_deviation > three_percent_of_average:
        return one_standard_deviation

    return three_percent_of_average


def status_of(
    current: float,
    base: models.Baseline,
    *,
    min_relative: float = MINIMUM_RELATIVE_BAND,
) -> models.Status:
    """Is today above, below, or within the normal band?

    Note this reports DIRECTION only, not whether it is good news. Higher HRV is good
    and a higher resting heart rate is bad, and that judgement belongs to whoever knows
    which metric they are looking at -- see `recovery.py`. Keeping it out of here is
    what lets this module stay reusable.
    """
    band = band_for(base, min_relative=min_relative)

    upper_edge_of_normal = base.mean + band
    lower_edge_of_normal = base.mean - band

    if current > upper_edge_of_normal:
        return models.Status.ABOVE

    if current < lower_edge_of_normal:
        return models.Status.BELOW

    return models.Status.NORMAL


def deviation(
    current: float | None,
    base: models.Baseline | None,
    *,
    min_relative: float = MINIMUM_RELATIVE_BAND,
) -> models.Deviation | None:
    """Compare today's value against the baseline, three different ways.

      difference          the raw gap, in the metric's own units
      difference_percent  the same gap as a percentage of normal
      z_score             the gap measured in standard deviations

    Percentage is what the screen shows because it is the easiest to read. The z-score
    is the statistically meaningful one: it accounts for how variable this metric
    normally is for you, so a 10% drop in a stable metric registers as more unusual
    than a 10% drop in a jumpy one.
    """
    if current is None:
        return None
    if base is None:
        return None

    difference = current - base.mean

    if base.mean != 0:
        difference_percent = (difference / base.mean) * 100.0
    else:
        # Guard against dividing by zero. A baseline average of exactly zero is not
        # something any of our metrics should produce.
        difference_percent = 0.0

    if base.sd > 0:
        z_score = difference / base.sd
    else:
        # Every reading was identical, so "how many standard deviations away" has no
        # meaning. None is more honest than infinity.
        z_score = None

    return models.Deviation(
        metric=base.metric,
        current=current,
        baseline=base.mean,
        difference=difference,
        difference_percent=difference_percent,
        z_score=z_score,
        status=status_of(current, base, min_relative=min_relative),
        window_days=base.window_days,
        n=base.n,
    )


def consecutive_beyond(
    series: Series,
    base: models.Baseline,
    *,
    direction: models.Status,
    on: date,
    max_lookback: int = 30,
    min_relative: float = MINIMUM_RELATIVE_BAND,
) -> int:
    """Count how many days in a row, ending on `on`, sat outside the normal band.

    A MISSING DAY BREAKS THE RUN. That is deliberate: five low readings spread across
    three weeks is not a five-day streak, and treating it as one would turn ordinary
    scattered readings into an alarming-looking pattern.
    """
    # Turn the series into a lookup so we can ask about specific days directly.
    value_by_day: dict[date, float] = {}
    for day, value in series:
        if value is not None:
            value_by_day[day] = value

    band = band_for(base, min_relative=min_relative)
    upper_edge_of_normal = base.mean + band
    lower_edge_of_normal = base.mean - band

    days_in_a_row = 0

    for days_back in range(max_lookback):
        day_being_checked = on - timedelta(days=days_back)
        value = value_by_day.get(day_being_checked)

        # No reading that day, so the run ends here.
        if value is None:
            break

        if direction is models.Status.BELOW:
            is_beyond_the_band = value < lower_edge_of_normal
        else:
            is_beyond_the_band = value > upper_edge_of_normal

        if not is_beyond_the_band:
            break

        days_in_a_row += 1

    return days_in_a_row
