"""What you ate: one logged entry, and what a day adds up to.

The one decision worth understanding here
-----------------------------------------
A logged entry stores the MACROS, not just a pointer at the food.

That looks like duplication -- the numbers are already in the library -- and it is, on
purpose. If an entry only pointed at `whey-protein`, then correcting that food later
would silently rewrite every day you have ever logged. The case that makes it obvious is
switching brands: your new whey has 25 g of protein instead of 24, you update the
library, and now last month's dashboard quietly claims you ate something you did not.

So the numbers are copied onto the entry at the moment you log it. The library is what
you believe *today*; an entry is what you ate *then*, and it stops changing.

Note that this is the opposite of the rule used for Garmin data, and deliberately so.
A Garmin response is an immutable observation that we re-interpret as our reading of it
improves -- so we replay it. A food label is not an observation of your day; it is a
belief about a product, and it can change for reasons that have nothing to do with the
day you are looking at.
"""

from __future__ import annotations

import dataclasses
import datetime

from backend.food import library


@dataclasses.dataclass
class LoggedFood:
    """One thing you ate, with its numbers fixed at the moment it was logged."""

    food_id: str
    food_name: str
    servings: float
    serving_basis: str
    kilocalories: float
    protein_grams: float
    carbohydrate_grams: float
    fat_grams: float
    logged_at: datetime.datetime
    meal_id: str | None = None

    def grams(self, one_food: library.Food) -> float:
        """How many grams this entry is, given the food it came from.

        Not stored on the entry, because it is only ever wanted for display and it can
        always be recomputed. Storing it would be a third copy of the same fact.
        """
        return one_food.serving_grams * self.servings


@dataclasses.dataclass
class DayTotals:
    """What a day's entries add up to."""

    kilocalories: float = 0.0
    protein_grams: float = 0.0
    carbohydrate_grams: float = 0.0
    fat_grams: float = 0.0
    number_of_entries: int = 0


def portion_of(one_food: library.Food, servings: float) -> LoggedFood:
    """Work out the numbers for a given number of servings of a food.

    Multiplication, with no rounding. Rounding belongs at the point where a number is
    printed, not where it is stored -- round early and the error compounds across every
    entry in the day.
    """
    return LoggedFood(
        food_id=one_food.food_id,
        food_name=one_food.name,
        servings=servings,
        # The basis travels with the entry rather than being looked up in the library
        # later. If the library entry is ever corrected from `raw` to `cooked`, this
        # entry still records the basis you actually logged it on.
        serving_basis=one_food.serving_basis,
        kilocalories=one_food.kilocalories * servings,
        protein_grams=one_food.protein_grams * servings,
        carbohydrate_grams=one_food.carbohydrate_grams * servings,
        fat_grams=one_food.fat_grams * servings,
        # Filled in by the caller, which knows what time it actually is. This module
        # deliberately does not read the clock, so it stays testable.
        logged_at=datetime.datetime.min,
    )


def total_up(entries: list[LoggedFood]) -> DayTotals:
    """Add up a day's entries.

    An empty day totals zero rather than None, and that is not a contradiction of the
    "None means no reading" rule elsewhere. An empty food log is a real measurement: it
    means nothing has been logged. A missing HRV reading is different -- the watch
    tried and failed.
    """
    totals = DayTotals()

    for one_entry in entries:
        totals.kilocalories = totals.kilocalories + one_entry.kilocalories
        totals.protein_grams = totals.protein_grams + one_entry.protein_grams
        totals.carbohydrate_grams = totals.carbohydrate_grams + one_entry.carbohydrate_grams
        totals.fat_grams = totals.fat_grams + one_entry.fat_grams
        totals.number_of_entries = totals.number_of_entries + 1

    return totals


@dataclasses.dataclass
class Remaining:
    """How far a day's totals sit from its target.

    Positive means still to eat; negative means over. Both are useful, so the sign is
    kept rather than being turned into an absolute value with a word beside it.
    """

    kilocalories: float
    protein_grams: float
    carbohydrate_grams: float
    fat_grams: float


def remaining_against(totals: DayTotals, target: library.MacroTarget) -> Remaining:
    """Target minus what has been logged."""
    return Remaining(
        kilocalories=target.kilocalories - totals.kilocalories,
        protein_grams=target.protein_grams - totals.protein_grams,
        carbohydrate_grams=target.carbohydrate_grams - totals.carbohydrate_grams,
        fat_grams=target.fat_grams - totals.fat_grams,
    )


def expand_meal(
    one_meal: library.Meal,
    whole_library: library.Library,
    servings_for_variable_items: dict[str, float] | None = None,
) -> tuple[list[LoggedFood], list[str]]:
    """Turn a saved meal into the entries it stands for.

    Returns the entries AND a list of anything that could not be worked out, because a
    meal with a missing amount must not quietly log as zero. Rice is the case this
    exists for: the meal is fixed except for how much rice, which depends on the day.

    `servings_for_variable_items` is how the caller answers that question, as
    food_id -> servings.
    """
    if servings_for_variable_items is None:
        servings_for_variable_items = {}

    entries = []
    unanswered = []

    for one_item in one_meal.items:
        one_food = whole_library.foods.get(one_item.food_id)

        if one_food is None:
            unanswered.append(f"'{one_item.food_id}' is not in the library")
            continue

        if one_item.servings is not None:
            servings = one_item.servings
        elif one_item.food_id in servings_for_variable_items:
            servings = servings_for_variable_items[one_item.food_id]
        else:
            # A None amount is a question, not a zero. Say so and skip it.
            unanswered.append(
                f"'{one_item.food_id}' varies by day -- say how many servings"
            )
            continue

        entries.append(portion_of(one_food, servings))

    return (entries, unanswered)
