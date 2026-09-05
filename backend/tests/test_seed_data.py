"""Validate both seed files.

`food-library.template.yaml` is the pristine all-null template; nulls are allowed there.
`food-library.yaml` is the working file with PROVISIONAL values; those must satisfy
4/4/9, so a typo in a macro fails the build rather than quietly skewing every total.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from backend.core import models
from backend.core import nutrition

SEED_DIR = Path(__file__).resolve().parents[2] / "seed"
TEMPLATE = SEED_DIR / "food-library.template.yaml"
WORKING = SEED_DIR / "food-library.yaml"
NUTRITION_FIELDS = ("kcal", "protein_g", "carbs_g", "fat_g")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def working() -> dict:
    return load(WORKING)


@pytest.fixture(params=[TEMPLATE, WORKING], ids=["template", "working"])
def seed(request: pytest.FixtureRequest) -> dict:
    return load(request.param)


def to_food(raw: dict) -> models.Food:
    return models.Food(
        id=raw["id"], name=raw["name"], brand=raw.get("brand"),
        serving_desc=raw["serving_desc"], serving_g=raw.get("serving_g"),
        serving_basis=models.ServingBasis(raw["serving_basis"]),
        kcal=raw["kcal"], protein_g=raw["protein_g"],
        carbs_g=raw["carbs_g"], fat_g=raw["fat_g"],
        fiber_g=raw.get("fiber_g"), sodium_mg=raw.get("sodium_mg"),
    )


# --- properties both files must satisfy ------------------------------------


def test_profile_matches_the_locked_values(seed: dict) -> None:
    profile = seed["profile"]
    assert profile["sex"] == "male"
    assert profile["birth_date"] == date(2003, 5, 1)
    assert profile["height_cm"] == 180
    assert profile["timezone"] == "America/Vancouver"


def test_starting_target_is_internally_consistent(seed: dict) -> None:
    raw = seed["macro_targets"][0]
    target = models.MacroTarget(
        effective_from=raw["effective_from"], goal=models.GoalType(raw["goal"]),
        kcal=raw["kcal"], protein_g=raw["protein_g"],
        carbs_g=raw["carbs_g"], fat_g=raw["fat_g"],
    )
    assert target.implied_kcal == pytest.approx(2345.0)
    assert abs(target.implied_kcal - target.kcal) <= 10.0


def test_protein_target_is_appropriate_for_cutting(seed: dict) -> None:
    """1.6-2.2 g/kg is the evidence-based range; the top of it protects lean mass."""
    per_kg = seed["macro_targets"][0]["protein_g"] / seed["profile"]["starting_weight_kg"]
    assert 1.6 <= per_kg <= 2.6


def test_every_food_declares_a_serving_basis(seed: dict) -> None:
    """The highest-impact field in the nutrition model -- it may never be implicit."""
    for food in seed["foods"]:
        assert models.ServingBasis(food["serving_basis"]), food["id"]


def test_dry_weight_foods_are_marked_raw(seed: dict) -> None:
    """Rice, oats and chicken are the three that will bite."""
    basis = {f["id"]: f["serving_basis"] for f in seed["foods"]}
    for food_id in ("rice", "oats", "chicken-breast"):
        assert basis[food_id] == "raw", f"{food_id} must declare its weight state"


def test_nutrition_is_either_unfilled_or_consistent(seed: dict) -> None:
    """Passes on the all-null template; enforces 4/4/9 on the working file."""
    for raw in seed["foods"]:
        values = [raw.get(f) for f in NUTRITION_FIELDS]
        if all(v is None for v in values):
            continue
        assert all(v is not None for v in values), f"{raw['id']}: partially filled"
        assert nutrition.validate_food(to_food(raw)), (
            f"{raw['id']}: stated kcal does not reconcile with 4P+4C+9F"
        )


def test_saved_meals_reference_real_foods(seed: dict) -> None:
    known = {f["id"] for f in seed["foods"]}
    for meal in seed["saved_meals"]:
        for item in meal["items"]:
            assert item["food_id"] in known, f"{meal['id']} -> unknown food {item['food_id']}"


def test_day_templates_reference_real_meals(seed: dict) -> None:
    known = {m["id"] for m in seed["saved_meals"]}
    for template in seed["day_templates"]:
        for meal_id in template["meals"]:
            assert meal_id in known, f"{template['id']} -> unknown meal {meal_id}"


def test_variable_portions_are_left_unset(seed: dict) -> None:
    """Rice varies day to day, so it must not ship with a hardcoded serving."""
    rice = [
        item["servings"]
        for meal in seed["saved_meals"]
        for item in meal["items"]
        if item["food_id"] == "rice"
    ]
    assert rice and all(s is None for s in rice)


# --- the working file only -------------------------------------------------


def test_working_file_is_flagged_provisional(working: dict) -> None:
    """These are published typical values, not his labels. The flag must stay until
    real label data replaces them."""
    assert working["provisional"] is True


def test_every_working_food_is_fully_specified(working: dict) -> None:
    for raw in working["foods"]:
        for field in NUTRITION_FIELDS:
            assert raw.get(field) is not None, f"{raw['id']}.{field} is unset"


def test_the_default_day_clears_the_protein_floor(working: dict) -> None:
    """The one target the described day does hit -- 207 g against a 180 g floor."""
    totals, target = compute_default_day(working)
    assert totals.protein_g >= target.protein_g


def test_the_default_day_is_short_on_fat_and_calories(working: dict) -> None:
    """Documents a real finding rather than hiding it: the day as described carries only
    ~22 g of fat against a 65 g target, and the missing ~390 kcal of fat accounts for
    almost the whole calorie shortfall. See the note at the bottom of the seed file."""
    totals, target = compute_default_day(working)
    assert totals.fat_g < target.fat_g - 30
    assert totals.kcal < target.kcal - 200


def compute_default_day(seed: dict) -> tuple[models.MacroTotals, models.MacroTarget]:
    """Sum the Normal Day template, treating unset servings as 1."""
    foods = {f["id"]: to_food(f) for f in seed["foods"]}
    meals = {m["id"]: m for m in seed["saved_meals"]}
    totals = models.MacroTotals()
    for meal_id in seed["day_templates"][0]["meals"]:
        for item in meals[meal_id]["items"]:
            servings = 1.0 if item["servings"] is None else float(item["servings"])
            totals = totals + nutrition.resolve_entry(foods[item["food_id"]], servings)
    raw = seed["macro_targets"][0]
    target = models.MacroTarget(
        effective_from=raw["effective_from"], goal=models.GoalType(raw["goal"]),
        kcal=raw["kcal"], protein_g=raw["protein_g"],
        carbs_g=raw["carbs_g"], fat_g=raw["fat_g"],
    )
    return totals, target
