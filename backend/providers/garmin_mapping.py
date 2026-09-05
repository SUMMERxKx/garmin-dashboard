"""Turn Garmin's JSON into our own canonical model.

This module is PURE: it has no client, makes no network calls and reads no clock. That
means it can be tested against saved response files, which is exactly how it was built.

Every field path in here was DISCOVERED by running `scripts/garmin_probe.py` against a
real Forerunner 165. That is not a small distinction. The numeric sleep score lives at

    dailySleepDTO.sleepScores.overall.value

three levels down, right next to three similarly-named fields that all contain prose
("sleepScoreFeedback", "sleepScoreInsight", "sleepScorePersonalizedInsight"). No amount
of sensible guessing would have landed on the right one.

Two rules this file follows everywhere:

1. NEVER raise because a field is missing.
   A watch left on the charger is a normal Tuesday. Every lookup returns None, and None
   travels onward meaning "we do not know", which is different from zero.

2. ALWAYS record where a value came from.
   The `provenance` dictionary maps our field name to the source path it came from. That
   turns "which fields did this sync actually fill in?" into something we can measure.
   This matters more than it sounds: two Forerunner 165 endpoints return a successful
   HTTP 200 response whose values are all null. So "the endpoint worked" is NOT the same
   as "the metric is available".
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from typing import Any

from backend.core import models
from backend.providers import base as provider_base

# ---------------------------------------------------------------------------
# Reading a value out of nested JSON
# ---------------------------------------------------------------------------
#
# Garmin's responses nest deeply, so we need a way to say "give me the value at
# dailySleepDTO.sleepScores.overall.value, and if anything along the way is missing,
# just give me None instead of crashing".


def split_path_into_steps(path: str) -> list[str | int]:
    """Turn a text path into a list of steps to follow.

    Examples:
        "totalSteps"                  -> ["totalSteps"]
        "hrvSummary.lastNightAvg"     -> ["hrvSummary", "lastNightAvg"]
        "dateWeightList[0].weight"    -> ["dateWeightList", 0, "weight"]

    A string step means "look up this key in a dictionary".
    An integer step means "take this position from a list".
    """
    steps: list[str | int] = []

    # Paths are separated by dots, so start by splitting on those.
    for piece in path.split("."):
        # A piece might carry a list index on the end, like "dateWeightList[0]".
        # Peel those off one at a time until none are left.
        while "[" in piece:
            name_before_bracket, _, remainder = piece.partition("[")

            if name_before_bracket:
                steps.append(name_before_bracket)

            index_text, _, rest_of_piece = remainder.partition("]")
            steps.append(int(index_text))

            # Keep going in case there was a second index, like "matrix[0][1]".
            piece = rest_of_piece

        # Whatever is left is a plain key name (it can be empty if the piece was
        # nothing but an index, which is why we check).
        if piece:
            steps.append(piece)

    return steps


def read_path(data: Any, path: str) -> Any | None:
    """Follow `path` into `data` and return what is there, or None.

    Returns None if anything at all goes wrong: a missing key, a missing list position,
    or a path that tries to go deeper than the data actually goes. Nothing raises.
    """
    current_value = data

    for step in split_path_into_steps(path):
        # If we have already run out of data, there is nowhere left to go.
        if current_value is None:
            return None

        if isinstance(step, str):
            # We want a dictionary key, so we need a dictionary.
            if not isinstance(current_value, Mapping):
                return None
            current_value = current_value.get(step)

        else:
            # We want a list position, so we need a list. Strings are technically
            # sequences in Python, but indexing into a string here is never what
            # we mean, so they are excluded on purpose.
            if not isinstance(current_value, Sequence):
                return None
            if isinstance(current_value, (str, bytes)):
                return None
            if step >= len(current_value):
                return None
            current_value = current_value[step]

    return current_value


# ---------------------------------------------------------------------------
# Converting raw values into the units we store
# ---------------------------------------------------------------------------
#
# We store SI units everywhere (minutes, metres, kilograms), so anything Garmin sends
# in a different unit gets converted right here at the edge and never again.


def optional_float(value: Any) -> float | None:
    """Convert to a float, or return None if that is not possible.

    Used for values that may legitimately be absent. An unofficial API can also send
    something unexpected (a string like "n/a" has happened), and one odd field should
    cost us that field, not the whole day.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def optional_int(value: Any) -> int | None:
    """Convert to an int, or return None if that is not possible."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def seconds_to_minutes(value: Any) -> float:
    """Garmin reports sleep and workout lengths in seconds; we store minutes."""
    return float(value) / 60.0


def epoch_milliseconds_to_utc(value: Any) -> datetime:
    """Convert a Garmin timestamp into a proper UTC datetime.

    Garmin sends timestamps as "milliseconds since 1 January 1970" -- a 13-digit number.
    Python's fromtimestamp expects seconds, so we divide by 1000 first.

    We deliberately store UTC. Converting to the user's local timezone is the display
    layer's job, which keeps one timezone in the database and avoids the classic bug
    where a late-evening workout lands on the wrong calendar day.
    """
    seconds_since_1970 = float(value) / 1000.0
    return datetime.fromtimestamp(seconds_since_1970, tz=UTC)


def garmin_weight_to_kilograms(value: Any) -> float:
    """Convert a Garmin weigh-in to kilograms.

    Garmin records weigh-ins in grams, so 79.4 kg arrives as 79400.

    The guard below handles both shapes, because this code path has never actually seen
    a real value: weight is entered in our own app, and this reads whatever might have
    been typed into Garmin Connect instead. The test is safe because no person weighs
    more than 500 kg, and no person's weight in grams is less than 500.
    """
    number = float(value)

    if number > 500.0:
        return number / 1000.0

    return number


# ---------------------------------------------------------------------------
# Sorting workouts into our own categories
# ---------------------------------------------------------------------------


def classify_activity(garmin_type_key: str | None) -> models.ActivityKind:
    """Map Garmin's activity type name onto one of our own categories.

    Garmin has hundreds of activity types ("strength_training", "treadmill_running",
    "indoor_cardio", ...). We only care about a handful of groups, so we match on
    keywords rather than trying to list every possible value.

    Resistance training is checked FIRST, on purpose. It is the one category whose
    calorie number we do not trust -- heart rate stays high between sets without the
    matching oxygen cost, so Garmin overestimates it. If a lifting session were
    misclassified, the warning about that would silently disappear from the dashboard.
    """
    if not garmin_type_key:
        return models.ActivityKind.OTHER

    # Compare in lower case so "Strength_Training" and "strength_training" both match.
    name = garmin_type_key.lower()

    if "strength" in name:
        return models.ActivityKind.RESISTANCE
    if "weight_training" in name:
        return models.ActivityKind.RESISTANCE

    if "running" in name:
        return models.ActivityKind.RUNNING
    if "treadmill" in name:
        return models.ActivityKind.RUNNING

    if "walking" in name:
        return models.ActivityKind.WALKING
    if "hiking" in name:
        return models.ActivityKind.WALKING

    if "cycling" in name:
        return models.ActivityKind.CARDIO_OTHER
    if "elliptical" in name:
        return models.ActivityKind.CARDIO_OTHER
    if "rowing" in name:
        return models.ActivityKind.CARDIO_OTHER
    if "swimming" in name:
        return models.ActivityKind.CARDIO_OTHER
    if "hiit" in name:
        return models.ActivityKind.CARDIO_OTHER
    if "cardio" in name:
        return models.ActivityKind.CARDIO_OTHER

    return models.ActivityKind.OTHER


def parse_activity_start_time(value: Any) -> datetime | None:
    """Parse a workout start time, or return None if we cannot.

    Garmin has shipped two formats for these over time:
        "2026-09-02 14:05:00"   (a space in the middle)
        "2026-09-02T14:05:00"   (a T in the middle, the ISO 8601 style)

    We try both. If neither works we return None, so a change in this one field costs
    us the start time and nothing else about the workout.
    """
    if not isinstance(value, str):
        return None

    formats_garmin_has_used = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ]

    for time_format in formats_garmin_has_used:
        try:
            parsed = datetime.strptime(value, time_format)
        except ValueError:
            # Not this format; try the next one.
            continue
        return parsed.replace(tzinfo=UTC)

    return None


# ---------------------------------------------------------------------------
# Pulling fields out, and remembering where each one came from
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSource:
    """One place a value might be found: which endpoint, and which path inside it."""

    endpoint: str
    path: str

    def describe(self) -> str:
        """A short label for the provenance record, e.g. "sleep:dailySleepDTO.avgHeartRate"."""
        return f"{self.endpoint}:{self.path}"


class FieldReader:
    """Reads fields out of the raw responses and records where each one was found.

    Many values are available from more than one endpoint. For example the calorie
    totals appear in both `user_summary` and `stats`. So each field is given a list of
    sources in order of preference, and the first one that actually has a value wins.

    Recording the winner is the point. If `user_summary` stops returning calories and we
    silently fall back to `stats`, the provenance record shows that happened, which is
    how a partially-broken sync becomes visible instead of invisible.
    """

    def __init__(self, raw: provider_base.RawPayloads) -> None:
        self._raw = raw

        # Maps our field name -> the source label it came from.
        # A field that is missing simply does not appear here.
        self.provenance: dict[str, str] = {}

    def take(
        self,
        our_field_name: str,
        sources: list[FieldSource],
        convert: Callable[[Any], Any] | None = None,
    ) -> Any | None:
        """Find a value for `our_field_name`, trying each source in order.

        Returns the converted value from the first source that has one, or None if none
        of them do.
        """
        for source in sources:
            payload = self._raw.get(source.endpoint)
            raw_value = read_path(payload, source.path)

            # This source does not have the field. Try the next one.
            if raw_value is None:
                continue

            if convert is None:
                converted_value = raw_value
            else:
                converted_value = convert(raw_value)

                # The converter rejected the value -- for example a calorie field
                # containing the text "n/a". Treat it as if this source did not have
                # the field at all and keep looking.
                if converted_value is None:
                    continue

            self.provenance[our_field_name] = source.describe()
            return converted_value

        return None


# ---------------------------------------------------------------------------
# Building each part of the snapshot
# ---------------------------------------------------------------------------


def read_energy(reader: FieldReader) -> models.Energy:
    """Calories burned: the number the whole energy-balance feature depends on."""
    total_calories = reader.take(
        "energy.total_kcal",
        [
            FieldSource("user_summary", "totalKilocalories"),
            FieldSource("stats", "totalKilocalories"),
        ],
        convert=optional_float,
    )

    active_calories = reader.take(
        "energy.active_kcal",
        [
            FieldSource("user_summary", "activeKilocalories"),
            FieldSource("stats", "activeKilocalories"),
        ],
        convert=optional_float,
    )

    # Garmin calls the resting portion "bmrKilocalories" (basal metabolic rate).
    resting_calories = reader.take(
        "energy.resting_kcal",
        [
            FieldSource("user_summary", "bmrKilocalories"),
            FieldSource("stats", "bmrKilocalories"),
        ],
        convert=optional_float,
    )

    return models.Energy(
        total_kcal=total_calories,
        active_kcal=active_calories,
        resting_kcal=resting_calories,
    )


def read_one_activity(item: Mapping[str, Any]) -> models.Activity:
    """Turn one workout from Garmin's list into one of our Activity objects."""
    garmin_type_key = read_path(item, "activityType.typeKey")
    activity_id = read_path(item, "activityId")

    # Garmin gives the length in seconds; we store minutes.
    duration_in_seconds = read_path(item, "duration")
    if duration_in_seconds is None:
        duration_in_minutes = None
    else:
        duration_in_minutes = seconds_to_minutes(duration_in_seconds)

    # Prefer the UTC start time. Fall back to the local one, which is better than
    # nothing for ordering workouts within a day.
    start_time_text = read_path(item, "startTimeGMT")
    if start_time_text is None:
        start_time_text = read_path(item, "startTimeLocal")

    return models.Activity(
        provider_id=str(activity_id) if activity_id is not None else "",
        kind=classify_activity(garmin_type_key),
        type_raw=str(garmin_type_key) if garmin_type_key else "unknown",
        start=parse_activity_start_time(start_time_text),
        duration_min=duration_in_minutes,
        calories=optional_float(read_path(item, "calories")),
        avg_hr=optional_float(read_path(item, "averageHR")),
        max_hr=optional_float(read_path(item, "maxHR")),
        # Heart-rate zone splits need a separate call per activity
        # (`get_activity_hr_in_timezones`) which the daily fetch does not make. None
        # here means "not fetched", not "zero". The optional training-load metrics are
        # what would need this.
        zone_seconds=None,
    )


def read_activities(raw: provider_base.RawPayloads) -> list[models.Activity]:
    """Turn Garmin's list of workouts into our Activity objects.

    Skips anything that is not shaped like a workout, rather than crashing, because an
    unofficial API can change shape without warning.
    """
    items = raw.get("activities")

    if items is None:
        return []
    if not isinstance(items, Sequence):
        return []

    activities: list[models.Activity] = []

    for item in items:
        # Defensive: the list should contain objects, but if one entry is a string or
        # a null we skip it and keep the rest of the day's workouts.
        if not isinstance(item, Mapping):
            continue

        activities.append(read_one_activity(item))

    return activities


def calculate_intensity_minutes(
    moderate_minutes: float | None,
    vigorous_minutes: float | None,
) -> float | None:
    """Combine moderate and vigorous minutes the way Garmin does.

    Garmin's own convention is that a vigorous minute counts double toward the weekly
    goal, so 34 moderate + 12 vigorous shows as 34 + 24 = 58.

    Returns None only if both numbers are missing, because zero moderate minutes is a
    real answer while "the watch reported nothing" is not.
    """
    if moderate_minutes is None and vigorous_minutes is None:
        return None

    moderate = moderate_minutes or 0.0
    vigorous = vigorous_minutes or 0.0

    return moderate + (2.0 * vigorous)


def read_activity_metrics(reader: FieldReader, raw: provider_base.RawPayloads) -> models.ActivityMetrics:
    """Steps, distance, intensity minutes and the day's workouts."""
    steps = reader.take(
        "activity.steps",
        [
            FieldSource("user_summary", "totalSteps"),
            FieldSource("stats", "totalSteps"),
        ],
        convert=optional_int,
    )

    step_goal = reader.take(
        "activity.step_goal",
        [FieldSource("user_summary", "dailyStepGoal")],
        convert=optional_int,
    )

    distance_in_metres = reader.take(
        "activity.distance_m",
        [
            FieldSource("user_summary", "totalDistanceMeters"),
            FieldSource("stats", "totalDistanceMeters"),
        ],
        convert=optional_float,
    )

    moderate_minutes = reader.take(
        "activity.moderate_minutes",
        [FieldSource("user_summary", "moderateIntensityMinutes")],
        convert=optional_float,
    )

    vigorous_minutes = reader.take(
        "activity.vigorous_minutes",
        [FieldSource("user_summary", "vigorousIntensityMinutes")],
        convert=optional_float,
    )

    activities = read_activities(raw)

    # Add up the workout time. If there were no workouts we want None ("nothing
    # recorded") rather than 0.0, which would read as "a workout of zero length".
    total_workout_minutes: float | None = None
    if activities:
        minutes_so_far = 0.0
        for activity in activities:
            minutes_so_far += activity.duration_min or 0.0

        if minutes_so_far > 0.0:
            total_workout_minutes = minutes_so_far

    return models.ActivityMetrics(
        steps=steps,
        step_goal=step_goal,
        distance_m=distance_in_metres,
        intensity_minutes=calculate_intensity_minutes(moderate_minutes, vigorous_minutes),
        workout_minutes=total_workout_minutes,
        activities=activities,
    )


def read_heart(reader: FieldReader) -> models.Heart:
    """Resting heart rate and heart-rate variability."""
    resting_heart_rate = reader.take(
        "heart.resting_hr",
        [
            FieldSource("user_summary", "restingHeartRate"),
            FieldSource("stats", "restingHeartRate"),
            FieldSource("sleep", "restingHeartRate"),
        ],
        convert=optional_float,
    )

    # HRV has a dedicated endpoint, but the sleep response also carries an overnight
    # average. Having the fallback means losing the HRV endpoint degrades the Recovery
    # screen instead of blanking it.
    heart_rate_variability = reader.take(
        "heart.hrv_ms",
        [
            FieldSource("hrv", "hrvSummary.lastNightAvg"),
            FieldSource("sleep", "avgOvernightHrv"),
        ],
        convert=optional_float,
    )

    average_heart_rate = reader.take(
        "heart.avg_hr",
        [FieldSource("sleep", "dailySleepDTO.avgHeartRate")],
        convert=optional_float,
    )

    return models.Heart(
        resting_hr=resting_heart_rate,
        hrv_ms=heart_rate_variability,
        avg_hr=average_heart_rate,
        max_hr=None,
    )


def read_sleep(reader: FieldReader) -> models.Sleep:
    """Sleep length, score, stages and the window it happened in.

    All the lengths arrive in seconds and are stored as minutes.
    """
    sleep_dto = "dailySleepDTO"

    total_sleep = reader.take(
        "sleep.duration_min",
        [FieldSource("sleep", f"{sleep_dto}.sleepTimeSeconds")],
        convert=seconds_to_minutes,
    )

    # The numeric score. Note the three fields sitting beside it in the response --
    # sleepScoreFeedback, sleepScoreInsight and sleepScorePersonalizedInsight -- are
    # all text. The probe is what found the real number, nested two levels further in.
    sleep_score = reader.take(
        "sleep.score",
        [FieldSource("sleep", f"{sleep_dto}.sleepScores.overall.value")],
        convert=optional_float,
    )

    sleep_start = reader.take(
        "sleep.start",
        [FieldSource("sleep", f"{sleep_dto}.sleepStartTimestampGMT")],
        convert=epoch_milliseconds_to_utc,
    )

    sleep_end = reader.take(
        "sleep.end",
        [FieldSource("sleep", f"{sleep_dto}.sleepEndTimestampGMT")],
        convert=epoch_milliseconds_to_utc,
    )

    deep_sleep = reader.take(
        "sleep.deep_min",
        [FieldSource("sleep", f"{sleep_dto}.deepSleepSeconds")],
        convert=seconds_to_minutes,
    )

    light_sleep = reader.take(
        "sleep.light_min",
        [FieldSource("sleep", f"{sleep_dto}.lightSleepSeconds")],
        convert=seconds_to_minutes,
    )

    rem_sleep = reader.take(
        "sleep.rem_min",
        [FieldSource("sleep", f"{sleep_dto}.remSleepSeconds")],
        convert=seconds_to_minutes,
    )

    awake_time = reader.take(
        "sleep.awake_min",
        [FieldSource("sleep", f"{sleep_dto}.awakeSleepSeconds")],
        convert=seconds_to_minutes,
    )

    return models.Sleep(
        duration_min=total_sleep,
        score=sleep_score,
        start=sleep_start,
        end=sleep_end,
        deep_min=deep_sleep,
        light_min=light_sleep,
        rem_min=rem_sleep,
        awake_min=awake_time,
    )


def read_recovery(reader: FieldReader) -> models.RecoveryMetrics:
    """Body Battery, stress, respiration and blood oxygen."""
    body_battery_high = reader.take(
        "recovery.body_battery_high",
        [FieldSource("user_summary", "bodyBatteryHighestValue")],
        convert=optional_float,
    )

    body_battery_low = reader.take(
        "recovery.body_battery_low",
        [FieldSource("user_summary", "bodyBatteryLowestValue")],
        convert=optional_float,
    )

    body_battery_current = reader.take(
        "recovery.body_battery_current",
        [FieldSource("user_summary", "bodyBatteryMostRecentValue")],
        convert=optional_float,
    )

    average_stress = reader.take(
        "recovery.stress_avg",
        [FieldSource("user_summary", "averageStressLevel")],
        convert=optional_float,
    )

    average_respiration = reader.take(
        "recovery.respiration_avg",
        [
            FieldSource("user_summary", "avgWakingRespirationValue"),
            FieldSource("sleep", "dailySleepDTO.averageRespirationValue"),
        ],
        convert=optional_float,
    )

    # Confirmed unavailable on the Forerunner 165: the endpoint returns a complete
    # object with every value null. We still ask for it, so that if a future watch or
    # firmware update starts reporting it, we pick it up without a code change.
    blood_oxygen = reader.take(
        "recovery.spo2_avg",
        [
            FieldSource("spo2", "averageSpO2"),
            FieldSource("spo2", "avgSleepSpO2"),
        ],
        convert=optional_float,
    )

    return models.RecoveryMetrics(
        body_battery_high=body_battery_high,
        body_battery_low=body_battery_low,
        body_battery_current=body_battery_current,
        stress_avg=average_stress,
        respiration_avg=average_respiration,
        spo2_avg=blood_oxygen,
    )


def read_fitness(reader: FieldReader) -> models.Fitness:
    """VO2 max.

    Also confirmed unavailable on the Forerunner 165: the max_metrics endpoint returns
    an empty list, and training_status returns an object whose VO2 max field is null.
    Both sources are listed anyway for the same reason as blood oxygen above.
    """
    vo2_max = reader.take(
        "fitness.vo2max",
        [
            FieldSource("max_metrics", "[0].generic.vo2MaxValue"),
            FieldSource("training_status", "mostRecentVO2Max"),
        ],
        convert=optional_float,
    )

    return models.Fitness(vo2max=vo2_max)


def read_body(reader: FieldReader) -> models.BodyMetrics:
    """Weight, if any was recorded in Garmin.

    Weight is normally entered in our own app, so this only picks up anything typed
    into the Garmin Connect app instead. In practice it is empty.
    """
    weight_in_kilograms = reader.take(
        "body.weight_kg",
        [
            FieldSource("daily_weigh_ins", "dateWeightList[0].weight"),
            FieldSource("daily_weigh_ins", "totalAverage.weight"),
        ],
        convert=garmin_weight_to_kilograms,
    )

    return models.BodyMetrics(weight_kg=weight_in_kilograms)


# ---------------------------------------------------------------------------
# The main entry point
# ---------------------------------------------------------------------------


def normalize_day(raw: provider_base.RawPayloads, on: date | None = None) -> models.DailyHealthSnapshot:
    """Turn one day of raw Garmin responses into one canonical snapshot.

    This fills in the `measured` section (what the device reported) and the weight, and
    nothing else. The `derived` section -- our own calculations like recovery status and
    energy balance -- and the `nutrition` section are filled in later by the engine.

    Keeping those separate is what makes the measured/derived split trustworthy: the
    provider layer physically cannot write a calculated value into a field that claims
    to be the device's own reading.
    """
    reader = FieldReader(raw)

    measured = models.MeasuredMetrics(
        energy=read_energy(reader),
        activity=read_activity_metrics(reader, raw),
        heart=read_heart(reader),
        sleep=read_sleep(reader),
        recovery=read_recovery(reader),
        fitness=read_fitness(reader),
        provenance=reader.provenance,
    )

    body = read_body(reader)

    # `on` lets the caller override the date, which the fixture tests use. Normally the
    # date travels with the raw payloads.
    snapshot_date = on if on is not None else raw.on

    return models.DailyHealthSnapshot(date=snapshot_date, measured=measured, body=body)


# ---------------------------------------------------------------------------
# Field coverage: our health check
# ---------------------------------------------------------------------------

# The dashboard is designed so that these fields alone are enough to render it. If one
# of them goes missing, that is a real problem worth alerting on.
#
# Measuring coverage over this list -- rather than watching for HTTP errors -- is the
# whole lesson from Phase 0. Two endpoints return a successful response with no data in
# it, so a monitor that only checks status codes would report everything as fine while
# the Recovery screen sat empty.

TIER_1_FIELDS: tuple[str, ...] = (
    "energy.total_kcal",
    "energy.active_kcal",
    "energy.resting_kcal",
    "activity.steps",
    "sleep.duration_min",
    "sleep.score",
    "heart.hrv_ms",
    "heart.resting_hr",
    "recovery.body_battery_high",
)


def coverage(snapshot: models.DailyHealthSnapshot) -> tuple[list[str], list[str]]:
    """Check which of the essential fields this snapshot actually has.

    Returns two lists: the fields that are present, and the fields that are missing.
    Reporting `len(missing)` as a metric is what makes a silent upstream change visible
    -- coverage drops instead of an error being raised.
    """
    provenance = snapshot.measured.provenance

    present: list[str] = []
    missing: list[str] = []

    for field_name in TIER_1_FIELDS:
        if field_name in provenance:
            present.append(field_name)
        else:
            missing.append(field_name)

    return present, missing
