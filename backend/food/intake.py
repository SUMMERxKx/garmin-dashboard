"""What a day's eating added up to, when it was typed in as one number.

Why this exists beside the food log
-----------------------------------
The food log records what you ate item by item, with macros. That is the better record
and it stays the better record. But on a fixed diet most days are the same day, and the
question the energy panel asks is only "how many calories went in?". A single typed
number answers it in five seconds, so it is allowed as a second route in.

Two rules, and both are decisions rather than mechanics:

**1. A typed total beats the food log for the same day.**
If you took the trouble to type a total, it is because the log was wrong or incomplete
for that day -- a meal out, a day you did not bother logging item by item. The typed
number is your statement about the WHOLE day; the log might be half of it.

**2. A day with nothing recorded is assumed to be the same as the last day that was.**
This is the one place in the project that carries a value forward, and it is worth
being clear about why it is allowed here and nowhere else. Weight is never carried
forward because an invented weigh-in is indistinguishable from a real one afterwards,
and every later calculation would count it as "no change". Intake is different in two
ways: the diet is genuinely the same most days, so the assumption is usually right; and
the carried value is LABELLED as carried, with the day it came from, so it can never be
mistaken for a measurement. Strip the label and this rule becomes the same mistake.

Nothing here reads the clock or the database. The span and the records come in as
arguments, which is what makes the rule testable with a fixed list of days.
"""

from __future__ import annotations

import dataclasses
import datetime

#: The three places a day's intake figure can come from. Sent over the wire as text,
#: so the dashboard can draw an assumed day differently from a recorded one.
SOURCE_MANUAL = "manual"
SOURCE_LOGGED = "logged"
SOURCE_CARRIED = "carried"

#: Sanity bounds on a typed total. These catch typing mistakes -- a dropped digit, an
#: extra zero -- not dietary judgements. The floor is 500 because a dropped digit from
#: any ordinary day (2,100 -> 210) lands well under it, while a genuinely tiny day is a
#: fast, which is a different thing to record. 10,000 is beyond what a day of eating
#: produces.
LOWEST_BELIEVABLE_KILOCALORIES = 500.0
HIGHEST_BELIEVABLE_KILOCALORIES = 10_000.0


@dataclasses.dataclass
class ManualIntake:
    """One typed-in total for one day, exactly as entered."""

    day: datetime.date
    kilocalories: float
    recorded_at: datetime.datetime

    #: Free text, if you want to remember why the day was typed in rather than logged
    #: ("dinner out", "travel"). Optional, and never used in any calculation.
    note: str | None = None


@dataclasses.dataclass
class DailyIntake:
    """What the dashboard is told a day's intake was, and how much to trust it.

    `source` says which of the three rules produced the number. `from_day` says which
    day the number was actually recorded on: the same day for a manual or logged figure,
    and an earlier day for a carried one. The dashboard shows both, because "2,078 kcal,
    assumed from 14 Sep" and "2,078 kcal, logged" are different kinds of fact.
    """

    kilocalories: float
    source: str
    from_day: datetime.date


def describe_problem(kilocalories: float) -> str | None:
    """Say what is wrong with a typed total, or None if it looks believable.

    A sentence rather than an exception, so the command line and the API can both print
    it and stop. The two mistakes this catches are a dropped digit (210 for 2,100) and an
    extra one (21,000).
    """
    if kilocalories <= 0:
        return "A day's intake has to be greater than zero."

    if kilocalories < LOWEST_BELIEVABLE_KILOCALORIES:
        return (
            f"{kilocalories:g} kcal is too little to be a whole day's eating."
            " Did you drop a digit?"
        )

    if kilocalories > HIGHEST_BELIEVABLE_KILOCALORIES:
        return (
            f"{kilocalories:g} kcal is more than a day of eating produces."
            " Did you add a digit?"
        )

    return None


def resolve_intake_for_span(
    days_in_order: list[datetime.date],
    manual_by_day: dict[datetime.date, ManualIntake],
    logged_kilocalories_by_day: dict[datetime.date, float],
) -> dict[datetime.date, DailyIntake | None]:
    """Decide, for every day in the span, what its intake figure is and where it came from.

    Walks the days oldest to newest, applying the two rules from the module docstring:
    a typed total wins, then the food log, and a day with neither inherits the most
    recent day that had one. Days before the first recorded figure get None -- there is
    nothing yet to carry, and inventing a number there would be a guess with no source.

    `days_in_order` must be oldest first. The carry only works forwards in time, and a
    list passed in newest-first would silently carry tomorrow's figure into yesterday.
    """
    resolved: dict[datetime.date, DailyIntake | None] = {}

    # The most recent day that had a real figure, and what it was. None until the first
    # recorded day is reached.
    last_known: DailyIntake | None = None

    for day in days_in_order:
        if day in manual_by_day:
            todays_figure = DailyIntake(
                kilocalories=manual_by_day[day].kilocalories,
                source=SOURCE_MANUAL,
                from_day=day,
            )
        elif day in logged_kilocalories_by_day:
            todays_figure = DailyIntake(
                kilocalories=logged_kilocalories_by_day[day],
                source=SOURCE_LOGGED,
                from_day=day,
            )
        elif last_known is not None:
            # Carried. The kilocalories are copied but `from_day` is NOT updated, so a
            # figure carried across five days still points at the one morning it was
            # actually recorded. That is what keeps rule 2 honest.
            todays_figure = DailyIntake(
                kilocalories=last_known.kilocalories,
                source=SOURCE_CARRIED,
                from_day=last_known.from_day,
            )
        else:
            todays_figure = None

        resolved[day] = todays_figure

        # Only a real figure becomes the thing later days inherit. A carried day does
        # not, or its `from_day` would drift forward one day at a time.
        if todays_figure is not None and todays_figure.source != SOURCE_CARRIED:
            last_known = todays_figure

    return resolved
