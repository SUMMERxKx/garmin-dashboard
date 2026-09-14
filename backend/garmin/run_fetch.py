"""The command that ties the other four modules together.

Run it like this, from the project root:

    .venv/bin/python -m backend.garmin.run_fetch                  # yesterday
    .venv/bin/python -m backend.garmin.run_fetch --date 2026-09-10
    .venv/bin/python -m backend.garmin.run_fetch --days 3         # three days back

What it does, in order:

    login.log_in()            get an authenticated client
    fetch.fetch_one_day()     knock on all seventeen doors
    raw_files.save_whole_day()  write what came back to disk

Why `-m backend.garmin.run_fetch` rather than a path to a file
--------------------------------------------------------------
`python -m` tells Python to run a module that is part of an installed package. Because
it starts from the project root, every `from backend.garmin import ...` below just
works. Running a loose script by its path would put the script's own folder first on the
import path instead, and those imports would fail -- which is why the old version of
this project had to modify the import path by hand at the top of its scripts.
"""

from __future__ import annotations

import argparse
import datetime

from backend.garmin import fetch
from backend.garmin import login
from backend.garmin import raw_files


def work_out_which_days_to_fetch(
    date_text: str | None,
    number_of_days: int,
) -> list[datetime.date]:
    """Turn the command-line options into a list of dates, oldest first.

    The default is YESTERDAY rather than today, and that is deliberate. Today's data is
    always incomplete: the watch may not have synced since this morning, and the day
    itself is not over, so calories and steps are still climbing. A day only becomes
    worth trusting once it has finished.
    """
    if date_text is None:
        most_recent_day = datetime.date.today() - datetime.timedelta(days=1)
    else:
        # `fromisoformat` parses "2026-09-10". If the text is not a valid date it
        # raises ValueError, which main() turns into a readable message.
        most_recent_day = datetime.date.fromisoformat(date_text)

    days = []

    for how_many_days_back in range(number_of_days):
        one_day = most_recent_day - datetime.timedelta(days=how_many_days_back)
        days.append(one_day)

    # `sorted` puts the oldest first, which reads more naturally in the output than
    # counting backwards does.
    return sorted(days)


def describe_one_day(result: fetch.DayFetchResult, folder_saved_to) -> None:
    """Print a short readable report of how one day went."""
    print()
    print(f"== {result.day.isoformat()} ==")

    number_that_worked = len(result.names_that_worked())
    number_of_endpoints = number_that_worked + len(result.names_that_failed())

    print(f"  {number_that_worked} of {number_of_endpoints} endpoints returned something")

    # Only mention failures if there were any. A clean run should stay quiet.
    if result.errors:
        print("  failed:")
        for endpoint_name in result.names_that_failed():
            print(f"    {endpoint_name}: {result.errors[endpoint_name]}")

    # The line that actually matters. Tier-2 endpoints fail harmlessly; tier 1 is what
    # the dashboard is built on, so that is the pass/fail signal worth printing loudly.
    if result.every_tier_one_endpoint_worked():
        print("  all tier-1 endpoints present: this day is usable")
    else:
        print("  !! a tier-1 endpoint is missing: this day is incomplete")

    print(f"  saved to {folder_saved_to}")


def main() -> int:
    """Entry point. Returns 0 if everything went well and 1 if it did not.

    Returning a number rather than printing and stopping is the long-standing shell
    convention: 0 means success, anything else means failure. It is what lets a
    scheduler or another script tell whether this run worked.
    """
    parser = argparse.ArgumentParser(
        description="Fetch one or more days of Garmin data and save the raw responses."
    )
    parser.add_argument(
        "--date",
        help="the most recent day to fetch, as YYYY-MM-DD (default: yesterday)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="how many days to fetch, counting back from --date (default: 1)",
    )
    arguments = parser.parse_args()

    try:
        days_to_fetch = work_out_which_days_to_fetch(arguments.date, arguments.days)
    except ValueError:
        print(f"'{arguments.date}' is not a date. Use the form 2026-09-10.")
        return 1

    print("Logging in to Garmin.")

    try:
        client = login.log_in()
    except Exception as error:
        # Broad on purpose: someone typing a password should get a readable sentence,
        # not a stack trace. The type name is included because it is often the most
        # useful clue about what actually failed.
        print(f"\nLogin failed: {type(error).__name__}: {error}")
        print("If two-factor is on, run this in a terminal so it can prompt you.")
        return 1

    for day in days_to_fetch:
        result = fetch.fetch_one_day(client, day)
        folder = raw_files.save_whole_day(result)
        describe_one_day(result, folder)

    print()
    print(f"Done. Fetched {len(days_to_fetch)} day(s).")

    return 0


# This block runs only when the file is executed directly, not when it is imported by
# another module. It is the closest thing Python has to `public static void main`.
#
# `raise SystemExit(...)` is how a Python program sets the exit code the shell sees.
if __name__ == "__main__":
    raise SystemExit(main())
