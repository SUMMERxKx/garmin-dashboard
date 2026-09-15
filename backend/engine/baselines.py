"""Personal baselines: what is normal FOR YOU, and whether today departs from it.

The problem this solves
-----------------------
`HRV 96` is not information. The same 96 is reassuring for one person and alarming for
another, and it is reassuring or alarming for the SAME person depending on what their
last month looked like. A number only becomes a fact about you once there is something
of yours to compare it against.

So every metric on the dashboard gets a rolling baseline built from your own history,
and today is reported as a position relative to that rather than as a bare value.

Why insufficient data returns None rather than an estimate
----------------------------------------------------------
A baseline computed from four readings is worse than no baseline: it carries all the
authority of a real one and none of the reliability, and the screen gives no hint which
kind it is looking at. So there is a documented minimum per window, and below it this
returns None. The caller is expected to say "still building baseline (12 of 15 days)"
rather than to invent something.

HRV is the sharpest case. Garmin needs about three weeks of nights before its own HRV
figures settle, and a baseline built during that period is measuring the watch learning
about you, not you.

Nothing here reads the clock
----------------------------
The window is defined by the newest reading given, not by today. That is what makes a
baseline for a day three weeks ago computable, and it is what makes every function here
testable with a fixed list of numbers.
"""

from __future__ import annotations

import dataclasses
import datetime
import statistics

#: How many readings a window needs before its baseline is trustworthy enough to show.
#: These are judgment calls, not arithmetic -- they trade "tells you something sooner"
#: against "tells you something wrong". They are deliberately a little above half the
#: window: a 30-day baseline built from 8 scattered readings is a different animal from
#: one built from 28.
MINIMUM_READINGS_BY_WINDOW = {
    7: 5,
    14: 9,
    30: 18,
    90: 45,
}

#: The fallback for a window not in the table above: three fifths of it, rounded up.
MINIMUM_READINGS_FRACTION = 0.6

#: A change smaller than this fraction of the baseline is called typical regardless of
#: what the arithmetic says. Without it, a metric with very little scatter would report
#: a meaningless half-percent move as "unusual" and the reader would learn to ignore the
#: verdict entirely -- which costs more than the occasional missed signal.
MINIMUM_RELATIVE_BAND = 0.03

#: How many standard deviations from the mean before a reading is called unusual. Around
#: two thirds of readings fall within one standard deviation, so this fires often enough
#: to be useful and rarely enough to mean something.
UNUSUAL_STANDARD_DEVIATIONS = 1.0


@dataclasses.dataclass
class Baseline:
    """What normal looks like for one metric over one window."""

    metric_name: str
    window_days: int
    mean: float
    standard_deviation: float
    sample_size: int
    oldest_day: datetime.date
    newest_day: datetime.date

    def describe_coverage(self) -> str:
        """How much of the window actually had readings, in words."""
        return f"{self.sample_size} readings across {self.window_days} days"


@dataclasses.dataclass
class Deviation:
    """Where one reading sits against a baseline."""

    value: float
    baseline: Baseline
    difference: float
    relative_difference: float

    #: How many standard deviations from the mean. None when the baseline has no
    #: scatter at all, which happens with integer metrics that did not move all month --
    #: dividing by that zero would produce an infinity, not an insight.
    standard_deviations: float | None

    #: "typical", "above" or "below". Purely positional: it says where the number sits,
    #: never whether that is good. Whether above is good depends on the metric, and that
    #: judgement belongs with the caller who knows which metric this is.
    position: str


def minimum_readings_for(window_days: int) -> int:
    """How many readings this window needs before a baseline is worth showing."""
    if window_days in MINIMUM_READINGS_BY_WINDOW:
        return MINIMUM_READINGS_BY_WINDOW[window_days]

    # Round up, so a window is never satisfied by fewer readings than the fraction says.
    needed = window_days * MINIMUM_READINGS_FRACTION

    return int(needed) + (1 if needed > int(needed) else 0)


def readings_within_window(
    readings: list[tuple[datetime.date, float | None]],
    window_days: int,
    ending_on: datetime.date,
) -> list[float]:
    """The values that fall inside the window, ignoring days with no reading.

    `ending_on` is passed in rather than taken from the clock, which is what lets a
    baseline be computed for any day in the past -- and what lets every test here use a
    fixed date instead of whatever day it happens to be run on.

    The window INCLUDES its end day. A 7-day window ending on the 14th covers the 8th to
    the 14th, which is seven days, not eight.
    """
    oldest_allowed = ending_on - datetime.timedelta(days=window_days - 1)

    values = []

    for day, value in readings:
        if value is None:
            continue

        if day < oldest_allowed:
            continue

        if day > ending_on:
            continue

        values.append(value)

    return values


def build_baseline(
    metric_name: str,
    readings: list[tuple[datetime.date, float | None]],
    window_days: int,
    ending_on: datetime.date,
) -> Baseline | None:
    """Build one baseline, or return None if there is not enough to build one honestly.

    None is a real answer here and the caller must handle it. It means "we do not know
    what normal looks like for you yet", which is the truth during the first weeks of
    owning a watch and after any long gap in wearing it.
    """
    values = readings_within_window(readings, window_days, ending_on)

    if len(values) < minimum_readings_for(window_days):
        return None

    # `pstdev` treats these readings as the whole population rather than a sample drawn
    # from a larger one, which is the right description here: this IS every reading in
    # the window, not a sample of them.
    scatter = statistics.pstdev(values) if len(values) > 1 else 0.0

    days_present = []

    for day, value in readings:
        if value is not None and day <= ending_on:
            oldest_allowed = ending_on - datetime.timedelta(days=window_days - 1)
            if day >= oldest_allowed:
                days_present.append(day)

    return Baseline(
        metric_name=metric_name,
        window_days=window_days,
        mean=statistics.mean(values),
        standard_deviation=scatter,
        sample_size=len(values),
        oldest_day=min(days_present),
        newest_day=max(days_present),
    )


def compare_to(value: float | None, baseline: Baseline | None) -> Deviation | None:
    """Place one reading against a baseline, or None if either is missing.

    The verdict is positional only -- "above", "below", "typical". Whether above is good
    news depends entirely on the metric: a high HRV is encouraging and a high resting
    heart rate is not. That judgement needs to know which metric this is, so it lives
    with the caller rather than being guessed at here.
    """
    if value is None:
        return None

    if baseline is None:
        return None

    difference = value - baseline.mean

    if baseline.mean == 0:
        # Guarding a division rather than expecting it: a mean of zero is possible for
        # a metric like vigorous intensity minutes across a quiet fortnight.
        relative = 0.0
    else:
        relative = difference / baseline.mean

    if baseline.standard_deviation == 0:
        standard_deviations = None
    else:
        standard_deviations = difference / baseline.standard_deviation

    position = decide_position(relative, standard_deviations)

    return Deviation(
        value=value,
        baseline=baseline,
        difference=difference,
        relative_difference=relative,
        standard_deviations=standard_deviations,
        position=position,
    )


def decide_position(relative: float, standard_deviations: float | None) -> str:
    """Decide whether a reading counts as above, below or simply typical.

    Two conditions, and BOTH have to be satisfied before a reading is called unusual:

      1. it is at least a standard deviation from the mean, and
      2. it is at least MINIMUM_RELATIVE_BAND away in proportional terms.

    The second exists because the first alone misfires on steady metrics. A resting
    heart rate that sat between 43 and 45 all month has a tiny standard deviation, so
    44 to 46 is "two standard deviations" -- arithmetically true and practically
    meaningless. Requiring a real proportional change as well keeps the verdict worth
    reading.
    """
    if standard_deviations is None:
        return "typical"

    if abs(standard_deviations) < UNUSUAL_STANDARD_DEVIATIONS:
        return "typical"

    if abs(relative) < MINIMUM_RELATIVE_BAND:
        return "typical"

    if standard_deviations > 0:
        return "above"

    return "below"
