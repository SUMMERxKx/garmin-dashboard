"""Turning a DailySnapshot into something storable, and back again.

A database holds text and numbers. `normalize.DailySnapshot` is a Python object holding
other Python objects, a `date`, a `datetime` and a list. This module is the translation
between the two, and it lives on its own because it is the one place that has to know
both shapes.

Why not just store the whole raw Garmin response
------------------------------------------------
Those are already saved, under `fixtures/raw/`, and they stay the source of truth. What
goes in the database is the INTERPRETED day, because that is what gets read constantly:
ninety days of snapshots for a baseline is one lookup, where ninety days of raw files
would be ninety folders of seventeen files each, re-interpreted every time.

The raw files are the archive. The database is the working copy. If the mapping
improves, the working copy is thrown away and rebuilt from the archive -- which is what
the import command does, and why it is safe to run again whenever you like.
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any

from backend.garmin import normalize


def to_storable(value: Any) -> Any:
    """Turn dates and datetimes into text, leaving everything else alone.

    JSON has no date type. Rather than each field remembering to convert itself, this
    runs over the whole record on the way out.

    ISO format ("2026-09-12", "2026-09-12T15:06:55") is used because it is unambiguous
    -- no argument about whether 09-12 is September or December -- and because it sorts
    correctly as plain text, which is the same property the key scheme depends on.
    """
    if isinstance(value, datetime.datetime):
        # Checked BEFORE date, because in Python a datetime IS a date: the check for
        # date would catch datetimes too and throw away the time of day.
        return value.isoformat()

    if isinstance(value, datetime.date):
        return value.isoformat()

    if isinstance(value, dict):
        converted = {}
        for key, one_value in value.items():
            converted[key] = to_storable(one_value)
        return converted

    if isinstance(value, list):
        converted_list = []
        for one_value in value:
            converted_list.append(to_storable(one_value))
        return converted_list

    return value


def snapshot_to_record(snapshot: normalize.DailySnapshot) -> dict[str, Any]:
    """Turn one day into a plain dictionary ready to be stored.

    `dataclasses.asdict` walks the object and its nested objects and hands back plain
    dictionaries, so adding a field to `normalize.py` cannot leave it silently
    unsaved -- which is exactly the kind of drift that writing the conversion out by
    hand, field by field, invites.
    """
    return to_storable(dataclasses.asdict(snapshot))


def record_to_snapshot(record: dict[str, Any]) -> normalize.DailySnapshot:
    """Turn a stored record back into a DailySnapshot.

    The way back cannot be automatic in the same way: a dictionary does not say which
    class it came from, and the two timestamps have to be parsed back from text. Each
    section is rebuilt with `SomeClass(**section)`, which works because the dictionary
    keys are the field names -- they were written by `asdict` from those same fields.
    """
    activities = []

    for one_activity_record in record.get("activities", []):
        activities.append(record_to_activity(one_activity_record))

    return normalize.DailySnapshot(
        day=datetime.date.fromisoformat(record["day"]),
        energy=normalize.Energy(**record["energy"]),
        sleep=normalize.Sleep(**record["sleep"]),
        recovery=normalize.Recovery(**record["recovery"]),
        body=normalize.Body(**record["body"]),
        activities=activities,
        provenance=record.get("provenance", {}),
    )


def record_to_activity(record: dict[str, Any]) -> normalize.Activity:
    """Turn one stored activity back into an Activity.

    Copied rather than passed straight through with `**record`, because the start time
    has to be parsed from text back into a datetime and modifying the caller's
    dictionary while reading it would be a rude surprise.
    """
    fields = dict(record)

    started_at_text = fields.get("started_at_local")

    if started_at_text is None:
        fields["started_at_local"] = None
    else:
        fields["started_at_local"] = datetime.datetime.fromisoformat(started_at_text)

    return normalize.Activity(**fields)
