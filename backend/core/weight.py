"""Weight: always look at the trend, never at a single reading.

One morning's weigh-in is mostly water. Salt, carbohydrate, how much you drank, whether
you have been to the bathroom -- all of it moves the number by a kilogram or more, which
is far bigger than a week of real fat loss. So every function here is about the shape of
the line, not the last point on it.

Weight is entered by hand, so gaps are expected and normal. Nothing here fills a gap in
with a made-up number: if there is not enough data, the answer is None.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from datetime import timedelta

from backend.core import models
from backend.core import reasons

# A list of (day, weight in kilograms) pairs. Days can be missing.
Series = Sequence[tuple[date, float]]

# A weekly change smaller than this is treated as "no real movement".
FLAT_SLOPE_KG_PER_WEEK = 0.1

# If day-to-day scatter is bigger than this, water movement is drowning out the signal
# and we refuse to draw a conclusion about a plateau.
NOISY_SD_KG = 0.8


def exponential_weight_for_gap(days_since_last_reading: float, halflife_days: float) -> float:
    """How much a new reading should move the running average.

    This is what makes the average handle missing days correctly. If you weigh yourself
    every morning, each reading should only nudge the average. If you skip five days,
    the next reading is much more informative and should move it further.

    The formula is `1 - 0.5 ** (gap / halflife)`. "Halflife" means: after this many
    days, half the weight of the old average has decayed away.

    With a 7-day halflife:
        gap of 1 day   -> 0.09  (a small nudge)
        gap of 7 days  -> 0.50  (move halfway to the new reading)
        gap of 14 days -> 0.75  (the old average barely matters now)
    """
    return 1.0 - 0.5 ** (days_since_last_reading / halflife_days)


def ema(series: Series, *, halflife_days: float = 7.0) -> list[tuple[date, float]]:
    """Smooth the weight series, returning (day, smoothed value) for each reading.

    EMA stands for "exponential moving average": a running average that gives recent
    readings more importance than old ones.

    A plain EMA assumes your readings are evenly spaced. Ours are not, because weighing
    in is manual and gets skipped, so the gap between readings is taken into account.
    """
    readings_oldest_first = sorted(series, key=lambda pair: pair[0])

    smoothed: list[tuple[date, float]] = []
    running_average: float | None = None
    previous_day: date | None = None

    for day, weight_today in readings_oldest_first:
        if running_average is None or previous_day is None:
            # The very first reading has nothing to average with, so it IS the average.
            running_average = weight_today
        else:
            # `max(..., 1)` guards against two readings on the same day, which would
            # otherwise give a gap of 0 and a weight of 0 (no movement at all).
            days_since_last = max((day - previous_day).days, 1)
            weight_for_this_reading = exponential_weight_for_gap(days_since_last, halflife_days)

            # Move the running average part of the way toward the new reading.
            distance_to_new_reading = weight_today - running_average
            running_average = running_average + weight_for_this_reading * distance_to_new_reading

        previous_day = day
        smoothed.append((day, running_average))

    return smoothed


def ema_on(series: Series, on: date, *, halflife_days: float = 7.0) -> float | None:
    """The smoothed weight as of one particular day.

    Only readings up to and including that day are used, so asking about a past date
    gives the answer as it would have looked back then, not one informed by the future.
    """
    readings_up_to_that_day = []
    for day, weight in series:
        if day <= on:
            readings_up_to_that_day.append((day, weight))

    if not readings_up_to_that_day:
        return None

    smoothed = ema(readings_up_to_that_day, halflife_days=halflife_days)

    # The last entry is the most recent, which is the value on `on`.
    last_day_and_value = smoothed[-1]
    return last_day_and_value[1]


def rolling_mean(series: Series, on: date, window_days: int) -> float | None:
    """The plain average weight over the last `window_days` days, ending on `on`."""
    first_day_in_window = on - timedelta(days=window_days - 1)

    weights_in_window = []
    for day, weight in series:
        if first_day_in_window <= day <= on:
            weights_in_window.append(weight)

    if not weights_in_window:
        return None

    return sum(weights_in_window) / len(weights_in_window)


def change_over(series: Series, on: date, days: int) -> float | None:
    """How much the smoothed weight changed over the last `days` days.

    Deliberately compares two SMOOTHED values rather than two raw readings. Comparing
    raw readings would mostly measure how hydrated you happened to be on two particular
    mornings, which can easily be a kilogram of noise on top of the real change.
    """
    smoothed_now = ema_on(series, on)
    smoothed_then = ema_on(series, on - timedelta(days=days))

    if smoothed_now is None or smoothed_then is None:
        return None

    return smoothed_now - smoothed_then


def trend(series: Series, on: date, *, window_days: int = 28) -> models.TrendResult | None:
    """Fit a straight line through the weights and report its slope.

    This is "least squares" linear regression: find the straight line that comes
    closest to all the points, then report how steep it is.

    Returns None if there are fewer than three readings, because two points always fit
    a line perfectly and would give a confident-looking answer built on nothing.
    """
    first_day_in_window = on - timedelta(days=window_days - 1)

    readings_in_window = []
    for day, weight in series:
        if first_day_in_window <= day <= on:
            readings_in_window.append((day, weight))

    readings_in_window.sort(key=lambda pair: pair[0])

    number_of_readings = len(readings_in_window)
    if number_of_readings < 3:
        return None

    # Convert dates into plain numbers so we can do arithmetic with them: day 0 is the
    # first reading in the window, and every other reading is "days since that one".
    first_day = readings_in_window[0][0]
    days_since_start: list[float] = []
    weights: list[float] = []
    for day, weight in readings_in_window:
        days_since_start.append(float((day - first_day).days))
        weights.append(weight)

    average_day = sum(days_since_start) / number_of_readings
    average_weight = sum(weights) / number_of_readings

    # Least squares needs three running totals. Each one measures how far the values
    # sit from their own average:
    #
    #   spread_in_days      how spread out the reading dates are
    #   spread_in_weights   how spread out the weights are
    #   joint_spread        whether days and weights move together (the key one)
    spread_in_days = 0.0
    spread_in_weights = 0.0
    joint_spread = 0.0

    for day_number, weight in zip(days_since_start, weights, strict=True):
        day_difference = day_number - average_day
        weight_difference = weight - average_weight

        spread_in_days += day_difference * day_difference
        spread_in_weights += weight_difference * weight_difference
        joint_spread += day_difference * weight_difference

    # All readings landed on the same day, so there is no time axis to fit a line to.
    if spread_in_days == 0:
        return None

    # The slope is the change in weight per day.
    slope_per_day = joint_spread / spread_in_days

    # R squared says how well the line actually fits, from 0 (useless) to 1 (perfect).
    # It lets the dashboard show how much to trust the slope.
    if spread_in_weights > 0:
        r_squared = (joint_spread * joint_spread) / (spread_in_days * spread_in_weights)
    else:
        # Every weight was identical, so the line fits perfectly but explains nothing.
        r_squared = 0.0

    return models.TrendResult(
        slope_per_day=slope_per_day,
        slope_per_week=slope_per_day * 7.0,
        r_squared=r_squared,
        n=number_of_readings,
        window_days=window_days,
    )


def rate_of_change(series: Series, on: date, *, window_days: int = 14) -> float | None:
    """How fast the weight is moving, in kilograms per week."""
    result = trend(series, on, window_days=window_days)

    if result is None:
        return None

    return result.slope_per_week


def standard_deviation(values: Sequence[float]) -> float:
    """How spread out a set of numbers is.

    Roughly: the average distance of each value from the group's average. A small
    number means the readings are clustered together; a large one means they jump
    around. Here it tells us how much day-to-day water movement there is.

    Needs at least two values to mean anything, so one value gives 0.0.
    """
    count = len(values)
    if count < 2:
        return 0.0

    average = sum(values) / count

    total_squared_distance = 0.0
    for value in values:
        distance_from_average = value - average
        total_squared_distance += distance_from_average * distance_from_average

    # Dividing by (count - 1) rather than count is the standard correction for
    # measuring the spread of a sample rather than a whole population.
    variance = total_squared_distance / (count - 1)
    return variance**0.5


def plateau(
    series: Series,
    on: date,
    *,
    window_days: int = 21,
    flat_slope: float = FLAT_SLOPE_KG_PER_WEEK,
    noisy_sd: float = NOISY_SD_KG,
) -> models.PlateauResult | None:
    """Work out whether a flat-looking weight is a real stall or just water.

    Three possible answers:

      1. Flat AND steady            -> a genuine plateau
      2. Flat BUT jumping around    -> we refuse to call it; the noise is bigger
                                       than the signal
      3. Actually moving            -> not a plateau, report the direction

    Case 2 is the one that matters. A high-salt weekend can hold your weight up for a
    week and make a working diet look broken. Cutting calories in response to that is
    the classic mistake, so when the scatter is large we say so instead of guessing.
    """
    line = trend(series, on, window_days=window_days)
    if line is None:
        return None

    first_day_in_window = on - timedelta(days=window_days - 1)
    weights_in_window = []
    for day, weight in series:
        if first_day_in_window <= day <= on:
            weights_in_window.append(weight)

    scatter = standard_deviation(weights_in_window)

    weight_is_flat = abs(line.slope_per_week) < flat_slope
    readings_are_noisy = scatter > noisy_sd

    is_plateau = weight_is_flat and not readings_are_noisy

    trend_reasons: list[reasons.Reason] = []

    if is_plateau:
        trend_reasons.append(
            reasons.Reason(
                code=reasons.ReasonCode.PLATEAU_DETECTED,
                metric="weight_kg",
                window_days=window_days,
                n=len(weights_in_window),
            )
        )
    elif weight_is_flat and readings_are_noisy:
        trend_reasons.append(
            reasons.Reason(
                code=reasons.ReasonCode.LIKELY_WATER_FLUCTUATION,
                metric="weight_kg",
                window_days=window_days,
                n=len(weights_in_window),
            )
        )
    else:
        # The weight is genuinely moving, so report which way.
        if line.slope_per_week < 0:
            direction_code = reasons.ReasonCode.WEIGHT_TREND_DOWN
        else:
            direction_code = reasons.ReasonCode.WEIGHT_TREND_UP

        trend_reasons.append(
            reasons.Reason(
                code=direction_code,
                metric="weight_kg",
                window_days=window_days,
                n=len(weights_in_window),
                detail={
                    "rate": round(abs(line.slope_per_week), 2),
                    "window": window_days,
                },
            )
        )

    return models.PlateauResult(
        is_plateau=is_plateau,
        window_days=window_days,
        slope_per_week=line.slope_per_week,
        sd=scatter,
        n=len(weights_in_window),
        reasons=trend_reasons,
    )
