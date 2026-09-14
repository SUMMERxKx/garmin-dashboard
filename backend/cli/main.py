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

from backend.garmin import normalize
from backend.garmin import raw_files
from backend.store import database
from backend.store import day_store

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


def print_snapshot(snapshot: normalize.DailySnapshot, show_provenance: bool) -> None:
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
    # Directly after energy, because a workout is the explanation for the day's active
    # calories sitting where they are.
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

    if not saved_responses:
        explain_that_the_day_is_missing(day)
        return 1

    snapshot = normalize.normalize_day(saved_responses, day)

    print_snapshot(snapshot, show_provenance=arguments.provenance)

    return 0


# This block runs only when the file is executed directly, not when it is imported by
# another module. `raise SystemExit(...)` is how a Python program sets the exit code the
# shell sees.
if __name__ == "__main__":
    raise SystemExit(main())
