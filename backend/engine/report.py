"""The baselines the dashboard shows, worked out for every metric on it at once.

`baselines.py` answers one question about one metric. This module asks that question
for each metric the dashboard draws and packs the answers up, so the API can send them
in one block and the browser never has to compute a standard deviation.

Why the browser does not do this itself
---------------------------------------
It could -- a mean and a standard deviation are a few lines of JavaScript. But the rule
in this project is that anything which turns numbers into a judgement lives in Python,
where it is tested and where the method is written down next to the code. "Your HRV is
below your 30-day normal" is a judgement. The browser draws what it is told.

Two windows, on purpose
-----------------------
Seven days says what this week has been like; thirty says what a normal month looks
like. A reading can be typical for the week and low for the month at the same time,
which is exactly the case worth seeing -- it means the week itself is the unusual thing.
"""

from __future__ import annotations

import dataclasses
import datetime

from backend.engine import baselines
from backend.garmin import normalize

#: The two windows sent to the dashboard. Both are in the hand-written minimum table in
#: `baselines.py`, so neither falls back to the fraction rule.
SHORT_WINDOW_DAYS = 7
LONG_WINDOW_DAYS = 30

#: A reading is one (day, value-or-None) pair. The same shape `baselines.py` takes.
Readings = list[tuple[datetime.date, float | None]]


@dataclasses.dataclass
class MetricSummary:
    """Everything the dashboard shows about one metric's history, in one object."""

    metric_name: str

    #: The most recent reading on or before the window's end, and the day it was taken.
    #: None when nothing in the span has a value.
    latest_day: datetime.date | None
    latest_value: float | None

    short_window: baselines.Baseline | None
    long_window: baselines.Baseline | None

    #: Where the latest reading sits against the long window: "above", "below",
    #: "typical", or None when either half is missing. Positional only -- see
    #: `baselines.compare_to` for why this is never "good" or "bad".
    position_against_long_window: str | None


def summarise_readings(
    metric_name: str,
    readings: Readings,
    ending_on: datetime.date,
) -> MetricSummary:
    """Both windows and the latest reading, for one list of readings."""
    latest_day = None
    latest_value = None

    # The newest reading that has a value and is not after the window's end. Readings
    # arrive oldest first, so the last match wins.
    for day, value in readings:
        if value is None:
            continue

        if day > ending_on:
            continue

        latest_day = day
        latest_value = value

    short_window = baselines.build_baseline(metric_name, readings, SHORT_WINDOW_DAYS, ending_on)
    long_window = baselines.build_baseline(metric_name, readings, LONG_WINDOW_DAYS, ending_on)

    deviation = baselines.compare_to(latest_value, long_window)

    if deviation is None:
        position = None
    else:
        position = deviation.position

    return MetricSummary(
        metric_name=metric_name,
        latest_day=latest_day,
        latest_value=latest_value,
        short_window=short_window,
        long_window=long_window,
        position_against_long_window=position,
    )


# ---------------------------------------------------------------------------
# Pulling each metric out of a snapshot
# ---------------------------------------------------------------------------
#
# One small named function per metric rather than a table of lambdas, so that a reader
# can search for `read_resting_heart_rate` and find exactly where the number comes from.


def read_hrv(snapshot: normalize.DailySnapshot) -> float | None:
    return snapshot.recovery.hrv_last_night


def read_resting_heart_rate(snapshot: normalize.DailySnapshot) -> float | None:
    return snapshot.recovery.resting_heart_rate


def read_sleep_minutes(snapshot: normalize.DailySnapshot) -> float | None:
    return snapshot.sleep.total_minutes


def read_sleep_score(snapshot: normalize.DailySnapshot) -> float | None:
    return snapshot.sleep.score


def read_body_battery_charged(snapshot: normalize.DailySnapshot) -> float | None:
    return snapshot.recovery.body_battery_charged


def read_average_stress(snapshot: normalize.DailySnapshot) -> float | None:
    return snapshot.recovery.average_stress


def read_steps(snapshot: normalize.DailySnapshot) -> float | None:
    return snapshot.energy.steps


def read_total_kilocalories(snapshot: normalize.DailySnapshot) -> float | None:
    return snapshot.energy.total_kilocalories


def read_active_kilocalories(snapshot: normalize.DailySnapshot) -> float | None:
    return snapshot.energy.active_kilocalories


#: The metrics the dashboard gets a baseline for, by the name the wire format uses.
#: Written out as a plain dictionary so adding one is one line here and nothing else.
SNAPSHOT_METRICS = {
    "hrv_last_night": read_hrv,
    "resting_heart_rate": read_resting_heart_rate,
    "sleep_total_minutes": read_sleep_minutes,
    "sleep_score": read_sleep_score,
    "body_battery_charged": read_body_battery_charged,
    "average_stress": read_average_stress,
    "steps": read_steps,
    "total_kilocalories": read_total_kilocalories,
    "active_kilocalories": read_active_kilocalories,
}


def readings_for(
    snapshots: list[normalize.DailySnapshot],
    read_value,
) -> Readings:
    """One (day, value) pair per snapshot, in the order given."""
    readings: Readings = []

    for one_snapshot in snapshots:
        readings.append((one_snapshot.day, read_value(one_snapshot)))

    return readings


def has_any_reading(snapshot: normalize.DailySnapshot) -> bool:
    """Whether at least one daily field on this snapshot has a value.

    Checked on the values themselves rather than on `how_many_fields_found()`, which
    counts provenance entries. A snapshot read back from the database has its
    provenance; one built by hand in a test does not, and the two must be judged the
    same way.
    """
    for one_block in (snapshot.energy, snapshot.sleep, snapshot.recovery):
        for one_field in dataclasses.fields(one_block):
            if getattr(one_block, one_field.name) is not None:
                return True

    return False


def last_day_with_garmin_data(
    snapshots: list[normalize.DailySnapshot],
) -> datetime.date | None:
    """The newest day that actually has readings, which is where every window should end.

    Not simply the newest day in the span. Today's snapshot usually does not exist yet,
    and a morning weigh-in creates a day with no Garmin data at all. Ending a 7-day
    window on an empty day would quietly make it a 6-day window.
    """
    newest = None

    for one_snapshot in snapshots:
        if not has_any_reading(one_snapshot):
            continue

        if newest is None or one_snapshot.day > newest:
            newest = one_snapshot.day

    return newest


def summarise_snapshots(
    snapshots: list[normalize.DailySnapshot],
    ending_on: datetime.date,
) -> dict[str, MetricSummary]:
    """A summary for every metric in SNAPSHOT_METRICS, keyed by wire name."""
    in_order = sorted(snapshots, key=lambda one: one.day)

    summaries: dict[str, MetricSummary] = {}

    for metric_name, read_value in SNAPSHOT_METRICS.items():
        readings = readings_for(in_order, read_value)
        summaries[metric_name] = summarise_readings(metric_name, readings, ending_on)

    return summaries
