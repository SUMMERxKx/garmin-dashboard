"""Weigh-ins: the number that decides whether everything else was right.

Why this small file matters more than its size suggests
-------------------------------------------------------
Garmin estimates what you burned. The food log records what you believe you ate. Both
carry known error -- Garmin overstates resistance-training calories, and a food log is
only as good as the weighing behind it. Neither can be checked against itself.

Measured weight is what checks them. If the numbers say you are eating 500 kcal under
maintenance and your weight has not moved in three weeks, the numbers are wrong,
whatever they claim. That comparison is the whole idea behind observed maintenance, and
it cannot be made without a record of weight over time.

There is no smart scale here, so every reading is typed in by hand.

One reading is noise
--------------------
Day-to-day weight moves by a kilogram or more on water, salt, glycogen and what is
simply still inside you. Nothing here tries to hide that: a weigh-in is recorded exactly
as it was read. Smoothing is a job for the engine, later, where the method is visible
and can be argued with -- not something applied quietly on the way into storage.
"""

from __future__ import annotations

import dataclasses
import datetime

#: A human weight in kilograms sits well inside these. The check exists to catch the
#: obvious typing mistakes -- a weight in POUNDS (173 rather than 78), or a missing
#: decimal point (784) -- not to make a medical judgement about anybody's body.
LOWEST_BELIEVABLE_KILOGRAMS = 25.0
HIGHEST_BELIEVABLE_KILOGRAMS = 300.0

#: Above this, the number was almost certainly meant to be pounds. 300 kg is beyond the
#: heaviest recorded human, while 300 lb is an ordinary weight, so the two ranges do not
#: overlap in practice.
LIKELY_POUNDS_ABOVE = 300.0


@dataclasses.dataclass
class Weighing:
    """One weigh-in, exactly as it was read off the scale."""

    day: datetime.date
    kilograms: float
    recorded_at: datetime.datetime

    #: Where the number came from: typed in here, or read from Garmin Connect. Kept
    #: because the two can disagree, and knowing which you are looking at matters more
    #: than the disagreement itself.
    source: str = "manual"

    #: Body fat percentage, if the scale reported one that morning. Optional because
    #: most mornings will not have it, and None means "not measured" rather than zero.
    #:
    #: This is NOT the same measurement as a DEXA fat percentage and must never be shown
    #: as though it were. A scale estimates body fat by passing a small current through
    #: the body and inferring composition from the resistance, which moves with how
    #: hydrated you are, what you ate and how warm your feet are -- it can swing a couple
    #: of points between two mornings that were physically identical. A DEXA measures it.
    #: The scale reading is useful for its TREND over weeks; the scan is the anchor that
    #: says what the trend is a trend around.
    fat_percent: float | None = None


def describe_problem(kilograms: float) -> str | None:
    """Say what is wrong with a weight, or None if it looks fine.

    Returns a sentence rather than raising, so the command can print it and stop
    without a stack trace. The point is to catch the two mistakes that are easy to make
    and hard to notice afterwards: entering pounds, and missing the decimal point.
    """
    if kilograms <= 0:
        return "A weight has to be greater than zero."

    if kilograms > LIKELY_POUNDS_ABOVE:
        return (
            f"{kilograms:g} kg is beyond any recorded human weight."
            f" Did you mean pounds? {kilograms:g} lb is"
            f" {kilograms * 0.45359237:.1f} kg."
        )

    if kilograms < LOWEST_BELIEVABLE_KILOGRAMS:
        return f"{kilograms:g} kg looks too low to be a whole-body weight."

    return None


#: A jump larger than this from your most recent weigh-in is treated as suspicious. Real
#: day-to-day swings of a kilogram or two happen on water and food weight; three is
#: already unusual, and the mistakes this catches are far bigger than that.
SUSPICIOUS_JUMP_KILOGRAMS = 3.0


def describe_jump(previous: Weighing | None, kilograms: float) -> str | None:
    """Say whether a new weight is implausibly far from the last one, or None if not.

    This catches what a fixed range cannot. 173.89 sits comfortably inside any sane
    range of human weights, so nothing about the number alone is wrong -- but it is
    your weight in POUNDS, and it is 95 kg away from what you weighed last week. The
    same goes for a slipped decimal point.

    Compared against your own last reading rather than against a table, because the
    question is not "is this a possible weight" but "is this a possible weight for the
    person who weighed 80.0 kg four days ago".
    """
    if previous is None:
        # Nothing to compare against yet. The fixed range in `describe_problem` is the
        # only guard on a first weigh-in, and that is the best that can be done.
        return None

    jump = abs(kilograms - previous.kilograms)

    if jump <= SUSPICIOUS_JUMP_KILOGRAMS:
        return None

    return (
        f"{kilograms:g} kg is {jump:.1f} kg away from your last weigh-in"
        f" ({previous.kilograms:g} kg on {previous.day.isoformat()})."
    )


def newest_first(weighings: list[Weighing]) -> list[Weighing]:
    """Most recent weigh-in first. Useful for "what do I weigh now?"."""
    return sorted(weighings, key=lambda one: one.day, reverse=True)


def change_between(earlier: Weighing, later: Weighing) -> tuple[float, int]:
    """How much weight changed between two weigh-ins, and over how many days.

    Returned as a pair rather than as a rate, because a rate hides its own sample size:
    "0.4 kg per week" reads the same whether it came from two weeks or from two days,
    and only one of those is worth acting on.
    """
    difference = later.kilograms - earlier.kilograms
    days_between = (later.day - earlier.day).days

    return (difference, days_between)
