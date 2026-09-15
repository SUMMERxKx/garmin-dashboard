"""The food library: what you eat, and what is in it.

The library is a YAML file (`seed/food-library.yaml`) rather than rows typed into a
database, and that is deliberate. It is the one part of this project you will edit by
hand -- correcting a number off a product label, adding a food -- and a text file you
can open, read, and see the whole of beats a table you have to query. It also means the
library is diffable: `git diff` shows that you changed whey from 24 g protein to 25.

What lives in it
----------------
    foods           one entry per thing you eat, per SERVING
    meals           named groups of foods -- "Breakfast" is four foods in fixed amounts
    day_templates   named groups of meals -- "Normal Day" is four meals
    macro_targets   what you are aiming at, dated
    profile         sex, height, birth date, timezone

The meals and templates are the part that matters for a fixed diet: if you eat the same
four meals most days, logging a day should be one command, not twenty.

The most important field in the whole file
------------------------------------------
`serving_basis`, which is one of `raw`, `cooked` or `as_sold`. Cooking changes weight
but not macros:

    200 g raw chicken  -> ~150 g cooked.   Weigh it cooked, log it against raw macros,
                                           and you UNDER-count protein by a third.
    100 g dry rice     -> ~250-300 g cooked. Weigh it cooked, log it against dry macros,
                                           and you OVER-count by 2.5-3x -- which is
                                           larger than an entire daily deficit.

So the basis travels with the food, and later with every logged entry, and **nothing in
this project ever converts between one basis and another**. A mismatch is meant to stay
visible rather than be silently absorbed by a conversion factor nobody remembers.
"""

from __future__ import annotations

import dataclasses
import datetime
from pathlib import Path
from typing import Any

import yaml

from backend import paths

#: Where the library lives by default.
DEFAULT_LIBRARY_PATH = paths.PROJECT_ROOT / "seed" / "food-library.yaml"

#: The three states a food can be weighed in. Anything else is a typo, and a typo here
#: is not cosmetic -- it is the raw/cooked trap above.
VALID_SERVING_BASES = ["raw", "cooked", "as_sold"]

#: Calories per gram of each macronutrient. These are not opinions or estimates; they
#: are the Atwater factors, the standard the numbers on every food label are computed
#: with. They are what makes it possible to check a label against itself.
KILOCALORIES_PER_GRAM_OF_PROTEIN = 4
KILOCALORIES_PER_GRAM_OF_CARBOHYDRATE = 4
KILOCALORIES_PER_GRAM_OF_FAT = 9

#: How far a food's stated calories may sit from the sum of its macros before we call it
#: a mistake. Real labels are rounded -- to the nearest gram, and often to the nearest
#: five or ten calories -- so a small gap is normal and expected. A large one means a
#: digit was mistyped.
CALORIE_CHECK_TOLERANCE_KCAL = 12.0
CALORIE_CHECK_TOLERANCE_FRACTION = 0.06


@dataclasses.dataclass
class Food:
    """One food, described per serving.

    Everything is per SERVING rather than per 100 g, because a serving is what you
    actually think in: one scoop, one slice, one tablespoon. How much a serving weighs
    is recorded in `serving_grams` so the two can always be reconciled.
    """

    food_id: str
    name: str
    serving_description: str
    serving_grams: float
    serving_basis: str
    kilocalories: float
    protein_grams: float
    carbohydrate_grams: float
    fat_grams: float
    brand: str | None = None
    notes: str | None = None

    def macros_as_kilocalories(self) -> float:
        """What this serving's macros add up to, by the Atwater factors.

        Used to check the food against itself. If a label says 120 kcal but its macros
        add up to 180, one of the numbers was mistyped, and every day logged with it
        would be wrong in a way no amount of careful logging could catch.
        """
        from_protein = self.protein_grams * KILOCALORIES_PER_GRAM_OF_PROTEIN
        from_carbohydrate = self.carbohydrate_grams * KILOCALORIES_PER_GRAM_OF_CARBOHYDRATE
        from_fat = self.fat_grams * KILOCALORIES_PER_GRAM_OF_FAT

        return from_protein + from_carbohydrate + from_fat


@dataclasses.dataclass
class MealItem:
    """One food inside a meal, and how many servings of it.

    `servings` may be None, meaning "this varies, tell me on the day". Rice is the
    example: the meal is otherwise fixed, but how much rice depends on the day's
    training. A None here is a question the logging command has to ask, not a zero.
    """

    food_id: str
    servings: float | None = None


@dataclasses.dataclass
class Meal:
    """A named group of foods in fixed amounts -- "Breakfast", "Dinner"."""

    meal_id: str
    name: str
    items: list[MealItem] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class DayTemplate:
    """A named group of meals -- "Normal Day".

    This is the payoff of a fixed diet: a day you eat often becomes one command instead
    of twenty.
    """

    template_id: str
    name: str
    meal_ids: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class MacroTarget:
    """What you are aiming at, from a given date onwards.

    Targets are dated and nothing is ever overwritten, so a dashboard for a past day is
    scored against the target that actually applied then. Changing your target next
    month must not silently re-score last month.
    """

    effective_from: datetime.date
    goal: str
    kilocalories: float
    protein_grams: float
    carbohydrate_grams: float
    fat_grams: float


@dataclasses.dataclass
class Library:
    """The whole library, loaded."""

    foods: dict[str, Food] = dataclasses.field(default_factory=dict)
    meals: dict[str, Meal] = dataclasses.field(default_factory=dict)
    templates: dict[str, DayTemplate] = dataclasses.field(default_factory=dict)
    targets: list[MacroTarget] = dataclasses.field(default_factory=list)

    #: The fixed facts about the person: sex, height, birth date, timezone. Kept as a
    #: plain dictionary rather than a dataclass because nothing computes with it here --
    #: it is carried so a dashboard can work out BMI and age, and giving every optional
    #: key a typed field would be ceremony around a passthrough.
    profile: dict[str, Any] = dataclasses.field(default_factory=dict)

    provisional: bool = True

    def target_in_force_on(self, day: datetime.date) -> MacroTarget | None:
        """The target that applied on a given day, or None if none did yet.

        The most recent target whose start date is not after that day. Because targets
        are never overwritten, asking about a day in the past gives the answer that was
        true then rather than the answer that is true now.
        """
        applicable = []

        for one_target in self.targets:
            if one_target.effective_from <= day:
                applicable.append(one_target)

        if not applicable:
            return None

        applicable.sort(key=lambda one_target: one_target.effective_from)

        return applicable[-1]


def read_food(entry: dict[str, Any]) -> Food:
    """Turn one `foods:` entry from the YAML into a Food.

    Read field by field rather than with `Food(**entry)`, because the YAML uses the
    names a person would write (`kcal`, `protein_g`) and the code uses names a person
    can read (`kilocalories`, `protein_grams`). This function is the one place those
    two vocabularies meet.
    """
    return Food(
        food_id=entry["id"],
        name=entry["name"],
        serving_description=entry.get("serving_desc", ""),
        serving_grams=float(entry["serving_g"]),
        serving_basis=entry["serving_basis"],
        kilocalories=float(entry["kcal"]),
        protein_grams=float(entry["protein_g"]),
        carbohydrate_grams=float(entry["carbs_g"]),
        fat_grams=float(entry["fat_g"]),
        brand=entry.get("brand"),
        notes=entry.get("notes"),
    )


def read_meal(entry: dict[str, Any]) -> Meal:
    """Turn one `meals:` entry into a Meal."""
    items = []

    for one_item in entry.get("items", []):
        servings = one_item.get("servings")

        if servings is None:
            items.append(MealItem(food_id=one_item["food_id"], servings=None))
        else:
            items.append(MealItem(food_id=one_item["food_id"], servings=float(servings)))

    return Meal(meal_id=entry["id"], name=entry["name"], items=items)


def read_template(entry: dict[str, Any]) -> DayTemplate:
    """Turn one `day_templates:` entry into a DayTemplate."""
    return DayTemplate(
        template_id=entry["id"],
        name=entry["name"],
        meal_ids=list(entry.get("meals", [])),
    )


def read_target(entry: dict[str, Any]) -> MacroTarget:
    """Turn one `macro_targets:` entry into a MacroTarget."""
    effective_from = entry["effective_from"]

    # PyYAML turns an unquoted 2026-09-03 into a date by itself, but a quoted one stays
    # text. Handle both rather than depending on how the file happens to be written.
    if isinstance(effective_from, str):
        effective_from = datetime.date.fromisoformat(effective_from)

    return MacroTarget(
        effective_from=effective_from,
        goal=entry.get("goal", ""),
        kilocalories=float(entry["kcal"]),
        protein_grams=float(entry["protein_g"]),
        carbohydrate_grams=float(entry["carbs_g"]),
        fat_grams=float(entry["fat_g"]),
    )


def load_library(library_path: str | Path = DEFAULT_LIBRARY_PATH) -> Library:
    """Read the whole library from YAML."""
    with open(library_path, encoding="utf-8") as open_file:
        contents = yaml.safe_load(open_file)

    library = Library(provisional=bool(contents.get("provisional", True)))

    for entry in contents.get("foods", []):
        one_food = read_food(entry)
        library.foods[one_food.food_id] = one_food

    # The YAML calls this section `saved_meals` -- "meal" on its own is ambiguous in a
    # food app, where it could mean a stored group of foods or one you ate today.
    for entry in contents.get("saved_meals", []):
        one_meal = read_meal(entry)
        library.meals[one_meal.meal_id] = one_meal

    for entry in contents.get("day_templates", []):
        one_template = read_template(entry)
        library.templates[one_template.template_id] = one_template

    for entry in contents.get("macro_targets", []):
        library.targets.append(read_target(entry))

    library.profile = contents.get("profile", {}) or {}

    return library


def find_problems(library: Library) -> list[str]:
    """Check the library over and describe anything wrong with it, in plain sentences.

    Returns a list of problems rather than raising on the first one, because if you
    have just edited six foods off their labels you want to hear about all six at once.
    An empty list means the library is consistent.

    This catches the mistakes that are invisible later: a food whose calories disagree
    with its own macros, a serving basis that is a typo, and a meal pointing at a food
    that is not in the library.
    """
    problems = []

    for one_food in library.foods.values():
        if one_food.serving_basis not in VALID_SERVING_BASES:
            problems.append(
                f"{one_food.food_id}: serving_basis is '{one_food.serving_basis}',"
                f" which is not one of {', '.join(VALID_SERVING_BASES)}"
            )

        if one_food.serving_grams <= 0:
            problems.append(f"{one_food.food_id}: serving_g must be greater than zero")

        from_macros = one_food.macros_as_kilocalories()
        difference = abs(from_macros - one_food.kilocalories)

        # Allowed to be off by a flat amount OR by a fraction, whichever is larger, so
        # that both a 59 kcal yogurt and a 900 kcal serving get a sensible allowance.
        allowed = max(
            CALORIE_CHECK_TOLERANCE_KCAL,
            one_food.kilocalories * CALORIE_CHECK_TOLERANCE_FRACTION,
        )

        if difference > allowed:
            problems.append(
                f"{one_food.food_id}: says {one_food.kilocalories:.0f} kcal but its macros"
                f" add up to {from_macros:.0f} kcal"
                f" ({one_food.protein_grams:.1f}P {one_food.carbohydrate_grams:.1f}C"
                f" {one_food.fat_grams:.1f}F). One of those numbers is mistyped."
            )

    for one_meal in library.meals.values():
        for one_item in one_meal.items:
            if one_item.food_id not in library.foods:
                problems.append(
                    f"meal '{one_meal.meal_id}' uses food '{one_item.food_id}',"
                    f" which is not in the library"
                )

    for one_template in library.templates.values():
        for meal_id in one_template.meal_ids:
            if meal_id not in library.meals:
                problems.append(
                    f"template '{one_template.template_id}' uses meal '{meal_id}',"
                    f" which is not in the library"
                )

    return problems
