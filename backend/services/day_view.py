"""Assemble everything known about one day.

This is the layer that brings the pure engine together with stored data. It reads from
a repository, calls the calculation functions in `backend/core`, and returns one object
the screen (or the CLI, or later the API) can render without doing any maths itself.

The split is deliberate:

    DailyHealthSnapshot   the canonical record. Storable, and what the LLM layer will
                          eventually be handed.
    DayView               the snapshot plus presentation extras -- weight trend, 30-day
                          change, the maintenance estimate. Not stored; recalculated
                          whenever it is asked for.

Keeping the display extras out of the stored model means the stored model stays exactly
what the plan says it is, and adding something to a screen never changes the database.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from datetime import timedelta

from backend.adapters import repository as storage
from backend.core import baselines
from backend.core import body_composition
from backend.core import calibration
from backend.core import energy
from backend.core import models
from backend.core import nutrition
from backend.core import reasons
from backend.core import recovery
from backend.core import weight

# How much history to load. 90 days covers every baseline window and the maintenance
# estimate, and at one record a day that is a few hundred kilobytes -- small enough that
# loading it all and calculating in memory is simpler than any cleverer alternative.
DEFAULT_HISTORY_DAYS = 90

DEFAULT_BASELINE_WINDOW_DAYS = 30

# Which metrics get a baseline, and how to read each one out of a snapshot. Written as
# data so adding a metric to the Recovery screen is one line here rather than a new
# branch somewhere.
METRIC_EXTRACTORS: dict[str, Callable[[models.DailyHealthSnapshot], float | None]] = {
    "sleep_duration_min": lambda snapshot: snapshot.measured.sleep.duration_min,
    "sleep_score": lambda snapshot: snapshot.measured.sleep.score,
    "hrv_ms": lambda snapshot: snapshot.measured.heart.hrv_ms,
    "resting_hr": lambda snapshot: snapshot.measured.heart.resting_hr,
    "body_battery_high": lambda snapshot: snapshot.measured.recovery.body_battery_high,
    "stress_avg": lambda snapshot: snapshot.measured.recovery.stress_avg,
    "total_kcal": lambda snapshot: snapshot.measured.energy.total_kcal,
    "steps": lambda snapshot: _as_float(snapshot.measured.activity.steps),
}

# The metrics the Recovery section shows a baseline comparison for.
RECOVERY_METRICS = (
    "sleep_duration_min",
    "sleep_score",
    "hrv_ms",
    "resting_hr",
    "body_battery_high",
    "stress_avg",
)


def _as_float(value: int | None) -> float | None:
    if value is None:
        return None
    return float(value)


@dataclass
class DayView:
    """One day, fully assembled and ready to render."""

    snapshot: models.DailyHealthSnapshot
    target: models.MacroTarget | None = None

    # Weight, beyond the single reading held on the snapshot.
    weight_trend: models.TrendResult | None = None
    weight_change_7d: float | None = None
    weight_change_30d: float | None = None
    plateau: models.PlateauResult | None = None

    # What the system has learned from the data itself.
    observed_maintenance: models.MaintenanceEstimate | None = None

    # How much history was available, so the screen can be honest about thin data.
    history_days_available: int = 0
    weigh_ins_available: int = 0

    @property
    def all_reasons(self) -> list[reasons.Reason]:
        """Every explanation produced for this day, in one list.

        The screen's "Why?" panel reads this, and the LLM layer will later receive
        exactly this and nothing else.
        """
        collected: list[reasons.Reason] = []

        derived = self.snapshot.derived

        if derived.bmr is not None:
            collected.extend(derived.bmr.reasons)
        if derived.balance is not None:
            collected.extend(derived.balance.reasons)
        if derived.recovery_status is not None:
            collected.extend(derived.recovery_status.reasons)
        if derived.composition is not None:
            collected.extend(derived.composition.reasons)
        if self.snapshot.nutrition.adherence is not None:
            collected.extend(self.snapshot.nutrition.adherence.reasons)
        if self.plateau is not None:
            collected.extend(self.plateau.reasons)

        collected.extend(derived.reasons)

        return collected


def build_metric_series(
    snapshots: list[models.DailyHealthSnapshot],
    metric_name: str,
) -> list[tuple[date, float | None]]:
    """Pull one metric out of a list of snapshots as (day, value) pairs."""
    extractor = METRIC_EXTRACTORS[metric_name]

    series: list[tuple[date, float | None]] = []
    for snapshot in snapshots:
        series.append((snapshot.date, extractor(snapshot)))

    return series


def build_all_recovery_history(
    snapshots: list[models.DailyHealthSnapshot],
) -> dict[str, list[tuple[date, float | None]]]:
    """Every recovery metric's history, keyed by metric name."""
    history: dict[str, list[tuple[date, float | None]]] = {}

    for metric_name in RECOVERY_METRICS:
        history[metric_name] = build_metric_series(snapshots, metric_name)

    return history


def current_recovery_values(snapshot: models.DailyHealthSnapshot) -> dict[str, float | None]:
    """Today's readings for the recovery metrics."""
    values: dict[str, float | None] = {}

    for metric_name in RECOVERY_METRICS:
        values[metric_name] = METRIC_EXTRACTORS[metric_name](snapshot)

    return values


def build_nutrition(
    repository: storage.HealthRepository,
    user_id: str,
    day: date,
) -> tuple[models.NutritionTotals, models.MacroTarget | None]:
    """Total up the day's food and compare it against the target in force that day."""
    entries = repository.list_entries(user_id, day)
    consumed = nutrition.day_totals(entries)

    targets = repository.list_targets(user_id)
    target = nutrition.target_on(day, targets)

    if target is None:
        # No target set for this date yet, so there is nothing to compare against.
        return (
            models.NutritionTotals(consumed=consumed, entry_count=len(entries)),
            None,
        )

    return (
        models.NutritionTotals(
            consumed=consumed,
            target=target,
            remaining=nutrition.remaining(consumed, target),
            adherence=nutrition.adherence(consumed, target, entry_count=len(entries)),
            entry_count=len(entries),
        ),
        target,
    )


def pick_weight_for_the_day(
    repository: storage.HealthRepository,
    user_id: str,
    day: date,
    weight_history: list[tuple[date, float]],
) -> tuple[float | None, float | None]:
    """Today's weight and the smoothed value, falling back sensibly.

    Missing a weigh-in is explicitly fine, so if there is no reading for today we use
    the smoothed value from the readings we do have. That keeps the BMR calculation
    working rather than blanking the whole Energy section over one skipped morning.
    """
    todays_entry = repository.get_weight(user_id, day)
    smoothed = weight.ema_on(weight_history, day)

    if todays_entry is not None:
        return todays_entry.weight_kg, smoothed

    return None, smoothed


def build_derived(
    profile: models.Profile | None,
    snapshot: models.DailyHealthSnapshot,
    nutrition_totals: models.NutritionTotals,
    weight_for_bmr: float | None,
    lean_mass_kg: float | None,
    history: list[models.DailyHealthSnapshot],
    day: date,
    *,
    baseline_window_days: int,
) -> models.DerivedMetrics:
    """Run the engine over one day and collect everything it produces."""
    derived = models.DerivedMetrics()
    extra_reasons: list[reasons.Reason] = []

    # --- basal metabolic rate ------------------------------------------
    if profile is not None and weight_for_bmr is not None:
        derived.bmr = energy.bmr(profile, weight_for_bmr, day, lean_mass_kg=lean_mass_kg)
    else:
        extra_reasons.append(
            reasons.Reason(code=reasons.ReasonCode.NO_WEIGH_IN, metric="weight_kg")
        )

    # --- energy balance -------------------------------------------------
    burned = snapshot.measured.energy.total_kcal

    if burned is None:
        extra_reasons.append(
            reasons.Reason(code=reasons.ReasonCode.METRIC_MISSING, metric="total_kcal")
        )
    else:
        derived.balance = energy.energy_balance(
            burned,
            nutrition_totals.consumed.kcal,
            activities=snapshot.measured.activity.activities,
        )

    # --- baselines and deviations ---------------------------------------
    computed_baselines: dict[str, models.Baseline] = {}
    computed_deviations: dict[str, models.Deviation] = {}

    for metric_name in RECOVERY_METRICS:
        series = build_metric_series(history, metric_name)
        metric_baseline = baselines.baseline(
            series, metric_name, baseline_window_days, day
        )

        if metric_baseline is None:
            continue

        computed_baselines[metric_name] = metric_baseline

        today_value = METRIC_EXTRACTORS[metric_name](snapshot)
        metric_deviation = baselines.deviation(today_value, metric_baseline)

        if metric_deviation is not None:
            computed_deviations[metric_name] = metric_deviation

    derived.baselines = computed_baselines
    derived.deviations = computed_deviations

    # --- recovery status (ours, not Garmin's) ---------------------------
    derived.recovery_status = recovery.recovery_status(
        current_recovery_values(snapshot),
        build_all_recovery_history(history),
        day,
        window_days=baseline_window_days,
    )

    derived.reasons = extra_reasons
    return derived


def build_day(
    repository: storage.HealthRepository,
    user_id: str,
    day: date,
    *,
    baseline_window_days: int = DEFAULT_BASELINE_WINDOW_DAYS,
    history_days: int = DEFAULT_HISTORY_DAYS,
) -> DayView:
    """Everything known about one day, calculated fresh.

    Loads the day itself plus enough history for baselines and trends, then runs the
    engine over it. Nothing is cached: at this data volume recalculating is cheaper than
    working out when a cached value went stale.
    """
    profile = repository.get_profile(user_id)

    history_start = day - timedelta(days=history_days)

    # The stored Garmin data for this day, if it has been synced.
    snapshot = repository.get_snapshot(user_id, day)
    if snapshot is None:
        # No sync yet for this day. An empty snapshot is a valid answer -- the food log
        # and weigh-in still work, and the screen shows dashes for the watch metrics.
        snapshot = models.DailyHealthSnapshot(date=day)

    history = repository.list_snapshots(user_id, history_start, day)

    # --- food -----------------------------------------------------------
    nutrition_totals, target = build_nutrition(repository, user_id, day)
    snapshot.nutrition = nutrition_totals

    # --- weight ---------------------------------------------------------
    weight_entries = repository.list_weights(user_id, history_start, day)

    weight_history: list[tuple[date, float]] = []
    for entry in weight_entries:
        weight_history.append((entry.date, entry.weight_kg))

    todays_weight, smoothed_weight = pick_weight_for_the_day(
        repository, user_id, day, weight_history
    )

    # --- body composition ------------------------------------------------
    scans = repository.list_dexa_scans(user_id)

    weight_for_composition = todays_weight or smoothed_weight
    composition = body_composition.composition_on(weight_for_composition, day, scans)

    lean_mass_for_bmr = None
    if composition is not None:
        lean_mass_for_bmr = composition.lean_mass_kg

    snapshot.body = models.BodyMetrics(
        weight_kg=todays_weight,
        weight_ema_kg=smoothed_weight,
        composition=composition,
    )

    # --- the engine ------------------------------------------------------
    snapshot.derived = build_derived(
        profile,
        snapshot,
        nutrition_totals,
        todays_weight or smoothed_weight,
        lean_mass_for_bmr,
        history,
        day,
        baseline_window_days=baseline_window_days,
    )
    snapshot.derived.composition = composition

    # --- trends and what the data has taught us --------------------------
    view = DayView(
        snapshot=snapshot,
        target=target,
        weight_trend=weight.trend(weight_history, day),
        weight_change_7d=weight.change_over(weight_history, day, 7),
        weight_change_30d=weight.change_over(weight_history, day, 30),
        plateau=weight.plateau(weight_history, day),
        history_days_available=len(history),
        weigh_ins_available=len(weight_history),
    )

    view.observed_maintenance = build_observed_maintenance(
        repository, user_id, day, history, weight_history, history_days
    )

    return view


def build_observed_maintenance(
    repository: storage.HealthRepository,
    user_id: str,
    day: date,
    history: list[models.DailyHealthSnapshot],
    weight_history: list[tuple[date, float]],
    history_days: int,
) -> models.MaintenanceEstimate | None:
    """What the data suggests the real maintenance calories are.

    This compares logged intake against the measured weight trend, so it is anchored to
    what the body actually did rather than to what the watch estimated. It returns None
    on thin data instead of guessing -- it is meant to be trusted over Garmin's own
    figure, so a version built from nine weigh-ins would be worse than nothing.
    """
    intake_history: list[tuple[date, float | None]] = []
    garmin_history: list[tuple[date, float | None]] = []

    for days_back in range(history_days):
        past_day = day - timedelta(days=days_back)

        entries = repository.list_entries(user_id, past_day)
        if entries:
            intake_history.append((past_day, nutrition.day_totals(entries).kcal))
        else:
            intake_history.append((past_day, None))

    for snapshot in history:
        garmin_history.append((snapshot.date, snapshot.measured.energy.total_kcal))

    return calibration.observed_maintenance(
        intake_history,
        weight_history,
        day,
        garmin_expenditure=garmin_history,
    )
