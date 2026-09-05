"""Load the seed YAML file into a repository.

The seed file (`seed/food-library.yaml`) holds the starting point: the profile, the
macro target, the food library, the saved meals and the day template. This turns that
file into stored records.

Note the nutrition numbers in that file are currently PROVISIONAL -- typical published
values rather than readings from the actual product labels. The file says so, and
`validate_food` still checks each one reconciles with 4P + 4C + 9F, so a typo fails
loudly rather than quietly skewing every total.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from backend.adapters import repository as storage
from backend.core import models
from backend.core import nutrition

# The project root is two folders up from this file: backend/adapters/ -> backend/ -> root
THIS_FILE = Path(__file__).resolve()
ADAPTERS_DIRECTORY = THIS_FILE.parent
BACKEND_DIRECTORY = ADAPTERS_DIRECTORY.parent
PROJECT_ROOT = BACKEND_DIRECTORY.parent

DEFAULT_SEED_FILE = PROJECT_ROOT / "seed" / "food-library.yaml"


class SeedError(Exception):
    """Raised when the seed file cannot be trusted.

    Deliberately loud. A wrong macro value here would flow into every calculation the
    app makes, so it is better to refuse to load than to load something wrong.
    """


def read_seed_file(path: str | Path = DEFAULT_SEED_FILE) -> dict[str, Any]:
    """Parse the YAML file into plain dictionaries and lists."""
    seed_path = Path(path)

    if not seed_path.exists():
        raise SeedError(f"seed file not found: {seed_path}")

    return yaml.safe_load(seed_path.read_text(encoding="utf-8"))


def build_profile(seed: dict[str, Any], user_id: str) -> models.Profile:
    """Turn the `profile` section into a Profile."""
    section = seed["profile"]

    return models.Profile(
        user_id=user_id,
        sex=models.Sex(section["sex"]),
        birth_date=section["birth_date"],
        height_cm=float(section["height_cm"]),
        timezone=section.get("timezone", "America/Vancouver"),
    )


def build_targets(seed: dict[str, Any]) -> list[models.MacroTarget]:
    """Turn the `macro_targets` section into MacroTarget records.

    These are effective-dated and append-only, so there can be several and each applies
    from its own start date onward.
    """
    targets: list[models.MacroTarget] = []

    for entry in seed.get("macro_targets", []):
        target = models.MacroTarget(
            effective_from=entry["effective_from"],
            goal=models.GoalType(entry["goal"]),
            kcal=float(entry["kcal"]),
            protein_g=float(entry["protein_g"]),
            carbs_g=float(entry["carbs_g"]),
            fat_g=float(entry["fat_g"]),
        )

        # The stated calorie figure should match what the macros imply. A gap here
        # usually means a typo in one of the four numbers.
        gap = abs(target.implied_kcal - target.kcal)
        if gap > 25.0:
            raise SeedError(
                f"target from {target.effective_from} is inconsistent: "
                f"macros imply {target.implied_kcal:.0f} kcal but it says {target.kcal:.0f}"
            )

        targets.append(target)

    return targets


def build_food(entry: dict[str, Any]) -> models.Food:
    """Turn one entry from the `foods` section into a Food."""
    missing_fields = []
    for required in ("kcal", "protein_g", "carbs_g", "fat_g"):
        if entry.get(required) is None:
            missing_fields.append(required)

    if missing_fields:
        raise SeedError(
            f"food '{entry['id']}' is missing {', '.join(missing_fields)} -- "
            "fill it in from the product label before loading"
        )

    food = models.Food(
        id=entry["id"],
        name=entry["name"],
        brand=entry.get("brand"),
        serving_desc=entry["serving_desc"],
        serving_g=entry.get("serving_g"),
        serving_basis=models.ServingBasis(entry["serving_basis"]),
        kcal=float(entry["kcal"]),
        protein_g=float(entry["protein_g"]),
        carbs_g=float(entry["carbs_g"]),
        fat_g=float(entry["fat_g"]),
        fiber_g=entry.get("fiber_g"),
        sodium_mg=entry.get("sodium_mg"),
    )

    if not nutrition.validate_food(food):
        raise SeedError(
            f"food '{food.id}' does not reconcile: stated {food.kcal:.0f} kcal, but "
            f"4P + 4C + 9F implies {food.protein_g * 4 + food.carbs_g * 4 + food.fat_g * 9:.0f}"
        )

    return food


def build_foods(seed: dict[str, Any]) -> list[models.Food]:
    foods: list[models.Food] = []
    for entry in seed.get("foods", []):
        foods.append(build_food(entry))
    return foods


def build_meals(seed: dict[str, Any], known_food_ids: set[str]) -> list[models.SavedMeal]:
    """Turn the `saved_meals` section into SavedMeal records.

    A serving of None means "decide this per day" -- rice is the reason that exists,
    since the portion changes.
    """
    meals: list[models.SavedMeal] = []

    for entry in seed.get("saved_meals", []):
        items: list[models.MealItem] = []

        for item in entry["items"]:
            food_id = item["food_id"]

            if food_id not in known_food_ids:
                raise SeedError(f"meal '{entry['id']}' refers to unknown food '{food_id}'")

            servings = item.get("servings")
            if servings is None:
                items.append(models.MealItem(food_id=food_id, servings=None))
            else:
                items.append(models.MealItem(food_id=food_id, servings=float(servings)))

        meals.append(models.SavedMeal(id=entry["id"], name=entry["name"], items=items))

    return meals


def build_templates(seed: dict[str, Any], known_meal_ids: set[str]) -> list[models.DayTemplate]:
    """Turn the `day_templates` section into DayTemplate records."""
    templates: list[models.DayTemplate] = []

    for entry in seed.get("day_templates", []):
        meal_ids = entry.get("meals", [])

        for meal_id in meal_ids:
            if meal_id not in known_meal_ids:
                raise SeedError(
                    f"template '{entry['id']}' refers to unknown meal '{meal_id}'"
                )

        templates.append(
            models.DayTemplate(id=entry["id"], name=entry["name"], meal_ids=list(meal_ids))
        )

    return templates


def load_seed(
    repository: storage.HealthRepository,
    user_id: str,
    *,
    path: str | Path = DEFAULT_SEED_FILE,
) -> dict[str, int]:
    """Read the seed file and write everything into the repository.

    Returns a count of what was written, so the CLI can report it.
    """
    seed = read_seed_file(path)

    profile = build_profile(seed, user_id)
    targets = build_targets(seed)
    foods = build_foods(seed)

    known_food_ids = {food.id for food in foods}
    meals = build_meals(seed, known_food_ids)

    known_meal_ids = {meal.id for meal in meals}
    templates = build_templates(seed, known_meal_ids)

    # Only write once everything has been built and validated, so a failure halfway
    # through the file does not leave storage half-populated.
    repository.save_profile(profile)

    for target in targets:
        repository.save_target(user_id, target)
    for food in foods:
        repository.save_food(user_id, food)
    for meal in meals:
        repository.save_meal(user_id, meal)
    for template in templates:
        repository.save_template(user_id, template)

    return {
        "targets": len(targets),
        "foods": len(foods),
        "meals": len(meals),
        "templates": len(templates),
    }


def seed_is_provisional(path: str | Path = DEFAULT_SEED_FILE) -> bool:
    """Whether the seed file still holds placeholder nutrition values.

    The CLI uses this to print a reminder, because a dashboard built on typical
    published figures rather than your own labels is only approximately right.
    """
    seed = read_seed_file(path)
    return bool(seed.get("provisional", False))


def latest_target_date(targets: list[models.MacroTarget]) -> date | None:
    if not targets:
        return None
    return max(target.effective_from for target in targets)
