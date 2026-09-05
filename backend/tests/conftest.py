from __future__ import annotations

from datetime import date
from datetime import timedelta

import pytest

from backend.core import models

TODAY = date(2026, 9, 3)


@pytest.fixture
def profile() -> models.Profile:
    return models.Profile(
        user_id="deep", sex=models.Sex.MALE, birth_date=date(2003, 5, 1),
        height_cm=180.0, timezone="America/Vancouver",
    )


@pytest.fixture
def target() -> models.MacroTarget:
    """The real starting target: 2350 kcal / 180 P / 260 C / 65 F, effective 2026-09-03."""
    return models.MacroTarget(
        effective_from=date(2026, 9, 3), goal=models.GoalType.CUTTING,
        kcal=2350.0, protein_g=180.0, carbs_g=260.0, fat_g=65.0,
    )


@pytest.fixture
def chicken() -> models.Food:
    """Macros are illustrative; the real library comes from actual labels."""
    return models.Food(
        id="chicken-breast", name="Chicken breast", serving_desc="100 g raw",
        serving_g=100.0, serving_basis=models.ServingBasis.RAW,
        kcal=165.0, protein_g=31.0, carbs_g=0.0, fat_g=3.6,
    )


def make_entry(day: date, food: models.Food, servings: float, **kw) -> models.LogEntry:
    return models.LogEntry(
        id=f"{day}-{food.id}", date=day, food_id=food.id, food_name=food.name,
        servings=servings, macros_snapshot=food.per_serving.scale(servings),
        serving_basis=food.serving_basis, **kw,
    )


def series(values: list[float | None], end: date = TODAY) -> list[tuple[date, float | None]]:
    """Newest last. `values[-1]` lands on `end`."""
    n = len(values)
    return [(end - timedelta(days=n - 1 - i), v) for i, v in enumerate(values)]


def flat_series(value: float, days: int, end: date = TODAY) -> list[tuple[date, float | None]]:
    return series([value] * days, end)


@pytest.fixture
def empty_totals() -> models.MacroTotals:
    return models.MacroTotals()
