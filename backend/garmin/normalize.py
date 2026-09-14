"""Turning saved Garmin responses into one tidy shape per day.

The seventeen saved files for a day are Garmin's shapes, not ours. They nest, they
disagree with each other, they use seconds where we want minutes, and they spread
related numbers across several endpoints. This module reads them and produces a single
`DailySnapshot`: a flat, predictable object where `snapshot.sleep.score` is just there.

Nothing here touches the network or the clock. It reads dictionaries that were loaded
from disk and returns an object. That is what makes it testable against the real saved
files, which is exactly how it was written.

Two rules this module follows everywhere
----------------------------------------
1. A missing field is never an error. Every value is optional and None means "we have no
   reading". A watch on the charger is a normal Tuesday.

2. Every value that IS found records where it came from, in `provenance`. That turns
   "which fields did this sync actually fill in?" into something we can measure, which
   matters more than it sounds: some Forerunner 165 endpoints return a perfectly
   successful response whose values are all null. "The endpoint worked" is not the same
   as "the metric is available", so counting fields is the honest health signal.
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any

from backend.garmin import json_paths

#: Garmin records weigh-ins in grams, so 79.4 kg arrives as 79400. Anything above this
#: is therefore grams and gets divided. The threshold is safe because no person weighs
#: more than 500 kg, and nobody's weight in grams is below 500.
GRAMS_THRESHOLD = 500.0

#: How Garmin writes a timestamp: "2026-09-12 15:06:55". Named here rather than buried
#: in the parsing call, because it is a fact about their format, not about our code.
LOCAL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

#: How many seconds in a minute. Named rather than written as a bare 60 in the middle of
#: a calculation, so the conversion says out loud what it is doing.
SECONDS_PER_MINUTE = 60.0


def seconds_to_minutes(seconds: float | None) -> float | None:
    """Convert seconds to minutes, passing None straight through.

    Garmin reports every sleep duration in seconds. We store minutes, because minutes
    are what a person reads on a dashboard. Converting once here, at the edge, means no
    code further in ever has to ask which unit it is holding.
    """
    if seconds is None:
        return None

    return seconds / SECONDS_PER_MINUTE


def to_kilograms(weight_from_garmin: float | None) -> float | None:
    """Convert a Garmin weigh-in to kilograms, whichever unit it arrived in."""
    if weight_from_garmin is None:
        return None

    if weight_from_garmin > GRAMS_THRESHOLD:
        return weight_from_garmin / 1000.0

    return weight_from_garmin


class ValueReader:
    """Reads values out of a day's saved responses, remembering where each came from.

    This exists so that reading a field and recording its source cannot drift apart. If
    they were two separate steps, someone would eventually add a field and forget the
    second one, and the provenance record would quietly become a lie.
    """

    def __init__(self, saved_responses: dict[str, Any]) -> None:
        #: endpoint name -> the response we loaded from disk
        self.saved_responses = saved_responses

        #: our field name -> "endpoint -> path", for every field we actually found
        self.provenance: dict[str, str] = {}

    def read_number(self, field_name: str, endpoint_name: str, path: str) -> float | None:
        """Read one decimal number, recording its source if it was there."""
        response = self.saved_responses.get(endpoint_name)

        value = json_paths.read_float(response, path)

        if value is not None:
            self.provenance[field_name] = f"{endpoint_name} -> {path}"

        return value

    def read_whole_number(self, field_name: str, endpoint_name: str, path: str) -> int | None:
        """Read one whole number, recording its source if it was there."""
        response = self.saved_responses.get(endpoint_name)

        value = json_paths.read_integer(response, path)

        if value is not None:
            self.provenance[field_name] = f"{endpoint_name} -> {path}"

        return value


    def read_text(self, field_name: str, endpoint_name: str, path: str) -> str | None:
        """Read one piece of text, recording its source if it was there."""
        response = self.saved_responses.get(endpoint_name)

        value = json_paths.read_text(response, path)

        if value is not None:
            self.provenance[field_name] = f"{endpoint_name} -> {path}"

        return value


@dataclasses.dataclass
class Energy:
    """Calories in and out, and the movement behind them."""

    total_kilocalories: int | None = None
    active_kilocalories: int | None = None
    resting_kilocalories: int | None = None
    steps: int | None = None
    distance_metres: float | None = None
    moderate_intensity_minutes: int | None = None
    vigorous_intensity_minutes: int | None = None


@dataclasses.dataclass
class Sleep:
    """Last night, in minutes. Garmin sends seconds; we convert on the way in."""

    total_minutes: float | None = None
    score: int | None = None
    deep_minutes: float | None = None
    light_minutes: float | None = None
    rem_minutes: float | None = None
    awake_minutes: float | None = None


@dataclasses.dataclass
class Recovery:
    """The signals the recovery picture is built from."""

    hrv_last_night: float | None = None
    hrv_weekly_average: float | None = None
    hrv_baseline: float | None = None
    resting_heart_rate: int | None = None
    body_battery_charged: int | None = None
    body_battery_drained: int | None = None
    average_stress: int | None = None


@dataclasses.dataclass
class Body:
    """Body measurements. Usually empty: weight is entered in our own app, not Garmin."""

    weight_kilograms: float | None = None


@dataclasses.dataclass
class Activity:
    """One workout, in our shape rather than Garmin's.

    A day has a list of these, and an empty list is the normal case: most days have no
    recorded workout at all. Absence here is a rest day, not a failed sync, which is
    why activities are deliberately left out of the day's field count.

    Garmin sends about ninety fields per activity. Most are either specific to a sport
    we do not do (dive gases, elevation correction), duplicated under two names
    (`favorite` and `isFavorite`), or personal rather than measured -- the owner's full
    name, profile photo URLs, and the device id all travel in that payload. None of
    those are copied here. What is kept is what an energy-balance and recovery picture
    actually needs.
    """

    name: str | None = None
    type_key: str | None = None
    started_at_local: datetime.datetime | None = None
    duration_minutes: float | None = None
    distance_metres: float | None = None
    total_kilocalories: int | None = None
    resting_kilocalories: int | None = None
    average_heart_rate: int | None = None
    maximum_heart_rate: int | None = None
    steps: int | None = None
    aerobic_training_effect: float | None = None
    anaerobic_training_effect: float | None = None

    #: field name -> where the value came from, exactly as on the daily snapshot.
    provenance: dict[str, str] = dataclasses.field(default_factory=dict)

    def active_kilocalories(self) -> int | None:
        """DERIVED, not measured: the calories above what resting would have cost.

        Garmin reports `calories` for a workout as the gross figure -- everything the
        body spent during that window, including the resting burn that would have
        happened on the sofa anyway. `bmrCalories` is that resting portion. The
        difference is the part the workout is actually responsible for.

        It is a method rather than a field on purpose. A field would sit in the same
        list as the measured numbers and, a month from now, read exactly like one of
        them. This is ours, computed from two of Garmin's, and the shape of the code
        should say so without needing a comment at every use site.
        """
        if self.total_kilocalories is None:
            return None

        if self.resting_kilocalories is None:
            return None

        return self.total_kilocalories - self.resting_kilocalories


@dataclasses.dataclass
class DailySnapshot:
    """One day, in our shape rather than Garmin's."""

    day: datetime.date
    energy: Energy
    sleep: Sleep
    recovery: Recovery
    body: Body

    #: Every workout recorded on this day, oldest first. Empty on a rest day.
    activities: list[Activity] = dataclasses.field(default_factory=list)

    #: field name -> where the value came from, for every field that was found.
    provenance: dict[str, str] = dataclasses.field(default_factory=dict)

    def field_names_found(self) -> list[str]:
        """Every field we managed to fill in for this day."""
        return sorted(self.provenance.keys())

    def how_many_fields_found(self) -> int:
        """How many fields this day actually has values for.

        This is the number worth watching over time. A day that suddenly drops from
        twenty fields to four is a broken sync, even though every endpoint returned a
        perfectly successful response.

        Activities are deliberately not counted. They come and go with whether there
        was a workout, so including them would make the number move for an ordinary
        reason and destroy its value as an alarm: a rest day would look like a fault.
        The fields counted here are the ones the watch reports every single day.
        """
        return len(self.provenance)


def read_energy(reader: ValueReader) -> Energy:
    """Pull the energy numbers out of the `user_summary` response.

    `stats` carries most of these too, and the two occasionally disagree. We read
    `user_summary` because that is the one the Garmin Connect app itself displays, so
    our numbers match what you see on your phone.
    """
    return Energy(
        total_kilocalories=reader.read_whole_number(
            "total_kilocalories", "user_summary", "totalKilocalories"
        ),
        active_kilocalories=reader.read_whole_number(
            "active_kilocalories", "user_summary", "activeKilocalories"
        ),
        resting_kilocalories=reader.read_whole_number(
            "resting_kilocalories", "user_summary", "bmrKilocalories"
        ),
        steps=reader.read_whole_number("steps", "user_summary", "totalSteps"),
        distance_metres=reader.read_number(
            "distance_metres", "user_summary", "totalDistanceMeters"
        ),
        moderate_intensity_minutes=reader.read_whole_number(
            "moderate_intensity_minutes", "user_summary", "moderateIntensityMinutes"
        ),
        vigorous_intensity_minutes=reader.read_whole_number(
            "vigorous_intensity_minutes", "user_summary", "vigorousIntensityMinutes"
        ),
    )


def read_sleep(reader: ValueReader) -> Sleep:
    """Pull last night's sleep out of the `sleep` response.

    Note where the score comes from: `dailySleepDTO.sleepScores.overall.value`. Sitting
    immediately beside it are `sleepScoreFeedback`, `sleepScoreInsight` and
    `sleepScorePersonalizedInsight`, which all contain prose like "FAIR". Any sensible
    guess lands on a word instead of a number. This path came from the probe, not from
    guessing, and it is the clearest single argument for having run one.
    """
    return Sleep(
        total_minutes=seconds_to_minutes(
            reader.read_number("sleep_total", "sleep", "dailySleepDTO.sleepTimeSeconds")
        ),
        score=reader.read_whole_number(
            "sleep_score", "sleep", "dailySleepDTO.sleepScores.overall.value"
        ),
        deep_minutes=seconds_to_minutes(
            reader.read_number("sleep_deep", "sleep", "dailySleepDTO.deepSleepSeconds")
        ),
        light_minutes=seconds_to_minutes(
            reader.read_number("sleep_light", "sleep", "dailySleepDTO.lightSleepSeconds")
        ),
        rem_minutes=seconds_to_minutes(
            reader.read_number("sleep_rem", "sleep", "dailySleepDTO.remSleepSeconds")
        ),
        awake_minutes=seconds_to_minutes(
            reader.read_number("sleep_awake", "sleep", "dailySleepDTO.awakeSleepSeconds")
        ),
    )


def read_recovery(reader: ValueReader) -> Recovery:
    """Pull the recovery signals together from two different endpoints.

    HRV comes from the `hrv` endpoint and everything else from `user_summary`. That
    split is Garmin's, not ours, and gathering them into one object here is a large part
    of what this module is for.
    """
    return Recovery(
        hrv_last_night=reader.read_number("hrv_last_night", "hrv", "hrvSummary.lastNightAvg"),
        hrv_weekly_average=reader.read_number("hrv_weekly", "hrv", "hrvSummary.weeklyAvg"),
        hrv_baseline=reader.read_number(
            "hrv_baseline", "hrv", "hrvSummary.baseline.balancedLow"
        ),
        resting_heart_rate=reader.read_whole_number(
            "resting_heart_rate", "user_summary", "restingHeartRate"
        ),
        body_battery_charged=reader.read_whole_number(
            "body_battery_charged", "user_summary", "bodyBatteryChargedValue"
        ),
        body_battery_drained=reader.read_whole_number(
            "body_battery_drained", "user_summary", "bodyBatteryDrainedValue"
        ),
        average_stress=reader.read_whole_number(
            "average_stress", "user_summary", "averageStressLevel"
        ),
    )


def read_body(reader: ValueReader) -> Body:
    """Pull a weigh-in out of `daily_weigh_ins`, if one was typed into Garmin Connect.

    This is usually empty, and that is expected rather than a fault: there is no smart
    scale, and weight is entered in our own app. It is read anyway so that a weight
    typed into Garmin on a whim is not silently lost.
    """
    return Body(
        weight_kilograms=to_kilograms(
            reader.read_number("weight", "daily_weigh_ins", "dateWeightList[0].weight")
        )
    )


def parse_local_start_time(start_time_text: str | None) -> datetime.datetime | None:
    """Turn Garmin's "2026-09-12 15:06:55" into a datetime, or None.

    Garmin sends two start times for every activity: `startTimeGMT` and
    `startTimeLocal`. We read the local one, because the question a person asks of a
    workout is "was that the morning session or the evening one?", and in GMT a
    Vancouver evening run lands on the following day.

    Neither string carries a timezone, so what comes back is a naive datetime -- a wall
    clock reading with no offset attached. That is honest about what Garmin gave us.
    Attaching a timezone here would mean inventing one.
    """
    if start_time_text is None:
        return None

    try:
        return datetime.datetime.strptime(start_time_text, LOCAL_TIME_FORMAT)
    except ValueError:
        # An unparseable timestamp is a missing reading, not a reason to lose the whole
        # activity. The calories and heart rate beside it are still perfectly good.
        return None


def read_one_activity(one_activity: dict[str, Any], position_in_list: int) -> Activity:
    """Turn one entry from the `activities` response into an Activity.

    `position_in_list` is only used to write a provenance line that points at the right
    entry, so a surprising number can be traced back to the exact activity it came from
    rather than to "somewhere in the list".
    """
    # The same ValueReader as the daily fields, pointed at one activity. Reusing it
    # keeps the rule that reading a value and recording its source are one step.
    reader = ValueReader({f"activities[{position_in_list}]": one_activity})
    source = f"activities[{position_in_list}]"

    return Activity(
        name=reader.read_text("name", source, "activityName"),
        # `activityType.typeKey`, not `activityName`: the name is free text the user can
        # edit to anything, while the type key is Garmin's own vocabulary and is what
        # any later rule about lifting versus running has to be built on.
        type_key=reader.read_text("type_key", source, "activityType.typeKey"),
        started_at_local=parse_local_start_time(
            reader.read_text("started_at_local", source, "startTimeLocal")
        ),
        duration_minutes=seconds_to_minutes(
            reader.read_number("duration_minutes", source, "duration")
        ),
        distance_metres=reader.read_number("distance_metres", source, "distance"),
        total_kilocalories=reader.read_whole_number(
            "total_kilocalories", source, "calories"
        ),
        resting_kilocalories=reader.read_whole_number(
            "resting_kilocalories", source, "bmrCalories"
        ),
        average_heart_rate=reader.read_whole_number("average_heart_rate", source, "averageHR"),
        maximum_heart_rate=reader.read_whole_number("maximum_heart_rate", source, "maxHR"),
        steps=reader.read_whole_number("steps", source, "steps"),
        aerobic_training_effect=reader.read_number(
            "aerobic_training_effect", source, "aerobicTrainingEffect"
        ),
        anaerobic_training_effect=reader.read_number(
            "anaerobic_training_effect", source, "anaerobicTrainingEffect"
        ),
        provenance=reader.provenance,
    )


def read_activities(saved_responses: dict[str, Any]) -> list[Activity]:
    """Read every workout recorded on this day, earliest first.

    The `activities` endpoint answers with a list rather than an object, and on most
    days that list is empty. An empty list here means "no workout", which is a fact
    about the day rather than a gap in the data.
    """
    response = saved_responses.get("activities")

    if not isinstance(response, list):
        # Either the endpoint was never fetched, or it answered with something that is
        # not a list. Both mean we have no activities to report.
        return []

    activities = []

    for position_in_list, one_activity in enumerate(response):
        if not isinstance(one_activity, dict):
            continue

        activities.append(read_one_activity(one_activity, position_in_list))

    return sort_by_start_time(activities)


def sort_by_start_time(activities: list[Activity]) -> list[Activity]:
    """Put the earliest workout first, with any undated ones at the end.

    Sorting cannot simply compare the start times, because one of them may be None and
    Python refuses to compare None with a datetime. Rather than dropping those, they
    are pushed to the end, where an activity we know less about belongs.
    """
    with_a_time = []
    without_a_time = []

    for one_activity in activities:
        if one_activity.started_at_local is None:
            without_a_time.append(one_activity)
        else:
            with_a_time.append(one_activity)

    with_a_time.sort(key=lambda one_activity: one_activity.started_at_local)

    return with_a_time + without_a_time


def normalize_day(
    saved_responses: dict[str, Any],
    day: datetime.date,
) -> DailySnapshot:
    """Turn one day's saved responses into a single snapshot.

    `saved_responses` is what `raw_files.load_whole_day()` gives back: endpoint name ->
    the response that was saved. Reading from disk rather than from the network is what
    makes this re-runnable over history whenever the mapping improves.
    """
    reader = ValueReader(saved_responses)

    # Order matters only in that every read must happen before the provenance is taken,
    # because each read is what adds to it.
    energy = read_energy(reader)
    sleep = read_sleep(reader)
    recovery = read_recovery(reader)
    body = read_body(reader)

    # Read separately, with their own readers, so that a day's workouts never land in
    # the daily provenance and move the field count about.
    activities = read_activities(saved_responses)

    return DailySnapshot(
        day=day,
        energy=energy,
        sleep=sleep,
        recovery=recovery,
        body=body,
        activities=activities,
        provenance=reader.provenance,
    )
