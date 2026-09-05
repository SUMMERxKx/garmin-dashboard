"""The key scheme: how every record is addressed in storage.

This is written once, here, and used by every storage adapter. The shape is taken
directly from the planned DynamoDB table, which uses a "single table design": instead of
one table per kind of thing, everything lives in one table and the KEY says what it is.

Every record has two parts to its key:

    PK  the partition key -- always the user, so all of one person's data sits together
    SK  the sort key      -- what this record actually is, and when

    PK              SK
    USER#me         PROFILE
    USER#me         FOOD#chicken-breast
    USER#me         TARGET#2026-09-03
    USER#me         DAY#2026-09-02#SNAPSHOT
    USER#me         DAY#2026-09-02#FOOD#20260902T120000
    USER#me         DAY#2026-09-02#WEIGHT

Why it is shaped this way: sort keys are stored in order, so asking for everything
starting with "DAY#2026-09-02#" returns that whole day -- the snapshot, every food entry
and the weigh-in -- in a single lookup. That one access pattern is the reason the
database is a key-value store rather than a relational one.

The local SQLite store deliberately uses these exact same keys, so moving to DynamoDB
later is a swap of the storage class rather than a redesign.
"""

from __future__ import annotations

from datetime import date
from datetime import datetime

# Single user for now. It is a parameter everywhere rather than a hardcoded value, so
# supporting more than one person later is a change of caller, not of storage.
DEFAULT_USER_ID = "me"

# Separator between parts of a key. "#" is conventional in single-table designs because
# it does not appear in ids or dates, so a key can always be split back apart.
SEPARATOR = "#"


def user_partition(user_id: str) -> str:
    """The partition key: everything belonging to one person."""
    return f"USER{SEPARATOR}{user_id}"


# --- things there is one of, per user --------------------------------------


def profile_key() -> str:
    return "PROFILE"


# --- the food library, meals and day templates ----------------------------


def food_key(food_id: str) -> str:
    return f"FOOD{SEPARATOR}{food_id}"


def food_prefix() -> str:
    """Prefix matching every food, for "list my whole library"."""
    return f"FOOD{SEPARATOR}"


def meal_key(meal_id: str) -> str:
    return f"MEAL{SEPARATOR}{meal_id}"


def meal_prefix() -> str:
    return f"MEAL{SEPARATOR}"


def template_key(template_id: str) -> str:
    return f"TMPL{SEPARATOR}{template_id}"


def template_prefix() -> str:
    return f"TMPL{SEPARATOR}"


# --- macro targets, which are dated ---------------------------------------


def target_key(effective_from: date) -> str:
    """Targets are addressed by the date they came into force.

    Because sort keys are ordered, "the target in force on 15 August" is answered by
    asking for the largest TARGET# key that is not after that date. Nothing is ever
    overwritten, so a dashboard for a past day is scored against the target that
    actually applied then.
    """
    return f"TARGET{SEPARATOR}{effective_from.isoformat()}"


def target_prefix() -> str:
    return f"TARGET{SEPARATOR}"


# --- DEXA scans, also dated -----------------------------------------------


def dexa_key(scan_date: date) -> str:
    return f"DEXA{SEPARATOR}{scan_date.isoformat()}"


def dexa_prefix() -> str:
    return f"DEXA{SEPARATOR}"


# --- everything that belongs to one particular day ------------------------


def day_prefix(day: date) -> str:
    """Prefix matching every record for one day.

    This is the important one. A single lookup with this prefix returns the Garmin
    snapshot, every food entry and the weigh-in together.
    """
    return f"DAY{SEPARATOR}{day.isoformat()}{SEPARATOR}"


def snapshot_key(day: date) -> str:
    """The measured Garmin data for a day."""
    return f"{day_prefix(day)}SNAPSHOT"


def weight_key(day: date) -> str:
    return f"{day_prefix(day)}WEIGHT"


def food_entry_key(day: date, logged_at: datetime) -> str:
    """One logged food item.

    The timestamp is part of the key so several entries can exist for one day and come
    back in the order they were logged. It is compacted (no dashes or colons) so it
    cannot be confused with the date part of the key.
    """
    timestamp = logged_at.strftime("%Y%m%dT%H%M%S%f")
    return f"{day_prefix(day)}FOOD{SEPARATOR}{timestamp}"


def food_entry_prefix(day: date) -> str:
    return f"{day_prefix(day)}FOOD{SEPARATOR}"


# --- ranges over several days ---------------------------------------------


def day_range_bounds(start: date, end: date) -> tuple[str, str]:
    """The lowest and highest sort keys covering a span of days.

    Used for trends and baselines: "give me every record from 1 August to 3 September".
    Because dates are written as YYYY-MM-DD, sorting them as text sorts them correctly
    as dates too, which is why this works at all.

    The upper bound uses "~" because it sorts after every character we use in a key,
    so the last day is fully included rather than cut off at "DAY#2026-09-03#".
    """
    lower_bound = f"DAY{SEPARATOR}{start.isoformat()}"
    upper_bound = f"DAY{SEPARATOR}{end.isoformat()}~"
    return lower_bound, upper_bound


def day_from_sort_key(sort_key: str) -> date | None:
    """Read the date back out of a day-scoped sort key, or None if it is not one.

    "DAY#2026-09-02#SNAPSHOT" -> date(2026, 9, 2)
    "FOOD#chicken-breast"     -> None
    """
    parts = sort_key.split(SEPARATOR)

    if len(parts) < 2:
        return None
    if parts[0] != "DAY":
        return None

    try:
        return date.fromisoformat(parts[1])
    except ValueError:
        return None
