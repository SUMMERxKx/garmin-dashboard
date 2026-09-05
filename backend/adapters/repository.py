"""The storage port, plus an in-memory implementation used by tests.

"Port" means an interface that the rest of the application talks to, so the actual
storage can be swapped without touching anything else. There are two implementations:

    InMemoryRepository   a dictionary. Used by every test.
    DynamoRepository     real AWS DynamoDB. Used when the app runs.

Both are addressed with the same keys (see `keys.py`), because the in-memory one is
deliberately a small imitation of how DynamoDB behaves: records are looked up by an
exact key, by a key prefix, or by a range of keys, and nothing else. Keeping the fake
that restricted is the point -- if a test passes here it will behave the same way
against the real database.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from datetime import datetime
from typing import Protocol
from typing import runtime_checkable

from pydantic import BaseModel

from backend.adapters import keys
from backend.core import models


@runtime_checkable
class HealthRepository(Protocol):
    """Everything the application needs from storage.

    Deliberately small and shaped around the access patterns in the plan, rather than
    offering a general query language. If a new screen needs a new kind of lookup, that
    is a decision to make explicitly here, not something to improvise in a caller.
    """

    # --- profile -----------------------------------------------------------
    def get_profile(self, user_id: str) -> models.Profile | None: ...
    def save_profile(self, profile: models.Profile) -> None: ...

    # --- food library ------------------------------------------------------
    def list_foods(self, user_id: str) -> list[models.Food]: ...
    def get_food(self, user_id: str, food_id: str) -> models.Food | None: ...
    def save_food(self, user_id: str, food: models.Food) -> None: ...

    # --- saved meals and day templates -------------------------------------
    def list_meals(self, user_id: str) -> list[models.SavedMeal]: ...
    def get_meal(self, user_id: str, meal_id: str) -> models.SavedMeal | None: ...
    def save_meal(self, user_id: str, meal: models.SavedMeal) -> None: ...
    def list_templates(self, user_id: str) -> list[models.DayTemplate]: ...
    def get_template(self, user_id: str, template_id: str) -> models.DayTemplate | None: ...
    def save_template(self, user_id: str, template: models.DayTemplate) -> None: ...

    # --- the food log ------------------------------------------------------
    def list_entries(self, user_id: str, day: date) -> list[models.LogEntry]: ...
    def save_entry(self, user_id: str, entry: models.LogEntry) -> None: ...
    def delete_entry(self, user_id: str, day: date, entry_id: str) -> bool: ...
    def clear_day_entries(self, user_id: str, day: date) -> int: ...

    # --- weight ------------------------------------------------------------
    def get_weight(self, user_id: str, day: date) -> models.WeightEntry | None: ...
    def save_weight(self, user_id: str, entry: models.WeightEntry) -> None: ...
    def list_weights(self, user_id: str, start: date, end: date) -> list[models.WeightEntry]: ...

    # --- macro targets -----------------------------------------------------
    def list_targets(self, user_id: str) -> list[models.MacroTarget]: ...
    def save_target(self, user_id: str, target: models.MacroTarget) -> None: ...

    # --- DEXA scans --------------------------------------------------------
    def list_dexa_scans(self, user_id: str) -> list[models.DexaScan]: ...
    def save_dexa_scan(self, user_id: str, scan: models.DexaScan) -> None: ...

    # --- Garmin snapshots --------------------------------------------------
    def get_snapshot(self, user_id: str, day: date) -> models.DailyHealthSnapshot | None: ...
    def save_snapshot(self, user_id: str, snapshot: models.DailyHealthSnapshot) -> None: ...
    def list_snapshots(
        self, user_id: str, start: date, end: date
    ) -> list[models.DailyHealthSnapshot]: ...


# ---------------------------------------------------------------------------
# Turning models into stored records and back
# ---------------------------------------------------------------------------
#
# Every record is stored the same way: two key columns, and the model serialised to a
# JSON string in a third.
#
# Storing the body as JSON text rather than as individual database attributes is a
# deliberate simplification, and it removes a well-known DynamoDB annoyance: DynamoDB
# has no floating-point type, so numbers normally come back as `Decimal` objects that
# then break JSON serialisation further down the line. A JSON string goes in and comes
# out unchanged.
#
# The trade-off is that we cannot filter on a field inside the body -- only on the keys.
# Every access pattern we have is key-based, so that costs us nothing today. If an
# ad-hoc query is ever genuinely needed, the raw responses in S3 are the place for it.


def encode_body(model: BaseModel) -> str:
    """Serialise a Pydantic model to a JSON string for storage."""
    return model.model_dump_json()


def decode_body[ModelType: BaseModel](model_class: type[ModelType], body: str) -> ModelType:
    """Rebuild a Pydantic model from a stored JSON string.

    The `[ModelType: BaseModel]` part reads as: "this function works for any type called
    ModelType, as long as it is a Pydantic model". Whatever class you pass in is the type
    you get back -- so `decode_body(Food, body)` is known to return a Food.

    That is the difference between this and returning `Any`. With `Any`, nothing would
    notice if a caller then asked the result for a field that does not exist.
    """
    return model_class.model_validate_json(body)


# ---------------------------------------------------------------------------
# The in-memory implementation
# ---------------------------------------------------------------------------


class InMemoryRepository:
    """A dictionary pretending to be DynamoDB. Used by tests.

    Kept intentionally limited to the three lookups the real database supports:
    get one item, get items by key prefix, and get items in a key range.
    """

    def __init__(self) -> None:
        # (partition key, sort key) -> stored JSON body
        self._items: dict[tuple[str, str], str] = {}

    # --- the three primitive operations -----------------------------------

    def _put(self, user_id: str, sort_key: str, model: BaseModel) -> None:
        partition = keys.user_partition(user_id)
        self._items[(partition, sort_key)] = encode_body(model)

    def _get[ModelType: BaseModel](
        self, user_id: str, sort_key: str, model_class: type[ModelType]
    ) -> ModelType | None:
        partition = keys.user_partition(user_id)
        body = self._items.get((partition, sort_key))

        if body is None:
            return None

        return decode_body(model_class, body)

    def _query_prefix[ModelType: BaseModel](
        self, user_id: str, prefix: str, model_class: type[ModelType]
    ) -> list[ModelType]:
        """Every item whose sort key starts with `prefix`, in sort-key order."""
        partition = keys.user_partition(user_id)

        matching: list[tuple[str, str]] = []
        for (item_partition, sort_key), body in self._items.items():
            if item_partition != partition:
                continue
            if not sort_key.startswith(prefix):
                continue
            matching.append((sort_key, body))

        matching.sort(key=lambda pair: pair[0])

        return [decode_body(model_class, body) for _sort_key, body in matching]

    def _query_range(
        self, user_id: str, lower: str, upper: str
    ) -> list[tuple[str, str]]:
        """Every (sort key, body) between two bounds, in sort-key order."""
        partition = keys.user_partition(user_id)

        matching: list[tuple[str, str]] = []
        for (item_partition, sort_key), body in self._items.items():
            if item_partition != partition:
                continue
            if lower <= sort_key <= upper:
                matching.append((sort_key, body))

        matching.sort(key=lambda pair: pair[0])
        return matching

    def _delete(self, user_id: str, sort_key: str) -> bool:
        partition = keys.user_partition(user_id)
        existed = (partition, sort_key) in self._items
        self._items.pop((partition, sort_key), None)
        return existed

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
        logged_at = entry.logged_at or datetime.now()
        self._put(user_id, keys.food_entry_key(entry.date, logged_at), entry)

    def delete_entry(self, user_id: str, day: date, entry_id: str) -> bool:
        partition = keys.user_partition(user_id)
        prefix = keys.food_entry_prefix(day)

        for (item_partition, sort_key), body in list(self._items.items()):
            if item_partition != partition:
                continue
            if not sort_key.startswith(prefix):
                continue

            entry = decode_body(models.LogEntry, body)
            if entry.id == entry_id:
                del self._items[(item_partition, sort_key)]
                return True

        return False

    def clear_day_entries(self, user_id: str, day: date) -> int:
        partition = keys.user_partition(user_id)
        prefix = keys.food_entry_prefix(day)

        removed = 0
        for item_partition, sort_key in list(self._items.keys()):
            if item_partition != partition:
                continue
            if sort_key.startswith(prefix):
                del self._items[(item_partition, sort_key)]
                removed += 1

        return removed

    # --- weight ------------------------------------------------------------

    def get_weight(self, user_id: str, day: date) -> models.WeightEntry | None:
        return self._get(user_id, keys.weight_key(day), models.WeightEntry)

    def save_weight(self, user_id: str, entry: models.WeightEntry) -> None:
        self._put(user_id, keys.weight_key(entry.date), entry)

    def list_weights(self, user_id: str, start: date, end: date) -> list[models.WeightEntry]:
        lower, upper = keys.day_range_bounds(start, end)

        weights: list[models.WeightEntry] = []
        for sort_key, body in self._query_range(user_id, lower, upper):
            if sort_key.endswith("#WEIGHT"):
                weights.append(decode_body(models.WeightEntry, body))

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
        for sort_key, body in self._query_range(user_id, lower, upper):
            if sort_key.endswith("#SNAPSHOT"):
                snapshots.append(decode_body(models.DailyHealthSnapshot, body))

        return snapshots

    # --- helpers for tests and tooling ------------------------------------

    def item_count(self) -> int:
        return len(self._items)

    def all_sort_keys(self, user_id: str) -> list[str]:
        partition = keys.user_partition(user_id)

        sort_keys = []
        for stored_key in self._items:
            item_partition, sort_key = stored_key
            if item_partition == partition:
                sort_keys.append(sort_key)

        return sorted(sort_keys)

    def export_items(self) -> list[dict[str, str]]:
        """Dump every record, for seeding a real table from a local run."""
        exported = []
        for (partition, sort_key), body in sorted(self._items.items()):
            exported.append({"pk": partition, "sk": sort_key, "body": body})
        return exported

    def import_items(self, items: Iterable[dict[str, str]]) -> int:
        count = 0
        for item in items:
            self._items[(item["pk"], item["sk"])] = item["body"]
            count += 1
        return count


def dump_json(repository: InMemoryRepository) -> str:
    """Serialise a whole in-memory repository, used by the seeding tools."""
    return json.dumps(repository.export_items(), indent=2)
