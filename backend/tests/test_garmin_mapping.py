"""Parser tests for the Garmin -> canonical mapping.

Runs against `fixtures/sample/`: committed, synthetic, internally consistent. The real
probe output in `fixtures/raw/` is gitignored (real health data), so a separate smoke test
at the bottom exercises it only when present and asserts shape rather than values.
"""

from __future__ import annotations

import json
from datetime import UTC
from datetime import date
from pathlib import Path

import pytest

from backend.core import models
from backend.providers import base as provider_base
from backend.providers import garmin_mapping

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "fixtures" / "sample" / "dt=2026-09-02"
RAW = REPO / "fixtures" / "raw" / "garmin"
ON = date(2026, 9, 2)


def load(directory: Path) -> provider_base.RawPayloads:
    payloads = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in directory.glob("*.json")}
    return provider_base.RawPayloads(provider="garmin", on=ON, payloads=payloads)


@pytest.fixture(scope="module")
def snapshot() -> models.DailyHealthSnapshot:
    return garmin_mapping.normalize_day(load(SAMPLE))


# --- read_path -------------------------------------------------------------------


def test_split_path_into_steps_handles_plain_keys() -> None:
    assert garmin_mapping.split_path_into_steps("totalSteps") == ["totalSteps"]
    assert garmin_mapping.split_path_into_steps("hrvSummary.lastNightAvg") == ["hrvSummary", "lastNightAvg"]


def test_split_path_into_steps_turns_indices_into_integers() -> None:
    """A string step means "look up a dictionary key"; an integer means "take a list
    position". Keeping them as different types is what lets read_path check the shape."""
    assert garmin_mapping.split_path_into_steps("dateWeightList[0].weight") == ["dateWeightList", 0, "weight"]
    assert garmin_mapping.split_path_into_steps("[0].generic.vo2MaxValue") == [0, "generic", "vo2MaxValue"]


def test_split_path_into_steps_handles_repeated_indices() -> None:
    assert garmin_mapping.split_path_into_steps("matrix[0][1]") == ["matrix", 0, 1]


def test_read_path_walks_nested_paths() -> None:
    assert garmin_mapping.read_path({"a": {"b": {"c": 7}}}, "a.b.c") == 7


def test_read_path_handles_list_indices() -> None:
    assert garmin_mapping.read_path({"list": [{"w": 79400}]}, "list[0].w") == 79400


def test_read_path_returns_none_for_every_missing_link() -> None:
    payload = {"a": {"b": 1}}
    assert garmin_mapping.read_path(payload, "a.missing") is None
    assert garmin_mapping.read_path(payload, "missing.b") is None
    assert garmin_mapping.read_path(payload, "a.b.c") is None          # walking into a scalar
    assert garmin_mapping.read_path(payload, "a[0]") is None            # indexing a mapping
    assert garmin_mapping.read_path({"l": []}, "l[0].x") is None        # index past the end
    assert garmin_mapping.read_path(None, "a.b") is None


def test_read_path_does_not_index_into_strings() -> None:
    assert garmin_mapping.read_path({"s": "abc"}, "s[0]") is None


# --- transforms ------------------------------------------------------------


def test_seconds_to_minutes() -> None:
    assert garmin_mapping.seconds_to_minutes(25440) == 424.0


def test_epoch_milliseconds_to_utc_is_timezone_aware() -> None:
    """Garmin sends 13-digit epoch ms. Store UTC; the presentation layer localises."""
    parsed = garmin_mapping.epoch_milliseconds_to_utc(1788329520000)
    assert parsed.tzinfo is not None
    assert parsed.astimezone(UTC).hour == 6


def test_garmin_weight_guard_handles_grams_and_kg() -> None:
    """Garmin records weigh-ins in grams. Nobody weighs >500 kg and no person's weight
    in grams is <500, so the guard covers both shapes."""
    assert garmin_mapping.garmin_weight_to_kilograms(79400) == pytest.approx(79.4)
    assert garmin_mapping.garmin_weight_to_kilograms(79.4) == pytest.approx(79.4)


# --- activity classification ----------------------------------------------


@pytest.mark.parametrize(
    ("type_key", "expected"),
    [
        ("strength_training", models.ActivityKind.RESISTANCE),
        ("indoor_strength", models.ActivityKind.RESISTANCE),
        ("weight_training", models.ActivityKind.RESISTANCE),
        ("running", models.ActivityKind.RUNNING),
        ("treadmill_running", models.ActivityKind.RUNNING),
        ("walking", models.ActivityKind.WALKING),
        ("hiking", models.ActivityKind.WALKING),
        ("cycling", models.ActivityKind.CARDIO_OTHER),
        ("indoor_cycling", models.ActivityKind.CARDIO_OTHER),
        ("elliptical", models.ActivityKind.CARDIO_OTHER),
        ("indoor_rowing", models.ActivityKind.CARDIO_OTHER),
        ("lap_swimming", models.ActivityKind.CARDIO_OTHER),
        ("hiit", models.ActivityKind.CARDIO_OTHER),
        ("indoor_cardio", models.ActivityKind.CARDIO_OTHER),
        ("treadmill_running", models.ActivityKind.RUNNING),
        ("trail_running", models.ActivityKind.RUNNING),
        ("yoga", models.ActivityKind.OTHER),
        ("", models.ActivityKind.OTHER),
        (None, models.ActivityKind.OTHER),
    ],
)
def test_activity_classification(type_key: str | None, expected: models.ActivityKind) -> None:
    assert garmin_mapping.classify_activity(type_key) is expected


def test_treadmill_without_the_word_running_is_still_running() -> None:
    """Garmin's own key is "treadmill_running", which the "running" check already
    catches. This covers the defensive case of a key that says treadmill but not
    running -- the branch exists so a naming change does not silently reclassify runs
    as "other"."""
    assert garmin_mapping.classify_activity("indoor_treadmill") is models.ActivityKind.RUNNING


def test_resistance_is_matched_before_other_rules() -> None:
    """A misclassification here silently removes the unreliable-calorie caveat from the
    dashboard, which is the one place the expenditure input should be doubted."""
    assert garmin_mapping.classify_activity("strength_training_cardio") is models.ActivityKind.RESISTANCE


# --- the sample day --------------------------------------------------------


def test_energy_extraction(snapshot: models.DailyHealthSnapshot) -> None:
    energy = snapshot.measured.energy
    assert energy.total_kcal == 2421.0
    assert energy.active_kcal == 617.0
    assert energy.resting_kcal == 1804.0


def test_sleep_seconds_become_minutes(snapshot: models.DailyHealthSnapshot) -> None:
    sleep = snapshot.measured.sleep
    assert sleep.duration_min == 424.0            # 25440 s = 7h04m
    assert sleep.deep_min == 78.0
    assert sleep.light_min == 272.0
    assert sleep.rem_min == 74.0
    assert sleep.awake_min == 17.0
    assert sleep.has_stages is True


def test_sleep_stages_sum_to_the_reported_duration(snapshot: models.DailyHealthSnapshot) -> None:
    """Not a mapping guarantee -- an internal consistency check on the fixture, which is
    what makes the stage assertions above meaningful."""
    sleep = snapshot.measured.sleep
    assert sleep.deep_min is not None and sleep.light_min is not None and sleep.rem_min is not None
    assert sleep.deep_min + sleep.light_min + sleep.rem_min == pytest.approx(sleep.duration_min)


def test_numeric_sleep_score_comes_from_the_nested_path(snapshot: models.DailyHealthSnapshot) -> None:
    """`sleepScoreFeedback`, `sleepScoreInsight` and `sleepScorePersonalizedInsight` sit
    beside it and are all prose. The probe found the numeric one three levels down."""
    assert snapshot.measured.sleep.score == 81.0
    assert snapshot.measured.provenance["sleep.score"] == "sleep:dailySleepDTO.sleepScores.overall.value"


def test_sleep_window_is_parsed_from_epoch_millis(snapshot: models.DailyHealthSnapshot) -> None:
    sleep = snapshot.measured.sleep
    assert sleep.start is not None and sleep.end is not None
    assert (sleep.end - sleep.start).total_seconds() == 26_460  # asleep + awake
    assert sleep.start.tzinfo is not None


def test_heart_extraction(snapshot: models.DailyHealthSnapshot) -> None:
    heart = snapshot.measured.heart
    assert heart.hrv_ms == 51.0
    assert heart.resting_hr == 53.0
    assert heart.avg_hr == 56.0


def test_hrv_prefers_the_dedicated_endpoint(snapshot: models.DailyHealthSnapshot) -> None:
    assert snapshot.measured.provenance["heart.hrv_ms"] == "hrv:hrvSummary.lastNightAvg"


def test_hrv_falls_back_to_the_sleep_payload() -> None:
    """The sleep response also carries `avgOvernightHrv`, so losing the HRV endpoint
    degrades rather than blanking the Recovery screen."""
    raw = load(SAMPLE)
    without_hrv = provider_base.RawPayloads(
        provider="garmin", on=ON,
        payloads={k: v for k, v in raw.payloads.items() if k != "hrv"},
    )
    snapshot = garmin_mapping.normalize_day(without_hrv)
    assert snapshot.measured.heart.hrv_ms == 51.0
    assert snapshot.measured.provenance["heart.hrv_ms"] == "sleep:avgOvernightHrv"


def test_energy_falls_back_from_user_summary_to_stats() -> None:
    raw = load(SAMPLE)
    without_summary = provider_base.RawPayloads(
        provider="garmin", on=ON,
        payloads={k: v for k, v in raw.payloads.items() if k != "user_summary"},
    )
    snapshot = garmin_mapping.normalize_day(without_summary)
    assert snapshot.measured.energy.total_kcal == 2421.0
    assert snapshot.measured.provenance["energy.total_kcal"] == "stats:totalKilocalories"


def test_activity_extraction(snapshot: models.DailyHealthSnapshot) -> None:
    activity = snapshot.measured.activity
    assert activity.steps == 13842
    assert activity.step_goal == 10000
    assert activity.distance_m == 10450.0


def test_intensity_minutes_double_count_vigorous(snapshot: models.DailyHealthSnapshot) -> None:
    """Garmin's own convention: 34 moderate + 12 vigorous -> 34 + 24 = 58."""
    assert snapshot.measured.activity.intensity_minutes == 58.0


def test_workout_minutes_are_summed_from_activities(snapshot: models.DailyHealthSnapshot) -> None:
    assert snapshot.measured.activity.workout_minutes == 58.0


def test_activities_are_mapped_and_classified(snapshot: models.DailyHealthSnapshot) -> None:
    activities = snapshot.measured.activity.activities
    assert len(activities) == 1
    lifting = activities[0]
    assert lifting.kind is models.ActivityKind.RESISTANCE
    assert lifting.type_raw == "strength_training"
    assert lifting.provider_id == "90000001"
    assert lifting.duration_min == 58.0          # 3480 s
    assert lifting.calories == 402.0
    assert lifting.avg_hr == 118.0
    assert lifting.max_hr == 152.0


def test_hr_zones_are_not_populated_by_the_day_fetch(snapshot: models.DailyHealthSnapshot) -> None:
    """Zone splits need a per-activity call the day fetch doesn't make. None means
    "not fetched", and the optional load metrics are what would need it."""
    assert snapshot.measured.activity.activities[0].zone_seconds is None


def test_recovery_extraction(snapshot: models.DailyHealthSnapshot) -> None:
    recovery = snapshot.measured.recovery
    assert recovery.body_battery_high == 72.0
    assert recovery.body_battery_low == 24.0
    assert recovery.body_battery_current == 61.0
    assert recovery.stress_avg == 28.0
    assert recovery.respiration_avg == 14.2


def test_confirmed_unavailable_metrics_are_none_not_zero(snapshot: models.DailyHealthSnapshot) -> None:
    """The FR165 returns HTTP 200 with fully null bodies for these. Zero would be a lie;
    None correctly means "not reported"."""
    assert snapshot.measured.recovery.spo2_avg is None
    assert snapshot.measured.fitness.vo2max is None
    assert "recovery.spo2_avg" not in snapshot.measured.provenance
    assert "fitness.vo2max" not in snapshot.measured.provenance


def test_weight_is_absent_because_it_is_logged_in_this_app(snapshot: models.DailyHealthSnapshot) -> None:
    assert snapshot.body.weight_kg is None


def test_normalization_leaves_derived_and_nutrition_empty(snapshot: models.DailyHealthSnapshot) -> None:
    """The measured/derived split is only honest if the provider layer cannot write into
    `derived`. Nutrition is ours too -- Garmin never populates it."""
    assert snapshot.derived.recovery_status is None
    assert snapshot.derived.bmr is None
    assert snapshot.derived.balance is None
    assert snapshot.nutrition.entry_count == 0
    assert snapshot.nutrition.consumed.kcal == 0.0


# --- coverage --------------------------------------------------------------


def test_full_tier_1_coverage_on_a_good_day(snapshot: models.DailyHealthSnapshot) -> None:
    present, missing = garmin_mapping.coverage(snapshot)
    assert missing == []
    assert len(present) == len(garmin_mapping.TIER_1_FIELDS)


def test_coverage_reports_what_a_partial_sync_lost() -> None:
    """This is the observability signal: a silent upstream schema change shows up as
    coverage dropping, not as an exception."""
    raw = load(SAMPLE)
    partial = provider_base.RawPayloads(
        provider="garmin", on=ON,
        payloads={k: v for k, v in raw.payloads.items() if k not in {"sleep", "hrv"}},
    )
    present, missing = garmin_mapping.coverage(garmin_mapping.normalize_day(partial))
    assert set(missing) == {"sleep.duration_min", "sleep.score", "heart.hrv_ms"}
    assert "energy.total_kcal" in present


# --- degradation -----------------------------------------------------------


def test_empty_payloads_produce_a_valid_empty_snapshot() -> None:
    """A watch left on the charger is a normal Tuesday, not an exception."""
    snapshot = garmin_mapping.normalize_day(provider_base.RawPayloads(provider="garmin", on=ON, payloads={}))
    assert snapshot.date == ON
    assert snapshot.measured.energy.total_kcal is None
    assert snapshot.measured.sleep.duration_min is None
    assert snapshot.measured.activity.activities == []
    assert snapshot.measured.provenance == {}
    _, missing = garmin_mapping.coverage(snapshot)
    assert len(missing) == len(garmin_mapping.TIER_1_FIELDS)


def test_malformed_payloads_do_not_raise() -> None:
    """Defensive: an unofficial API can change shape without warning, and a parser crash
    would lose the whole day rather than one field."""
    snapshot = garmin_mapping.normalize_day(
        provider_base.RawPayloads(
            provider="garmin", on=ON,
            payloads={
                "user_summary": "not a dict",
                "sleep": {"dailySleepDTO": None},
                "activities": {"unexpected": "shape"},
                "hrv": [],
            },
        )
    )
    assert snapshot.measured.energy.total_kcal is None
    assert snapshot.measured.activity.activities == []


def test_non_numeric_values_are_skipped_not_crashed() -> None:
    """A transform that rejects a value must withdraw its provenance and move on."""
    snapshot = garmin_mapping.normalize_day(
        provider_base.RawPayloads(
            provider="garmin", on=ON,
            payloads={
                "user_summary": {"totalKilocalories": "n/a"},
                "stats": {"totalKilocalories": 2100.0},
            },
        )
    )
    assert snapshot.measured.energy.total_kcal == 2100.0
    assert snapshot.measured.provenance["energy.total_kcal"] == "stats:totalKilocalories"


def test_activities_missing_fields_still_map() -> None:
    snapshot = garmin_mapping.normalize_day(
        provider_base.RawPayloads(
            provider="garmin", on=ON,
            payloads={"activities": [{"activityType": {"typeKey": "running"}}]},
        )
    )
    activity = snapshot.measured.activity.activities[0]
    assert activity.kind is models.ActivityKind.RUNNING
    assert activity.duration_min is None
    assert activity.calories is None
    assert activity.provider_id == ""
    assert snapshot.measured.activity.workout_minutes is None


# --- against the real probe output, when it exists -------------------------


@pytest.mark.skipif(not RAW.exists(), reason="real fixtures are gitignored; run scripts/garmin_probe.py")
def test_real_fixtures_normalize_without_error() -> None:
    """Shape only -- never asserts values, so it stays safe to run over real health data.
    This is the test that would catch a Garmin schema change."""
    days = sorted(RAW.glob("dt=*"))
    assert days, "no probed days found"
    for day in days:
        raw = load(day)
        snapshot = garmin_mapping.normalize_day(raw, on=date.fromisoformat(day.name.removeprefix("dt=")))
        assert isinstance(snapshot, models.DailyHealthSnapshot)
        present, _ = garmin_mapping.coverage(snapshot)
        # energy and steps come from user_summary and must be present on any real day
        assert "energy.total_kcal" in present
        assert "activity.steps" in present


# --- start-time parsing edge cases ----------------------------------------


def test_activity_start_accepts_both_garmin_timestamp_formats() -> None:
    """Garmin has shipped both a space-separated and an ISO 'T' variant."""
    space = garmin_mapping.normalize_day(
        provider_base.RawPayloads(provider="garmin", on=ON, payloads={
            "activities": [{"activityType": {"typeKey": "running"}, "startTimeGMT": "2026-09-02 14:05:00"}]
        })
    ).measured.activity.activities[0]
    iso = garmin_mapping.normalize_day(
        provider_base.RawPayloads(provider="garmin", on=ON, payloads={
            "activities": [{"activityType": {"typeKey": "running"}, "startTimeGMT": "2026-09-02T14:05:00"}]
        })
    ).measured.activity.activities[0]
    assert space.start is not None and iso.start is not None
    assert space.start == iso.start
    assert space.start.hour == 14


def test_activity_start_is_none_for_an_unparseable_value() -> None:
    """A shape change in a timestamp must cost that one field, not the whole activity."""
    activity = garmin_mapping.normalize_day(
        provider_base.RawPayloads(provider="garmin", on=ON, payloads={
            "activities": [{
                "activityType": {"typeKey": "running"},
                "startTimeGMT": "sometime last Tuesday",
                "duration": 1800.0,
            }]
        })
    ).measured.activity.activities[0]
    assert activity.start is None
    assert activity.duration_min == 30.0        # the rest of the activity survived


def test_activity_start_is_none_when_not_a_string() -> None:
    activity = garmin_mapping.normalize_day(
        provider_base.RawPayloads(provider="garmin", on=ON, payloads={
            "activities": [{"activityType": {"typeKey": "running"}, "startTimeGMT": 1788329520000}]
        })
    ).measured.activity.activities[0]
    assert activity.start is None


def test_non_mapping_entries_in_the_activity_list_are_skipped() -> None:
    snapshot = garmin_mapping.normalize_day(
        provider_base.RawPayloads(provider="garmin", on=ON, payloads={
            "activities": ["unexpected", None, {"activityType": {"typeKey": "walking"}}]
        })
    )
    activities = snapshot.measured.activity.activities
    assert len(activities) == 1
    assert activities[0].kind is models.ActivityKind.WALKING


# --- converters and the no-conversion path ---------------------------------


def test_optional_int_and_float_return_none_for_missing_values() -> None:
    assert garmin_mapping.optional_int(None) is None
    assert garmin_mapping.optional_float(None) is None


def test_optional_int_and_float_return_none_for_unconvertible_values() -> None:
    """An unofficial API can send something unexpected. One odd field should cost us
    that field, not the whole day."""
    assert garmin_mapping.optional_int("n/a") is None
    assert garmin_mapping.optional_int({"unexpected": "shape"}) is None
    assert garmin_mapping.optional_float("n/a") is None
    assert garmin_mapping.optional_float([1, 2, 3]) is None


def test_optional_int_truncates_a_float() -> None:
    assert garmin_mapping.optional_int(13842.0) == 13842


def test_a_field_with_no_converter_is_passed_through_unchanged() -> None:
    """Most fields are converted, but `take` also supports reading a raw value as-is."""
    reader = garmin_mapping.FieldReader(
        provider_base.RawPayloads(provider="garmin", on=ON, payloads={"sleep": {"hrvStatus": "BALANCED"}})
    )
    value = reader.take("sleep.hrv_status", [garmin_mapping.FieldSource("sleep", "hrvStatus")])
    assert value == "BALANCED"
    assert reader.provenance["sleep.hrv_status"] == "sleep:hrvStatus"


def test_field_source_describes_itself_for_the_provenance_record() -> None:
    source = garmin_mapping.FieldSource("sleep", "dailySleepDTO.sleepTimeSeconds")
    assert source.describe() == "sleep:dailySleepDTO.sleepTimeSeconds"
