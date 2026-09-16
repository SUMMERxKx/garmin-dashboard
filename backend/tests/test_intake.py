"""Tests for the day's-calories rule: typed beats logged, and gaps inherit -- labelled.

The carry-forward is the one place this project deliberately fills a gap, so the tests
here are mostly about the LABEL: a carried figure must always say it was carried and
which day it came from. Lose the label and the rule turns into the mistake it was
designed not to be.
"""

from __future__ import annotations

import datetime

from hypothesis import given
from hypothesis import strategies as st

from backend.food import intake

SEPTEMBER = datetime.date(2026, 9, 1)
LOGGED_AT = datetime.datetime(2026, 9, 1, 20, 0)


def day(offset: int) -> datetime.date:
    """The nth day of the test span."""
    return SEPTEMBER + datetime.timedelta(days=offset)


def a_span(length: int) -> list[datetime.date]:
    """`length` consecutive days, oldest first."""
    return [day(offset) for offset in range(length)]


def typed(on: datetime.date, kilocalories: float) -> intake.ManualIntake:
    return intake.ManualIntake(day=on, kilocalories=kilocalories, recorded_at=LOGGED_AT)


# ---------------------------------------------------------------------------
# The two rules
# ---------------------------------------------------------------------------


def test_a_typed_total_beats_the_food_log_for_the_same_day() -> None:
    """Rule 1. A typed figure is a statement about the whole day; the log may be half of it."""
    resolved = intake.resolve_intake_for_span(
        a_span(1),
        manual_by_day={day(0): typed(day(0), 2600.0)},
        logged_kilocalories_by_day={day(0): 2078.0},
    )

    assert resolved[day(0)] == intake.DailyIntake(2600.0, intake.SOURCE_MANUAL, day(0))


def test_the_food_log_is_used_when_nothing_was_typed() -> None:
    resolved = intake.resolve_intake_for_span(
        a_span(1),
        manual_by_day={},
        logged_kilocalories_by_day={day(0): 2078.0},
    )

    assert resolved[day(0)] == intake.DailyIntake(2078.0, intake.SOURCE_LOGGED, day(0))


def test_a_day_with_nothing_recorded_inherits_the_last_known_figure_and_says_so() -> None:
    """Rule 2, and the label that makes it acceptable."""
    resolved = intake.resolve_intake_for_span(
        a_span(3),
        manual_by_day={},
        logged_kilocalories_by_day={day(0): 2078.0},
    )

    assert resolved[day(1)] == intake.DailyIntake(2078.0, intake.SOURCE_CARRIED, day(0))
    assert resolved[day(2)] == intake.DailyIntake(2078.0, intake.SOURCE_CARRIED, day(0))


def test_a_carried_figure_keeps_pointing_at_the_day_it_was_recorded() -> None:
    """`from_day` must not drift forward one day at a time.

    If day 2 inherited from day 1 (itself carried), the label would say "from yesterday"
    on every day and the reader would never learn the figure is actually a week old.
    """
    resolved = intake.resolve_intake_for_span(
        a_span(8),
        manual_by_day={day(0): typed(day(0), 2400.0)},
        logged_kilocalories_by_day={},
    )

    assert resolved[day(7)].from_day == day(0)


def test_days_before_the_first_recorded_figure_are_none() -> None:
    """There is nothing to carry yet. Inventing a number there would be a guess with no source."""
    resolved = intake.resolve_intake_for_span(
        a_span(3),
        manual_by_day={day(2): typed(day(2), 2400.0)},
        logged_kilocalories_by_day={},
    )

    assert resolved[day(0)] is None
    assert resolved[day(1)] is None
    assert resolved[day(2)].source == intake.SOURCE_MANUAL


def test_a_new_recorded_day_resets_what_later_days_inherit() -> None:
    resolved = intake.resolve_intake_for_span(
        a_span(4),
        manual_by_day={},
        logged_kilocalories_by_day={day(0): 2000.0, day(2): 2500.0},
    )

    assert resolved[day(1)] == intake.DailyIntake(2000.0, intake.SOURCE_CARRIED, day(0))
    assert resolved[day(3)] == intake.DailyIntake(2500.0, intake.SOURCE_CARRIED, day(2))


def test_an_empty_span_resolves_to_nothing() -> None:
    assert intake.resolve_intake_for_span([], {}, {}) == {}


# ---------------------------------------------------------------------------
# The property behind all of them
# ---------------------------------------------------------------------------


@given(
    length=st.integers(min_value=1, max_value=40),
    typed_offsets=st.sets(st.integers(min_value=0, max_value=39)),
    logged_offsets=st.sets(st.integers(min_value=0, max_value=39)),
)
def test_every_figure_points_at_a_day_that_was_actually_recorded(
    length: int,
    typed_offsets: set[int],
    logged_offsets: set[int],
) -> None:
    """Whatever the pattern of recorded days, a figure's `from_day` is never invented.

    It is on or before the day it is shown for, it is a day with a real record, and a
    figure shown for its own recorded day is never labelled carried.
    """
    span = a_span(length)

    manual_by_day = {}
    for offset in typed_offsets:
        if offset < length:
            manual_by_day[day(offset)] = typed(day(offset), 2000.0 + offset)

    logged_by_day = {}
    for offset in logged_offsets:
        if offset < length:
            logged_by_day[day(offset)] = 1500.0 + offset

    resolved = intake.resolve_intake_for_span(span, manual_by_day, logged_by_day)

    recorded_days = set(manual_by_day) | set(logged_by_day)

    for one_day in span:
        figure = resolved[one_day]

        if figure is None:
            # Allowed only before anything was recorded.
            assert not any(recorded <= one_day for recorded in recorded_days)
            continue

        assert figure.from_day <= one_day
        assert figure.from_day in recorded_days

        if one_day in recorded_days:
            assert figure.source != intake.SOURCE_CARRIED
            assert figure.from_day == one_day
        else:
            assert figure.source == intake.SOURCE_CARRIED


# ---------------------------------------------------------------------------
# The typing-mistake check
# ---------------------------------------------------------------------------


def test_a_believable_total_has_no_problem() -> None:
    assert intake.describe_problem(2100.0) is None


def test_a_dropped_digit_is_caught() -> None:
    assert "drop a digit" in (intake.describe_problem(210.0) or "")


def test_an_extra_digit_is_caught() -> None:
    assert "add a digit" in (intake.describe_problem(21000.0) or "")


def test_zero_and_negatives_are_refused() -> None:
    assert intake.describe_problem(0.0) is not None
    assert intake.describe_problem(-500.0) is not None
