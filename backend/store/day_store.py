"""Saving and loading whole days, in terms the rest of the project thinks in.

`database.py` knows about partition keys and JSON blobs. `records.py` knows how to turn
a snapshot into a dictionary. Neither of them should be what the command line talks to,
because then every caller would have to remember the key scheme.

This module is that seam: it takes and returns `DailySnapshot` objects, and keeps the
keys to itself.
"""

from __future__ import annotations

import datetime

from backend.garmin import normalize
from backend.store import database
from backend.store import keys
from backend.store import records


def save_snapshot(
    open_database: database.Database,
    snapshot: normalize.DailySnapshot,
    user_id: str = keys.DEFAULT_USER_ID,
) -> None:
    """Store one day, replacing whatever was stored for that day before."""
    open_database.save(
        partition_key=keys.user_partition(user_id),
        sort_key=keys.snapshot_key(snapshot.day),
        body=records.snapshot_to_record(snapshot),
    )


def load_snapshot(
    open_database: database.Database,
    day: datetime.date,
    user_id: str = keys.DEFAULT_USER_ID,
) -> normalize.DailySnapshot | None:
    """Read one day back, or None if that day has not been imported."""
    record = open_database.load(
        partition_key=keys.user_partition(user_id),
        sort_key=keys.snapshot_key(day),
    )

    if record is None:
        return None

    return records.record_to_snapshot(record)


def load_snapshots_between(
    open_database: database.Database,
    first_day: datetime.date,
    last_day: datetime.date,
    user_id: str = keys.DEFAULT_USER_ID,
) -> list[normalize.DailySnapshot]:
    """Read every stored day in a span, oldest first.

    One lookup, however many days are asked for. This is the read that baselines are
    built on, and the reason the key scheme was worth copying exactly.

    A range over days returns every record in them -- snapshots, and later weigh-ins
    and food entries too -- so the ones that are not snapshots are skipped here rather
    than being asked for separately.
    """
    lowest, highest = keys.day_range_bounds(first_day, last_day)

    found = open_database.load_by_range(
        partition_key=keys.user_partition(user_id),
        lowest_sort_key=lowest,
        highest_sort_key=highest,
    )

    snapshots = []

    for sort_key, record in found:
        if not sort_key.endswith("SNAPSHOT"):
            continue

        snapshots.append(records.record_to_snapshot(record))

    # Already in key order, which for these keys is date order. Sorted again anyway
    # because that guarantee belongs to the key scheme, and a caller reading this
    # function should not have to go and verify it.
    snapshots.sort(key=lambda one_snapshot: one_snapshot.day)

    return snapshots
