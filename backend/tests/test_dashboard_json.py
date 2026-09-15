"""Tests for the wire format the dashboard reads.

A contract is exactly the kind of thing worth testing: it is read by code written in a
different language, in a different repository, that cannot be refactored alongside it. A
field quietly renamed here does not break Python -- it breaks a chart, later, silently.

So these tests assert the *shape* as much as the values: that a key exists, that it is
spelled the way the contract says, and that "missing" crosses the wire as null rather
than as a zero or a dropped key.

Everything here builds its own objects by hand. Nothing reads the database, so nothing
here depends on what happens to be stored today.
"""

from __future__ import annotations

import datetime
import json

from backend.api import dashboard_json
from backend.body import weight
from backend.food import log
from backend.garmin import normalize

DAY = datetime.date(2026, 9, 14)
LOGGED_AT = datetime.datetime(2026, 9, 14, 16, 7, 40)


def a_full_snapshot() -> normalize.DailySnapshot:
    """A day with a reading in every field, so nothing is missing by accident."""
    return normalize.DailySnapshot(
        day=DAY,
        energy=normalize.Energy(
            total_kilocalories=3000,
            active_kilocalories=1000,
            resting_kilocalories=2000,
            steps=20000,
            distance_metres=18000.0,
            moderate_intensity_minutes=30,
            vigorous_intensity_minutes=20,
        ),
        sleep=normalize.Sleep(
            total_minutes=400.0,
            score=70,
            deep_minutes=100.0,
            light_minutes=200.0,
            rem_minutes=80.0,
            awake_minutes=20.0,
        ),
        recovery=normalize.Recovery(
            hrv_last_night=100.0,
            hrv_weekly_average=95.0,
            hrv_baseline=90.0,
            resting_heart_rate=50,
            body_battery_charged=80,
            body_battery_drained=70,
            average_stress=30,
        ),
        body=normalize.Body(weight_kilograms=80.0),
    )


def an_empty_snapshot() -> normalize.DailySnapshot:
    """A day Garmin has nothing for -- the shape a fresh morning has."""
    return normalize.normalize_day({}, DAY)


# ---------------------------------------------------------------------------
# The rules the format promises
# ---------------------------------------------------------------------------


def test_a_missing_reading_crosses_the_wire_as_null_with_its_key_intact() -> None:
    """Rule 1, and the reason the whole project distinguishes None from 0.

    The key has to survive. A dropped key and a null key look the same to a chart that
    only reads values, but they mean different things to the person debugging it: one is
    "no reading last night", the other is "this API does not have that field at all".
    """
    day = dashboard_json.day_to_json(an_empty_snapshot())

    assert "hrv_last_night" in day["recovery"]
    assert day["recovery"]["hrv_last_night"] is None

    assert "steps" in day["energy"]
    assert day["energy"]["steps"] is None

    # And emphatically not zero, which would be a measurement.
    assert day["energy"]["steps"] != 0


def test_every_block_is_present_even_on_a_day_with_nothing_in_it() -> None:
    """The dashboard should never need to check whether a block exists before reading it."""
    day = dashboard_json.day_to_json(an_empty_snapshot())

    for block_name in ("energy", "sleep", "recovery", "body", "activities"):
        assert block_name in day, f"{block_name} missing from an empty day"

    # These two are nullable blocks rather than always-objects, which is itself contract.
    assert day["weight"] is None
    assert day["food"] is None
    assert day["activities"] == []


def test_numbers_go_over_raw_and_never_formatted() -> None:
    """Rule 2. A chart has to do arithmetic on these."""
    day = dashboard_json.day_to_json(a_full_snapshot())

    assert day["sleep"]["total_minutes"] == 400.0
    assert isinstance(day["sleep"]["total_minutes"], float)

    assert day["energy"]["steps"] == 20000
    assert isinstance(day["energy"]["steps"], int)


def test_dates_are_iso_text() -> None:
    """Rule 4. Sorts correctly as text and parses everywhere."""
    day = dashboard_json.day_to_json(a_full_snapshot())

    assert day["day"] == "2026-09-14"


def test_the_contract_spells_out_every_key_it_promises() -> None:
    """The field names the dashboard will be written against, pinned by name.

    This is the test that fails if someone renames a field in `normalize.py` and lets the
    rename leak into the API. That rename is fine; leaking it is not.
    """
    day = dashboard_json.day_to_json(a_full_snapshot())

    assert set(day["energy"]) == {
        "total_kilocalories",
        "active_kilocalories",
        "resting_kilocalories",
        "steps",
        "distance_metres",
        "moderate_intensity_minutes",
        "vigorous_intensity_minutes",
    }

    assert set(day["sleep"]) == {
        "total_minutes",
        "score",
        "deep_minutes",
        "light_minutes",
        "rem_minutes",
        "awake_minutes",
    }

    assert set(day["recovery"]) == {
        "hrv_last_night",
        "hrv_weekly_average",
        "hrv_baseline",
        "resting_heart_rate",
        "body_battery_charged",
        "body_battery_drained",
        "average_stress",
    }

    assert set(day) == {
        "day",
        "energy",
        "sleep",
        "recovery",
        "body",
        "weight",
        "food",
        "activities",
        "fields_found",
    }


# ---------------------------------------------------------------------------
# Weight -- the block where an invented number would do real damage
# ---------------------------------------------------------------------------


def test_garmin_weight_is_named_so_it_cannot_be_mistaken_for_a_weigh_in() -> None:
    """Two different measurements taken at different times must not share a name."""
    day = dashboard_json.day_to_json(a_full_snapshot())

    assert day["body"]["garmin_weight_kilograms"] == 80.0
    assert "weight_kilograms" not in day["body"]


def test_a_missed_morning_sends_null_rather_than_yesterdays_weight() -> None:
    """Rule 5, and the one decision here that cannot be undone later.

    Carrying a weight forward at this layer would write a measurement that never
    happened and leave it indistinguishable from a real one. Any later calculation
    reading this history would count the invented day as "no change", biasing the rate
    of loss toward zero. Drawing an unbroken line is the dashboard's decision to make,
    where it is visible.
    """
    day = dashboard_json.day_to_json(a_full_snapshot(), weighing=None)

    assert day["weight"] is None


def test_a_real_weigh_in_carries_its_source_and_time() -> None:
    """Which reading it is matters more than the number: a DEXA total is not a morning scale."""
    weighing = weight.Weighing(
        day=DAY,
        kilograms=75.0,
        recorded_at=datetime.datetime(2026, 9, 14, 7, 2, 28),
        source="manual",
    )

    day = dashboard_json.day_to_json(a_full_snapshot(), weighing=weighing)

    assert day["weight"] == {
        "kilograms": 75.0,
        "recorded_at": "2026-09-14T07:02:28",
        "source": "manual",
        "fat_percent": None,
    }


def test_a_morning_without_a_body_fat_reading_sends_null() -> None:
    """Most mornings will not have one, and absent must not read as zero percent."""
    weighing = weight.Weighing(
        day=DAY,
        kilograms=75.0,
        recorded_at=datetime.datetime(2026, 9, 14, 7, 2, 28),
        source="manual",
    )

    day = dashboard_json.day_to_json(a_full_snapshot(), weighing=weighing)

    assert day["weight"]["fat_percent"] is None


def test_a_scale_body_fat_reading_travels_with_the_weigh_in() -> None:
    """The scale's estimate rides on the morning entry, not on the scan.

    Kept apart from a DEXA figure on purpose: a scale infers composition from electrical
    resistance and moves with hydration, while a scan measures it. Same units, different
    kinds of fact, so they must never land in the same field.
    """
    weighing = weight.Weighing(
        day=DAY,
        kilograms=75.0,
        recorded_at=datetime.datetime(2026, 9, 14, 7, 2, 28),
        source="manual",
        fat_percent=18.4,
    )

    day = dashboard_json.day_to_json(a_full_snapshot(), weighing=weighing)

    assert day["weight"]["fat_percent"] == 18.4


# ---------------------------------------------------------------------------
# Food -- where null and zero genuinely differ
# ---------------------------------------------------------------------------


def a_logged_food(kilocalories: float, protein: float) -> log.LoggedFood:
    """One entry, with only the fields these tests care about made interesting."""
    return log.LoggedFood(
        food_id="whey-protein",
        food_name="Whey protein",
        servings=1.0,
        serving_basis="as_sold",
        kilocalories=kilocalories,
        protein_grams=protein,
        carbohydrate_grams=3.0,
        fat_grams=1.0,
        logged_at=LOGGED_AT,
    )


def test_a_day_with_no_food_logged_sends_null_not_zero() -> None:
    """The deliberate difference from the CLI, and it matters on a chart.

    In the CLI an empty log for *today* totals zero, because "I have eaten nothing yet"
    is a real measurement. In the archive, a day with no entries means the log was not
    kept -- not that nothing was eaten. Sending zeroes would put a run of 0 kcal days
    beside real ones and make every average wrong.
    """
    day = dashboard_json.day_to_json(a_full_snapshot(), food_entries=[])

    assert day["food"] is None


def test_food_sends_totals_and_the_entries_behind_them() -> None:
    """Totals so a chart need not sum thirteen entries; entries so a detail view can exist."""
    entries = [a_logged_food(120.0, 24.0), a_logged_food(180.0, 17.0)]

    day = dashboard_json.day_to_json(a_full_snapshot(), food_entries=entries)

    assert day["food"]["totals"]["kilocalories"] == 300.0
    assert day["food"]["totals"]["protein_grams"] == 41.0
    assert len(day["food"]["entries"]) == 2
    assert day["food"]["entries"][0]["food_name"] == "Whey protein"


def test_an_entry_carries_its_own_macros_and_its_basis() -> None:
    """The raw/cooked trap is the biggest accuracy risk in the log, so the basis travels."""
    day = dashboard_json.day_to_json(a_full_snapshot(), food_entries=[a_logged_food(120.0, 24.0)])

    entry = day["food"]["entries"][0]

    assert entry["serving_basis"] == "as_sold"
    assert entry["kilocalories"] == 120.0
    assert entry["logged_at"] == "2026-09-14T16:07:40"


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------


def test_a_workout_sends_its_derived_active_calories() -> None:
    """Derived, and sent anyway.

    Garmin's `calories` is gross and includes the resting burn that would have happened
    regardless. It is a method rather than a field for that reason. Sending the result
    means every screen agrees on it instead of each recomputing it.
    """
    activity = normalize.Activity(
        name="Evening Lift",
        type_key="strength_training",
        started_at_local=datetime.datetime(2026, 9, 14, 18, 30),
        duration_minutes=45.0,
        total_kilocalories=400,
        resting_kilocalories=100,
        average_heart_rate=120,
    )

    snapshot = a_full_snapshot()
    snapshot.activities = [activity]

    day = dashboard_json.day_to_json(snapshot)

    assert len(day["activities"]) == 1
    assert day["activities"][0]["total_kilocalories"] == 400
    assert day["activities"][0]["active_kilocalories"] == 300
    assert day["activities"][0]["started_at_local"] == "2026-09-14T18:30:00"


def test_a_rest_day_sends_an_empty_list_not_null() -> None:
    """"No workouts" is a real and common answer; the dashboard can iterate it safely."""
    day = dashboard_json.day_to_json(a_full_snapshot())

    assert day["activities"] == []


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------


def test_the_envelope_reports_the_span_it_contains() -> None:
    """So the dashboard can say what it is showing without scanning the array."""
    days = [
        dashboard_json.day_to_json(normalize.normalize_day({}, datetime.date(2026, 9, 12))),
        dashboard_json.day_to_json(normalize.normalize_day({}, datetime.date(2026, 9, 13))),
    ]

    payload = dashboard_json.span_to_json(days, datetime.datetime(2026, 9, 15, 10, 30))

    assert payload["schema_version"] == dashboard_json.SCHEMA_VERSION
    assert payload["generated_at"] == "2026-09-15T10:30:00"
    assert payload["first_day"] == "2026-09-12"
    assert payload["last_day"] == "2026-09-13"
    assert len(payload["days"]) == 2


def test_an_empty_span_is_still_a_valid_payload() -> None:
    """A fresh install has no days. The dashboard should get a shape it can read, not a crash."""
    payload = dashboard_json.span_to_json([], datetime.datetime(2026, 9, 15, 10, 30))

    assert payload["days"] == []
    assert payload["first_day"] is None
    assert payload["last_day"] is None


def test_the_whole_payload_survives_a_round_trip_through_json() -> None:
    """The point of the format. A date or a dataclass left in would raise right here.

    This is the test that catches a new field added carelessly -- a `datetime` handed
    straight through serialises fine in Python and explodes at `json.dumps`.
    """
    days = [dashboard_json.day_to_json(a_full_snapshot(), food_entries=[a_logged_food(120.0, 24.0)])]
    payload = dashboard_json.span_to_json(days, datetime.datetime(2026, 9, 15, 10, 30))

    as_text = json.dumps(payload)
    came_back = json.loads(as_text)

    assert came_back == payload
