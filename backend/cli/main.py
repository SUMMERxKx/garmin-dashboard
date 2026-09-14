"""The terminal interface: print one day of Garmin data in a form a person can read.

Run it like this, from the project root:

    .venv/bin/python -m backend.cli.main today
    .venv/bin/python -m backend.cli.main today --date 2026-09-12
    .venv/bin/python -m backend.cli.main today --date 2026-09-12 --provenance

What it does, in order:

    raw_files.load_whole_day()    read the saved responses back off the disk
    normalize.normalize_day()     turn them into one tidy snapshot
    (everything below)            lay that snapshot out on the screen

Why this never touches the network
----------------------------------
Fetching and displaying are separate commands on purpose. `run_fetch` talks to Garmin
and writes files; this reads those files and nothing else. So printing a day is instant,
works on a plane, and cannot possibly be blamed for a Garmin outage. When the way we
read a field improves, this command shows the corrected history immediately, because the
original responses are still sitting on disk.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime

from backend.food import library
from backend.food import log
from backend.garmin import normalize
from backend.garmin import raw_files
from backend.store import database
from backend.store import day_store
from backend.store import food_store

#: What to print where a value is missing. Every field in a snapshot can genuinely be
#: absent -- a watch left on the charger is a normal Tuesday -- so this is a normal
#: sight rather than an error. Two dashes read as "nothing here" at a glance, where the
#: word `None` reads as something having gone wrong.
NOTHING_TO_SHOW = "--"

#: How wide the label column is, so the numbers line up underneath each other. Columns
#: that line up are much faster to scan than columns that do not.
LABEL_WIDTH = 20

#: Metres in a kilometre. Named rather than written as a bare 1000 inside a sum.
METRES_PER_KILOMETRE = 1000.0

#: Minutes in an hour, for the same reason.
MINUTES_PER_HOUR = 60

#: Seconds in a minute, used to turn a fractional pace into mm:ss.
SECONDS_PER_MINUTE = 60


def count_possible_fields() -> int:
    """How many fields a perfect day would have values for.

    This is counted from the dataclasses themselves rather than written down as a
    number, so that adding a field to `normalize.py` cannot leave a stale "of 21" on
    the screen. A number that quietly goes wrong is worse than no number.
    """
    sections = [
        normalize.Energy,
        normalize.Sleep,
        normalize.Recovery,
        normalize.Body,
    ]

    total = 0

    for one_section in sections:
        total = total + len(dataclasses.fields(one_section))

    return total


def show_number(
    value: float | int | None,
    unit: str = "",
    decimal_places: int = 0,
) -> str:
    """Format one number for the screen, or `--` if we have no reading for it.

    Every field goes through here rather than each print line deciding for itself what
    to do about a missing value. One place to decide means one place to change.
    """
    if value is None:
        return NOTHING_TO_SHOW

    formatted_number = f"{value:,.{decimal_places}f}"

    if unit == "":
        return formatted_number

    return f"{formatted_number} {unit}"


def show_duration(minutes: float | None) -> str:
    """Format a number of minutes as hours and minutes, e.g. `5 h 36 m`.

    Sleep is stored in minutes because that is the smallest unit anybody cares about,
    but 336 minutes is not a quantity a person feels. `5 h 36 m` is.
    """
    if minutes is None:
        return NOTHING_TO_SHOW

    whole_minutes = round(minutes)
    hours = whole_minutes // MINUTES_PER_HOUR
    minutes_left_over = whole_minutes % MINUTES_PER_HOUR

    if hours == 0:
        return f"{minutes_left_over} m"

    return f"{hours} h {minutes_left_over:02d} m"


def show_signed_number(value: int | None, sign: str) -> str:
    """Format a number with a leading + or -, or `--` if we have no reading.

    Body battery is reported as two separate amounts, one gained and one spent, and the
    signs are what make that readable at a glance. A missing reading must not pick up a
    sign, because `+--` looks like a bug rather than an absence.
    """
    if value is None:
        return NOTHING_TO_SHOW

    return f"{sign}{show_number(value)}"


def to_kilometres(metres: float | None) -> float | None:
    """Convert metres to kilometres, passing None straight through.

    Garmin reports every distance in metres. Nobody reads a run in metres, so the
    division happens here, once, rather than at each of the three places below that
    print a distance.
    """
    if metres is None:
        return None

    return metres / METRES_PER_KILOMETRE


def show_pace(duration_minutes: float | None, distance_metres: float | None) -> str:
    """Minutes per kilometre, the unit a run is actually read in.

    Garmin reports speed in metres per second, which nobody thinks in. This is derived
    from duration and distance rather than read from `averageSpeed`, so that the pace on
    screen always agrees with the two numbers printed directly above it.
    """
    if duration_minutes is None:
        return NOTHING_TO_SHOW

    if distance_metres is None:
        return NOTHING_TO_SHOW

    # A lifting session records no distance. Dividing by it would crash, and a pace for
    # a session that did not move anywhere would be meaningless even if it did not.
    if distance_metres <= 0:
        return NOTHING_TO_SHOW

    # Safe to divide by: the check above has already ruled out None and zero.
    kilometres = to_kilometres(distance_metres)
    minutes_per_kilometre = duration_minutes / kilometres

    whole_minutes = int(minutes_per_kilometre)
    seconds = round((minutes_per_kilometre - whole_minutes) * SECONDS_PER_MINUTE)

    return f"{whole_minutes}:{seconds:02d} /km"


def print_line(label: str, value: str, label_width: int = LABEL_WIDTH) -> None:
    """Print one indented `label    value` row, with the labels all the same width.

    `label_width` is adjustable because the provenance listing uses the raw field names,
    which are longer than the labels on the main view. Without it the longest names ran
    straight into their values with no gap.
    """
    print(f"  {label.ljust(label_width)}{value}")


def print_heading(heading: str) -> None:
    """Print a section heading with a blank line above it."""
    print()
    print(heading)


def print_energy(energy: normalize.Energy) -> None:
    """Print the calories-and-movement section."""
    print_heading("ENERGY")

    print_line("total burned", show_number(energy.total_kilocalories, "kcal"))
    print_line("active", show_number(energy.active_kilocalories, "kcal"))
    print_line("resting", show_number(energy.resting_kilocalories, "kcal"))
    print_line("steps", show_number(energy.steps))

    # `to_kilometres` passes a missing distance through as None, and `show_number`
    # turns that into `--`, so there is no missing-value case to handle here.
    kilometres = to_kilometres(energy.distance_metres)
    print_line("distance", show_number(kilometres, "km", decimal_places=1))

    # The two intensity figures mean nothing apart, so they are printed as one row.
    moderate = show_number(energy.moderate_intensity_minutes)
    vigorous = show_number(energy.vigorous_intensity_minutes)
    print_line("intensity minutes", f"{moderate} moderate / {vigorous} vigorous")


def print_one_activity(activity: normalize.Activity) -> None:
    """Print one workout."""
    if activity.started_at_local is None:
        started = NOTHING_TO_SHOW
    else:
        started = activity.started_at_local.strftime("%H:%M")

    # The name is free text the user can edit; the type key is Garmin's own vocabulary.
    # Printing both means a renamed activity is still identifiable.
    name = activity.name or NOTHING_TO_SHOW
    type_key = activity.type_key or NOTHING_TO_SHOW

    print()
    print(f"  {started}  {name}  ({type_key})")

    # Every label in this function starts with two extra spaces, which indents these
    # rows under the workout's own title line printed just above. On a day with two
    # workouts that indent is what keeps them from reading as one long block.
    print_line("  duration", show_duration(activity.duration_minutes))

    if activity.distance_metres is None or activity.distance_metres <= 0:
        # A lifting session covers no ground. Saying so beats printing "0.0 km".
        print_line("  distance", NOTHING_TO_SHOW)
    else:
        kilometres = to_kilometres(activity.distance_metres)
        print_line("  distance", show_number(kilometres, "km", decimal_places=2))
        print_line("  pace", show_pace(activity.duration_minutes, activity.distance_metres))

    # The active figure is ours, subtracted from two of Garmin's, so it is labelled.
    # The gross number is printed beside it rather than instead of it, because that is
    # the one the Garmin Connect app shows and the two must be reconcilable by eye.
    active = show_number(activity.active_kilocalories(), "kcal")
    gross = show_number(activity.total_kilocalories, "kcal")
    print_line("  calories (active)", f"{active}   [{gross} gross, ours = gross - resting]")

    average = show_number(activity.average_heart_rate, "bpm")
    maximum = show_number(activity.maximum_heart_rate, "bpm")
    print_line("  heart rate", f"{average} average / {maximum} max")

    aerobic = show_number(activity.aerobic_training_effect, decimal_places=1)
    anaerobic = show_number(activity.anaerobic_training_effect, decimal_places=1)
    print_line("  training effect", f"{aerobic} aerobic / {anaerobic} anaerobic")


def print_activities(activities: list[normalize.Activity]) -> None:
    """Print every workout on this day, or say plainly that there was not one."""
    print_heading("ACTIVITIES")

    if not activities:
        # An empty list is a fact about the day, not a gap in the data, and it should
        # not read like one.
        print("  no workout recorded -- rest day")
        return

    for one_activity in activities:
        print_one_activity(one_activity)

    print()
    # Worth saying every time. These calories are a breakdown of the day's active
    # total, not an addition to it: Garmin has already counted them there. Adding a
    # workout's calories on top would double-count the largest number of the day.
    print("  (already counted inside the day's active calories, not on top of them)")


#: The narrowest the INTAKE label column is allowed to get, so a day with two short
#: entries still lines up with the sections above and below it.
INTAKE_LABEL_WIDTH = 34


def describe_entry(one_entry: log.LoggedFood) -> str:
    """How one logged entry is named on screen.

    The serving basis is printed on every line rather than assumed, because
    raw-versus-cooked is the largest accuracy risk in the whole food log: logging
    cooked rice against dry macros over-counts by 2.5-3x, which is more than an entire
    day's deficit. It stays visible so a mismatch is caught by eye.
    """
    return f"{one_entry.food_name} x{one_entry.servings:g} ({one_entry.serving_basis})"


def print_intake(
    entries: list[log.LoggedFood],
    target: library.MacroTarget | None,
) -> None:
    """Print what was eaten, and how it sits against the target.

    Printed directly under ENERGY because the pair is the entire point of the project:
    calories out on their own are trivia, calories in on their own are a diary. Only
    together are they a measurement.
    """
    print_heading("INTAKE")

    if not entries:
        print("  nothing logged")
        return

    # Sized to the longest line actually present, so a long food name cannot run into
    # its own numbers. The floor keeps short days looking like the rest of the screen.
    descriptions = [describe_entry(one_entry) for one_entry in entries]
    column_width = max(INTAKE_LABEL_WIDTH, max(len(one) for one in descriptions) + 2)

    for one_entry in entries:
        description = describe_entry(one_entry)

        macros = (
            f"{one_entry.kilocalories:.0f} kcal"
            f"  {one_entry.protein_grams:.0f} P"
            f"  {one_entry.carbohydrate_grams:.0f} C"
            f"  {one_entry.fat_grams:.0f} F"
        )

        print_line(description, macros, label_width=column_width)

    totals = log.total_up(entries)

    print()
    print_line(
        f"total ({totals.number_of_entries} items)",
        f"{totals.kilocalories:.0f} kcal"
        f"  {totals.protein_grams:.0f} P"
        f"  {totals.carbohydrate_grams:.0f} C"
        f"  {totals.fat_grams:.0f} F",
        label_width=column_width,
    )

    if target is None:
        return

    print_line(
        "target",
        f"{target.kilocalories:.0f} kcal"
        f"  {target.protein_grams:.0f} P"
        f"  {target.carbohydrate_grams:.0f} C"
        f"  {target.fat_grams:.0f} F",
        label_width=column_width,
    )

    left = log.remaining_against(totals, target)

    # A positive number is still to eat, a negative one is over. The sign is kept
    # rather than being replaced with the words "left" and "over", so the column
    # stays readable straight down.
    print_line(
        "remaining",
        f"{left.kilocalories:+.0f} kcal"
        f"  {left.protein_grams:+.0f} P"
        f"  {left.carbohydrate_grams:+.0f} C"
        f"  {left.fat_grams:+.0f} F",
        label_width=column_width,
    )


def print_energy_balance(
    entries: list[log.LoggedFood],
    energy: normalize.Energy,
) -> None:
    """Print intake minus expenditure, when both are actually known.

    Nothing is estimated here. If either side is missing the section says so, because a
    balance computed against a guess is worse than no balance: it looks exactly as
    confident as a real one.

    Both numbers carry known error -- Garmin overstates resistance-training calories,
    and a food log is only as good as the weighing. The honest use of this figure is as
    a trend across weeks against measured weight, not as a verdict on one day.
    """
    print_heading("ENERGY BALANCE")

    if not entries:
        print("  nothing logged, so there is nothing to compare")
        return

    if energy.total_kilocalories is None:
        print("  no Garmin expenditure for this day, so there is nothing to compare")
        return

    eaten = log.total_up(entries).kilocalories
    burned = float(energy.total_kilocalories)
    balance = eaten - burned

    print_line("eaten", f"{eaten:.0f} kcal")
    print_line("burned (Garmin)", f"{burned:.0f} kcal")

    if balance < 0:
        print_line("balance", f"{balance:+.0f} kcal   deficit")
    else:
        print_line("balance", f"{balance:+.0f} kcal   surplus")


def print_sleep(sleep: normalize.Sleep) -> None:
    """Print last night."""
    print_heading("SLEEP")

    print_line("slept", show_duration(sleep.total_minutes))

    if sleep.score is None:
        score = NOTHING_TO_SHOW
    else:
        # Out of 100, said out loud, because a bare "71" invites the question.
        score = f"{sleep.score} / 100"

    print_line("score", score)

    print_line("deep", show_duration(sleep.deep_minutes))
    print_line("light", show_duration(sleep.light_minutes))
    print_line("rem", show_duration(sleep.rem_minutes))
    print_line("awake", show_duration(sleep.awake_minutes))


def print_recovery(recovery: normalize.Recovery) -> None:
    """Print the recovery signals.

    HRV is printed next to its own weekly average and baseline, and that layout is the
    point of the section rather than a decoration. `HRV 96` on its own says nothing at
    all: the same 96 is reassuring for one person and alarming for another. It only
    becomes information beside the number that is normal for YOU.
    """
    print_heading("RECOVERY")

    hrv_tonight = show_number(recovery.hrv_last_night, "ms", decimal_places=0)
    hrv_weekly = show_number(recovery.hrv_weekly_average, "ms", decimal_places=0)
    hrv_baseline = show_number(recovery.hrv_baseline, "ms", decimal_places=0)

    print_line("HRV last night", hrv_tonight)
    print_line("   vs 7-day average", hrv_weekly)
    print_line("   vs baseline", hrv_baseline)

    print_line("resting heart rate", show_number(recovery.resting_heart_rate, "bpm"))

    # The + and - signs are attached here rather than inside the format string, so that
    # a missing reading prints as a plain `--` instead of a nonsense `+--`.
    charged = show_signed_number(recovery.body_battery_charged, "+")
    drained = show_signed_number(recovery.body_battery_drained, "-")
    print_line("body battery", f"{charged} charged / {drained} drained")

    print_line("average stress", show_number(recovery.average_stress))


def print_body(body: normalize.Body) -> None:
    """Print the body measurements.

    Usually one empty row, and that is expected rather than a fault: there is no smart
    scale, so weight is normally typed in by hand rather than arriving from Garmin.
    """
    print_heading("BODY")

    print_line("weight", show_number(body.weight_kilograms, "kg", decimal_places=1))


def print_provenance(snapshot: normalize.DailySnapshot) -> None:
    """Print where every filled-in field actually came from.

    This is the answer to "are you sure that number means what you think it means?".
    It is behind a flag because it is a debugging view, not a daily one.
    """
    print_heading("WHERE EACH VALUE CAME FROM")

    field_names = snapshot.field_names_found()

    if not field_names:
        # Possible even when the files exist: some endpoints answer with a perfectly
        # successful response whose every value is null. Say so plainly rather than
        # printing an empty heading.
        print("  nothing was found for this day")
        return

    # Two spaces past the longest name, so there is always a visible gap between the
    # name and its source however long the names happen to be. The activity names are
    # measured too, because they are printed in the same column further down and one
    # long one would otherwise run straight into its source.
    every_name = list(field_names)

    for one_activity in snapshot.activities:
        every_name.extend(one_activity.provenance.keys())

    widest_name = max(len(one_name) for one_name in every_name)
    column_width = widest_name + 2

    for field_name in field_names:
        print_line(field_name, snapshot.provenance[field_name], label_width=column_width)

    # Each activity keeps its own provenance, because the daily one deliberately does
    # not carry them. Listed under its own heading so the source of a workout number is
    # traceable in exactly the same way.
    for one_activity in snapshot.activities:
        print()
        print(f"  {one_activity.name or NOTHING_TO_SHOW}:")

        for field_name in sorted(one_activity.provenance):
            print_line(
                field_name,
                one_activity.provenance[field_name],
                label_width=column_width,
            )


def print_snapshot(
    snapshot: normalize.DailySnapshot,
    show_provenance: bool,
    entries: list[log.LoggedFood],
    target: library.MacroTarget | None,
) -> None:
    """Print one whole day."""
    # "Friday 12 September 2026" rather than "2026-09-12", because a weekday is what
    # makes a day recognisable -- a bad night is much easier to place once you can see
    # it was a Sunday.
    day_in_words = snapshot.day.strftime("%A %d %B %Y")

    print()
    print(f"== {day_in_words} ==")

    fields_found = snapshot.how_many_fields_found()
    fields_possible = count_possible_fields()

    # The health signal, printed first because it tells you whether to trust the rest.
    # Some Forerunner 165 endpoints answer with a perfectly successful response whose
    # values are all null, so "the fetch worked" is not the same as "the data is here".
    # A day that drops from twenty-one fields to four is a broken sync, whatever the
    # status codes said.
    print(f"   {fields_found} of {fields_possible} fields filled in")

    print_energy(snapshot.energy)
    print_intake(entries, target)
    print_energy_balance(entries, snapshot.energy)
    # After the three numbers it explains: a workout is the reason the day's active
    # calories sit where they do.
    print_activities(snapshot.activities)
    print_sleep(snapshot.sleep)
    print_recovery(snapshot.recovery)
    print_body(snapshot.body)

    if show_provenance:
        print_provenance(snapshot)

    print()


def days_we_have_saved() -> list[datetime.date]:
    """Every day that has a folder of saved responses on disk, oldest first.

    Used only to give a helpful message when the day asked for is not there. Folders
    are named `dt=YYYY-MM-DD`, which is the same layout the S3 bucket will use later.
    """
    if not raw_files.DEFAULT_RAW_DIRECTORY.exists():
        return []

    days = []

    for one_folder in raw_files.DEFAULT_RAW_DIRECTORY.iterdir():
        if not one_folder.is_dir():
            continue

        if not one_folder.name.startswith("dt="):
            continue

        date_text = one_folder.name.removeprefix("dt=")

        try:
            days.append(datetime.date.fromisoformat(date_text))
        except ValueError:
            # A folder whose name is not a date is not ours. Skip it rather than
            # crashing the whole command over it.
            continue

    return sorted(days)


def explain_that_the_day_is_missing(day: datetime.date) -> None:
    """Say why there is nothing to print, and what to do about it."""
    print()
    print(f"No saved data for {day.isoformat()}.")
    print()
    print("Fetch it first:")
    print(f"    .venv/bin/python -m backend.garmin.run_fetch --date {day.isoformat()}")

    days_available = days_we_have_saved()

    if days_available:
        print()
        print("Days already saved:")
        for one_day in days_available:
            print(f"    {one_day.isoformat()}")

    print()


def work_out_which_day_to_show(date_text: str | None) -> datetime.date:
    """Turn the `--date` option into a date.

    The default is YESTERDAY, matching `run_fetch` for the same reason: today is always
    incomplete. The day is not over, the watch may not have synced since this morning,
    and calories and steps are still climbing. Showing a half-finished day next to a
    baseline built from finished ones invites a wrong conclusion every single time.
    """
    if date_text is None:
        return datetime.date.today() - datetime.timedelta(days=1)

    # Raises ValueError on anything that is not a date; main() turns that into a
    # readable sentence rather than a stack trace.
    return datetime.date.fromisoformat(date_text)


def run_import(days_to_import: list[datetime.date]) -> int:
    """Read saved raw responses for these days and store the interpreted day.

    Safe to run as often as you like. Storing a day replaces whatever was stored for it
    before, so importing the same day three times leaves one copy -- which is what makes
    this the way to apply an improved mapping to history: run it again over the files
    already on disk and every stored day is rebuilt.
    """
    if not days_to_import:
        print("Nothing to import: no saved days found.")
        print("Fetch some first:")
        print("    .venv/bin/python -m backend.garmin.run_fetch --days 7")
        return 1

    open_database = database.Database()

    print(f"Importing into {open_database.database_path}")
    print()

    number_imported = 0

    for day in days_to_import:
        saved_responses = raw_files.load_whole_day(day)

        if not saved_responses:
            print(f"  {day.isoformat()}  no saved files, skipped")
            continue

        snapshot = normalize.normalize_day(saved_responses, day)
        day_store.save_snapshot(open_database, snapshot)

        workouts = len(snapshot.activities)
        fields = snapshot.how_many_fields_found()

        print(f"  {day.isoformat()}  {fields} fields, {workouts} workout(s)")

        number_imported = number_imported + 1

    open_database.close()

    print()
    print(f"Done. {number_imported} day(s) stored.")

    return 0


#: The width of each column in the `days` table, in the order they are printed. The
#: date is left-aligned because it is a label; every number is right-aligned, because
#: digits only line up by place value when they end at the same column.
DAY_TABLE_COLUMN_WIDTHS = [10, 6, 9, 8, 9, 5, 8]


def build_row(*cells: str) -> str:
    """Lay one row of the `days` table out, using the shared column widths."""
    laid_out = []

    for position, one_cell in enumerate(cells):
        width = DAY_TABLE_COLUMN_WIDTHS[position]

        if position == 0:
            laid_out.append(one_cell.ljust(width))
        else:
            laid_out.append(one_cell.rjust(width))

    return "  " + "  ".join(laid_out)


def print_stored_days(snapshots: list[normalize.DailySnapshot]) -> None:
    """Print one line per stored day, so a span can be read at a glance.

    Deliberately one line each. The point of this view is the shape of the column --
    whether sleep is drifting down, whether a field count suddenly collapsed -- and
    that only appears when the days sit directly above each other.
    """
    # Header and rows are built from the same widths, so they cannot drift apart the
    # way hand-counted spaces in a header string always eventually do.
    header = build_row(
        "day", "fields", "kcal out", "steps", "sleep", "HRV", "workouts"
    )

    print()
    print(header)
    print("  " + "-" * (len(header) - 2))

    for snapshot in snapshots:
        print(
            build_row(
                snapshot.day.isoformat(),
                str(snapshot.how_many_fields_found()),
                show_number(snapshot.energy.total_kilocalories),
                show_number(snapshot.energy.steps),
                show_duration(snapshot.sleep.total_minutes),
                show_number(snapshot.recovery.hrv_last_night),
                str(len(snapshot.activities)),
            )
        )

    print()


def run_days(how_many_days: int) -> int:
    """Show the most recent stored days, oldest first."""
    last_day = datetime.date.today()
    first_day = last_day - datetime.timedelta(days=how_many_days - 1)

    open_database = database.Database()

    # One lookup for the whole span, however many days it covers. That is the access
    # pattern the key scheme exists for, and the one baselines will be built on.
    snapshots = day_store.load_snapshots_between(open_database, first_day, last_day)

    open_database.close()

    if not snapshots:
        print()
        print(f"No stored days in the last {how_many_days}.")
        print("Import the days you have already fetched:")
        print("    .venv/bin/python -m backend.cli.main import")
        print()
        return 1

    print_stored_days(snapshots)

    return 0


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
                show_number(one_food.kilocalories),
                show_number(one_food.protein_grams, decimal_places=1),
                show_number(one_food.carbohydrate_grams, decimal_places=1),
                show_number(one_food.fat_grams, decimal_places=1),
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


def build_argument_parser() -> argparse.ArgumentParser:
    """Describe the commands this tool accepts.

    Subcommands (`today`) rather than one flat set of options, because this will grow:
    logging food and recording a weigh-in are coming, and they are separate verbs. The
    shape is easier to set up now than to retrofit later.
    """
    parser = argparse.ArgumentParser(
        prog="backend.cli.main",
        description="Show saved Garmin data, and store it for reading a span at a time.",
    )

    subcommands = parser.add_subparsers(dest="command")

    today = subcommands.add_parser(
        "today",
        help="print one day (default: yesterday, because today is still unfinished)",
    )
    today.add_argument(
        "--date",
        help="the day to show, as YYYY-MM-DD (default: yesterday)",
    )
    today.add_argument(
        "--provenance",
        action="store_true",
        help="also list where each value was read from",
    )

    import_command = subcommands.add_parser(
        "import",
        help="read saved raw responses into the database (safe to re-run)",
    )
    import_command.add_argument(
        "--date",
        help="import one day only, as YYYY-MM-DD (default: every saved day)",
    )

    subcommands.add_parser(
        "foods",
        help="list the food library and check it for mistakes",
    )

    log_command = subcommands.add_parser(
        "log",
        help="log a food you have eaten",
    )
    log_command.add_argument("food_id", help="which food, e.g. whey-protein")
    log_command.add_argument(
        "servings",
        type=float,
        help="how many servings, e.g. 1.5",
    )
    log_command.add_argument(
        "--date",
        help="the day to log it against, as YYYY-MM-DD (default: today)",
    )

    days_command = subcommands.add_parser(
        "days",
        help="one line per stored day, to see a span at a glance",
    )
    days_command.add_argument(
        "--days",
        type=int,
        default=14,
        help="how many days back to show (default: 14)",
    )

    return parser


def main() -> int:
    """Entry point. Returns 0 if everything went well and 1 if it did not.

    Returning a number rather than just printing is the long-standing shell convention:
    0 means success, anything else means failure. It is what lets another script -- or
    a scheduler, later on -- tell whether this run worked.
    """
    parser = build_argument_parser()
    arguments = parser.parse_args()

    if arguments.command is None:
        # Nobody typed a subcommand. Show the help rather than doing nothing silently.
        parser.print_help()
        return 1

    if arguments.command == "foods":
        return run_foods()

    if arguments.command == "log":
        return run_log(arguments.food_id, arguments.servings, arguments.date)

    if arguments.command == "days":
        return run_days(arguments.days)

    if arguments.command == "import":
        if arguments.date is None:
            # No day named, so import everything already on disk. Re-importing is
            # harmless, and this is the command you want after improving the mapping.
            return run_import(days_we_have_saved())

        try:
            return run_import([datetime.date.fromisoformat(arguments.date)])
        except ValueError:
            print(f"'{arguments.date}' is not a date. Use the form 2026-09-12.")
            return 1

    try:
        day = work_out_which_day_to_show(arguments.date)
    except ValueError:
        print(f"'{arguments.date}' is not a date. Use the form 2026-09-12.")
        return 1

    # Reads from disk only. `load_whole_day` hands back an empty dictionary rather than
    # raising when the folder is not there, so a missing day is handled here as the
    # ordinary situation it is.
    saved_responses = raw_files.load_whole_day(day)

    # The Garmin side comes off the disk; the food side comes out of the database.
    # Two different stores because they are two different kinds of fact: one is an
    # observation we were handed, the other is something you typed.
    open_database = database.Database()
    entries = food_store.load_entries_for_day(open_database, day)
    open_database.close()

    # Only give up when there is nothing at all. Today is the ordinary case here: you
    # have logged breakfast, and Garmin has nothing yet because the day is not over and
    # the watch has not been fetched. Refusing to show the food you just typed, because
    # the OTHER half of the day is missing, would be exactly backwards.
    if not saved_responses and not entries:
        explain_that_the_day_is_missing(day)
        return 1

    snapshot = normalize.normalize_day(saved_responses, day)

    if not saved_responses:
        print()
        print(f"  (no Garmin data for {day.isoformat()} yet -- showing the food log only)")

    whole_library = library.load_library()
    target = whole_library.target_in_force_on(day)

    print_snapshot(
        snapshot,
        show_provenance=arguments.provenance,
        entries=entries,
        target=target,
    )

    return 0


# This block runs only when the file is executed directly, not when it is imported by
# another module. `raise SystemExit(...)` is how a Python program sets the exit code the
# shell sees.
if __name__ == "__main__":
    raise SystemExit(main())
