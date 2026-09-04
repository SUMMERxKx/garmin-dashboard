"""Garmin JSON -> canonical model.

PURE. No client, no network, no clock -- so it tests against saved fixtures.

Every path here was DISCOVERED by `scripts/garmin_probe.py` against a real Forerunner
165, not guessed. That distinction is the whole reason Phase 0 exists: the numeric sleep
score lives at `dailySleepDTO.sleepScores.overall.value`, three levels down and next to
three same-named string fields, and no amount of reasoning would have found it.

Two rules the extraction obeys:

  1. **Never raise on a missing field.** A watch left on the charger is a normal Tuesday.
     Every lookup returns None, and None propagates as "unknown" rather than zero.
  2. **Record where every value came from.** `provenance` maps canonical field -> source
     path, so "which fields did this sync actually populate" becomes a metric. This is
     load-bearing: two FR165 endpoints return HTTP 200 with fully null bodies, so
     endpoint success is NOT metric availability.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from backend.core.models import (
    Activity,
    ActivityKind,
    ActivityMetrics,
    BodyMetrics,
    DailyHealthSnapshot,
    Energy,
    Fitness,
    Heart,
    MeasuredMetrics,
    RecoveryMetrics,
    Sleep,
)
from backend.providers.base import RawPayloads

_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def dig(obj: Any, path: str) -> Any | None:
    """Safe dotted-path lookup with list indices: `dailySleepDTO.sleepScores.overall.value`
    or `dateWeightList[0].weight`. Returns None for any missing or wrongly-typed link."""
    current = obj
    for name, index in _TOKEN.findall(path):
        if current is None:
            return None
        if name:
            if not isinstance(current, Mapping):
                return None
            current = current.get(name)
        else:
            if not isinstance(current, Sequence) or isinstance(current, (str, bytes)):
                return None
            position = int(index)
            current = current[position] if position < len(current) else None
    return current


# --- transforms -------------------------------------------------------------


def seconds_to_minutes(value: Any) -> float:
    return float(value) / 60.0


def epoch_ms_to_utc(value: Any) -> datetime:
    """Garmin sends 13-digit epoch milliseconds. Store UTC; the presentation layer
    applies the profile timezone."""
    return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)


def garmin_weight_to_kg(value: Any) -> float:
    """Garmin records weigh-ins in grams.

    The guard covers both shapes, because this path is secondary -- weight is entered in
    our own app -- and has never been exercised against a real value: no human weighs
    more than 500 kg, and no person's weight in grams is under 500.
    """
    numeric = float(value)
    return numeric / 1000.0 if numeric > 500.0 else numeric


# --- activity classification ------------------------------------------------

#: Ordered; first substring match wins. RESISTANCE must be tested first -- it is the
#: kind whose calorie estimate we distrust (energy.py), so a misclassification there
#: silently removes the caveat from the dashboard.
_KIND_RULES: tuple[tuple[str, ActivityKind], ...] = (
    ("strength", ActivityKind.RESISTANCE),
    ("weight_training", ActivityKind.RESISTANCE),
    ("running", ActivityKind.RUNNING),
    ("treadmill", ActivityKind.RUNNING),
    ("walking", ActivityKind.WALKING),
    ("hiking", ActivityKind.WALKING),
    ("cycling", ActivityKind.CARDIO_OTHER),
    ("elliptical", ActivityKind.CARDIO_OTHER),
    ("rowing", ActivityKind.CARDIO_OTHER),
    ("swimming", ActivityKind.CARDIO_OTHER),
    ("hiit", ActivityKind.CARDIO_OTHER),
    ("cardio", ActivityKind.CARDIO_OTHER),
)


def classify_activity(type_key: str | None) -> ActivityKind:
    if not type_key:
        return ActivityKind.OTHER
    lowered = type_key.lower()
    for fragment, kind in _KIND_RULES:
        if fragment in lowered:
            return kind
    return ActivityKind.OTHER


def _parse_activity_start(value: Any) -> datetime | None:
    """Garmin sends 'YYYY-MM-DD HH:MM:SS'. The GMT variant is preferred by the caller."""
    if not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


# --- extraction -------------------------------------------------------------


class _Extractor:
    """Pulls fields and records where each one came from.

    `take` accepts sources in priority order as "endpoint:path". The first source that
    yields a non-None value wins and is recorded; if a transform rejects the value, the
    provenance entry is withdrawn and the next source is tried.
    """

    def __init__(self, raw: RawPayloads) -> None:
        self._raw = raw
        self.provenance: dict[str, str] = {}

    def take(
        self,
        field: str,
        *sources: str,
        transform: Callable[[Any], Any] | None = None,
    ) -> Any | None:
        for source in sources:
            endpoint, _, path = source.partition(":")
            value = dig(self._raw.get(endpoint), path)
            if value is None:
                continue
            try:
                converted = transform(value) if transform else value
            except (TypeError, ValueError):
                continue
            self.provenance[field] = source
            return converted
        return None


def _energy(f: _Extractor) -> Energy:
    return Energy(
        total_kcal=f.take("energy.total_kcal", "user_summary:totalKilocalories", "stats:totalKilocalories", transform=float),
        active_kcal=f.take("energy.active_kcal", "user_summary:activeKilocalories", "stats:activeKilocalories", transform=float),
        resting_kcal=f.take("energy.resting_kcal", "user_summary:bmrKilocalories", "stats:bmrKilocalories", transform=float),
    )


def _activity_metrics(f: _Extractor, raw: RawPayloads) -> ActivityMetrics:
    moderate = f.take("activity.moderate_minutes", "user_summary:moderateIntensityMinutes", transform=float)
    vigorous = f.take("activity.vigorous_minutes", "user_summary:vigorousIntensityMinutes", transform=float)
    intensity = None
    if moderate is not None or vigorous is not None:
        # Garmin's own convention: vigorous minutes count double toward the weekly goal.
        intensity = (moderate or 0.0) + 2.0 * (vigorous or 0.0)

    activities = _activities(raw)
    workout_minutes = sum(a.duration_min or 0.0 for a in activities) or None

    return ActivityMetrics(
        steps=f.take("activity.steps", "user_summary:totalSteps", "stats:totalSteps", transform=int),
        step_goal=f.take("activity.step_goal", "user_summary:dailyStepGoal", transform=int),
        distance_m=f.take("activity.distance_m", "user_summary:totalDistanceMeters", "stats:totalDistanceMeters", transform=float),
        intensity_minutes=intensity,
        workout_minutes=workout_minutes,
        activities=activities,
    )


def _activities(raw: RawPayloads) -> list[Activity]:
    """One Activity per workout.

    `zone_seconds` stays None: HR-zone splits need a per-activity call
    (`get_activity_hr_in_timezones`) that the day fetch does not make. The field exists
    because the optional training-load metrics would need it.
    """
    items = raw.get("activities") or []
    if not isinstance(items, Sequence):
        return []
    out: list[Activity] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        type_key = dig(item, "activityType.typeKey")
        duration_s = dig(item, "duration")
        provider_id = dig(item, "activityId")
        out.append(
            Activity(
                provider_id=str(provider_id) if provider_id is not None else "",
                kind=classify_activity(type_key),
                type_raw=str(type_key) if type_key else "unknown",
                start=_parse_activity_start(dig(item, "startTimeGMT") or dig(item, "startTimeLocal")),
                duration_min=seconds_to_minutes(duration_s) if duration_s is not None else None,
                calories=float(dig(item, "calories")) if dig(item, "calories") is not None else None,
                avg_hr=float(dig(item, "averageHR")) if dig(item, "averageHR") is not None else None,
                max_hr=float(dig(item, "maxHR")) if dig(item, "maxHR") is not None else None,
                zone_seconds=None,
            )
        )
    return out


def _heart(f: _Extractor) -> Heart:
    return Heart(
        resting_hr=f.take(
            "heart.resting_hr",
            "user_summary:restingHeartRate", "stats:restingHeartRate", "sleep:restingHeartRate",
            transform=float,
        ),
        hrv_ms=f.take(
            "heart.hrv_ms",
            "hrv:hrvSummary.lastNightAvg", "sleep:avgOvernightHrv",
            transform=float,
        ),
        avg_hr=f.take("heart.avg_hr", "sleep:dailySleepDTO.avgHeartRate", transform=float),
        max_hr=None,
    )


def _sleep(f: _Extractor) -> Sleep:
    return Sleep(
        duration_min=f.take("sleep.duration_min", "sleep:dailySleepDTO.sleepTimeSeconds", transform=seconds_to_minutes),
        # The numeric score. `sleepScoreFeedback`/`Insight`/`PersonalizedInsight` sit
        # beside it and are all prose -- the probe found this path, guessing would not have.
        score=f.take("sleep.score", "sleep:dailySleepDTO.sleepScores.overall.value", transform=float),
        start=f.take("sleep.start", "sleep:dailySleepDTO.sleepStartTimestampGMT", transform=epoch_ms_to_utc),
        end=f.take("sleep.end", "sleep:dailySleepDTO.sleepEndTimestampGMT", transform=epoch_ms_to_utc),
        deep_min=f.take("sleep.deep_min", "sleep:dailySleepDTO.deepSleepSeconds", transform=seconds_to_minutes),
        light_min=f.take("sleep.light_min", "sleep:dailySleepDTO.lightSleepSeconds", transform=seconds_to_minutes),
        rem_min=f.take("sleep.rem_min", "sleep:dailySleepDTO.remSleepSeconds", transform=seconds_to_minutes),
        awake_min=f.take("sleep.awake_min", "sleep:dailySleepDTO.awakeSleepSeconds", transform=seconds_to_minutes),
    )


def _recovery(f: _Extractor) -> RecoveryMetrics:
    return RecoveryMetrics(
        body_battery_high=f.take("recovery.body_battery_high", "user_summary:bodyBatteryHighestValue", transform=float),
        body_battery_low=f.take("recovery.body_battery_low", "user_summary:bodyBatteryLowestValue", transform=float),
        body_battery_current=f.take("recovery.body_battery_current", "user_summary:bodyBatteryMostRecentValue", transform=float),
        stress_avg=f.take("recovery.stress_avg", "user_summary:averageStressLevel", transform=float),
        respiration_avg=f.take(
            "recovery.respiration_avg",
            "user_summary:avgWakingRespirationValue", "sleep:dailySleepDTO.averageRespirationValue",
            transform=float,
        ),
        # Confirmed unavailable on the FR165: the endpoint returns a full envelope with
        # every value null. Kept so the day it appears, it is picked up for free.
        spo2_avg=f.take("recovery.spo2_avg", "spo2:averageSpO2", "spo2:avgSleepSpO2", transform=float),
    )


def _fitness(f: _Extractor) -> Fitness:
    # Also confirmed unavailable: max_metrics returns [] and mostRecentVO2Max is null.
    return Fitness(
        vo2max=f.take(
            "fitness.vo2max",
            "max_metrics:[0].generic.vo2MaxValue", "training_status:mostRecentVO2Max",
            transform=float,
        )
    )


def _body(f: _Extractor) -> BodyMetrics:
    """Weight from the provider only. He logs weight in this app, so this is a fallback
    for anything typed into Garmin Connect -- and it is empty in practice."""
    return BodyMetrics(
        weight_kg=f.take(
            "body.weight_kg",
            "daily_weigh_ins:dateWeightList[0].weight", "daily_weigh_ins:totalAverage.weight",
            transform=garmin_weight_to_kg,
        )
    )


def normalize_day(raw: RawPayloads, on: date | None = None) -> DailyHealthSnapshot:
    """Raw Garmin payloads -> one canonical snapshot.

    Fills `measured` and `body.weight_kg` only. `derived` and `nutrition` are ours and
    stay empty here -- the engine populates them, which is what keeps the measured/derived
    split honest.
    """
    f = _Extractor(raw)
    measured = MeasuredMetrics(
        energy=_energy(f),
        activity=_activity_metrics(f, raw),
        heart=_heart(f),
        sleep=_sleep(f),
        recovery=_recovery(f),
        fitness=_fitness(f),
        provenance=f.provenance,
    )
    return DailyHealthSnapshot(date=on or raw.on, measured=measured, body=_body(f))


# --- field coverage ---------------------------------------------------------

#: The dashboard must render on these alone (PRODUCT.md tiering). Coverage over this
#: list -- not HTTP status -- is the observability signal, because an endpoint can
#: return 200 with a fully null body.
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


def coverage(snapshot: DailyHealthSnapshot) -> tuple[list[str], list[str]]:
    """(present, missing) over TIER_1_FIELDS. Emit `len(missing)` as a metric: a silent
    upstream schema change shows up as coverage dropping, not as an exception."""
    provenance = snapshot.measured.provenance
    present = [name for name in TIER_1_FIELDS if name in provenance]
    missing = [name for name in TIER_1_FIELDS if name not in provenance]
    return present, missing
