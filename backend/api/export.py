"""Write the dashboard's JSON to a file, for Phase 1.

This is the only part of the API layer that touches a database or a disk, kept apart
from `dashboard_json.py` for the same reason `raw_files.py` is kept apart from
`fetch.py`: the translation is worth testing on its own, and nothing that reads a
database is easy to test.

It is also temporary in a specific way. When the dashboard moves to AWS, a Lambda will
do exactly what `collect_days` does below -- read the span, build the payload -- and
return it over HTTP instead of writing it next to the web app. The functions it calls do
not change at all.

Run it from the project root:

    .venv/bin/python -m backend.api.export
    .venv/bin/python -m backend.api.export --days 90 --out dashboard/public/data/days.json
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
from typing import Any

from backend import paths
from backend.api import dashboard_json
from backend.body import dexa
from backend.food import library
from backend.garmin import normalize
from backend.store import database
from backend.store import day_store
from backend.store import food_store
from backend.store import weight_store

#: Where the web app expects to find it. A file under the dashboard's own `public`
#: folder is served at `/data/days.json`, which is what the browser fetches in Phase 1
#: and what the API will answer in Phase 3.
DEFAULT_OUTPUT_PATH = paths.PROJECT_ROOT / "dashboard" / "public" / "data" / "days.json"

#: How many days to export when nothing is asked for. Wide enough to cover every day
#: fetched so far, so the default is "everything" rather than a window that quietly
#: starts dropping history.
DEFAULT_DAYS = 400


def collect_days(
    open_database: database.Database,
    first_day: datetime.date,
    last_day: datetime.date,
) -> list[dict[str, Any]]:
    """Read the span and build one JSON object per day, oldest first.

    Three lookups for the whole range -- snapshots, weigh-ins, food -- rather than three
    per day. Against SQLite the difference is invisible; against DynamoDB in Phase 2 it
    is ninety network round trips against three, on every page load. Reading a span is
    the access pattern the key scheme was built around, so using it here costs nothing.

    **A day appears if ANY of the three has something for it**, not only if Garmin does.
    That is not a nicety. The Garmin fetch deliberately runs a day behind, because today
    is unfinished -- so this morning's weigh-in always lands on a day that has no
    snapshot yet. Keying the loop to snapshots would silently drop the most recent
    weigh-in every single day, which is exactly the one you just typed in and want to see.
    """
    snapshots_by_day = {}

    for snapshot in day_store.load_snapshots_between(open_database, first_day, last_day):
        snapshots_by_day[snapshot.day] = snapshot

    weighings_by_day = {}

    for one_weighing in weight_store.load_weighings_between(open_database, first_day, last_day):
        weighings_by_day[one_weighing.day] = one_weighing

    entries_by_day = food_store.load_entries_between(open_database, first_day, last_day)

    every_day = set(snapshots_by_day) | set(weighings_by_day) | set(entries_by_day)

    days = []

    for day in sorted(every_day):
        snapshot = snapshots_by_day.get(day)

        if snapshot is None:
            # A day with a weigh-in or a food log but no Garmin data yet. Normalizing an
            # empty set of responses gives a snapshot whose every field is None, which is
            # the honest answer and exactly the shape the dashboard already handles for a
            # missing reading. No special case needed, because every field was built to
            # default to "no reading" in the first place.
            snapshot = normalize.normalize_day({}, day)

        days.append(
            dashboard_json.day_to_json(
                snapshot,
                weighings_by_day.get(day),
                entries_by_day.get(day, []),
            )
        )

    return days


def write_payload(payload: dict[str, Any], output_path: Path) -> None:
    """Write the JSON, creating the folder if it is not there yet.

    `indent=2` because this file gets read by a human more often than it gets parsed
    while we are still building. It costs a few kilobytes and saves squinting.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as open_file:
        json.dump(payload, open_file, indent=2)
        # A trailing newline, so the file plays nicely with git and with `tail`.
        open_file.write("\n")


def main() -> int:
    """Entry point. 0 if the export worked, 1 if there was nothing to export."""
    parser = argparse.ArgumentParser(
        description="Export stored days as the JSON the dashboard reads."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"how many days back to export (default: {DEFAULT_DAYS})",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUTPUT_PATH),
        help="where to write the file",
    )
    arguments = parser.parse_args()

    last_day = datetime.date.today()
    first_day = last_day - datetime.timedelta(days=arguments.days - 1)

    open_database = database.Database()
    days = collect_days(open_database, first_day, last_day)
    open_database.close()

    if not days:
        print("Nothing to export: no stored days in that span.")
        print("Fetch and import some first.")
        return 1

    # Body composition, the macro target and the fixed profile facts are read here and
    # handed in. All three are optional: a fresh install has no scan and no library, and
    # the dashboard is written to show what it has rather than to require all of it.
    latest_scan = None
    macro_target = None
    profile = None

    try:
        scans = dexa.load_scans()
        if scans:
            # Newest scan wins. `scan_nearest_to` exists for scoring a past day against
            # the scan that applied then; the dashboard header wants the current one.
            latest_scan = dashboard_json.scan_to_json(
                max(scans, key=lambda one: one.scan_date)
            )
    except FileNotFoundError:
        pass

    try:
        whole_library = library.load_library()
        macro_target = dashboard_json.target_to_json(
            whole_library.target_in_force_on(last_day)
        )
        profile = dashboard_json.profile_to_json(
            whole_library.profile.get("height_cm"),
            # PyYAML parses an unquoted 2003-05-01 into a date object, so this may be
            # a date or a string depending on how the file was written. isoformat() on
            # whichever it is keeps the wire value text either way.
            str(whole_library.profile.get("birth_date") or "") or None,
        )
    except (FileNotFoundError, AttributeError):
        pass

    # The clock is read here, at the edge, and passed inwards -- so every function that
    # builds the payload stays testable with a fixed time.
    payload = dashboard_json.span_to_json(
        days,
        datetime.datetime.now(),
        latest_scan=latest_scan,
        macro_target=macro_target,
        profile=profile,
    )

    output_path = Path(arguments.out)
    write_payload(payload, output_path)

    size_in_kilobytes = output_path.stat().st_size / 1024

    print(f"Wrote {len(days)} day(s) to {output_path}")
    print(f"  {payload['first_day']} .. {payload['last_day']}")
    print(f"  {size_in_kilobytes:.1f} KB, schema version {payload['schema_version']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
