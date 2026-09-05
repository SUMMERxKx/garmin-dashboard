"""Command-line interface for the dashboard.

This is the Phase 2 "screen": enough to actually use the thing daily from a terminal,
before any web frontend exists. Every command is a thin wrapper around a service
function, so the logic stays testable without going through the CLI.

    python -m backend.cli.main init          # create the database and load the seed
    python -m backend.cli.main today         # the day view
    python -m backend.cli.main weigh 79.4    # log a weigh-in
    python -m backend.cli.main copy-yesterday
    python -m backend.cli.main log rice 1.25
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from pathlib import Path

import typer

from backend.adapters import keys
from backend.adapters import seed_loader
from backend.adapters import sqlite_repository
from backend.core import models
from backend.core import units
from backend.services import day_view
from backend.services import food_log
from backend.services import garmin_import

THIS_FILE = Path(__file__).resolve()
CLI_DIRECTORY = THIS_FILE.parent
BACKEND_DIRECTORY = CLI_DIRECTORY.parent
PROJECT_ROOT = BACKEND_DIRECTORY.parent

DEFAULT_DATABASE_PATH = PROJECT_ROOT / "garmin-dashboard.db"

app = typer.Typer(add_completion=False, help="Personal health dashboard.")

# A line of dashes used to separate sections of the day view.
DIVIDER = "-" * 52


def open_repository(database_path: Path = DEFAULT_DATABASE_PATH) -> sqlite_repository.SqliteRepository:
    return sqlite_repository.SqliteRepository(database_path)


def parse_day(text: str | None) -> date:
    """Turn a --date argument into a date. No argument means today."""
    if text is None:
        return date.today()
    return date.fromisoformat(text)


def show_optional(value: float | None, suffix: str = "", decimals: int = 0) -> str:
    """Format a number that might be missing.

    Missing values print as a dash rather than "None" or "0". That distinction matters:
    zero steps is a real reading, and no reading at all is not.
    """
    if value is None:
        return "--"
    return f"{value:.{decimals}f}{suffix}"


@app.command()
def init(
    database: Path = typer.Option(DEFAULT_DATABASE_PATH, help="Where to keep the database."),
    user: str = typer.Option(keys.DEFAULT_USER_ID, help="User id."),
    skip_import: bool = typer.Option(False, help="Do not import saved Garmin responses."),
) -> None:
    """Create the database, load the seed file, and import any saved Garmin days."""
    repository = open_repository(database)

    counts = seed_loader.load_seed(repository, user)
    typer.echo(
        f"Loaded seed: {counts['foods']} foods, {counts['meals']} meals, "
        f"{counts['templates']} templates, {counts['targets']} target(s)."
    )

    if seed_loader.seed_is_provisional():
        typer.echo(
            "  NOTE: the food library holds PROVISIONAL values -- typical published\n"
            "  figures, not your product labels. Replace them before trusting totals."
        )

    if not skip_import:
        imported = garmin_import.import_all_days(repository, user)

        if not imported:
            typer.echo("No saved Garmin responses found. Run scripts/garmin_probe.py first.")
        else:
            typer.echo(f"Imported {len(imported)} day(s) of Garmin data:")
            for day, present, missing in imported:
                if missing == 0:
                    typer.echo(f"  {day}  all {present} essential fields present")
                else:
                    typer.echo(f"  {day}  {present} present, {missing} MISSING")

    typer.echo(f"\nDatabase: {database}")


@app.command()
def today(
    date_text: str = typer.Option(None, "--date", help="YYYY-MM-DD (default: today)."),
    database: Path = typer.Option(DEFAULT_DATABASE_PATH, help="Where the database is."),
    user: str = typer.Option(keys.DEFAULT_USER_ID, help="User id."),
    imperial: bool = typer.Option(False, help="Show weight in pounds."),
) -> None:
    """Show everything known about one day."""
    repository = open_repository(database)
    day = parse_day(date_text)

    view = day_view.build_day(repository, user, day)
    snapshot = view.snapshot

    if imperial:
        units = units.UnitPreference.IMPERIAL
    else:
        units = units.UnitPreference.METRIC

    typer.echo(f"\n{day.strftime('%A %-d %B %Y')}")
    typer.echo(DIVIDER)

    # --- energy balance: the question with the shortest shelf life ---------
    typer.echo("ENERGY BALANCE")
    balance = snapshot.derived.balance

    if balance is None:
        typer.echo("  no expenditure data for this day yet")
    else:
        typer.echo(f"  burned      {balance.burned_kcal:>7.0f} kcal")
        typer.echo(f"  consumed    {balance.consumed_kcal:>7.0f} kcal")
        typer.echo(f"  balance     {balance.balance_kcal:>+7.0f} kcal   ({balance.state.value})")

    # --- nutrition ---------------------------------------------------------
    typer.echo("")
    typer.echo("NUTRITION")
    consumed = snapshot.nutrition.consumed
    target = snapshot.nutrition.target

    if target is None:
        typer.echo(f"  {consumed.kcal:.0f} kcal | P {consumed.protein_g:.0f} "
                   f"| C {consumed.carbs_g:.0f} | F {consumed.fat_g:.0f}")
        typer.echo("  no macro target in force on this date")
    else:
        typer.echo(f"  calories  {consumed.kcal:>7.0f} / {target.kcal:.0f}")
        typer.echo(f"  protein   {consumed.protein_g:>7.0f} / {target.protein_g:.0f} g")
        typer.echo(f"  carbs     {consumed.carbs_g:>7.0f} / {target.carbs_g:.0f} g")
        typer.echo(f"  fat       {consumed.fat_g:>7.0f} / {target.fat_g:.0f} g")

    typer.echo(f"  ({snapshot.nutrition.entry_count} item(s) logged)")

    # --- activity ----------------------------------------------------------
    typer.echo("")
    typer.echo("ACTIVITY")
    activity = snapshot.measured.activity
    typer.echo(f"  steps           {show_optional(activity.steps)}")
    typer.echo(f"  active cal      {show_optional(snapshot.measured.energy.active_kcal)}")
    typer.echo(f"  intensity min   {show_optional(activity.intensity_minutes)}")

    if activity.activities:
        for workout in activity.activities:
            typer.echo(
                f"  workout         {workout.kind.value}, "
                f"{show_optional(workout.duration_min)} min, "
                f"{show_optional(workout.calories)} kcal"
            )

    # --- recovery ----------------------------------------------------------
    typer.echo("")
    recovery_status = snapshot.derived.recovery_status

    if recovery_status is None:
        typer.echo("RECOVERY")
    else:
        typer.echo(f"RECOVERY  ({recovery_status.status.value})")

    sleep = snapshot.measured.sleep
    typer.echo(f"  sleep           {show_optional(sleep.duration_min)} min")
    typer.echo(f"  sleep score     {show_optional(sleep.score)}")
    typer.echo(f"  HRV             {show_optional(snapshot.measured.heart.hrv_ms)} ms")
    typer.echo(f"  resting HR      {show_optional(snapshot.measured.heart.resting_hr)} bpm")
    typer.echo(f"  body battery    {show_optional(snapshot.measured.recovery.body_battery_high)}")

    # --- body --------------------------------------------------------------
    typer.echo("")
    typer.echo("BODY")

    if snapshot.body.weight_kg is None:
        typer.echo("  weight          -- (not logged today)")
    else:
        typer.echo(f"  weight          {units.format_weight(snapshot.body.weight_kg, units)}")

    if snapshot.body.weight_ema_kg is not None:
        typer.echo(f"  7-day average   {units.format_weight(snapshot.body.weight_ema_kg, units)}")

    if view.weight_trend is not None:
        typer.echo(f"  trend           {view.weight_trend.slope_per_week:+.2f} kg/week")

    if view.weight_change_30d is not None:
        typer.echo(f"  30-day change   {view.weight_change_30d:+.2f} kg")

    if snapshot.body.composition is None:
        typer.echo("  DEXA            not recorded")
    else:
        composition = snapshot.body.composition
        measured_or_not = "measured" if composition.measured else "estimated"
        typer.echo(
            f"  body fat        {composition.body_fat_pct:.1f}% ({measured_or_not})"
        )

    # --- what the data has taught us ---------------------------------------
    if view.observed_maintenance is not None:
        estimate = view.observed_maintenance
        typer.echo("")
        typer.echo("OBSERVED MAINTENANCE")
        typer.echo(f"  your data suggests {estimate.kcal:.0f} kcal/day")

        if estimate.difference_vs_garmin_kcal is not None:
            typer.echo(
                f"  that is {estimate.difference_vs_garmin_kcal:+.0f} kcal against "
                f"Garmin's {estimate.garmin_mean_expenditure_kcal:.0f}"
            )

    # --- the explanations --------------------------------------------------
    reasons = view.all_reasons
    if reasons:
        typer.echo("")
        typer.echo("WHY")
        for reason in reasons:
            typer.echo(f"  - {reason.render()}")

    typer.echo(DIVIDER)
    typer.echo(
        f"{view.history_days_available} synced day(s), "
        f"{view.weigh_ins_available} weigh-in(s) in the last 90 days"
    )


@app.command()
def weigh(
    kilograms: float = typer.Argument(..., help="Your weight in kilograms."),
    date_text: str = typer.Option(None, "--date", help="YYYY-MM-DD (default: today)."),
    database: Path = typer.Option(DEFAULT_DATABASE_PATH),
    user: str = typer.Option(keys.DEFAULT_USER_ID),
) -> None:
    """Record a weigh-in. Missing a day is fine -- the trend tolerates gaps."""
    repository = open_repository(database)
    day = parse_day(date_text)

    repository.save_weight(user, models.WeightEntry(date=day, weight_kg=kilograms))
    typer.echo(f"Recorded {kilograms} kg for {day}.")


@app.command()
def log(
    food_id: str = typer.Argument(..., help="Food id from the library."),
    servings: float = typer.Argument(..., help="How many servings."),
    meal: str = typer.Option(None, help="Optional meal name."),
    date_text: str = typer.Option(None, "--date", help="YYYY-MM-DD (default: today)."),
    database: Path = typer.Option(DEFAULT_DATABASE_PATH),
    user: str = typer.Option(keys.DEFAULT_USER_ID),
) -> None:
    """Log one food item."""
    repository = open_repository(database)
    day = parse_day(date_text)

    try:
        entry = food_log.log_food(repository, user, day, food_id, servings, meal=meal)
    except food_log.FoodLogError as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(code=1) from error

    macros = entry.macros_snapshot
    typer.echo(
        f"Logged {entry.servings} x {entry.food_name} "
        f"({entry.serving_basis.value}): {macros.kcal:.0f} kcal, "
        f"{macros.protein_g:.0f}P {macros.carbs_g:.0f}C {macros.fat_g:.0f}F  [id {entry.id}]"
    )


@app.command("copy-yesterday")
def copy_yesterday(
    date_text: str = typer.Option(None, "--date", help="The day to copy TO."),
    database: Path = typer.Option(DEFAULT_DATABASE_PATH),
    user: str = typer.Option(keys.DEFAULT_USER_ID),
) -> None:
    """Copy yesterday's food onto today. The fast path for a repetitive diet."""
    repository = open_repository(database)
    day = parse_day(date_text)
    yesterday = day - timedelta(days=1)

    result = food_log.copy_day(repository, user, yesterday, day)

    if not result.entries:
        typer.echo(f"Nothing logged on {yesterday} to copy.")
        return

    typer.echo(f"Copied {len(result.entries)} item(s) from {yesterday} to {day}.")

    if result.replaced:
        typer.echo(f"  (replaced {result.replaced} item(s) already logged)")
    if result.unknown_foods:
        typer.echo(f"  skipped, no longer in the library: {', '.join(result.unknown_foods)}")


@app.command()
def template(
    template_id: str = typer.Argument(..., help="Day template id, e.g. normal-day."),
    rice: float = typer.Option(None, help="Servings of rice, which varies day to day."),
    date_text: str = typer.Option(None, "--date", help="YYYY-MM-DD (default: today)."),
    database: Path = typer.Option(DEFAULT_DATABASE_PATH),
    user: str = typer.Option(keys.DEFAULT_USER_ID),
) -> None:
    """Log a whole day from a template."""
    repository = open_repository(database)
    day = parse_day(date_text)

    overrides = {}
    if rice is not None:
        overrides["rice"] = rice

    try:
        result = food_log.apply_template(
            repository, user, day, template_id, servings_overrides=overrides
        )
    except food_log.FoodLogError as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(code=1) from error

    typer.echo(f"Logged {len(result.entries)} item(s) for {day}.")

    if result.needs_servings:
        unset = ", ".join(sorted(set(result.needs_servings)))
        typer.echo(f"  portion not set, so skipped: {unset}")
        typer.echo("  (pass --rice N, or log them individually)")


@app.command()
def entries(
    date_text: str = typer.Option(None, "--date", help="YYYY-MM-DD (default: today)."),
    database: Path = typer.Option(DEFAULT_DATABASE_PATH),
    user: str = typer.Option(keys.DEFAULT_USER_ID),
) -> None:
    """List what has been logged for a day."""
    repository = open_repository(database)
    day = parse_day(date_text)

    logged = repository.list_entries(user, day)

    if not logged:
        typer.echo(f"Nothing logged for {day}.")
        return

    for entry in logged:
        macros = entry.macros_snapshot
        edited_marker = " (edited)" if entry.was_edited else ""
        typer.echo(
            f"  {entry.id}  {entry.servings:>5.2f} x {entry.food_name:<26} "
            f"{macros.kcal:>6.0f} kcal  {macros.protein_g:>5.0f}P  "
            f"[{entry.source.value}]{edited_marker}"
        )


@app.command()
def remove(
    entry_id: str = typer.Argument(..., help="Entry id, shown by the `entries` command."),
    date_text: str = typer.Option(None, "--date", help="YYYY-MM-DD (default: today)."),
    database: Path = typer.Option(DEFAULT_DATABASE_PATH),
    user: str = typer.Option(keys.DEFAULT_USER_ID),
) -> None:
    """Remove one logged item."""
    repository = open_repository(database)
    day = parse_day(date_text)

    if food_log.remove_entry(repository, user, day, entry_id):
        typer.echo(f"Removed {entry_id}.")
    else:
        typer.echo(f"No entry {entry_id} on {day}.")
        raise typer.Exit(code=1)


@app.command()
def foods(
    database: Path = typer.Option(DEFAULT_DATABASE_PATH),
    user: str = typer.Option(keys.DEFAULT_USER_ID),
) -> None:
    """List the food library."""
    repository = open_repository(database)

    for food in repository.list_foods(user):
        typer.echo(
            f"  {food.id:<20} {food.serving_desc:<16} {food.kcal:>5.0f} kcal  "
            f"{food.protein_g:>5.1f}P {food.carbs_g:>5.1f}C {food.fat_g:>5.1f}F  "
            f"[{food.serving_basis.value}]"
        )


@app.command("set-target")
def set_target(
    kcal: float = typer.Argument(...),
    protein: float = typer.Argument(...),
    carbs: float = typer.Argument(...),
    fat: float = typer.Argument(...),
    goal: str = typer.Option("cutting", help="cutting, maintaining or gaining."),
    from_date: str = typer.Option(None, "--from", help="Effective date (default: today)."),
    database: Path = typer.Option(DEFAULT_DATABASE_PATH),
    user: str = typer.Option(keys.DEFAULT_USER_ID),
) -> None:
    """Set a macro target from a given date onward.

    Targets are never overwritten -- a new one is added with its own start date, so past
    days stay scored against the target that actually applied then.
    """
    repository = open_repository(database)
    effective_from = parse_day(from_date)

    target = models.MacroTarget(
        effective_from=effective_from,
        goal=models.GoalType(goal),
        kcal=kcal,
        protein_g=protein,
        carbs_g=carbs,
        fat_g=fat,
    )

    gap = abs(target.implied_kcal - target.kcal)
    if gap > 25.0:
        typer.echo(
            f"Warning: those macros imply {target.implied_kcal:.0f} kcal, "
            f"not {kcal:.0f}. Saving anyway."
        )

    repository.save_target(user, target)
    typer.echo(f"Target from {effective_from}: {kcal:.0f} kcal, {protein:.0f}P {carbs:.0f}C {fat:.0f}F")


if __name__ == "__main__":
    app()
