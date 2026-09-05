"""Food logging operations.

The design goal here is speed of logging, because logging friction is what kills every
nutrition app. The diet is repetitive, so the fast paths are "copy yesterday" and "apply
a saved meal", not searching a database of foods.

Everything in here is a plain function taking a repository, so it can be tested against
the in-memory store with no database and no mocking.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from datetime import datetime

from backend.adapters import repository as storage
from backend.core import models
from backend.core import nutrition


class FoodLogError(Exception):
    """Raised when an operation cannot be carried out at all, such as an unknown food."""


@dataclass
class ApplyResult:
    """What happened when a meal, template or previous day was applied.

    `needs_servings` is the interesting field. A meal can deliberately leave a portion
    unset -- rice is the example, because the amount changes day to day -- so those
    items are reported back rather than guessed at, and the caller can prompt for them.
    """

    entries: list[models.LogEntry] = field(default_factory=list)
    needs_servings: list[str] = field(default_factory=list)
    unknown_foods: list[str] = field(default_factory=list)
    replaced: int = 0


def new_entry_id() -> str:
    """A short unique id for a log entry.

    uuid4 is a random 128-bit identifier. The first 12 hex characters are more than
    enough to keep one person's entries distinct, and they are short enough to type
    into the CLI when deleting one.
    """
    return uuid.uuid4().hex[:12]


def log_food(
    repository: storage.HealthRepository,
    user_id: str,
    day: date,
    food_id: str,
    servings: float,
    *,
    meal: str | None = None,
    source: models.LogSource = models.LogSource.MANUAL,
    entry_id: str | None = None,
    logged_at: datetime | None = None,
) -> models.LogEntry:
    """Add one food to a day's log.

    The macros are worked out now and STORED WITH THE ENTRY. That is deliberate: if a
    food's label is corrected next month, last month's totals must not silently change.
    """
    food = repository.get_food(user_id, food_id)

    if food is None:
        raise FoodLogError(f"no food in the library with id '{food_id}'")

    entry = models.LogEntry(
        id=entry_id or new_entry_id(),
        date=day,
        food_id=food.id,
        food_name=food.name,
        servings=servings,
        macros_snapshot=nutrition.resolve_entry(food, servings),
        # The raw/cooked/as-sold basis travels with the entry so the screen can show it.
        # The engine never converts between states, so this has to be visible.
        serving_basis=food.serving_basis,
        meal=meal,
        logged_at=logged_at or datetime.now(),
        source=source,
        was_edited=False,
    )

    repository.save_entry(user_id, entry)
    return entry


def adjust_entry(
    repository: storage.HealthRepository,
    user_id: str,
    day: date,
    entry_id: str,
    new_servings: float,
) -> models.LogEntry | None:
    """Change how much of something was eaten.

    Re-reads the food from the library so the macros are recalculated, and marks the
    entry as edited. That flag is what will later tell us how often an automatically
    created entry needed correcting.
    """
    for entry in repository.list_entries(user_id, day):
        if entry.id != entry_id:
            continue

        food = repository.get_food(user_id, entry.food_id)
        if food is None:
            raise FoodLogError(f"food '{entry.food_id}' is no longer in the library")

        # Remove the old record first, because the servings are not part of the key but
        # the timestamp is, and we want to keep the original logging time.
        repository.delete_entry(user_id, day, entry_id)

        updated = models.LogEntry(
            id=entry.id,
            date=entry.date,
            food_id=entry.food_id,
            food_name=food.name,
            servings=new_servings,
            macros_snapshot=nutrition.resolve_entry(food, new_servings),
            serving_basis=food.serving_basis,
            meal=entry.meal,
            logged_at=entry.logged_at,
            source=entry.source,
            was_edited=True,
        )

        repository.save_entry(user_id, updated)
        return updated

    return None


def remove_entry(repository: storage.HealthRepository, user_id: str, day: date, entry_id: str) -> bool:
    """Delete one logged item. Returns whether anything was actually removed."""
    return repository.delete_entry(user_id, day, entry_id)


def clear_day(repository: storage.HealthRepository, user_id: str, day: date) -> int:
    """Remove every logged item for a day. Returns how many went."""
    return repository.clear_day_entries(user_id, day)


def _apply_items(
    repository: storage.HealthRepository,
    user_id: str,
    day: date,
    items: list[models.MealItem],
    *,
    meal_name: str | None,
    source: models.LogSource,
    servings_overrides: dict[str, float] | None,
) -> ApplyResult:
    """Shared work behind applying a meal or a template."""
    result = ApplyResult()
    overrides = servings_overrides or {}

    for item in items:
        food = repository.get_food(user_id, item.food_id)

        if food is None:
            result.unknown_foods.append(item.food_id)
            continue

        # An override always wins, then the meal's own figure. If neither exists the
        # portion is genuinely undecided, so report it instead of inventing one.
        if item.food_id in overrides:
            servings = overrides[item.food_id]
        elif item.servings is not None:
            servings = item.servings
        else:
            result.needs_servings.append(item.food_id)
            continue

        entry = log_food(
            repository,
            user_id,
            day,
            item.food_id,
            servings,
            meal=meal_name,
            source=source,
        )
        result.entries.append(entry)

    return result


def apply_meal(
    repository: storage.HealthRepository,
    user_id: str,
    day: date,
    meal_id: str,
    *,
    servings_overrides: dict[str, float] | None = None,
) -> ApplyResult:
    """Log a whole saved meal at once -- breakfast, dinner and so on."""
    meal = repository.get_meal(user_id, meal_id)

    if meal is None:
        raise FoodLogError(f"no saved meal with id '{meal_id}'")

    return _apply_items(
        repository,
        user_id,
        day,
        meal.items,
        meal_name=meal.name,
        source=models.LogSource.TEMPLATE,
        servings_overrides=servings_overrides,
    )


def apply_template(
    repository: storage.HealthRepository,
    user_id: str,
    day: date,
    template_id: str,
    *,
    servings_overrides: dict[str, float] | None = None,
    replace_existing: bool = True,
) -> ApplyResult:
    """Log a whole day at once from a template, such as "Normal Day"."""
    template = repository.get_template(user_id, template_id)

    if template is None:
        raise FoodLogError(f"no day template with id '{template_id}'")

    combined = ApplyResult()

    if replace_existing:
        combined.replaced = clear_day(repository, user_id, day)

    for meal_id in template.meal_ids:
        meal = repository.get_meal(user_id, meal_id)

        if meal is None:
            raise FoodLogError(
                f"template '{template_id}' refers to a meal that no longer exists: '{meal_id}'"
            )

        one_meal = _apply_items(
            repository,
            user_id,
            day,
            meal.items,
            meal_name=meal.name,
            source=models.LogSource.TEMPLATE,
            servings_overrides=servings_overrides,
        )

        combined.entries.extend(one_meal.entries)
        combined.needs_servings.extend(one_meal.needs_servings)
        combined.unknown_foods.extend(one_meal.unknown_foods)

    # Any leftover items from the template's own meals are also applied, if it has some
    # directly attached rather than grouped into meals.
    if template.items:
        direct = _apply_items(
            repository,
            user_id,
            day,
            template.items,
            meal_name=None,
            source=models.LogSource.TEMPLATE,
            servings_overrides=servings_overrides,
        )
        combined.entries.extend(direct.entries)
        combined.needs_servings.extend(direct.needs_servings)
        combined.unknown_foods.extend(direct.unknown_foods)

    return combined


def copy_day(
    repository: storage.HealthRepository,
    user_id: str,
    from_day: date,
    to_day: date,
    *,
    replace_existing: bool = True,
) -> ApplyResult:
    """Copy one day's food onto another. This is the "Copy Yesterday" button.

    The macros are RE-CALCULATED from the current food library rather than copied from
    the old entries. If a label was corrected in between, today should use the corrected
    figure -- while the original day keeps the numbers it was logged with.
    """
    source_entries = repository.list_entries(user_id, from_day)

    result = ApplyResult()

    if replace_existing:
        result.replaced = clear_day(repository, user_id, to_day)

    for source_entry in source_entries:
        food = repository.get_food(user_id, source_entry.food_id)

        if food is None:
            # The food has been deleted from the library since. Report it rather than
            # silently dropping part of the day.
            result.unknown_foods.append(source_entry.food_id)
            continue

        entry = log_food(
            repository,
            user_id,
            to_day,
            source_entry.food_id,
            source_entry.servings,
            meal=source_entry.meal,
            source=models.LogSource.COPY,
        )
        result.entries.append(entry)

    return result
