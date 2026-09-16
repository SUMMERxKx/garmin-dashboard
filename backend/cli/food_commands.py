"""The food log: `foods`, `log`, `meal`, `template` and `copy-yesterday`.

The rule that shapes all of these: a logged entry stores its own macros rather than
pointing at the library. The library is what you believe today; an entry is what you ate
then. Correcting whey off its label must not silently rewrite every day already logged.
"""

from __future__ import annotations

import datetime

from backend.cli import days
from backend.cli import formatting
from backend.food import intake
from backend.food import library
from backend.food import log
from backend.store import database
from backend.store import food_store
from backend.store import intake_store


def build_food_row(*cells: str) -> str:
    """Lay out one row of the `foods` table."""
    widths = [18, 25, 18, 9, 6, 6, 6, 6]

    laid_out = []

    for position, one_cell in enumerate(cells):
        width = widths[position]

        if position <= 2:
            laid_out.append(one_cell.ljust(width))
        else:
            laid_out.append(one_cell.rjust(width))

    return "  " + "  ".join(laid_out)

def run_foods() -> int:
    """List the food library, and say plainly if anything in it is wrong."""
    whole_library = library.load_library()

    print()
    print(f"  {len(whole_library.foods)} foods, {len(whole_library.meals)} saved meals,"
          f" {len(whole_library.templates)} day template(s)")

    if whole_library.provisional:
        # Worth saying every time it is printed. Provisional numbers look exactly like
        # real ones on screen, and a dashboard built on typical published values rather
        # than your actual labels is confidently wrong.
        print("  !! values are PROVISIONAL -- replace them from your own product labels")

    print()
    print(build_food_row("id", "food", "serving", "basis", "kcal", "P", "C", "F"))
    print("  " + "-" * (len(build_food_row("", "", "", "", "", "", "", "")) - 2))

    for one_food in sorted(whole_library.foods.values(), key=lambda f: f.food_id):
        print(
            build_food_row(
                one_food.food_id,
                one_food.name,
                one_food.serving_description,
                one_food.serving_basis,
                formatting.show_number(one_food.kilocalories),
                formatting.show_number(one_food.protein_grams, decimal_places=1),
                formatting.show_number(one_food.carbohydrate_grams, decimal_places=1),
                formatting.show_number(one_food.fat_grams, decimal_places=1),
            )
        )

    print()

    problems = library.find_problems(whole_library)

    if problems:
        print("  PROBLEMS:")
        for one_problem in problems:
            print(f"    - {one_problem}")
        print()
        return 1

    return 0

def run_log(food_id: str, servings: float, date_text: str | None) -> int:
    """Log one food.

    Defaults to TODAY, unlike the viewing commands, which default to yesterday. The
    reason for the difference: you view a finished day, but you log food as you eat it.
    """
    if date_text is None:
        day = datetime.date.today()
    else:
        try:
            day = datetime.date.fromisoformat(date_text)
        except ValueError:
            print(f"'{date_text}' is not a date. Use the form 2026-09-12.")
            return 1

    if servings <= 0:
        print("Servings must be greater than zero.")
        return 1

    whole_library = library.load_library()
    one_food = whole_library.foods.get(food_id)

    if one_food is None:
        print(f"No food called '{food_id}' in the library.")
        print("See what is there:")
        print("    .venv/bin/python -m backend.cli.main foods")
        return 1

    entry = log.portion_of(one_food, servings)

    # The clock is read HERE, at the edge, and never inside `log.py`. A function that
    # reads the clock cannot be tested, because its answer changes every time it runs.
    entry.logged_at = datetime.datetime.now()

    open_database = database.Database()
    food_store.save_entry(open_database, day, entry)
    entries = food_store.load_entries_for_day(open_database, day)
    open_database.close()

    grams = entry.grams(one_food)

    print()
    print(f"  logged  {one_food.name}  x{servings:g}"
          f"  ({grams:.0f} g {one_food.serving_basis})")
    print(f"          {entry.kilocalories:.0f} kcal"
          f"  {entry.protein_grams:.1f} P"
          f"  {entry.carbohydrate_grams:.1f} C"
          f"  {entry.fat_grams:.1f} F")

    totals = log.total_up(entries)
    target = whole_library.target_in_force_on(day)

    if target is None:
        print()
        print(f"  day total: {totals.kilocalories:.0f} kcal")
        print()
        return 0

    left = log.remaining_against(totals, target)

    print()
    print(f"  day so far: {totals.kilocalories:.0f} / {target.kilocalories:.0f} kcal"
          f"   left: {left.kilocalories:.0f} kcal,"
          f" {left.protein_grams:.0f} P,"
          f" {left.carbohydrate_grams:.0f} C,"
          f" {left.fat_grams:.0f} F")
    print()

    return 0

def work_out_serving_overrides(set_arguments: list[str] | None) -> dict[str, float] | None:
    """Turn `--set rice-jasmine=1.25` options into food_id -> servings.

    Returns None if one of them is malformed, having already said which. A meal with a
    variable amount asks a question, and a badly typed answer must not be treated as no
    answer.
    """
    overrides = {}

    if set_arguments is None:
        return overrides

    for one_argument in set_arguments:
        if "=" not in one_argument:
            print(f"'{one_argument}' should look like food-id=servings, e.g. rice-jasmine=1.25")
            return None

        food_id, servings_text = one_argument.split("=", 1)

        try:
            overrides[food_id] = float(servings_text)
        except ValueError:
            print(f"'{servings_text}' is not a number of servings.")
            return None

    return overrides

def store_entries(
    day: datetime.date,
    entries: list[log.LoggedFood],
    replace_existing: bool,
) -> int:
    """Write a batch of entries to a day, optionally clearing it first.

    Returns how many were stored. Each entry gets its own timestamp a second apart,
    because the timestamp is part of the storage key: written at the same instant, the
    second entry would replace the first and a meal would silently lose items.
    """
    open_database = database.Database()

    if replace_existing:
        removed = food_store.remove_whole_day(open_database, day)
        if removed:
            print(f"  cleared {removed} existing entr(ies) for {day.isoformat()}")

    moment = datetime.datetime.now()

    for position, one_entry in enumerate(entries):
        one_entry.logged_at = moment + datetime.timedelta(seconds=position)
        food_store.save_entry(open_database, day, one_entry)

    open_database.close()

    return len(entries)

def day_already_has_food(day: datetime.date) -> int:
    """How many entries are already logged for a day."""
    open_database = database.Database()
    existing = food_store.load_entries_for_day(open_database, day)
    open_database.close()

    return len(existing)

def refuse_to_double_log(day: datetime.date, already_there: int, command: str) -> None:
    """Explain that a day already has food, and how to say what you meant.

    Logging a whole day is the one command where a careless repeat is expensive: you end
    up with two breakfasts and a day that reads 4,600 kcal. So it stops and asks rather
    than guessing.
    """
    print()
    print(f"{day.isoformat()} already has {already_there} entr(ies) logged.")
    print()
    print("  to start the day again:   " + command + " --replace")
    print("  to add to what is there:  " + command + " --add")
    print()

def run_meal(
    meal_id: str,
    date_text: str | None,
    set_arguments: list[str] | None,
) -> int:
    """Log one saved meal."""
    day = days.work_out_day_for_logging(date_text)

    if day is None:
        return 1

    whole_library = library.load_library()
    one_meal = whole_library.meals.get(meal_id)

    if one_meal is None:
        print(f"No saved meal called '{meal_id}'.")
        print("There is: " + ", ".join(sorted(whole_library.meals)))
        return 1

    overrides = work_out_serving_overrides(set_arguments)

    if overrides is None:
        return 1

    entries, unanswered = log.expand_meal(one_meal, whole_library, overrides)

    if unanswered:
        print(f"Cannot log '{meal_id}' yet:")
        for one_problem in unanswered:
            print(f"  - {one_problem}")
        print()
        print("Say how much, like:")
        print(f"    .venv/bin/python -m backend.cli.main meal {meal_id} --set rice-jasmine=1")
        return 1

    store_entries(day, entries, replace_existing=False)

    print()
    print(f"  logged {one_meal.name}: {len(entries)} item(s) on {day.isoformat()}")
    print_day_running_total(day, whole_library)

    return 0

def run_template(
    template_id: str,
    date_text: str | None,
    set_arguments: list[str] | None,
    replace_existing: bool,
    add_to_existing: bool,
) -> int:
    """Log a whole day from a template. The point of a fixed diet."""
    day = days.work_out_day_for_logging(date_text)

    if day is None:
        return 1

    whole_library = library.load_library()
    one_template = whole_library.templates.get(template_id)

    if one_template is None:
        print(f"No day template called '{template_id}'.")
        print("There is: " + ", ".join(sorted(whole_library.templates)))
        return 1

    overrides = work_out_serving_overrides(set_arguments)

    if overrides is None:
        return 1

    already_there = day_already_has_food(day)

    if already_there and not replace_existing and not add_to_existing:
        refuse_to_double_log(
            day,
            already_there,
            f".venv/bin/python -m backend.cli.main template {template_id}",
        )
        return 1

    all_entries = []
    all_unanswered = []

    for meal_id in one_template.meal_ids:
        one_meal = whole_library.meals.get(meal_id)

        if one_meal is None:
            all_unanswered.append(f"meal '{meal_id}' is not in the library")
            continue

        entries, unanswered = log.expand_meal(one_meal, whole_library, overrides)

        all_entries.extend(entries)
        all_unanswered.extend(unanswered)

    if all_unanswered:
        print(f"Cannot log '{template_id}' yet:")
        for one_problem in all_unanswered:
            print(f"  - {one_problem}")
        return 1

    print()
    stored = store_entries(day, all_entries, replace_existing=replace_existing)
    print(f"  logged {one_template.name}: {stored} item(s) on {day.isoformat()}")
    print_day_running_total(day, whole_library)

    return 0

def run_copy_yesterday(date_text: str | None, replace_existing: bool, add_to_existing: bool) -> int:
    """Copy yesterday's food onto today.

    Deliberately copies the ENTRIES rather than re-applying a template: if you ate
    something different yesterday, copying reproduces what you actually ate, not what
    the template says you usually eat.
    """
    day = days.work_out_day_for_logging(date_text)

    if day is None:
        return 1

    previous_day = day - datetime.timedelta(days=1)

    open_database = database.Database()
    yesterdays_entries = food_store.load_entries_for_day(open_database, previous_day)
    open_database.close()

    if not yesterdays_entries:
        print(f"Nothing logged on {previous_day.isoformat()}, so there is nothing to copy.")
        return 1

    already_there = day_already_has_food(day)

    if already_there and not replace_existing and not add_to_existing:
        refuse_to_double_log(
            day,
            already_there,
            ".venv/bin/python -m backend.cli.main copy-yesterday",
        )
        return 1

    print()
    stored = store_entries(day, yesterdays_entries, replace_existing=replace_existing)
    print(f"  copied {stored} item(s) from {previous_day.isoformat()} to {day.isoformat()}")

    print_day_running_total(day, library.load_library())

    return 0

def print_day_running_total(day: datetime.date, whole_library: library.Library) -> None:
    """Print where a day stands after something was logged to it."""
    open_database = database.Database()
    entries = food_store.load_entries_for_day(open_database, day)
    open_database.close()

    totals = log.total_up(entries)
    target = whole_library.target_in_force_on(day)

    if target is None:
        print(f"  day total: {totals.kilocalories:.0f} kcal")
        print()
        return

    left = log.remaining_against(totals, target)

    print()
    print(f"  day so far: {totals.kilocalories:.0f} / {target.kilocalories:.0f} kcal"
          f"   left: {left.kilocalories:+.0f} kcal,"
          f" {left.protein_grams:+.0f} P,"
          f" {left.carbohydrate_grams:+.0f} C,"
          f" {left.fat_grams:+.0f} F")
    print()


def run_ate(kilocalories: float, date_text: str | None, note: str | None) -> int:
    """Record a day's calories as one typed number.

    The quick route in, for the days the itemised log is not worth the trouble. It
    overrides the food log for that day on the dashboard -- see `intake.py` for why --
    and any day after it with nothing recorded inherits the figure, labelled as carried.
    """
    day = days.work_out_day_for_logging(date_text)

    if day is None:
        return 1

    problem = intake.describe_problem(kilocalories)

    if problem is not None:
        print(problem)
        return 1

    open_database = database.Database()

    already_there = intake_store.load_intake(open_database, day)

    one_intake = intake.ManualIntake(
        day=day,
        kilocalories=kilocalories,
        # The clock is read here, at the edge, never inside the intake module.
        recorded_at=datetime.datetime.now(),
        note=note,
    )

    intake_store.save_intake(open_database, one_intake)
    open_database.close()

    print()

    if already_there is not None:
        # A day holds one total, so this replaced something. Say so rather than letting
        # a number quietly disappear.
        print(f"  replaced {already_there.kilocalories:g} kcal with"
              f" {kilocalories:g} kcal for {day.isoformat()}")
    else:
        print(f"  recorded {kilocalories:g} kcal for {day.isoformat()}")

    print("  Days after this with nothing recorded will show this figure, marked as assumed.")
    print()

    return 0
