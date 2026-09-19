"""Saving and loading typed-in daily calorie totals.

One per day, under `DAY#2026-09-14#INTAKE`, so it sits in the same day prefix as the
snapshot, the weigh-in and the food entries and comes back in the same single lookup.
Recording a second total for a day replaces the first -- see `keys.intake_key` for why.
"""

from __future__ import annotations

import datetime

from backend.food import intake
from backend.store import keys
from backend.store import open_store


def intake_to_record(one_intake: intake.ManualIntake) -> dict:
    """Turn a typed total into a plain dictionary for storage."""
    return {
        "day": one_intake.day.isoformat(),
        "kilocalories": one_intake.kilocalories,
        "recorded_at": one_intake.recorded_at.isoformat(),
        "note": one_intake.note,
    }


def record_to_intake(record: dict) -> intake.ManualIntake:
    """Turn a stored record back into a typed total."""
    return intake.ManualIntake(
        day=datetime.date.fromisoformat(record["day"]),
        kilocalories=record["kilocalories"],
        recorded_at=datetime.datetime.fromisoformat(record["recorded_at"]),
        note=record.get("note"),
    )


def save_intake(
    open_database: open_store.Store,
    one_intake: intake.ManualIntake,
    user_id: str = keys.DEFAULT_USER_ID,
) -> None:
    """Store a typed total, replacing any earlier one for the same day."""
    open_database.save(
        partition_key=keys.user_partition(user_id),
        sort_key=keys.intake_key(one_intake.day),
        body=intake_to_record(one_intake),
    )


def load_intake(
    open_database: open_store.Store,
    day: datetime.date,
    user_id: str = keys.DEFAULT_USER_ID,
) -> intake.ManualIntake | None:
    """Read one day's typed total, or None if none was typed."""
    record = open_database.load(
        partition_key=keys.user_partition(user_id),
        sort_key=keys.intake_key(day),
    )

    if record is None:
        return None

    return record_to_intake(record)


def load_intakes_between(
    open_database: open_store.Store,
    first_day: datetime.date,
    last_day: datetime.date,
    user_id: str = keys.DEFAULT_USER_ID,
) -> dict[datetime.date, intake.ManualIntake]:
    """Every typed total in a span, keyed by day.

    Returned as a dictionary rather than a list because the only caller is the
    carry-forward rule, which asks "was there one on this day?" for each day in turn.
    """
    lowest, highest = keys.day_range_bounds(first_day, last_day)

    found = open_database.load_by_range(
        partition_key=keys.user_partition(user_id),
        lowest_sort_key=lowest,
        highest_sort_key=highest,
    )

    intakes_by_day: dict[datetime.date, intake.ManualIntake] = {}

    for sort_key, record in found:
        # A day range returns everything in those days, so step over the records that
        # are not typed totals.
        if not sort_key.endswith("INTAKE"):
            continue

        one_intake = record_to_intake(record)
        intakes_by_day[one_intake.day] = one_intake

    return intakes_by_day
