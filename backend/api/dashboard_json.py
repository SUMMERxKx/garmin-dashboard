"""The wire format: one span of days, exactly as the dashboard receives it.

THE CONTRACT
============

The whole payload is one object:

    {
      "schema_version": 1,
      "generated_at":   "2026-09-15T10:30:00",
      "first_day":      "2026-08-16",
      "last_day":       "2026-09-14",
      "days":           [ ...one entry per day, oldest first... ]
    }

and one day looks like this, with every key always present:

    {
      "day":        "2026-09-14",
      "energy":     { total_kilocalories, active_kilocalories, resting_kilocalories,
                      steps, distance_metres,
                      moderate_intensity_minutes, vigorous_intensity_minutes },
      "sleep":      { total_minutes, score,
                      deep_minutes, light_minutes, rem_minutes, awake_minutes },
      "recovery":   { hrv_last_night, hrv_weekly_average, hrv_baseline,
                      resting_heart_rate,
                      body_battery_charged, body_battery_drained, average_stress },
      "body":       { garmin_weight_kilograms },
      "weight":     { kilograms, recorded_at, source }   or null
      "food":       { totals: {...}, entries: [...] }    or null
      "activities": [ ...one entry per workout, empty on a rest day... ],
      "fields_found": 24
    }

The five rules this format follows
=================================

**1. Missing is `null`, never `0`, and never a dropped key.**
The rule the whole project rests on, carried across the wire. `"hrv_last_night": null`
means the night produced no reading; `0` would mean it was measured as zero, and an
average over the two is a different and wrong number. The key is always present even
when the value is null, so the browser can tell "no reading today" apart from "this
version of the API does not know about that field".

**2. Numbers go over raw, never formatted.**
`"total_minutes": 412.5`, not `"6h 52m"`. A chart needs to do arithmetic on it, and how
a number is *shown* is a decision for the screen showing it -- the same value is an axis
label in one place and a sentence in another. Same reasoning as saving Garmin's raw
responses before anything interprets them.

**3. Every field is written out by hand below, rather than generated from the objects.**
`dataclasses.asdict()` would produce this payload in one line, and that is exactly the
problem: renaming a field inside `normalize.py` would silently rename it in the API and
break the dashboard, with nothing in between to notice. Spelling the contract out means
an internal rename is a local change, and changing the contract is a deliberate edit to
this file.

**4. Dates are ISO 8601 text.**
`"2026-09-14"`, `"2026-09-14T07:12:00"`. Sorts correctly as text, parses in every
language, and is what `datetime.date.isoformat()` already produces.

**5. A day with no food logged sends `null`, not zeroes.**
This differs from the CLI on purpose. There, an empty log for *today* totals zero,
because "I have eaten nothing so far" is a real measurement. Here, a day in the archive
with no entries almost always means the log was not kept that day -- not that nothing
was eaten. Sending zeroes would put 29 days of "0 kcal" on a chart next to one real day
and make the average meaningless. Same for `weight`: null means no weigh-in that
morning, and the dashboard decides how to draw the gap.

Why a schema version
====================
The browser and this file will drift -- one gets deployed without the other eventually.
A version number costs one line now and turns "the dashboard is mysteriously blank" into
a checkable difference.
"""

from __future__ import annotations

import datetime
from typing import Any

from backend.body import weight
from backend.food import log
from backend.garmin import normalize

#: Bumped whenever a key changes meaning or disappears. Adding a new key does not need a
#: bump: a browser that does not know about it simply ignores it.
SCHEMA_VERSION = 1


def date_or_none(value: datetime.date | datetime.datetime | None) -> str | None:
    """ISO text, or null. One helper so no call site below has to remember the rule."""
    if value is None:
        return None

    return value.isoformat()


def energy_to_json(energy: normalize.Energy) -> dict[str, Any]:
    """Calories and movement."""
    return {
        "total_kilocalories": energy.total_kilocalories,
        "active_kilocalories": energy.active_kilocalories,
        "resting_kilocalories": energy.resting_kilocalories,
        "steps": energy.steps,
        "distance_metres": energy.distance_metres,
        "moderate_intensity_minutes": energy.moderate_intensity_minutes,
        "vigorous_intensity_minutes": energy.vigorous_intensity_minutes,
    }


def sleep_to_json(sleep: normalize.Sleep) -> dict[str, Any]:
    """Last night, in minutes. Garmin sends seconds; the conversion already happened."""
    return {
        "total_minutes": sleep.total_minutes,
        "score": sleep.score,
        "deep_minutes": sleep.deep_minutes,
        "light_minutes": sleep.light_minutes,
        "rem_minutes": sleep.rem_minutes,
        "awake_minutes": sleep.awake_minutes,
    }


def recovery_to_json(recovery: normalize.Recovery) -> dict[str, Any]:
    """The signals a recovery picture would be built from, sent as measured."""
    return {
        "hrv_last_night": recovery.hrv_last_night,
        "hrv_weekly_average": recovery.hrv_weekly_average,
        "hrv_baseline": recovery.hrv_baseline,
        "resting_heart_rate": recovery.resting_heart_rate,
        "body_battery_charged": recovery.body_battery_charged,
        "body_battery_drained": recovery.body_battery_drained,
        "average_stress": recovery.average_stress,
    }


def body_to_json(body: normalize.Body) -> dict[str, Any]:
    """Garmin's own weight reading, which is usually null and is never a weigh-in.

    Named `garmin_weight_kilograms` rather than `weight_kilograms` so that nothing on the
    dashboard can confuse it with the morning weigh-in in the `weight` block. They are
    different measurements taken at different times, and mixing them would put a step in
    the trend that nothing in the body actually did.
    """
    return {
        "garmin_weight_kilograms": body.weight_kilograms,
    }


def activity_to_json(activity: normalize.Activity) -> dict[str, Any]:
    """One workout.

    `active_kilocalories` is DERIVED -- Garmin's `calories` is the gross figure and
    includes the resting burn that would have happened anyway. It is a method on the
    object rather than a field for exactly that reason. It is sent anyway, because the
    alternative is every screen recomputing it and eventually one of them getting it
    wrong.
    """
    return {
        "name": activity.name,
        "type_key": activity.type_key,
        "started_at_local": date_or_none(activity.started_at_local),
        "duration_minutes": activity.duration_minutes,
        "distance_metres": activity.distance_metres,
        "total_kilocalories": activity.total_kilocalories,
        "resting_kilocalories": activity.resting_kilocalories,
        "active_kilocalories": activity.active_kilocalories(),
        "average_heart_rate": activity.average_heart_rate,
        "maximum_heart_rate": activity.maximum_heart_rate,
        "steps": activity.steps,
        "aerobic_training_effect": activity.aerobic_training_effect,
        "anaerobic_training_effect": activity.anaerobic_training_effect,
    }


def weighing_to_json(weighing: weight.Weighing | None) -> dict[str, Any] | None:
    """The morning weigh-in, or null if there was not one.

    Null rather than the previous day's figure. Carrying a weight forward here would
    write a measurement that never happened and make it indistinguishable from a real
    one afterwards -- and any later calculation reading this history would count that
    invented day as "no change". Drawing an unbroken line across the gap is a decision
    for the screen, where it is visible and arguable.
    """
    if weighing is None:
        return None

    return {
        "kilograms": weighing.kilograms,
        "recorded_at": date_or_none(weighing.recorded_at),
        "source": weighing.source,
    }


def food_entry_to_json(entry: log.LoggedFood) -> dict[str, Any]:
    """One logged item.

    The macros travel with the entry rather than pointing at the food library, because
    the library is what you believe today and an entry is what you ate then. Correcting
    whey off its label must not silently rewrite every day already logged.
    """
    return {
        "food_id": entry.food_id,
        "food_name": entry.food_name,
        "servings": entry.servings,
        "serving_basis": entry.serving_basis,
        "kilocalories": entry.kilocalories,
        "protein_grams": entry.protein_grams,
        "carbohydrate_grams": entry.carbohydrate_grams,
        "fat_grams": entry.fat_grams,
        "logged_at": date_or_none(entry.logged_at),
        "meal_id": entry.meal_id,
    }


def food_to_json(entries: list[log.LoggedFood]) -> dict[str, Any] | None:
    """The day's food, or null if nothing was logged. See rule 5 in the module docstring."""
    if not entries:
        return None

    totals = log.total_up(entries)

    return {
        "totals": {
            "kilocalories": totals.kilocalories,
            "protein_grams": totals.protein_grams,
            "carbohydrate_grams": totals.carbohydrate_grams,
            "fat_grams": totals.fat_grams,
        },
        "entries": [food_entry_to_json(one_entry) for one_entry in entries],
    }


def day_to_json(
    snapshot: normalize.DailySnapshot,
    weighing: weight.Weighing | None = None,
    food_entries: list[log.LoggedFood] | None = None,
) -> dict[str, Any]:
    """Everything known about one day, in one object.

    Garmin's day, the morning weigh-in and the food log arrive together because that is
    how they are stored -- one lookup by day prefix returns all three. The dashboard
    should not have to make three requests to draw one row.
    """
    if food_entries is None:
        food_entries = []

    return {
        "day": snapshot.day.isoformat(),
        "energy": energy_to_json(snapshot.energy),
        "sleep": sleep_to_json(snapshot.sleep),
        "recovery": recovery_to_json(snapshot.recovery),
        "body": body_to_json(snapshot.body),
        "weight": weighing_to_json(weighing),
        "food": food_to_json(food_entries),
        "activities": [activity_to_json(one) for one in snapshot.activities],
        # How many Garmin fields this day actually has values for. The dashboard can use
        # it to mark a day as thin rather than drawing a gap as though it were a reading.
        "fields_found": snapshot.how_many_fields_found(),
    }


def span_to_json(
    days: list[dict[str, Any]],
    generated_at: datetime.datetime,
) -> dict[str, Any]:
    """Wrap the days in the envelope the dashboard actually fetches.

    `generated_at` is passed in rather than read from the clock, for the same reason
    nothing in the engine reads it: a function that asks what time it is cannot be tested
    without pretending to be a different time.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(),
        "first_day": days[0]["day"] if days else None,
        "last_day": days[-1]["day"] if days else None,
        "days": days,
    }
