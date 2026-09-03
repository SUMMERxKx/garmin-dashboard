"""Validate the seed food library.

Nutrition values are deliberately null until they come from real product labels. This
suite passes while they are unfilled AND enforces 4/4/9 consistency once they are, so it
becomes a real check the moment the data lands.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from backend.core import nutrition
from backend.core.models import Food, GoalType, MacroTarget, ServingBasis

SEED = Path(__file__).resolve().parents[2] / "seed" / "food-library.template.yaml"
NUTRITION_FIELDS = ("kcal", "protein_g", "carbs_g", "fat_g")


@pytest.fixture(scope="module")
def seed() -> dict:
    return yaml.safe_load(SEED.read_text(encoding="utf-8"))


def test_profile_matches_the_locked_values(seed: dict) -> None:
    profile = seed["profile"]
    assert profile["sex"] == "male"
    assert profile["birth_date"] == date(2003, 5, 1)
    assert profile["height_cm"] == 180
    assert profile["timezone"] == "America/Vancouver"


def test_starting_target_is_internally_consistent(seed: dict) -> None:
    raw = seed["macro_targets"][0]
    target = MacroTarget(
        effective_from=raw["effective_from"], goal=GoalType(raw["goal"]),
        kcal=raw["kcal"], protein_g=raw["protein_g"], carbs_g=raw["carbs_g"], fat_g=raw["fat_g"],
    )
    assert target.implied_kcal == pytest.approx(2345.0)
    assert abs(target.implied_kcal - target.kcal) <= 10.0


def test_protein_target_is_appropriate_for_cutting(seed: dict) -> None:
    """1.6-2.2 g/kg is the evidence-based range; the top of it protects lean mass."""
    grams = seed["macro_targets"][0]["protein_g"]
    per_kg = grams / seed["profile"]["starting_weight_kg"]
    assert 1.6 <= per_kg <= 2.6


def test_every_food_declares_a_serving_basis(seed: dict) -> None:
    """The highest-impact field in the nutrition model -- it may never be implicit."""
    for food in seed["foods"]:
        assert ServingBasis(food["serving_basis"]), food["id"]


def test_cooked_weight_foods_are_marked_raw(seed: dict) -> None:
    """Rice, oats and chicken are the three that will bite. 100 g dry rice becomes
    ~250-300 g cooked; logging cooked weight against dry macros over-counts 2.5-3x."""
    basis = {f["id"]: f["serving_basis"] for f in seed["foods"]}
    for food_id in ("rice", "oats", "chicken-breast"):
        assert basis[food_id] == "raw", f"{food_id} must declare its weight state"


def test_nutrition_is_either_unfilled_or_consistent(seed: dict) -> None:
    """Passes while values are null; enforces 4/4/9 the moment they are entered."""
    for raw in seed["foods"]:
        values = [raw.get(f) for f in NUTRITION_FIELDS]
        if all(v is None for v in values):
            continue
        assert all(v is not None for v in values), f"{raw['id']}: partially filled"
        food = Food(
            id=raw["id"], name=raw["name"], serving_desc=raw["serving_desc"],
            serving_g=raw.get("serving_g"), serving_basis=ServingBasis(raw["serving_basis"]),
            kcal=raw["kcal"], protein_g=raw["protein_g"],
            carbs_g=raw["carbs_g"], fat_g=raw["fat_g"],
        )
        assert nutrition.validate_food(food), f"{raw['id']}: kcal does not reconcile with 4/4/9"


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
    rice_servings = [
        item["servings"]
        for meal in seed["saved_meals"]
        for item in meal["items"]
        if item["food_id"] == "rice"
    ]
    assert rice_servings and all(s is None for s in rice_servings)
