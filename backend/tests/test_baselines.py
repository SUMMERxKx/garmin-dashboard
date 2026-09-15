"""Tests for the baseline engine.

Two kinds of test live here, and they answer different questions.

**Example-based tests** name an input and assert an output. They exist to pin down the
*decisions* in `baselines.py` -- the both-conditions rule in `decide_position`, the
minimum-readings table, the choice to return None rather than guess. None of those are
arithmetic; they are judgement calls, and a judgement call that is not written down as a
test is one refactor away from being quietly reversed.

**Property-based tests** (the ones marked `@given`) state something that must hold for
ANY input and let Hypothesis try to break it. They cover the cases nobody thought to
write down: the single reading, the list where every value is identical, the window with
nothing in it. When one fails, Hypothesis shrinks the counterexample to the smallest
input that still breaks and prints that, which is usually the whole diagnosis.

Everything here runs without a database, a network call, or a clock, because
`baselines.py` takes `ending_on` as an argument instead of asking what day it is. That
design choice is what makes this file possible without a single mock.
"""

from __future__ import annotations

import datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.engine import baselines

#: A fixed day for every test to end its window on. Any date would do; what matters is
#: that it never changes, so a test that passes today passes in March.
LAST_DAY = datetime.date(2026, 9, 14)


def readings_ending_on(
    values: list[float | None],
    last_day: datetime.date = LAST_DAY,
) -> list[tuple[datetime.date, float | None]]:
    """Attach one consecutive day to each value, oldest first, ending on `last_day`.

    Most tests care about how many readings there are and what they contain, not which
    calendar days they landed on. This builds the (day, value) pairs the module expects
    so each test can be written as a plain list of numbers.
    """
    readings = []

    for position, one_value in enumerate(values):
        days_before_the_end = len(values) - 1 - position
        day = last_day - datetime.timedelta(days=days_before_the_end)
        readings.append((day, one_value))

    return readings


# ---------------------------------------------------------------------------
# minimum_readings_for -- the table, and the fallback
# ---------------------------------------------------------------------------


def test_the_documented_windows_come_from_the_table() -> None:
    """The four windows we actually use have hand-chosen minimums, not computed ones."""
    assert baselines.minimum_readings_for(7) == 5
    assert baselines.minimum_readings_for(14) == 9
    assert baselines.minimum_readings_for(30) == 18
    assert baselines.minimum_readings_for(90) == 45


def test_an_unlisted_window_falls_back_to_a_fraction_and_rounds_up() -> None:
    """Rounding up matters: a window must never be satisfied by fewer than the fraction.

    21 days at 0.6 is 12.6 readings. Rounding down would accept 12, which is less
    coverage than the rule asks for, so it has to become 13.
    """
    assert baselines.minimum_readings_for(21) == 13

    # 10 * 0.6 is exactly 6, so there is nothing to round up and it stays 6.
    assert baselines.minimum_readings_for(10) == 6


@given(window_days=st.integers(min_value=1, max_value=365))
def test_a_window_never_needs_more_readings_than_it_has_days(window_days: int) -> None:
    """A minimum above the window length would be unsatisfiable by construction."""
    needed = baselines.minimum_readings_for(window_days)

    assert 0 < needed <= window_days


# ---------------------------------------------------------------------------
# readings_within_window -- which days count
# ---------------------------------------------------------------------------


def test_the_window_includes_its_end_day() -> None:
    """A 7-day window ending on the 14th covers the 8th to the 14th -- seven days.

    This is the off-by-one the docstring calls out, and it is worth a test of its own
    because getting it wrong changes every baseline in the project by one reading.
    """
    values = [float(day_number) for day_number in range(1, 15)]  # 1.0 .. 14.0
    readings = readings_ending_on(values)  # day N carries the value N

    inside = baselines.readings_within_window(readings, window_days=7, ending_on=LAST_DAY)

    assert inside == [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0]


def test_days_with_no_reading_are_skipped_not_counted_as_zero() -> None:
    """A missing reading must vanish, not become a zero that drags the mean down."""
    readings = readings_ending_on([50.0, None, 52.0, None, 54.0])

    inside = baselines.readings_within_window(readings, window_days=5, ending_on=LAST_DAY)

    assert inside == [50.0, 52.0, 54.0]


def test_days_after_the_end_of_the_window_are_ignored() -> None:
    """Asking for a baseline as of last Tuesday must not see Wednesday's reading.

    This is what makes a baseline for a past day computable and honest -- it sees only
    what was knowable then.
    """
    readings = readings_ending_on([10.0, 11.0, 12.0, 13.0, 14.0])
    three_days_earlier = LAST_DAY - datetime.timedelta(days=3)

    inside = baselines.readings_within_window(
        readings, window_days=30, ending_on=three_days_earlier
    )

    assert inside == [10.0, 11.0]


@given(
    values=st.lists(
        st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=60,
    ),
    window_days=st.integers(min_value=1, max_value=40),
)
def test_a_window_returns_exactly_its_last_n_readings(
    values: list[float],
    window_days: int,
) -> None:
    """With one reading per consecutive day, the window is simply the final N of them.

    Stated this way the property is exact rather than approximate, which makes it a much
    sharper trap than "the result is no longer than the window" would be.
    """
    readings = readings_ending_on(values)

    inside = baselines.readings_within_window(readings, window_days, LAST_DAY)

    assert inside == values[-window_days:]


# ---------------------------------------------------------------------------
# build_baseline -- and the refusal to build one
# ---------------------------------------------------------------------------


def test_too_few_readings_produces_no_baseline_at_all() -> None:
    """Below the minimum the answer is None, never a mean computed from what little there is.

    This is the module's central claim: a baseline from 17 readings would look exactly
    as authoritative on screen as one from 30, so it must not be offered.
    """
    seventeen_readings = [100.0] * 17

    assert baselines.build_baseline(
        "hrv", readings_ending_on(seventeen_readings), 30, LAST_DAY
    ) is None

    eighteen_readings = [100.0] * 18

    assert baselines.build_baseline(
        "hrv", readings_ending_on(eighteen_readings), 30, LAST_DAY
    ) is not None


def test_a_baseline_reports_what_it_was_built_from() -> None:
    """The sample size and date span are part of the answer, not decoration.

    They are what lets the screen say "18 readings across 30 days" instead of implying
    a solidity the baseline may not have.
    """
    values = [40.0, 42.0, 44.0, 46.0, 48.0]
    baseline = baselines.build_baseline("rhr", readings_ending_on(values), 5, LAST_DAY)

    assert baseline is not None
    assert baseline.metric_name == "rhr"
    assert baseline.window_days == 5
    assert baseline.mean == pytest.approx(44.0)
    assert baseline.sample_size == 5
    assert baseline.newest_day == LAST_DAY
    assert baseline.oldest_day == LAST_DAY - datetime.timedelta(days=4)
    assert baseline.describe_coverage() == "5 readings across 5 days"


def test_scatter_is_measured_across_the_whole_population_not_a_sample() -> None:
    """Pins `pstdev` over `stdev`, which is a real decision and not a detail.

    The two differ in what they divide by: `pstdev` by N, `stdev` by N-1. That second
    form exists to estimate the spread of a larger population from a sample drawn out of
    it -- which is not the situation here. These readings are not a sample of your week;
    they ARE your week, every reading in the window, so N is the honest divisor.

    The gap is not academic at these sizes. On the five readings below it is 2.83 against
    3.16, about 12%, and it feeds straight into how many standard deviations from normal
    today looks -- which is the thing that decides whether the dashboard says anything.
    """
    values = [40.0, 42.0, 44.0, 46.0, 48.0]
    baseline = baselines.build_baseline("rhr", readings_ending_on(values), 5, LAST_DAY)

    assert baseline is not None
    # sqrt(40/5), the population form. The sample form would give sqrt(40/4) = 3.162.
    assert baseline.standard_deviation == pytest.approx(2.8284271, rel=1e-6)


def test_the_date_span_covers_only_days_that_had_a_reading() -> None:
    """A gap at the edge of the window must not be claimed as covered."""
    # Oldest two days are blank, so the span starts at the third.
    readings = readings_ending_on([None, None, 44.0, 45.0, 46.0, 47.0, 48.0])

    baseline = baselines.build_baseline("rhr", readings, 7, LAST_DAY)

    assert baseline is not None
    assert baseline.sample_size == 5
    assert baseline.oldest_day == LAST_DAY - datetime.timedelta(days=4)


@given(
    values=st.lists(
        st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=5,
        max_size=7,
    )
)
def test_the_mean_always_sits_inside_the_range_it_came_from(values: list[float]) -> None:
    """An average outside its own readings would be arithmetically impossible.

    Cheap to state, and it would catch a whole family of slips -- summing the wrong
    list, dividing by the wrong count, including a day twice.
    """
    baseline = baselines.build_baseline("any", readings_ending_on(values), 7, LAST_DAY)

    assert baseline is not None
    assert min(values) <= baseline.mean <= max(values)


@given(
    values=st.lists(
        st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=40,
    ),
    window_days=st.integers(min_value=1, max_value=30),
)
def test_a_baseline_exists_only_when_there_was_enough_to_build_it(
    values: list[float],
    window_days: int,
) -> None:
    """The two halves of the module's promise, checked together for any input.

    If a baseline came back it had at least the minimum behind it; if none came back,
    there genuinely were fewer than the minimum available.
    """
    readings = readings_ending_on(values)
    how_many_were_available = len(baselines.readings_within_window(readings, window_days, LAST_DAY))

    baseline = baselines.build_baseline("any", readings, window_days, LAST_DAY)
    needed = baselines.minimum_readings_for(window_days)

    if baseline is None:
        assert how_many_were_available < needed
    else:
        assert baseline.sample_size == how_many_were_available
        assert baseline.sample_size >= needed
        assert baseline.standard_deviation >= 0.0


# ---------------------------------------------------------------------------
# compare_to and decide_position -- the judgement
# ---------------------------------------------------------------------------


def test_nothing_to_compare_gives_no_comparison() -> None:
    """A missing reading and a missing baseline both mean "we cannot say", not zero."""
    baseline = baselines.build_baseline("any", readings_ending_on([1.0] * 7), 7, LAST_DAY)

    assert baselines.compare_to(None, baseline) is None
    assert baselines.compare_to(50.0, None) is None
    assert baselines.compare_to(None, None) is None


def test_a_steady_metric_is_not_called_unusual_for_a_move_that_does_not_matter() -> None:
    """The case MINIMUM_RELATIVE_BAND exists for, and the reason it earns its place.

    A resting heart rate that barely moved all month has a tiny standard deviation, so
    a one-beat change is "two and a half standard deviations" -- arithmetically true and
    practically meaningless. Without the relative band this would read as unusual, the
    dashboard would cry wolf on every metric that holds steady, and the verdict would
    stop being worth reading.
    """
    barely_moved = [44.0, 44.0, 44.0, 45.0, 44.0, 44.0, 44.0]
    baseline = baselines.build_baseline("rhr", readings_ending_on(barely_moved), 7, LAST_DAY)

    assert baseline is not None

    deviation = baselines.compare_to(45.0, baseline)

    assert deviation is not None
    # Far outside the scatter...
    assert deviation.standard_deviations is not None
    assert abs(deviation.standard_deviations) > baselines.UNUSUAL_STANDARD_DEVIATIONS
    # ...but under 3% in proportional terms, so the verdict stays quiet.
    assert abs(deviation.relative_difference) < baselines.MINIMUM_RELATIVE_BAND
    assert deviation.position == "typical"


def test_a_move_that_is_both_large_and_real_does_get_called_out() -> None:
    """The other side of the same rule -- it must still fire, or it is just a mute button."""
    barely_moved = [44.0, 44.0, 44.0, 45.0, 44.0, 44.0, 44.0]
    baseline = baselines.build_baseline("rhr", readings_ending_on(barely_moved), 7, LAST_DAY)

    assert baseline is not None

    deviation = baselines.compare_to(52.0, baseline)

    assert deviation is not None
    assert deviation.position == "above"

    lower = baselines.compare_to(36.0, baseline)

    assert lower is not None
    assert lower.position == "below"


def test_a_metric_that_never_moved_gets_no_verdict() -> None:
    """Zero scatter means there is no scale to measure a departure against.

    Dividing by that zero would produce an infinity, which would then be reported as
    wildly unusual. None is the honest answer, and the position stays typical.
    """
    never_moved = [30.0] * 7
    baseline = baselines.build_baseline("stress", readings_ending_on(never_moved), 7, LAST_DAY)

    assert baseline is not None
    assert baseline.standard_deviation == 0.0

    deviation = baselines.compare_to(45.0, baseline)

    assert deviation is not None
    assert deviation.standard_deviations is None
    assert deviation.position == "typical"


def test_a_mean_of_zero_does_not_divide_by_zero() -> None:
    """Possible in real life: vigorous intensity minutes across a quiet fortnight."""
    all_zero = [0.0] * 7
    baseline = baselines.build_baseline("vigorous", readings_ending_on(all_zero), 7, LAST_DAY)

    assert baseline is not None
    assert baseline.mean == 0.0

    deviation = baselines.compare_to(12.0, baseline)

    assert deviation is not None
    assert deviation.relative_difference == 0.0
    assert deviation.position == "typical"


@given(
    values=st.lists(
        st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=5,
        max_size=7,
    )
)
def test_a_reading_equal_to_the_baseline_is_always_typical(values: list[float]) -> None:
    """Being exactly average is the definition of unremarkable, whatever the metric."""
    baseline = baselines.build_baseline("any", readings_ending_on(values), 7, LAST_DAY)

    assert baseline is not None

    deviation = baselines.compare_to(baseline.mean, baseline)

    assert deviation is not None
    assert deviation.difference == pytest.approx(0.0)
    assert deviation.position == "typical"


@given(
    values=st.lists(
        st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=5,
        max_size=7,
    ),
    today_value=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
)
def test_the_verdict_is_always_one_of_three_words(
    values: list[float],
    today_value: float,
) -> None:
    """The caller switches on this string, so an unexpected fourth value would be a bug."""
    baseline = baselines.build_baseline("any", readings_ending_on(values), 7, LAST_DAY)

    assert baseline is not None

    deviation = baselines.compare_to(today_value, baseline)

    assert deviation is not None
    assert deviation.position in {"typical", "above", "below"}


@given(
    values=st.lists(
        st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=5,
        max_size=7,
    ),
    today_value=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    multiplier=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
)
def test_the_verdict_does_not_depend_on_the_unit(
    values: list[float],
    today_value: float,
    multiplier: float,
) -> None:
    """Measuring sleep in minutes or in hours must not change whether it looks unusual.

    Both tests of unusualness are ratios -- difference over mean, and difference over
    standard deviation -- so scaling every number by the same factor has to leave them
    untouched. If a raw quantity ever leaked into the comparison this is what would
    catch it.

    Only the two ratios are asserted, not the verdict itself. The verdict is computed
    from exactly these two numbers, so pinning them pins it everywhere except precisely
    on a threshold, where floating-point noise could legitimately tip it either way.
    """
    original = baselines.compare_to(
        today_value,
        baselines.build_baseline("any", readings_ending_on(values), 7, LAST_DAY),
    )

    scaled_values = [one_value * multiplier for one_value in values]

    scaled = baselines.compare_to(
        today_value * multiplier,
        baselines.build_baseline("any", readings_ending_on(scaled_values), 7, LAST_DAY),
    )

    assert original is not None
    assert scaled is not None

    assert scaled.relative_difference == pytest.approx(original.relative_difference, rel=1e-9)

    if original.standard_deviations is None:
        assert scaled.standard_deviations is None
    else:
        assert scaled.standard_deviations == pytest.approx(
            original.standard_deviations, rel=1e-6
        )
