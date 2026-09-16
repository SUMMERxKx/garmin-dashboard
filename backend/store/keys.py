"""The key scheme: how every record is addressed in storage.

Written once here and used by every part of the store, so that the addressing rules
live in one file rather than being spelled out again at each call site.

The shape is taken from the DynamoDB table this will eventually run on. DynamoDB uses
what is called a *single table design*: rather than one table per kind of thing, as a
relational database would have, everything lives in one table and the KEY says what
each record is.

Every record has a two-part key:

    pk  the partition key -- always the user, so one person's data sits together
    sk  the sort key      -- what this record is, and when

    pk            sk
    USER#me       DAY#2026-09-12#SNAPSHOT
    USER#me       DAY#2026-09-12#WEIGHT
    USER#me       DAY#2026-09-12#INTAKE
    USER#me       DAY#2026-09-12#FOOD#20260912T120000000000

Why this shape
--------------
Sort keys are stored in order. So asking for every key starting with
`DAY#2026-09-12#` returns that whole day -- the Garmin snapshot, the weigh-in and every
food entry -- in one lookup rather than three. That single access pattern is the reason
this is a key-value store rather than a relational one.

It also means a RANGE of days is one lookup: because dates are written YYYY-MM-DD,
sorting the keys as text sorts them correctly as dates, so "every record from 1 August
to 3 September" is just "every key between these two strings". Baselines need exactly
that, which is why the scheme is worth copying carefully rather than inventing.
"""

from __future__ import annotations

import datetime

#: One user for now. It is passed as an argument everywhere rather than written into
#: the keys directly, so supporting a second person later is a change to the callers
#: and not to the storage layer.
DEFAULT_USER_ID = "me"

#: The separator between the parts of a key. "#" is the convention in single-table
#: designs because it never appears inside an id or a date, so a key can always be
#: split back into its parts without ambiguity.
SEPARATOR = "#"

#: What a food entry's key says it is, between the day and the timestamp. Named here
#: rather than spelled out at each call site, so that recognising a food key and building
#: one stay in the same file and cannot drift apart.
FOOD_MARKER = f"{SEPARATOR}FOOD{SEPARATOR}"

#: Sorts after every character that can appear in one of our keys, so a range whose
#: upper bound ends with it includes that last day completely rather than stopping at
#: the bare "DAY#2026-09-03#".
HIGHEST_CHARACTER = "~"


def user_partition(user_id: str = DEFAULT_USER_ID) -> str:
    """The partition key: everything belonging to one person."""
    return f"USER{SEPARATOR}{user_id}"
def day_prefix(day: datetime.date) -> str:
    """Matches every record belonging to one day.

    The important one: a single lookup with this prefix returns the snapshot, the
    weigh-in and every food entry for that day together.
    """
    return f"DAY{SEPARATOR}{day.isoformat()}{SEPARATOR}"


def snapshot_key(day: datetime.date) -> str:
    """The Garmin data for one day."""
    return f"{day_prefix(day)}SNAPSHOT"


def weight_key(day: datetime.date) -> str:
    """The weigh-in for one day. At most one, because a day has one morning."""
    return f"{day_prefix(day)}WEIGHT"


def intake_key(day: datetime.date) -> str:
    """The typed-in calorie total for one day. At most one, for the same reason as weight.

    A manual total is "what the whole day added up to", so a second one for the same day
    is a correction of the first rather than an addition to it -- and it REPLACES it.
    Letting two coexist would add them together and double the day.
    """
    return f"{day_prefix(day)}INTAKE"


def food_entry_key(day: datetime.date, logged_at: datetime.datetime) -> str:
    """One logged food item.

    The timestamp is part of the key so that a day can hold many entries and they come
    back in the order they were logged. It is written without dashes or colons so it
    cannot be mistaken for the date earlier in the same key.

    Microseconds are included because two entries logged in the same second would
    otherwise share a key, and the second would silently replace the first.
    """
    timestamp = logged_at.strftime("%Y%m%dT%H%M%S%f")
    return f"{day_prefix(day)}FOOD{SEPARATOR}{timestamp}"


def food_entry_prefix(day: datetime.date) -> str:
    """Matches every food entry for one day."""
    return f"{day_prefix(day)}FOOD{SEPARATOR}"


def day_range_bounds(
    first_day: datetime.date,
    last_day: datetime.date,
) -> tuple[str, str]:
    """The lowest and highest sort keys covering a span of days, both ends included.

    This is what baselines and trends are read with: ninety days of history is one
    lookup between two strings rather than ninety separate reads.
    """
    lowest = f"DAY{SEPARATOR}{first_day.isoformat()}{SEPARATOR}"
    highest = f"DAY{SEPARATOR}{last_day.isoformat()}{SEPARATOR}{HIGHEST_CHARACTER}"

    return (lowest, highest)


def day_from_key(sort_key: str) -> datetime.date | None:
    """Read the date back out of a sort key, or None if there is not one in it.

    Used when a range lookup hands back records from many days at once and each one
    needs to be filed under the day it belongs to.
    """
    parts = sort_key.split(SEPARATOR)

    # Every day record looks like DAY#<date>#<something>, so anything shorter than
    # three parts, or not starting with DAY, is not one.
    if len(parts) < 3:
        return None

    if parts[0] != "DAY":
        return None

    try:
        return datetime.date.fromisoformat(parts[1])
    except ValueError:
        return None
