"""The commands that move data about: `import` and `days`.

Neither talks to Garmin. `import` reads responses already saved on disk and writes the
interpreted day into the database; `days` reads that database back. Both are safe to run
as often as you like -- storing a day replaces whatever was stored for it before, which
is what makes re-importing the way to apply an improved mapping to history.
"""

from __future__ import annotations

import datetime

from backend.cli import formatting
from backend.garmin import normalize
from backend.garmin import raw_files
from backend.store import day_store
from backend.store import open_store

#: The width of each column in the `days` table, in the order they are printed. The
#: date is left-aligned because it is a label; every number is right-aligned, because
#: digits only line up by place value when they end at the same column.
DAY_TABLE_COLUMN_WIDTHS = [10, 6, 9, 8, 9, 5, 8]


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

    open_database = open_store.open_store()

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
                formatting.show_number(snapshot.energy.total_kilocalories),
                formatting.show_number(snapshot.energy.steps),
                formatting.show_duration(snapshot.sleep.total_minutes),
                formatting.show_number(snapshot.recovery.hrv_last_night),
                str(len(snapshot.activities)),
            )
        )

    print()

def run_days(how_many_days: int) -> int:
    """Show the most recent stored days, oldest first."""
    last_day = datetime.date.today()
    first_day = last_day - datetime.timedelta(days=how_many_days - 1)

    open_database = open_store.open_store()

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
