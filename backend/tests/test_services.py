"""The service layer: seed loading, Garmin import, food logging and day assembly.

All of these run against `InMemoryRepository`, which `test_storage.py` proves behaves
the same as the real store. So no database, no mocks, and the whole file runs in
milliseconds.
"""

from __future__ import annotations

import json
from datetime import date
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from backend.adapters import repository as repository_module
from backend.adapters import seed_loader
from backend.core import models
from backend.core import nutrition
from backend.core import reasons
from backend.services import day_view
from backend.services import food_log
from backend.services import garmin_import

USER = "test-user"
SAMPLE_DAY = date(2026, 9, 2)


@pytest.fixture
def seeded() -> repository_module.InMemoryRepository:
    """A repository with the real seed file loaded."""
    repository = repository_module.InMemoryRepository()
    seed_loader.load_seed(repository, USER)
    return repository


@pytest.fixture
def with_garmin(seeded: repository_module.InMemoryRepository) -> repository_module.InMemoryRepository:
    """Seeded, plus the committed sample Garmin day imported."""
    garmin_import.import_all_days(seeded, USER, directory=garmin_import.SAMPLE_FIXTURE_DIRECTORY)
    return seeded


# --- seed loading ----------------------------------------------------------


def test_the_real_seed_file_loads(seeded: repository_module.InMemoryRepository) -> None:
    assert len(seeded.list_foods(USER)) == 13
    assert len(seeded.list_meals(USER)) == 4
    assert len(seeded.list_templates(USER)) == 1
    assert seeded.get_profile(USER) is not None


def test_the_seed_profile_matches_the_locked_values(seeded: repository_module.InMemoryRepository) -> None:
    profile = seeded.get_profile(USER)
    assert profile is not None
    assert profile.birth_date == date(2003, 5, 1)
    assert profile.height_cm == 180.0
    assert profile.age_on(date(2026, 9, 3)) == 23


def test_the_seed_file_is_still_flagged_provisional() -> None:
    """A reminder that the nutrition values are published figures, not his labels."""
    assert seed_loader.seed_is_provisional() is True


def test_variable_portions_survive_loading_as_none(seeded: repository_module.InMemoryRepository) -> None:
    afternoon = seeded.get_meal(USER, "afternoon")
    assert afternoon is not None

    rice_items = [item for item in afternoon.items if item.food_id == "rice"]
    assert rice_items and rice_items[0].servings is None


def test_a_food_that_does_not_reconcile_is_refused() -> None:
    """A wrong macro here would flow into every calculation, so loading must fail loudly."""
    with pytest.raises(seed_loader.SeedError, match="does not reconcile"):
        seed_loader.build_food({
            "id": "broken", "name": "Broken", "serving_desc": "100 g",
            "serving_basis": "as_sold",
            "kcal": 1650, "protein_g": 31.0, "carbs_g": 0.0, "fat_g": 3.6,
        })


def test_a_partially_filled_food_is_refused() -> None:
    with pytest.raises(seed_loader.SeedError, match="missing"):
        seed_loader.build_food({
            "id": "half", "name": "Half", "serving_desc": "100 g",
            "serving_basis": "as_sold",
            "kcal": 100, "protein_g": None, "carbs_g": 10.0, "fat_g": 1.0,
        })


def test_an_inconsistent_target_is_refused() -> None:
    with pytest.raises(seed_loader.SeedError, match="inconsistent"):
        seed_loader.build_targets({
            "macro_targets": [{
                "effective_from": date(2026, 9, 3), "goal": "cutting",
                "kcal": 3000, "protein_g": 180, "carbs_g": 260, "fat_g": 65,
            }]
        })


def test_a_meal_referring_to_an_unknown_food_is_refused(tmp_path: Path) -> None:
    seed = yaml.safe_load(seed_loader.DEFAULT_SEED_FILE.read_text(encoding="utf-8"))
    seed["saved_meals"][0]["items"].append({"food_id": "does-not-exist", "servings": 1})

    broken_file = tmp_path / "broken.yaml"
    broken_file.write_text(yaml.safe_dump(seed), encoding="utf-8")

    with pytest.raises(seed_loader.SeedError, match="unknown food"):
        seed_loader.load_seed(repository_module.InMemoryRepository(), USER, path=broken_file)


def test_a_missing_seed_file_is_refused() -> None:
    with pytest.raises(seed_loader.SeedError, match="not found"):
        seed_loader.read_seed_file("/nonexistent/seed.yaml")


# --- Garmin import ---------------------------------------------------------


def test_day_folder_names_are_parsed() -> None:
    assert garmin_import.day_from_folder_name("dt=2026-09-02") == SAMPLE_DAY
    assert garmin_import.day_from_folder_name("dt=not-a-date") is None
    assert garmin_import.day_from_folder_name("something-else") is None


def test_the_sample_fixtures_import_with_full_coverage(seeded: repository_module.InMemoryRepository) -> None:
    results = garmin_import.import_all_days(seeded, USER, directory=garmin_import.SAMPLE_FIXTURE_DIRECTORY)

    assert len(results) == 1
    day, present, missing = results[0]
    assert day == SAMPLE_DAY
    assert missing == 0
    assert present == 9


def test_importing_stores_a_snapshot_that_can_be_read_back(with_garmin: repository_module.InMemoryRepository) -> None:
    snapshot = with_garmin.get_snapshot(USER, SAMPLE_DAY)
    assert snapshot is not None
    assert snapshot.measured.energy.total_kcal == 2421.0
    assert snapshot.measured.sleep.duration_min == 424.0


def test_importing_is_repeatable(with_garmin: repository_module.InMemoryRepository) -> None:
    """Re-running the import replaces snapshots rather than duplicating them. This is
    what makes "fix the parser and replay" a safe operation."""
    before = with_garmin.item_count()
    garmin_import.import_all_days(with_garmin, USER, directory=garmin_import.SAMPLE_FIXTURE_DIRECTORY)
    assert with_garmin.item_count() == before


def test_an_empty_fixture_directory_imports_nothing(tmp_path: Path) -> None:
    assert garmin_import.find_day_folders(tmp_path) == []
    assert garmin_import.import_all_days(repository_module.InMemoryRepository(), USER, directory=tmp_path) == []


def test_a_day_folder_with_a_broken_response_still_imports(tmp_path: Path) -> None:
    """One unparseable endpoint must cost that endpoint, not the day."""
    folder = tmp_path / "dt=2026-09-02"
    folder.mkdir()
    (folder / "user_summary.json").write_text(
        json.dumps({"totalKilocalories": 2421.0, "totalSteps": 13842}), encoding="utf-8"
    )
    (folder / "sleep.json").write_text(json.dumps({"dailySleepDTO": None}), encoding="utf-8")

    repository = repository_module.InMemoryRepository()
    results = garmin_import.import_all_days(repository, USER, directory=tmp_path)

    assert len(results) == 1
    snapshot = repository.get_snapshot(USER, SAMPLE_DAY)
    assert snapshot is not None
    assert snapshot.measured.energy.total_kcal == 2421.0
    assert snapshot.measured.sleep.duration_min is None


# --- food logging ----------------------------------------------------------


def test_logging_a_food_stores_its_macros_with_the_entry(seeded: repository_module.InMemoryRepository) -> None:
    entry = food_log.log_food(seeded, USER, SAMPLE_DAY, "chicken-breast", 2.0)

    assert entry.macros_snapshot.protein_g == pytest.approx(62.0)
    assert entry.serving_basis is models.ServingBasis.RAW
    assert entry.source is models.LogSource.MANUAL


def test_logging_an_unknown_food_is_an_error(seeded: repository_module.InMemoryRepository) -> None:
    with pytest.raises(food_log.FoodLogError, match="no food"):
        food_log.log_food(seeded, USER, SAMPLE_DAY, "unicorn-steak", 1.0)


def test_applying_a_template_logs_the_whole_day(seeded: repository_module.InMemoryRepository) -> None:
    result = food_log.apply_template(seeded, USER, SAMPLE_DAY, "normal-day")

    assert len(result.entries) == 8
    # Rice appears in two meals and is deliberately left unset in both.
    assert result.needs_servings == ["rice", "rice"]


def test_an_override_supplies_a_variable_portion(seeded: repository_module.InMemoryRepository) -> None:
    result = food_log.apply_template(
        seeded, USER, SAMPLE_DAY, "normal-day", servings_overrides={"rice": 1.25}
    )
    assert len(result.entries) == 10
    assert result.needs_servings == []


def test_applying_a_template_replaces_what_was_there(seeded: repository_module.InMemoryRepository) -> None:
    food_log.apply_template(seeded, USER, SAMPLE_DAY, "normal-day", servings_overrides={"rice": 1.0})
    second = food_log.apply_template(
        seeded, USER, SAMPLE_DAY, "normal-day", servings_overrides={"rice": 1.0}
    )

    assert second.replaced == 10
    assert len(seeded.list_entries(USER, SAMPLE_DAY)) == 10


def test_the_seeded_day_is_short_on_fat_as_expected(seeded: repository_module.InMemoryRepository) -> None:
    """Documents the real finding: the described diet has almost no fat source, so it
    lands well under the fat target even when calories are close."""
    food_log.apply_template(seeded, USER, SAMPLE_DAY, "normal-day", servings_overrides={"rice": 1.25})
    totals = nutrition.day_totals(seeded.list_entries(USER, SAMPLE_DAY))

    assert totals.protein_g > 200
    assert totals.fat_g < 30


def test_copy_yesterday_reproduces_the_totals(seeded: repository_module.InMemoryRepository) -> None:
    yesterday = SAMPLE_DAY - timedelta(days=1)
    food_log.apply_template(seeded, USER, yesterday, "normal-day", servings_overrides={"rice": 1.25})

    result = food_log.copy_day(seeded, USER, yesterday, SAMPLE_DAY)

    assert len(result.entries) == 10
    assert nutrition.day_totals(seeded.list_entries(USER, SAMPLE_DAY)).kcal == pytest.approx(
        nutrition.day_totals(seeded.list_entries(USER, yesterday)).kcal
    )
    assert all(entry.source is models.LogSource.COPY for entry in result.entries)


def test_copy_recalculates_from_the_current_library(seeded: repository_module.InMemoryRepository) -> None:
    """If a label is corrected, the copy uses the corrected figure while the original
    day keeps the numbers it was logged with."""
    yesterday = SAMPLE_DAY - timedelta(days=1)
    food_log.log_food(seeded, USER, yesterday, "rice", 1.0)

    original = seeded.list_entries(USER, yesterday)[0]

    corrected = seeded.get_food(USER, "rice")
    assert corrected is not None
    corrected.kcal = 400.0
    seeded.save_food(USER, corrected)

    food_log.copy_day(seeded, USER, yesterday, SAMPLE_DAY)

    copied = seeded.list_entries(USER, SAMPLE_DAY)[0]
    assert copied.macros_snapshot.kcal == 400.0
    assert original.macros_snapshot.kcal == 360.0


def test_copying_an_empty_day_copies_nothing(seeded: repository_module.InMemoryRepository) -> None:
    result = food_log.copy_day(seeded, USER, date(2020, 1, 1), SAMPLE_DAY)
    assert result.entries == []


def test_copy_reports_a_food_deleted_since(seeded: repository_module.InMemoryRepository) -> None:
    yesterday = SAMPLE_DAY - timedelta(days=1)
    food_log.log_food(seeded, USER, yesterday, "rice", 1.0)
    seeded._delete(USER, "FOOD#rice")

    result = food_log.copy_day(seeded, USER, yesterday, SAMPLE_DAY)
    assert result.unknown_foods == ["rice"]
    assert result.entries == []


def test_adjusting_an_entry_recalculates_and_marks_it_edited(seeded: repository_module.InMemoryRepository) -> None:
    entry = food_log.log_food(seeded, USER, SAMPLE_DAY, "rice", 1.0)

    updated = food_log.adjust_entry(seeded, USER, SAMPLE_DAY, entry.id, 1.25)

    assert updated is not None
    assert updated.servings == 1.25
    assert updated.macros_snapshot.kcal == pytest.approx(450.0)
    assert updated.was_edited is True
    assert len(seeded.list_entries(USER, SAMPLE_DAY)) == 1


def test_adjusting_an_unknown_entry_returns_none(seeded: repository_module.InMemoryRepository) -> None:
    assert food_log.adjust_entry(seeded, USER, SAMPLE_DAY, "nope", 1.0) is None


def test_removing_and_clearing(seeded: repository_module.InMemoryRepository) -> None:
    entry = food_log.log_food(seeded, USER, SAMPLE_DAY, "rice", 1.0)
    food_log.log_food(seeded, USER, SAMPLE_DAY, "oats", 0.4)

    assert food_log.remove_entry(seeded, USER, SAMPLE_DAY, entry.id) is True
    assert food_log.clear_day(seeded, USER, SAMPLE_DAY) == 1


def test_applying_an_unknown_meal_or_template_is_an_error(seeded: repository_module.InMemoryRepository) -> None:
    with pytest.raises(food_log.FoodLogError, match="saved meal"):
        food_log.apply_meal(seeded, USER, SAMPLE_DAY, "brunch")
    with pytest.raises(food_log.FoodLogError, match="day template"):
        food_log.apply_template(seeded, USER, SAMPLE_DAY, "cheat-day")


# --- day assembly ----------------------------------------------------------


def test_a_day_with_nothing_in_it_still_builds() -> None:
    """A brand-new user opening the app must not see a crash."""
    view = day_view.build_day(repository_module.InMemoryRepository(), USER, SAMPLE_DAY)

    assert view.snapshot.date == SAMPLE_DAY
    assert view.snapshot.derived.balance is None
    assert view.snapshot.nutrition.entry_count == 0
    assert view.target is None
    assert view.weight_trend is None
    assert view.observed_maintenance is None


def test_the_day_view_combines_garmin_and_food(with_garmin: repository_module.InMemoryRepository) -> None:
    food_log.apply_template(
        with_garmin, USER, SAMPLE_DAY, "normal-day", servings_overrides={"rice": 1.25}
    )
    with_garmin.save_target(USER, models.MacroTarget(
        effective_from=date(2026, 8, 1), goal=models.GoalType.CUTTING,
        kcal=2400.0, protein_g=180.0, carbs_g=270.0, fat_g=68.0,
    ))

    view = day_view.build_day(with_garmin, USER, SAMPLE_DAY)
    snapshot = view.snapshot

    assert snapshot.measured.energy.total_kcal == 2421.0
    assert snapshot.nutrition.consumed.kcal > 2000
    assert snapshot.derived.balance is not None
    assert snapshot.derived.balance.state is models.BalanceState.DEFICIT
    assert snapshot.nutrition.remaining is not None
    assert snapshot.nutrition.adherence is not None
    assert snapshot.nutrition.adherence.protein_target_met is True


def test_the_balance_is_expenditure_minus_intake(with_garmin: repository_module.InMemoryRepository) -> None:
    food_log.log_food(with_garmin, USER, SAMPLE_DAY, "rice", 1.0)

    view = day_view.build_day(with_garmin, USER, SAMPLE_DAY)
    balance = view.snapshot.derived.balance

    assert balance is not None
    assert balance.balance_kcal == pytest.approx(360.0 - 2421.0)


def test_no_target_yet_means_totals_without_a_comparison(with_garmin: repository_module.InMemoryRepository) -> None:
    """The seed target starts 2026-09-03, so a day before that has no target -- which is
    the effective-dated design working, not a bug."""
    food_log.log_food(with_garmin, USER, SAMPLE_DAY, "rice", 1.0)

    view = day_view.build_day(with_garmin, USER, SAMPLE_DAY)

    assert view.target is None
    assert view.snapshot.nutrition.consumed.kcal == 360.0
    assert view.snapshot.nutrition.remaining is None
    assert view.snapshot.nutrition.adherence is None


def test_bmr_uses_the_smoothed_weight_when_today_is_unlogged(with_garmin: repository_module.InMemoryRepository) -> None:
    """Skipping a weigh-in must not blank the Energy section."""
    for days_back in range(1, 8):
        with_garmin.save_weight(
            USER, models.WeightEntry(date=SAMPLE_DAY - timedelta(days=days_back), weight_kg=79.5)
        )

    view = day_view.build_day(with_garmin, USER, SAMPLE_DAY)

    assert view.snapshot.body.weight_kg is None          # nothing logged today
    assert view.snapshot.body.weight_ema_kg is not None  # but we still have a figure
    assert view.snapshot.derived.bmr is not None


def test_no_weight_at_all_reports_that_rather_than_guessing(with_garmin: repository_module.InMemoryRepository) -> None:
    view = day_view.build_day(with_garmin, USER, SAMPLE_DAY)

    assert view.snapshot.derived.bmr is None
    codes = [reason.code for reason in view.all_reasons]
    assert reasons.ReasonCode.NO_WEIGH_IN in codes


def test_recovery_is_unknown_until_a_baseline_exists(with_garmin: repository_module.InMemoryRepository) -> None:
    """One imported day is nowhere near enough history, and the app says so instead of
    inventing a score."""
    view = day_view.build_day(with_garmin, USER, SAMPLE_DAY)
    recovery_status = view.snapshot.derived.recovery_status

    assert recovery_status is not None
    assert recovery_status.status is models.Status.UNKNOWN
    assert recovery_status.score is None
    assert reasons.ReasonCode.BASELINE_BUILDING in [reason.code for reason in view.all_reasons]


def test_recovery_gets_a_verdict_once_there_is_enough_history() -> None:
    """Thirty days of steady readings, then a bad night, should read as below normal."""
    repository = repository_module.InMemoryRepository()
    seed_loader.load_seed(repository, USER)


    for days_back in range(1, 31):
        day = SAMPLE_DAY - timedelta(days=days_back)
        repository.save_snapshot(USER, models.DailyHealthSnapshot(
            date=day,
            measured=models.MeasuredMetrics(
                sleep=models.Sleep(duration_min=430.0, score=82.0),
                heart=models.Heart(hrv_ms=52.0, resting_hr=53.0),
            ),
        ))

    repository.save_snapshot(USER, models.DailyHealthSnapshot(
        date=SAMPLE_DAY,
        measured=models.MeasuredMetrics(
            sleep=models.Sleep(duration_min=360.0, score=61.0),
            heart=models.Heart(hrv_ms=42.0, resting_hr=59.0),
        ),
    ))

    view = day_view.build_day(repository, USER, SAMPLE_DAY)
    recovery_status = view.snapshot.derived.recovery_status

    assert recovery_status is not None
    assert recovery_status.status is models.Status.BELOW
    assert set(recovery_status.inputs_used) == {
        "sleep_duration_min", "sleep_score", "hrv_ms", "resting_hr",
    }

    codes = [reason.code for reason in view.all_reasons]
    assert reasons.ReasonCode.HRV_BELOW_BASELINE in codes
    assert reasons.ReasonCode.SLEEP_BELOW_BASELINE in codes
    assert reasons.ReasonCode.RHR_ABOVE_BASELINE in codes


def test_composition_appears_once_a_dexa_scan_exists(with_garmin: repository_module.InMemoryRepository) -> None:
    with_garmin.save_weight(USER, models.WeightEntry(date=SAMPLE_DAY, weight_kg=78.0))
    with_garmin.save_dexa_scan(USER, models.DexaScan(
        date=date(2026, 8, 1), total_mass_kg=80.0, fat_mass_kg=15.2,
        lean_mass_kg=61.5, bone_mass_kg=3.2, body_fat_pct=19.0,
    ))

    view = day_view.build_day(with_garmin, USER, SAMPLE_DAY)
    composition = view.snapshot.body.composition

    assert composition is not None
    assert composition.measured is False          # projected from the anchor, not measured
    assert composition.anchor_scan_date == date(2026, 8, 1)
    assert reasons.ReasonCode.COMPOSITION_ESTIMATED in [r.code for r in view.all_reasons]


def test_a_dexa_scan_switches_the_bmr_formula(with_garmin: repository_module.InMemoryRepository) -> None:
    """Lean mass being known is what makes Katch-McArdle available, and the switch has
    to be visible rather than silent."""

    with_garmin.save_weight(USER, models.WeightEntry(date=SAMPLE_DAY, weight_kg=80.0))

    before = day_view.build_day(with_garmin, USER, SAMPLE_DAY)
    assert before.snapshot.derived.bmr is not None
    assert before.snapshot.derived.bmr.formula is models.BmrFormula.MIFFLIN_ST_JEOR

    with_garmin.save_dexa_scan(USER, models.DexaScan(
        date=SAMPLE_DAY, total_mass_kg=80.0, fat_mass_kg=15.2,
        lean_mass_kg=61.5, bone_mass_kg=3.2, body_fat_pct=19.0,
    ))

    after = day_view.build_day(with_garmin, USER, SAMPLE_DAY)
    assert after.snapshot.derived.bmr is not None
    assert after.snapshot.derived.bmr.formula is models.BmrFormula.KATCH_MCARDLE
    assert reasons.ReasonCode.BMR_FORMULA_KATCH_MCARDLE in [r.code for r in after.all_reasons]


def test_weight_trend_and_changes_are_reported(with_garmin: repository_module.InMemoryRepository) -> None:
    for days_back in range(30):
        with_garmin.save_weight(USER, models.WeightEntry(
            date=SAMPLE_DAY - timedelta(days=days_back),
            weight_kg=79.0 + 0.03 * days_back,
        ))

    view = day_view.build_day(with_garmin, USER, SAMPLE_DAY)

    assert view.weight_trend is not None
    assert view.weight_trend.slope_per_week < 0        # losing weight
    assert view.weight_change_7d is not None
    assert view.weigh_ins_available == 30


def test_observed_maintenance_appears_with_enough_history() -> None:
    """The second feedback loop: intake plus measured weight trend implies what the real
    maintenance figure is, independent of what the watch estimated."""
    repository = repository_module.InMemoryRepository()
    seed_loader.load_seed(repository, USER)


    for days_back in range(45):
        day = SAMPLE_DAY - timedelta(days=days_back)

        food_log.log_food(repository, USER, day, "rice", 6.5)   # ~2340 kcal/day

        repository.save_snapshot(USER, models.DailyHealthSnapshot(
            date=day,
            measured=models.MeasuredMetrics(energy=models.Energy(total_kcal=2900.0)),
        ))

        if days_back % 2 == 0:
            repository.save_weight(USER, models.WeightEntry(
                date=day, weight_kg=80.0 - 0.05 * (44 - days_back)
            ))

    view = day_view.build_day(repository, USER, SAMPLE_DAY)
    estimate = view.observed_maintenance

    assert estimate is not None
    assert estimate.kcal > 2600
    # Garmin's figure is higher than what the body actually did, which is the whole
    # point of measuring this rather than trusting the device.
    assert estimate.difference_vs_garmin_kcal is not None
    assert estimate.difference_vs_garmin_kcal < 0


# --- remaining service paths ----------------------------------------------


def test_applying_a_single_meal(seeded: repository_module.InMemoryRepository) -> None:
    """Logging one meal at a time, rather than a whole day."""
    result = food_log.apply_meal(seeded, USER, SAMPLE_DAY, "breakfast")

    assert len(result.entries) == 2
    assert all(entry.meal == "Breakfast" for entry in result.entries)
    assert all(entry.source is models.LogSource.TEMPLATE for entry in result.entries)


def test_applying_a_meal_reports_unset_portions(seeded: repository_module.InMemoryRepository) -> None:
    result = food_log.apply_meal(seeded, USER, SAMPLE_DAY, "afternoon")

    assert result.needs_servings == ["rice"]
    assert len(result.entries) == 1      # the chicken went in, the rice did not


def test_applying_a_meal_skips_a_food_deleted_since(seeded: repository_module.InMemoryRepository) -> None:
    seeded._delete(USER, "FOOD#whey-protein")

    result = food_log.apply_meal(seeded, USER, SAMPLE_DAY, "breakfast")

    assert result.unknown_foods == ["whey-protein"]
    assert len(result.entries) == 1


def test_a_template_pointing_at_a_deleted_meal_is_an_error(seeded: repository_module.InMemoryRepository) -> None:
    seeded._delete(USER, "MEAL#breakfast")

    with pytest.raises(food_log.FoodLogError, match="no longer exists"):
        food_log.apply_template(seeded, USER, SAMPLE_DAY, "normal-day")


def test_a_template_can_carry_items_directly(seeded: repository_module.InMemoryRepository) -> None:
    """Templates normally group foods into meals, but can also list foods directly."""

    seeded.save_template(USER, models.DayTemplate(
        id="shake-only", name="Shake only",
        items=[models.MealItem(food_id="whey-protein", servings=2.0), models.MealItem(food_id="rice", servings=None)],
    ))

    result = food_log.apply_template(seeded, USER, SAMPLE_DAY, "shake-only")

    assert len(result.entries) == 1
    assert result.entries[0].food_id == "whey-protein"
    assert result.needs_servings == ["rice"]


def test_adjusting_an_entry_whose_food_was_deleted_is_an_error(seeded: repository_module.InMemoryRepository) -> None:
    entry = food_log.log_food(seeded, USER, SAMPLE_DAY, "rice", 1.0)
    seeded._delete(USER, "FOOD#rice")

    with pytest.raises(food_log.FoodLogError, match="no longer in the library"):
        food_log.adjust_entry(seeded, USER, SAMPLE_DAY, entry.id, 1.5)


def test_steps_are_available_as_a_baseline_metric(with_garmin: repository_module.InMemoryRepository) -> None:
    """Steps are stored as a whole number but baselines need floats, so there is a
    conversion on the way through."""
    series = day_view.build_metric_series(
        with_garmin.list_snapshots(USER, date(2026, 8, 1), SAMPLE_DAY), "steps"
    )
    assert series == [(SAMPLE_DAY, 13842.0)]


def test_a_metric_missing_from_a_snapshot_comes_through_as_none() -> None:

    series = day_view.build_metric_series([models.DailyHealthSnapshot(date=SAMPLE_DAY)], "steps")
    assert series == [(SAMPLE_DAY, None)]


def test_the_reason_list_gathers_from_every_part_of_the_day(with_garmin: repository_module.InMemoryRepository) -> None:
    """One list feeds both the "Why?" panel and, later, the LLM layer."""
    for days_back in range(25):
        with_garmin.save_weight(USER, models.WeightEntry(
            date=SAMPLE_DAY - timedelta(days=days_back), weight_kg=79.0
        ))
    food_log.log_food(with_garmin, USER, SAMPLE_DAY, "rice", 1.0)
    with_garmin.save_target(USER, models.MacroTarget(
        effective_from=date(2026, 8, 1), goal=models.GoalType.CUTTING,
        kcal=2400.0, protein_g=180.0, carbs_g=270.0, fat_g=68.0,
    ))

    view = day_view.build_day(with_garmin, USER, SAMPLE_DAY)
    codes = [reason.code for reason in view.all_reasons]

    assert reasons.ReasonCode.BMR_FORMULA_MIFFLIN_ST_JEOR in codes   # from the BMR result
    assert reasons.ReasonCode.ENERGY_DEFICIT in codes                # from the balance
    assert reasons.ReasonCode.PROTEIN_UNDER_TARGET in codes          # from adherence
    assert reasons.ReasonCode.PLATEAU_DETECTED in codes              # from the weight plateau check


def test_a_broken_json_file_in_a_day_folder_is_reported(tmp_path: Path) -> None:
    """A truncated download should fail loudly rather than importing a partial day."""
    folder = tmp_path / "dt=2026-09-02"
    folder.mkdir()
    (folder / "user_summary.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        garmin_import.import_all_days(repository_module.InMemoryRepository(), USER, directory=tmp_path)


def test_files_that_are_not_day_folders_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("notes", encoding="utf-8")
    (tmp_path / "dt=nonsense").mkdir()
    (tmp_path / "other-folder").mkdir()

    assert garmin_import.find_day_folders(tmp_path) == []


def test_import_falls_back_to_the_sample_fixtures(seeded: repository_module.InMemoryRepository) -> None:
    """With no directory given it uses the real probe output if present, and the
    committed sample fixtures otherwise -- so a fresh checkout still works."""
    results = garmin_import.import_all_days(seeded, USER)
    assert results
    assert all(present > 0 for _day, present, _missing in results)
