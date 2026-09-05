"""SQLite storage, using the same key scheme as the planned DynamoDB table.

Why SQLite looks nothing like a normal SQL schema here: there is one table, with a
partition key, a sort key, and the record itself as JSON text. That is not how you would
normally use a relational database -- but it IS how DynamoDB works, and copying that
shape has two payoffs.

  1. Moving to DynamoDB later swaps this class for `DynamoRepository` and changes
     nothing else in the application.
  2. The access patterns get exercised now. If a screen needs a lookup this shape
     cannot do, we find out while it is still cheap to change.

`sqlite3` is part of the Python standard library, so this adds no dependency, and there
is no ORM to learn on top of it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from backend.adapters import keys
from backend.adapters import repository
from backend.core import models

# One table, three columns. The primary key is the pair (pk, sk), exactly as in
# DynamoDB, which is what makes a save either insert a new record or replace the
# existing one at that key.
SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    pk   TEXT NOT NULL,
    sk   TEXT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (pk, sk)
);
"""


class SqliteRepository:
    """Local storage for one or more users, in a single file."""

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        """Open (or create) the database.

        The default ":memory:" is a database that lives only for the life of the
        process, which is handy in tests. Pass a file path for real use.
        """
        self._path = str(database_path)

        # `check_same_thread=False` lets the connection be used from more than one
        # thread. Safe here because the CLI is single-threaded; a web server would want
        # a connection per request instead.
        self._connection = sqlite3.connect(self._path, check_same_thread=False)

        # Return rows that can be accessed by column name rather than by position, so
        # the code below says row["body"] instead of row[2].
        self._connection.row_factory = sqlite3.Row

        self._connection.execute(SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    # --- the three primitive operations -----------------------------------
    #
    # Everything else in this class is built from these. They are the same three
    # operations DynamoDB offers: fetch one item, fetch by key prefix, fetch by key
    # range. Nothing here filters on the contents of the JSON body, on purpose.

    def _put(self, user_id: str, sort_key: str, model: BaseModel) -> None:
        partition = keys.user_partition(user_id)
        body = repository.encode_body(model)

        # "INSERT OR REPLACE" gives us DynamoDB's put-item behaviour: write the record,
        # overwriting whatever was at that key before.
        self._connection.execute(
            "INSERT OR REPLACE INTO items (pk, sk, body) VALUES (?, ?, ?)",
            (partition, sort_key, body),
        )
        self._connection.commit()

    def _get[ModelType: BaseModel](
        self, user_id: str, sort_key: str, model_class: type[ModelType]
    ) -> ModelType | None:
        partition = keys.user_partition(user_id)

        cursor = self._connection.execute(
            "SELECT body FROM items WHERE pk = ? AND sk = ?",
            (partition, sort_key),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return repository.decode_body(model_class, row["body"])

    def _query_prefix[ModelType: BaseModel](
        self, user_id: str, prefix: str, model_class: type[ModelType]
    ) -> list[ModelType]:
        """Every record whose sort key starts with `prefix`, in key order.

        The `GLOB` pattern is used rather than `LIKE` because GLOB is case-sensitive and
        does not treat "_" as a wildcard -- and our keys contain underscores.
        """
        partition = keys.user_partition(user_id)

        cursor = self._connection.execute(
            "SELECT body FROM items WHERE pk = ? AND sk GLOB ? ORDER BY sk",
            (partition, f"{prefix}*"),
        )

        return [repository.decode_body(model_class, row["body"]) for row in cursor.fetchall()]

    def _query_range(self, user_id: str, lower: str, upper: str) -> list[sqlite3.Row]:
        """Every record whose sort key falls between two bounds, in key order."""
        partition = keys.user_partition(user_id)

        cursor = self._connection.execute(
            "SELECT sk, body FROM items WHERE pk = ? AND sk BETWEEN ? AND ? ORDER BY sk",
            (partition, lower, upper),
        )

        return cursor.fetchall()

    def _delete(self, user_id: str, sort_key: str) -> bool:
        partition = keys.user_partition(user_id)

        cursor = self._connection.execute(
            "DELETE FROM items WHERE pk = ? AND sk = ?",
            (partition, sort_key),
        )
        self._connection.commit()

        # `rowcount` is how many rows the statement affected, so 0 means there was
        # nothing at that key.
        return cursor.rowcount > 0

    # --- profile -----------------------------------------------------------

    def get_profile(self, user_id: str) -> models.Profile | None:
        return self._get(user_id, keys.profile_key(), models.Profile)

    def save_profile(self, profile: models.Profile) -> None:
        self._put(profile.user_id, keys.profile_key(), profile)

    # --- food library ------------------------------------------------------

    def list_foods(self, user_id: str) -> list[models.Food]:
        return self._query_prefix(user_id, keys.food_prefix(), models.Food)

    def get_food(self, user_id: str, food_id: str) -> models.Food | None:
        return self._get(user_id, keys.food_key(food_id), models.Food)

    def save_food(self, user_id: str, food: models.Food) -> None:
        self._put(user_id, keys.food_key(food.id), food)

    # --- saved meals and day templates -------------------------------------

    def list_meals(self, user_id: str) -> list[models.SavedMeal]:
        return self._query_prefix(user_id, keys.meal_prefix(), models.SavedMeal)

    def get_meal(self, user_id: str, meal_id: str) -> models.SavedMeal | None:
        return self._get(user_id, keys.meal_key(meal_id), models.SavedMeal)

    def save_meal(self, user_id: str, meal: models.SavedMeal) -> None:
        self._put(user_id, keys.meal_key(meal.id), meal)

    def list_templates(self, user_id: str) -> list[models.DayTemplate]:
        return self._query_prefix(user_id, keys.template_prefix(), models.DayTemplate)

    def get_template(self, user_id: str, template_id: str) -> models.DayTemplate | None:
        return self._get(user_id, keys.template_key(template_id), models.DayTemplate)

    def save_template(self, user_id: str, template: models.DayTemplate) -> None:
        self._put(user_id, keys.template_key(template.id), template)

    # --- the food log ------------------------------------------------------

    def list_entries(self, user_id: str, day: date) -> list[models.LogEntry]:
        return self._query_prefix(user_id, keys.food_entry_prefix(day), models.LogEntry)

    def save_entry(self, user_id: str, entry: models.LogEntry) -> None:
        # The timestamp is part of the key, so several entries can coexist for one day.
        # A missing timestamp means "just now".
        logged_at = entry.logged_at or datetime.now()
        self._put(user_id, keys.food_entry_key(entry.date, logged_at), entry)

    def delete_entry(self, user_id: str, day: date, entry_id: str) -> bool:
        # The entry id is inside the body rather than in the key, so we have to read
        # the day's entries to find which key holds it.
        partition = keys.user_partition(user_id)
        prefix = keys.food_entry_prefix(day)

        cursor = self._connection.execute(
            "SELECT sk, body FROM items WHERE pk = ? AND sk GLOB ?",
            (partition, f"{prefix}*"),
        )

        for row in cursor.fetchall():
            entry = repository.decode_body(models.LogEntry, row["body"])
            if entry.id == entry_id:
                return self._delete(user_id, row["sk"])

        return False

    def clear_day_entries(self, user_id: str, day: date) -> int:
        partition = keys.user_partition(user_id)
        prefix = keys.food_entry_prefix(day)

        cursor = self._connection.execute(
            "DELETE FROM items WHERE pk = ? AND sk GLOB ?",
            (partition, f"{prefix}*"),
        )
        self._connection.commit()

        return cursor.rowcount

    # --- weight ------------------------------------------------------------

    def get_weight(self, user_id: str, day: date) -> models.WeightEntry | None:
        return self._get(user_id, keys.weight_key(day), models.WeightEntry)

    def save_weight(self, user_id: str, entry: models.WeightEntry) -> None:
        self._put(user_id, keys.weight_key(entry.date), entry)

    def list_weights(self, user_id: str, start: date, end: date) -> list[models.WeightEntry]:
        lower, upper = keys.day_range_bounds(start, end)

        weights: list[models.WeightEntry] = []
        for row in self._query_range(user_id, lower, upper):
            # The range covers every kind of day record, so pick out the weigh-ins.
            if row["sk"].endswith("#WEIGHT"):
                weights.append(repository.decode_body(models.WeightEntry, row["body"]))

        return weights

    # --- macro targets -----------------------------------------------------

    def list_targets(self, user_id: str) -> list[models.MacroTarget]:
        return self._query_prefix(user_id, keys.target_prefix(), models.MacroTarget)

    def save_target(self, user_id: str, target: models.MacroTarget) -> None:
        self._put(user_id, keys.target_key(target.effective_from), target)

    # --- DEXA scans --------------------------------------------------------

    def list_dexa_scans(self, user_id: str) -> list[models.DexaScan]:
        return self._query_prefix(user_id, keys.dexa_prefix(), models.DexaScan)

    def save_dexa_scan(self, user_id: str, scan: models.DexaScan) -> None:
        self._put(user_id, keys.dexa_key(scan.date), scan)

    # --- Garmin snapshots --------------------------------------------------

    def get_snapshot(self, user_id: str, day: date) -> models.DailyHealthSnapshot | None:
        return self._get(user_id, keys.snapshot_key(day), models.DailyHealthSnapshot)

    def save_snapshot(self, user_id: str, snapshot: models.DailyHealthSnapshot) -> None:
        self._put(user_id, keys.snapshot_key(snapshot.date), snapshot)

    def list_snapshots(
        self, user_id: str, start: date, end: date
    ) -> list[models.DailyHealthSnapshot]:
        lower, upper = keys.day_range_bounds(start, end)

        snapshots: list[models.DailyHealthSnapshot] = []
        for row in self._query_range(user_id, lower, upper):
            if row["sk"].endswith("#SNAPSHOT"):
                snapshots.append(repository.decode_body(models.DailyHealthSnapshot, row["body"]))

        return snapshots

    # --- helpers for tooling ----------------------------------------------

    def item_count(self) -> int:
        cursor = self._connection.execute("SELECT COUNT(*) AS total FROM items")
        return int(cursor.fetchone()["total"])

    def all_sort_keys(self, user_id: str) -> list[str]:
        partition = keys.user_partition(user_id)
        cursor = self._connection.execute(
            "SELECT sk FROM items WHERE pk = ? ORDER BY sk", (partition,)
        )
        return [row["sk"] for row in cursor.fetchall()]

    def export_items(self) -> list[dict[str, str]]:
        """Dump every record. This is how a real DynamoDB table gets seeded later."""
        cursor = self._connection.execute("SELECT pk, sk, body FROM items ORDER BY pk, sk")
        return [
            {"pk": row["pk"], "sk": row["sk"], "body": row["body"]}
            for row in cursor.fetchall()
        ]

    def import_items(self, items: Iterable[dict[str, str]]) -> int:
        count = 0
        for item in items:
            self._connection.execute(
                "INSERT OR REPLACE INTO items (pk, sk, body) VALUES (?, ?, ?)",
                (item["pk"], item["sk"], item["body"]),
            )
            count += 1
        self._connection.commit()
        return count
