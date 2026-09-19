"""Build the whole dashboard payload from the database.

This is the seam between storage and the wire format. `dashboard_json.py` turns objects
into JSON and touches nothing else; `database.py` reads records and knows nothing about
the dashboard. This module reads a span, resolves the things that need the whole span to
be seen at once -- the carry-forward rule for intake, the baselines -- and hands the
result to the translator.

Two callers, one function
-------------------------
`export.py` calls `build_payload` and writes the result to a file, which is how the
dashboard was fed in Phase 1. `server.py` calls the same function and returns the result
over HTTP. They cannot drift apart, because there is only one of it. When the backend
moves to AWS, a Lambda calls it too.
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any

from backend.api import dashboard_json
from backend.body import dexa
from backend.engine import report
from backend.food import intake
from backend.food import library
from backend.food import log
from backend.garmin import normalize
from backend.store import day_store
from backend.store import food_store
from backend.store import intake_store
from backend.store import open_store
from backend.store import weight_store


@dataclasses.dataclass
class FixedFacts:
    """The parts of the payload that are not daily readings and live in files, not the
    database: the newest DEXA scan, the macro target in force, and the profile.

    Gathered into one object so the two callers can fetch them with one call, and so a
    test can hand in an empty set rather than depending on what is on this machine.
    """

    latest_scan: dict[str, Any] | None = None
    macro_target: dict[str, Any] | None = None
    profile: dict[str, Any] | None = None


def read_fixed_facts(as_of: datetime.date) -> FixedFacts:
    """Read the scan, the target and the profile from their files, tolerating absence.

    All three are optional: a fresh install has no scan and no library, and the
    dashboard is written to show what it has rather than to require all of it.
    """
    facts = FixedFacts()

    try:
        scans = dexa.load_scans()
        if scans:
            # Newest scan wins. `scan_nearest_to` exists for scoring a past day against
            # the scan that applied then; the dashboard header wants the current one.
            newest_scan = max(scans, key=lambda one: one.scan_date)
            facts.latest_scan = dashboard_json.scan_to_json(newest_scan)
    except FileNotFoundError:
        pass

    try:
        whole_library = library.load_library()
        facts.macro_target = dashboard_json.target_to_json(
            whole_library.target_in_force_on(as_of)
        )
        facts.profile = dashboard_json.profile_to_json(
            whole_library.profile.get("height_cm"),
            # PyYAML parses an unquoted 2003-05-01 into a date object, so this may be
            # a date or a string depending on how the file was written. str() on
            # whichever it is keeps the wire value text either way.
            str(whole_library.profile.get("birth_date") or "") or None,
        )
    except (FileNotFoundError, AttributeError):
        pass

    return facts


def collect_days(
    open_database: open_store.Store,
    first_day: datetime.date,
    last_day: datetime.date,
) -> tuple[list[dict[str, Any]], list[normalize.DailySnapshot]]:
    """Read the span and build one JSON object per day, oldest first.

    Returns the snapshots as well, because the baselines are built from them and it
    would be wasteful to read the span twice.

    Four lookups for the whole range -- snapshots, weigh-ins, food, typed totals --
    rather than four per day. Against SQLite the difference is invisible; against
    DynamoDB it is a hundred network round trips against four, on every page load.

    **A day appears if ANY of the four has something for it**, not only if Garmin does.
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
    manual_by_day = intake_store.load_intakes_between(open_database, first_day, last_day)

    every_day = set(snapshots_by_day) | set(weighings_by_day) | set(entries_by_day)
    every_day = every_day | set(manual_by_day)

    days_in_order = sorted(every_day)

    # The carry-forward rule needs the food log's totals per day, and it needs the whole
    # span at once -- a day inherits from the last day before it that had a figure.
    logged_kilocalories_by_day = {}

    for day, entries in entries_by_day.items():
        logged_kilocalories_by_day[day] = log.total_up(entries).kilocalories

    intake_by_day = intake.resolve_intake_for_span(
        days_in_order,
        manual_by_day,
        logged_kilocalories_by_day,
    )

    days = []
    snapshots_in_order = []

    for day in days_in_order:
        snapshot = snapshots_by_day.get(day)

        if snapshot is None:
            # A day with a weigh-in or a food log but no Garmin data yet. Normalizing an
            # empty set of responses gives a snapshot whose every field is None, which is
            # the honest answer and exactly the shape the dashboard already handles for a
            # missing reading. No special case needed, because every field was built to
            # default to "no reading" in the first place.
            snapshot = normalize.normalize_day({}, day)

        snapshots_in_order.append(snapshot)

        days.append(
            dashboard_json.day_to_json(
                snapshot,
                weighings_by_day.get(day),
                entries_by_day.get(day, []),
                intake_by_day.get(day),
            )
        )

    return (days, snapshots_in_order)


def build_baselines(
    snapshots: list[normalize.DailySnapshot],
    open_database: open_store.Store,
    first_day: datetime.date,
    last_day: datetime.date,
) -> dict[str, Any]:
    """The baselines block: Garmin metrics from the snapshots, weight from the weigh-ins.

    Weight is summarised separately because it does not live in a snapshot, and it uses
    the same end day so all the windows line up.
    """
    ending_on = report.last_day_with_garmin_data(snapshots)

    if ending_on is None:
        # No Garmin data at all in the span. Every summary would be empty, and the
        # dashboard shows "still building" for each.
        return dashboard_json.baselines_to_json({}, None)

    summaries = report.summarise_snapshots(snapshots, ending_on)

    weight_readings: report.Readings = []

    for one_weighing in weight_store.load_weighings_between(open_database, first_day, last_day):
        weight_readings.append((one_weighing.day, one_weighing.kilograms))

    summaries["weight_kilograms"] = report.summarise_readings(
        "weight_kilograms", weight_readings, ending_on
    )

    return dashboard_json.baselines_to_json(summaries, ending_on)


def build_payload(
    open_database: open_store.Store,
    first_day: datetime.date,
    last_day: datetime.date,
    generated_at: datetime.datetime,
    fixed_facts: FixedFacts,
) -> dict[str, Any]:
    """The complete payload for a span.

    `generated_at` and `fixed_facts` are passed in rather than read here, for the same
    reason nothing in the engine reads the clock: a function that asks what time it is,
    or what is on disk, cannot be tested without pretending to be a different machine.
    """
    days, snapshots = collect_days(open_database, first_day, last_day)

    baselines_block = build_baselines(snapshots, open_database, first_day, last_day)

    return dashboard_json.span_to_json(
        days,
        generated_at,
        latest_scan=fixed_facts.latest_scan,
        macro_target=fixed_facts.macro_target,
        profile=fixed_facts.profile,
        baselines_block=baselines_block,
    )
