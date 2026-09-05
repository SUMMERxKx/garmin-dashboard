"""Storage: the key scheme, and one suite both repository implementations must pass.

The parametrized suite is the important part. Every other test in the project uses
`InMemoryRepository`, and that is only safe if the fake behaves the same way as the real
store. Running the identical suite against both is what earns that trust.
"""

from __future__ import annotations

from datetime import date
from datetime import datetime

import pytest

from backend.adapters import keys
from backend.adapters import repository as repository_module
from backend.adapters import sqlite_repository
from backend.core import models

USER = "test-user"
DAY = date(2026, 9, 2)


# --- the key scheme --------------------------------------------------------


def test_day_records_share_a_prefix() -> None:
    """The single most important property: one prefix fetches a whole day."""
    prefix = keys.day_prefix(DAY)

    assert keys.snapshot_key(DAY).startswith(prefix)
    assert keys.weight_key(DAY).startswith(prefix)
    assert keys.food_entry_key(DAY, datetime(2026, 9, 2, 12, 0)).startswith(prefix)


def test_day_prefixes_do_not_collide_across_days() -> None:
    assert not keys.snapshot_key(date(2026, 9, 3)).startswith(keys.day_prefix(DAY))


def test_dates_sort_correctly_as_text() -> None:
    """Keys are text, so the whole range-query design rests on ISO dates sorting the
    same way as real dates."""
    unsorted_keys = [
        keys.snapshot_key(date(2026, 12, 1)),
        keys.snapshot_key(date(2026, 2, 1)),
        keys.snapshot_key(date(2027, 1, 1)),
    ]
    assert sorted(unsorted_keys) == [
        keys.snapshot_key(date(2026, 2, 1)),
        keys.snapshot_key(date(2026, 12, 1)),
        keys.snapshot_key(date(2027, 1, 1)),
    ]


def test_range_bounds_include_the_whole_last_day() -> None:
    """The upper bound has to sort after every sort key on the final day, or the last
    day gets silently cut off."""
    lower, upper = keys.day_range_bounds(date(2026, 9, 1), DAY)

    assert lower <= keys.snapshot_key(date(2026, 9, 1)) <= upper
    assert lower <= keys.snapshot_key(DAY) <= upper
    assert lower <= keys.weight_key(DAY) <= upper
    assert lower <= keys.food_entry_key(DAY, datetime(2026, 9, 2, 23, 59)) <= upper
    assert keys.snapshot_key(date(2026, 9, 3)) > upper


def test_day_can_be_read_back_out_of_a_sort_key() -> None:
    assert keys.day_from_sort_key(keys.snapshot_key(DAY)) == DAY
    assert keys.day_from_sort_key(keys.food_key("rice")) is None
    assert keys.day_from_sort_key("DAY#not-a-date#SNAPSHOT") is None
    assert keys.day_from_sort_key("SOLO") is None


# --- the shared repository suite -------------------------------------------


@pytest.fixture(params=["in-memory", "sqlite"])
def repository(request: pytest.FixtureRequest):
    """Each test in this file runs twice: once per implementation."""
    if request.param == "in-memory":
        return repository_module.InMemoryRepository()
    return sqlite_repository.SqliteRepository(":memory:")


def make_food(food_id: str = "rice") -> models.Food:
    return models.Food(
        id=food_id, name="Rice, white, dry", serving_desc="100 g dry",
        serving_g=100.0, serving_basis=models.ServingBasis.RAW,
        kcal=360.0, protein_g=7.0, carbs_g=79.0, fat_g=0.9, fiber_g=1.3,
    )


def make_entry(entry_id: str, servings: float, minute: int) -> models.LogEntry:
    food = make_food()
    return models.LogEntry(
        id=entry_id, date=DAY, food_id=food.id, food_name=food.name,
        servings=servings, macros_snapshot=food.per_serving.scale(servings),
        serving_basis=food.serving_basis,
        logged_at=datetime(2026, 9, 2, 12, minute),
    )


def test_both_implementations_satisfy_the_port(repository) -> None:
    assert isinstance(repository, repository_module.HealthRepository)


def test_profile_round_trip(repository) -> None:
    profile = models.Profile(
        user_id=USER, sex=models.Sex.MALE, birth_date=date(2003, 5, 1),
        height_cm=180.0, timezone="America/Vancouver",
    )
    repository.save_profile(profile)

    loaded = repository.get_profile(USER)
    assert loaded is not None
    assert loaded.birth_date == date(2003, 5, 1)
    assert loaded.timezone == "America/Vancouver"


def test_missing_records_are_none_not_errors(repository) -> None:
    assert repository.get_profile(USER) is None
    assert repository.get_food(USER, "nope") is None
    assert repository.get_weight(USER, DAY) is None
    assert repository.get_snapshot(USER, DAY) is None
    assert repository.get_meal(USER, "nope") is None
    assert repository.get_template(USER, "nope") is None
    assert repository.list_foods(USER) == []
    assert repository.list_entries(USER, DAY) == []


def test_food_round_trip_preserves_optional_fields(repository) -> None:
    repository.save_food(USER, make_food())

    loaded = repository.get_food(USER, "rice")
    assert loaded is not None
    assert loaded.serving_basis is models.ServingBasis.RAW
    assert loaded.fiber_g == 1.3
    assert loaded.sodium_mg is None


def test_foods_come_back_in_key_order(repository) -> None:
    for food_id in ("rice", "oats", "chicken-breast"):
        repository.save_food(USER, make_food(food_id))

    ids = [food.id for food in repository.list_foods(USER)]
    assert ids == ["chicken-breast", "oats", "rice"]


def test_saving_the_same_key_replaces_rather_than_duplicates(repository) -> None:
    repository.save_food(USER, make_food())
    repository.save_food(USER, make_food())

    assert len(repository.list_foods(USER)) == 1


def test_several_entries_can_exist_for_one_day(repository) -> None:
    repository.save_entry(USER, make_entry("first", 1.0, 30))
    repository.save_entry(USER, make_entry("second", 1.25, 31))

    entries = repository.list_entries(USER, DAY)
    assert [entry.id for entry in entries] == ["first", "second"]


def test_entries_are_scoped_to_their_day(repository) -> None:
    repository.save_entry(USER, make_entry("today", 1.0, 30))
    assert repository.list_entries(USER, date(2026, 9, 3)) == []


def test_deleting_an_entry_by_id(repository) -> None:
    repository.save_entry(USER, make_entry("first", 1.0, 30))
    repository.save_entry(USER, make_entry("second", 1.0, 31))

    assert repository.delete_entry(USER, DAY, "first") is True
    assert repository.delete_entry(USER, DAY, "first") is False
    assert [entry.id for entry in repository.list_entries(USER, DAY)] == ["second"]


def test_clearing_a_day_leaves_other_days_alone(repository) -> None:
    repository.save_entry(USER, make_entry("a", 1.0, 30))
    repository.save_entry(USER, make_entry("b", 1.0, 31))
    repository.save_weight(USER, models.WeightEntry(date=DAY, weight_kg=79.4))

    assert repository.clear_day_entries(USER, DAY) == 2
    assert repository.list_entries(USER, DAY) == []
    # the weigh-in shares the day prefix but must survive
    assert repository.get_weight(USER, DAY) is not None


def test_weights_in_a_range_exclude_other_record_types(repository) -> None:
    """The range covers every kind of day record, so the filtering has to be right."""
    repository.save_weight(USER, models.WeightEntry(date=date(2026, 9, 1), weight_kg=79.8))
    repository.save_weight(USER, models.WeightEntry(date=DAY, weight_kg=79.4))
    repository.save_entry(USER, make_entry("noise", 1.0, 30))
    repository.save_snapshot(USER, models.DailyHealthSnapshot(date=DAY))

    weights = repository.list_weights(USER, date(2026, 8, 1), DAY)
    assert [entry.weight_kg for entry in weights] == [79.8, 79.4]


def test_weight_range_excludes_days_outside_it(repository) -> None:
    repository.save_weight(USER, models.WeightEntry(date=date(2026, 7, 1), weight_kg=82.0))
    repository.save_weight(USER, models.WeightEntry(date=DAY, weight_kg=79.4))

    weights = repository.list_weights(USER, date(2026, 9, 1), DAY)
    assert [entry.weight_kg for entry in weights] == [79.4]


def test_targets_are_append_only_and_keep_their_dates(repository) -> None:
    august = models.MacroTarget(
        effective_from=date(2026, 8, 1), goal=models.GoalType.CUTTING,
        kcal=2400.0, protein_g=180.0, carbs_g=270.0, fat_g=68.0,
    )
    september = models.MacroTarget(
        effective_from=date(2026, 9, 3), goal=models.GoalType.CUTTING,
        kcal=2350.0, protein_g=180.0, carbs_g=260.0, fat_g=65.0,
    )
    repository.save_target(USER, september)
    repository.save_target(USER, august)

    stored = repository.list_targets(USER)
    assert [target.effective_from for target in stored] == [date(2026, 8, 1), date(2026, 9, 3)]


def test_snapshot_round_trip_keeps_provenance(repository) -> None:
    snapshot = models.DailyHealthSnapshot(
        date=DAY,
        measured=models.MeasuredMetrics(
            energy=models.Energy(total_kcal=2421.0, active_kcal=617.0),
            provenance={"energy.total_kcal": "user_summary:totalKilocalories"},
        ),
    )
    repository.save_snapshot(USER, snapshot)

    loaded = repository.get_snapshot(USER, DAY)
    assert loaded is not None
    assert loaded.measured.energy.total_kcal == 2421.0
    assert loaded.measured.provenance["energy.total_kcal"] == "user_summary:totalKilocalories"


def test_snapshots_come_back_in_date_order(repository) -> None:
    for day in (date(2026, 9, 2), date(2026, 8, 31), date(2026, 9, 1)):
        repository.save_snapshot(USER, models.DailyHealthSnapshot(date=day))

    loaded = repository.list_snapshots(USER, date(2026, 8, 1), date(2026, 9, 30))
    assert [snapshot.date for snapshot in loaded] == [
        date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 2),
    ]


def test_meals_and_templates_round_trip(repository) -> None:
    meal = models.SavedMeal(
        id="breakfast", name="Breakfast",
        items=[models.MealItem(food_id="whey-protein", servings=1.0), models.MealItem(food_id="rice", servings=None)],
    )
    repository.save_meal(USER, meal)
    repository.save_template(USER, models.DayTemplate(id="normal-day", name="Normal Day", meal_ids=["breakfast"]))

    loaded_meal = repository.get_meal(USER, "breakfast")
    assert loaded_meal is not None
    # A serving of None means "decide per day" and must survive storage as None.
    assert loaded_meal.items[1].servings is None

    loaded_template = repository.get_template(USER, "normal-day")
    assert loaded_template is not None
    assert loaded_template.meal_ids == ["breakfast"]


def test_dexa_scans_round_trip_in_date_order(repository) -> None:
    for scan_date in (date(2027, 1, 15), date(2026, 10, 1)):
        repository.save_dexa_scan(
            USER,
            models.DexaScan(
                date=scan_date, total_mass_kg=80.0, fat_mass_kg=15.2,
                lean_mass_kg=61.5, bone_mass_kg=3.2, body_fat_pct=19.0,
            ),
        )

    scans = repository.list_dexa_scans(USER)
    assert [scan.date for scan in scans] == [date(2026, 10, 1), date(2027, 1, 15)]


def test_users_cannot_see_each_others_records(repository) -> None:
    """The partition key is the user, so this is structural rather than a filter that
    could be forgotten."""
    repository.save_food(USER, make_food())
    assert repository.list_foods("someone-else") == []
    assert repository.get_food("someone-else", "rice") is None


def test_export_and_import_move_every_record(repository) -> None:
    """This is how a local database seeds a real one later."""
    repository.save_food(USER, make_food())
    repository.save_weight(USER, models.WeightEntry(date=DAY, weight_kg=79.4))

    exported = repository.export_items()
    assert len(exported) == 2

    destination = repository_module.InMemoryRepository()
    assert destination.import_items(exported) == 2
    assert destination.get_weight(USER, DAY) is not None
    assert destination.get_food(USER, "rice") is not None
