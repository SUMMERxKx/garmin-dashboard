"""The `today` command: one day, laid out for a person to read.

Reads only from disk. Fetching and displaying are separate commands on purpose, so
printing a day is instant, works on a plane, and cannot be blamed on a Garmin outage.
When the way a field is read improves, this shows the corrected history immediately,
because the original responses are still sitting in `fixtures/raw/`.
"""

from __future__ import annotations

import dataclasses
import datetime

from backend.body import weight
from backend.cli import days
from backend.cli import formatting
from backend.food import library
from backend.food import log
from backend.garmin import normalize
from backend.garmin import raw_files
from backend.store import food_store
from backend.store import open_store
from backend.store import weight_store

#: The narrowest the INTAKE label column is allowed to get, so a day with two short
#: entries still lines up with the sections above and below it.
INTAKE_LABEL_WIDTH = 34



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

def print_energy(energy: normalize.Energy) -> None:
    """Print the calories-and-movement section."""
    formatting.print_heading("ENERGY")

    formatting.print_line("total burned", formatting.show_number(energy.total_kilocalories, "kcal"))
    formatting.print_line("active", formatting.show_number(energy.active_kilocalories, "kcal"))
    formatting.print_line("resting", formatting.show_number(energy.resting_kilocalories, "kcal"))
    formatting.print_line("steps", formatting.show_number(energy.steps))

    # `formatting.to_kilometres` passes a missing distance through as None, and `formatting.show_number`
    # turns that into `--`, so there is no missing-value case to handle here.
    kilometres = formatting.to_kilometres(energy.distance_metres)
    formatting.print_line("distance", formatting.show_number(kilometres, "km", decimal_places=1))

    # The two intensity figures mean nothing apart, so they are printed as one row.
    moderate = formatting.show_number(energy.moderate_intensity_minutes)
    vigorous = formatting.show_number(energy.vigorous_intensity_minutes)
    formatting.print_line("intensity minutes", f"{moderate} moderate / {vigorous} vigorous")

def print_one_activity(activity: normalize.Activity) -> None:
    """Print one workout."""
    if activity.started_at_local is None:
        started = formatting.NOTHING_TO_SHOW
    else:
        started = activity.started_at_local.strftime("%H:%M")

    # The name is free text the user can edit; the type key is Garmin's own vocabulary.
    # Printing both means a renamed activity is still identifiable.
    name = activity.name or formatting.NOTHING_TO_SHOW
    type_key = activity.type_key or formatting.NOTHING_TO_SHOW

    print()
    print(f"  {started}  {name}  ({type_key})")

    # Every label in this function starts with two extra spaces, which indents these
    # rows under the workout's own title line printed just above. On a day with two
    # workouts that indent is what keeps them from reading as one long block.
    formatting.print_line("  duration", formatting.show_duration(activity.duration_minutes))

    if activity.distance_metres is None or activity.distance_metres <= 0:
        # A lifting session covers no ground. Saying so beats printing "0.0 km".
        formatting.print_line("  distance", formatting.NOTHING_TO_SHOW)
    else:
        kilometres = formatting.to_kilometres(activity.distance_metres)
        formatting.print_line("  distance", formatting.show_number(kilometres, "km", decimal_places=2))
        formatting.print_line("  pace", formatting.show_pace(activity.duration_minutes, activity.distance_metres))

    # The active figure is ours, subtracted from two of Garmin's, so it is labelled.
    # The gross number is printed beside it rather than instead of it, because that is
    # the one the Garmin Connect app shows and the two must be reconcilable by eye.
    active = formatting.show_number(activity.active_kilocalories(), "kcal")
    gross = formatting.show_number(activity.total_kilocalories, "kcal")
    formatting.print_line("  calories (active)", f"{active}   [{gross} gross, ours = gross - resting]")

    average = formatting.show_number(activity.average_heart_rate, "bpm")
    maximum = formatting.show_number(activity.maximum_heart_rate, "bpm")
    formatting.print_line("  heart rate", f"{average} average / {maximum} max")

    aerobic = formatting.show_number(activity.aerobic_training_effect, decimal_places=1)
    anaerobic = formatting.show_number(activity.anaerobic_training_effect, decimal_places=1)
    formatting.print_line("  training effect", f"{aerobic} aerobic / {anaerobic} anaerobic")

def print_activities(activities: list[normalize.Activity]) -> None:
    """Print every workout on this day, or say plainly that there was not one."""
    formatting.print_heading("ACTIVITIES")

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


#: How far back to look for a previous weigh-in when sanity-checking a new one. Six
#: weeks is long enough to find one after a holiday, and short enough that the
#: comparison is still meaningful.
WEIGH_IN_LOOKBACK_DAYS = 42

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
    formatting.print_heading("INTAKE")

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

        formatting.print_line(description, macros, label_width=column_width)

    totals = log.total_up(entries)

    print()
    formatting.print_line(
        f"total ({totals.number_of_entries} items)",
        f"{totals.kilocalories:.0f} kcal"
        f"  {totals.protein_grams:.0f} P"
        f"  {totals.carbohydrate_grams:.0f} C"
        f"  {totals.fat_grams:.0f} F",
        label_width=column_width,
    )

    if target is None:
        return

    formatting.print_line(
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
    formatting.print_line(
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
    formatting.print_heading("ENERGY BALANCE")

    if not entries:
        print("  nothing logged, so there is nothing to compare")
        return

    if energy.total_kilocalories is None:
        print("  no Garmin expenditure for this day, so there is nothing to compare")
        return

    eaten = log.total_up(entries).kilocalories
    burned = float(energy.total_kilocalories)
    balance = eaten - burned

    formatting.print_line("eaten", f"{eaten:.0f} kcal")
    formatting.print_line("burned (Garmin)", f"{burned:.0f} kcal")

    if balance < 0:
        formatting.print_line("balance", f"{balance:+.0f} kcal   deficit")
    else:
        formatting.print_line("balance", f"{balance:+.0f} kcal   surplus")

def print_sleep(sleep: normalize.Sleep) -> None:
    """Print last night."""
    formatting.print_heading("SLEEP")

    formatting.print_line("slept", formatting.show_duration(sleep.total_minutes))

    if sleep.score is None:
        score = formatting.NOTHING_TO_SHOW
    else:
        # Out of 100, said out loud, because a bare "71" invites the question.
        score = f"{sleep.score} / 100"

    formatting.print_line("score", score)

    formatting.print_line("deep", formatting.show_duration(sleep.deep_minutes))
    formatting.print_line("light", formatting.show_duration(sleep.light_minutes))
    formatting.print_line("rem", formatting.show_duration(sleep.rem_minutes))
    formatting.print_line("awake", formatting.show_duration(sleep.awake_minutes))

def print_recovery(recovery: normalize.Recovery) -> None:
    """Print the recovery signals.

    HRV is printed next to its own weekly average and baseline, and that layout is the
    point of the section rather than a decoration. `HRV 96` on its own says nothing at
    all: the same 96 is reassuring for one person and alarming for another. It only
    becomes information beside the number that is normal for YOU.
    """
    formatting.print_heading("RECOVERY")

    hrv_tonight = formatting.show_number(recovery.hrv_last_night, "ms", decimal_places=0)
    hrv_weekly = formatting.show_number(recovery.hrv_weekly_average, "ms", decimal_places=0)
    hrv_baseline = formatting.show_number(recovery.hrv_baseline, "ms", decimal_places=0)

    formatting.print_line("HRV last night", hrv_tonight)
    formatting.print_line("   vs 7-day average", hrv_weekly)
    formatting.print_line("   vs baseline", hrv_baseline)

    formatting.print_line("resting heart rate", formatting.show_number(recovery.resting_heart_rate, "bpm"))

    # The + and - signs are attached here rather than inside the format string, so that
    # a missing reading prints as a plain `--` instead of a nonsense `+--`.
    charged = formatting.show_signed_number(recovery.body_battery_charged, "+")
    drained = formatting.show_signed_number(recovery.body_battery_drained, "-")
    formatting.print_line("body battery", f"{charged} charged / {drained} drained")

    formatting.print_line("average stress", formatting.show_number(recovery.average_stress))

def print_body(body: normalize.Body, recorded: weight.Weighing | None) -> None:
    """Print the weigh-in for this day.

    A weigh-in is a MANUAL entry, every morning, and nothing else counts as one. Garmin
    will occasionally hand back a weight -- someone typed one into Connect once, or a
    scan total got entered there -- and this deliberately ignores it. Two reasons:

    1. It is not the same measurement. A morning weigh-in is taken at a consistent time,
       before eating, which is what makes a run of them comparable. A number that turned
       up in Connect at some unknown hour is not comparable with those, and mixing the
       two would put a step in the trend that nothing in the body actually did.
    2. It would hide a missed morning. If Garmin quietly filled the gap, a day you forgot
       to weigh would look like a day you weighed -- and the gap is worth seeing.

    The row is always printed, even when empty, because an empty slot is a prompt.
    Garmin's number is still read and still stored in the snapshot; it is simply not
    treated as a weigh-in. Where it went is visible under `today --provenance`.
    """
    formatting.print_heading("BODY")

    if recorded is None:
        formatting.print_line("weight", formatting.NOTHING_TO_SHOW)
        formatting.print_line("", "not weighed yet -- `weigh 80.0` records it")
        return

    formatting.print_line("weight", formatting.show_number(recorded.kilograms, "kg", decimal_places=1))

    recorded_time = recorded.recorded_at.strftime("%H:%M")
    formatting.print_line("  recorded at", recorded_time)

def print_provenance(snapshot: normalize.DailySnapshot) -> None:
    """Print where every filled-in field actually came from.

    This is the answer to "are you sure that number means what you think it means?".
    It is behind a flag because it is a debugging view, not a daily one.
    """
    formatting.print_heading("WHERE EACH VALUE CAME FROM")

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
        formatting.print_line(field_name, snapshot.provenance[field_name], label_width=column_width)

    # Each activity keeps its own provenance, because the daily one deliberately does
    # not carry them. Listed under its own heading so the source of a workout number is
    # traceable in exactly the same way.
    for one_activity in snapshot.activities:
        print()
        print(f"  {one_activity.name or formatting.NOTHING_TO_SHOW}:")

        for field_name in sorted(one_activity.provenance):
            formatting.print_line(
                field_name,
                one_activity.provenance[field_name],
                label_width=column_width,
            )

def print_snapshot(
    snapshot: normalize.DailySnapshot,
    show_provenance: bool,
    entries: list[log.LoggedFood],
    target: library.MacroTarget | None,
    recorded_weight: weight.Weighing | None,
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
    print_body(snapshot.body, recorded_weight)

    if show_provenance:
        print_provenance(snapshot)

    print()

def explain_that_the_day_is_missing(day: datetime.date) -> None:
    """Say why there is nothing to print, and what to do about it."""
    print()
    print(f"No saved data for {day.isoformat()}.")
    print()
    print("Fetch it first:")
    print(f"    .venv/bin/python -m backend.garmin.run_fetch --date {day.isoformat()}")

    days_available = days.days_we_have_saved()

    if days_available:
        print()
        print("Days already saved:")
        for one_day in days_available:
            print(f"    {one_day.isoformat()}")

    print()

def run_today(date_text: str | None, show_provenance: bool) -> int:
    """The `today` command: print one day, or explain why there is nothing to print.

    The Garmin side comes off the disk and the typed-in side out of the database. Two
    different stores, because they hold two different kinds of fact: one is an
    observation we were handed, the other is something you entered by hand.
    """
    try:
        day = days.work_out_which_day_to_show(date_text)
    except ValueError:
        print(f"'{date_text}' is not a date. Use the form 2026-09-12.")
        return 1

    # Reads from disk only. `load_whole_day` hands back an empty dictionary rather than
    # raising when the folder is not there, so a missing day is handled here as the
    # ordinary situation it is.
    saved_responses = raw_files.load_whole_day(day)

    # The Garmin side comes off the disk; the food side comes out of the database.
    # Two different stores because they are two different kinds of fact: one is an
    # observation we were handed, the other is something you typed.
    open_database = open_store.open_store()
    entries = food_store.load_entries_for_day(open_database, day)
    recorded_weight = weight_store.load_weighing(open_database, day)
    open_database.close()

    # Only give up when there is nothing at all -- no Garmin data, no food, no weigh-in.
    # Today is the ordinary case here: you have weighed yourself and logged breakfast,
    # and Garmin has nothing yet because the day is not over and the watch has not been
    # fetched. Refusing to show what you just typed, because the OTHER part of the day is
    # missing, would be exactly backwards.
    if not saved_responses and not entries and recorded_weight is None:
        explain_that_the_day_is_missing(day)
        return 1

    snapshot = normalize.normalize_day(saved_responses, day)

    if not saved_responses:
        print()
        # Deliberately vague about WHICH of the two it is showing, because it may be
        # the food, the weigh-in, or both, and listing them here would go stale the next
        # time something else becomes part of a day.
        print(f"  (no Garmin data for {day.isoformat()} yet"
              f" -- showing what has been recorded here)")

    whole_library = library.load_library()
    target = whole_library.target_in_force_on(day)

    print_snapshot(
        snapshot,
        show_provenance=show_provenance,
        entries=entries,
        target=target,
        recorded_weight=recorded_weight,
    )

    return 0
