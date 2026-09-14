"""Saving and loading food entries, in the same store as the days.

The keys were designed for this from the start: a food entry's sort key is
`DAY#2026-09-12#FOOD#<timestamp>`, which sits under the same `DAY#2026-09-12#` prefix
as that day's snapshot and weigh-in. So "everything about this day" stays one lookup
however many things end up living in a day.

The timestamp in the key is what lets a day hold many entries and hand them back in the
order they were logged.
"""

from __future__ import annotations

import datetime

from backend.food import log
from backend.store import database
from backend.store import keys


def entry_to_record(entry: log.LoggedFood) -> dict:
    """Turn one logged entry into a plain dictionary for storage."""
    return {
        "food_id": entry.food_id,
        "food_name": entry.food_name,
        "servings": entry.servings,
        "serving_basis": entry.serving_basis,
        "kilocalories": entry.kilocalories,
        "protein_grams": entry.protein_grams,
        "carbohydrate_grams": entry.carbohydrate_grams,
        "fat_grams": entry.fat_grams,
        "logged_at": entry.logged_at.isoformat(),
        "meal_id": entry.meal_id,
    }


def record_to_entry(record: dict) -> log.LoggedFood:
    """Turn a stored record back into a logged entry."""
    return log.LoggedFood(
        food_id=record["food_id"],
        food_name=record["food_name"],
        servings=record["servings"],
        serving_basis=record["serving_basis"],
        kilocalories=record["kilocalories"],
        protein_grams=record["protein_grams"],
        carbohydrate_grams=record["carbohydrate_grams"],
        fat_grams=record["fat_grams"],
        logged_at=datetime.datetime.fromisoformat(record["logged_at"]),
        meal_id=record.get("meal_id"),
    )


def save_entry(
    open_database: database.Database,
    day: datetime.date,
    entry: log.LoggedFood,
    user_id: str = keys.DEFAULT_USER_ID,
) -> str:
    """Store one food entry and return the key it was stored under.

    The key is returned so the caller can undo it. Without that, removing the thing you
    just logged would mean guessing its timestamp.
    """
    sort_key = keys.food_entry_key(day, entry.logged_at)

    open_database.save(
        partition_key=keys.user_partition(user_id),
        sort_key=sort_key,
        body=entry_to_record(entry),
    )

    return sort_key


def load_entries_for_day(
    open_database: database.Database,
    day: datetime.date,
    user_id: str = keys.DEFAULT_USER_ID,
) -> list[log.LoggedFood]:
    """Every food entry for one day, in the order it was logged."""
    found = open_database.load_by_prefix(
        partition_key=keys.user_partition(user_id),
        sort_key_prefix=keys.food_entry_prefix(day),
    )

    entries = []

    for _sort_key, record in found:
        entries.append(record_to_entry(record))

    return entries


def remove_entry(
    open_database: database.Database,
    sort_key: str,
    user_id: str = keys.DEFAULT_USER_ID,
) -> None:
    """Remove one food entry by its key."""
    open_database.delete(partition_key=keys.user_partition(user_id), sort_key=sort_key)


def remove_whole_day(
    open_database: database.Database,
    day: datetime.date,
    user_id: str = keys.DEFAULT_USER_ID,
) -> int:
    """Remove every food entry for a day, and say how many went.

    Needed by "copy yesterday" and by re-applying a template: without it, running either
    twice would leave you with two breakfasts rather than one.
    """
    found = open_database.load_by_prefix(
        partition_key=keys.user_partition(user_id),
        sort_key_prefix=keys.food_entry_prefix(day),
    )

    for sort_key, _record in found:
        open_database.delete(partition_key=keys.user_partition(user_id), sort_key=sort_key)

    return len(found)
