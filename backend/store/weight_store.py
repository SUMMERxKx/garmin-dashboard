"""Saving and loading weigh-ins.

One weigh-in per day, which is why the key has no timestamp in it: `DAY#2026-09-14#WEIGHT`.
A day has one morning, and weighing yourself again after dinner does not produce a second
measurement worth keeping -- it produces a worse one. Recording a second weigh-in for a
day therefore REPLACES the first rather than adding to it.

That is a real decision and not merely convenient. Allowing several readings a day would
quietly change what a weekly average means, because days you happened to weigh twice
would count double.
"""

from __future__ import annotations

import datetime

from backend.body import weight
from backend.store import database
from backend.store import keys


def weighing_to_record(one_weighing: weight.Weighing) -> dict:
    """Turn a weigh-in into a plain dictionary for storage."""
    return {
        "day": one_weighing.day.isoformat(),
        "kilograms": one_weighing.kilograms,
        "recorded_at": one_weighing.recorded_at.isoformat(),
        "source": one_weighing.source,
        "fat_percent": one_weighing.fat_percent,
    }


def record_to_weighing(record: dict) -> weight.Weighing:
    """Turn a stored record back into a weigh-in."""
    return weight.Weighing(
        day=datetime.date.fromisoformat(record["day"]),
        kilograms=record["kilograms"],
        recorded_at=datetime.datetime.fromisoformat(record["recorded_at"]),
        source=record.get("source", "manual"),
        # `.get` rather than `[...]`: entries written before body fat existed have no
        # such key, and they must keep loading rather than raising.
        fat_percent=record.get("fat_percent"),
    )


def save_weighing(
    open_database: database.Database,
    one_weighing: weight.Weighing,
    user_id: str = keys.DEFAULT_USER_ID,
) -> None:
    """Store a weigh-in, replacing any earlier one for the same day."""
    open_database.save(
        partition_key=keys.user_partition(user_id),
        sort_key=keys.weight_key(one_weighing.day),
        body=weighing_to_record(one_weighing),
    )


def load_weighing(
    open_database: database.Database,
    day: datetime.date,
    user_id: str = keys.DEFAULT_USER_ID,
) -> weight.Weighing | None:
    """Read one day's weigh-in, or None if there was not one."""
    record = open_database.load(
        partition_key=keys.user_partition(user_id),
        sort_key=keys.weight_key(day),
    )

    if record is None:
        return None

    return record_to_weighing(record)


def load_weighings_between(
    open_database: database.Database,
    first_day: datetime.date,
    last_day: datetime.date,
    user_id: str = keys.DEFAULT_USER_ID,
) -> list[weight.Weighing]:
    """Every weigh-in in a span, oldest first.

    One lookup for the whole range, the same access pattern the daily snapshots use. A
    weight trend is meaningless from a single reading, so reading a span is the normal
    case here rather than the exception.
    """
    lowest, highest = keys.day_range_bounds(first_day, last_day)

    found = open_database.load_by_range(
        partition_key=keys.user_partition(user_id),
        lowest_sort_key=lowest,
        highest_sort_key=highest,
    )

    weighings = []

    for sort_key, record in found:
        # A day range returns everything in those days -- snapshots and food entries
        # too -- so the records that are not weigh-ins are stepped over here.
        if not sort_key.endswith("WEIGHT"):
            continue

        weighings.append(record_to_weighing(record))

    weighings.sort(key=lambda one: one.day)

    return weighings
