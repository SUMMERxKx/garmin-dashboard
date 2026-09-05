"""Canonical domain models.

Deliberately NOT shaped like Garmin's JSON. Garmin is one provider that populates this
model; normalising to a provider's shape would inherit that provider's gaps permanently.

Two structural guarantees enforced by the type layout rather than by convention:

  1. `DailyHealthSnapshot.measured` vs `.derived` -- a computed value cannot be written
     into a provider field by accident. (A provenance *flag* gets forgotten; a separate
     field cannot be.)
  2. `Composition.measured: bool` -- an estimate can never render as a DEXA scan.

Every measured field is Optional. A watch left on the charger is a normal Tuesday.
"""

from __future__ import annotations

from datetime import date
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from backend.core import units

# EXCEPTION to the import-the-module rule used everywhere else in this project.
# Several models below have a field literally called `reasons`, and inside a class
# body that name would shadow the module -- so `list[Reason]` would resolve
# to the field instead of the module and Pydantic would fail to build the model.
# Importing the two names directly avoids the collision, and in a file that is
# nothing but type definitions `Reason` on its own is unambiguous anyway.
from backend.core.reasons import Reason

# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------


class Sex(StrEnum):
    """Input variable for the Mifflin-St Jeor formula. Unused once lean mass is known."""

    MALE = "male"
    FEMALE = "female"


class GoalType(StrEnum):
    CUTTING = "cutting"
    MAINTAINING = "maintaining"
    GAINING = "gaining"


class ServingBasis(StrEnum):
    """The weight state a food's label macros refer to.

    The highest-impact field in the nutrition model. 100 g dry rice becomes ~250-300 g
    cooked; logging a cooked weight against dry macros over-counts by 2.5-3x, which is
    larger than a typical daily deficit. The engine NEVER converts between states -- a
    mismatch is a data-entry error, and silent conversion would make it undetectable.
    """

    RAW = "raw"
    COOKED = "cooked"
    AS_SOLD = "as_sold"


class LogSource(StrEnum):
    COPY = "copy"
    TEMPLATE = "template"
    MANUAL = "manual"
    LLM = "llm"


class BalanceState(StrEnum):
    DEFICIT = "deficit"
    MAINTENANCE = "maintenance"
    SURPLUS = "surplus"


class Status(StrEnum):
    ABOVE = "above"
    NORMAL = "normal"
    BELOW = "below"
    UNKNOWN = "unknown"


class BmrFormula(StrEnum):
    MIFFLIN_ST_JEOR = "mifflin_st_jeor"
    KATCH_MCARDLE = "katch_mcardle"


class ActivityKind(StrEnum):
    """Coarse grouping we control, mapped from provider activity types.

    RESISTANCE matters specifically: Garmin's heart-rate-derived calorie estimate runs
    high for lifting, because HR stays elevated between sets without matching oxygen
    cost. We surface that rather than silently "correcting" it.
    """

    RESISTANCE = "resistance"
    RUNNING = "running"
    CARDIO_OTHER = "cardio_other"
    WALKING = "walking"
    OTHER = "other"


# ---------------------------------------------------------------------------
# profile / goals
# ---------------------------------------------------------------------------


class Profile(BaseModel):
    """Birth date, not age -- `age: 23` is silently wrong within a year and quietly
    corrupts every BMR calculation after that. IANA zone, not a UTC offset -- offsets
    change twice a year."""

    user_id: str
    sex: Sex
    birth_date: date
    height_cm: float
    timezone: str = "America/Vancouver"
    unit_preference: units.UnitPreference = units.UnitPreference.METRIC

    def age_on(self, on: date) -> int:
        """How old this person was on a given date.

        Subtracting the years is not enough on its own. Someone born in May is still 22
        in April of their 23rd year -- their birthday has not happened yet -- so we take
        a year back off when the date falls before the birthday.

        Comparing (month, day) tuples works because Python compares them element by
        element: it checks the month first, and only looks at the day if the months
        are equal.
        """
        years_since_birth_year = on.year - self.birth_date.year

        birthday_this_year = (self.birth_date.month, self.birth_date.day)
        date_we_are_asking_about = (on.month, on.day)

        birthday_has_happened_yet = date_we_are_asking_about >= birthday_this_year

        if birthday_has_happened_yet:
            return years_since_birth_year

        return years_since_birth_year - 1


class MacroTarget(BaseModel):
    """Append-only, effective-dated. Overwriting would make every historical dashboard
    wrong, silently and irreversibly. The app never changes these on its own."""

    model_config = ConfigDict(frozen=True)

    effective_from: date
    goal: GoalType
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float

    @property
    def implied_kcal(self) -> float:
        """4/4/9. Should agree with `kcal` to within a few calories."""
        return self.protein_g * 4 + self.carbs_g * 4 + self.fat_g * 9


# ---------------------------------------------------------------------------
# nutrition
# ---------------------------------------------------------------------------


class MacroTotals(BaseModel):
    model_config = ConfigDict(frozen=True)

    kcal: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float | None = None
    sodium_mg: float | None = None

    def __add__(self, other: MacroTotals) -> MacroTotals:
        return MacroTotals(
            kcal=self.kcal + other.kcal,
            protein_g=self.protein_g + other.protein_g,
            carbs_g=self.carbs_g + other.carbs_g,
            fat_g=self.fat_g + other.fat_g,
            fiber_g=_add_optional(self.fiber_g, other.fiber_g),
            sodium_mg=_add_optional(self.sodium_mg, other.sodium_mg),
        )

    def scale(self, factor: float) -> MacroTotals:
        """Multiply everything by `factor` -- used to turn one serving into several."""
        # Fiber and sodium are optional. Scaling an unknown value has to leave it
        # unknown, so those two are handled separately from the rest.
        if self.fiber_g is None:
            scaled_fiber = None
        else:
            scaled_fiber = self.fiber_g * factor

        if self.sodium_mg is None:
            scaled_sodium = None
        else:
            scaled_sodium = self.sodium_mg * factor

        return MacroTotals(
            kcal=self.kcal * factor,
            protein_g=self.protein_g * factor,
            carbs_g=self.carbs_g * factor,
            fat_g=self.fat_g * factor,
            fiber_g=scaled_fiber,
            sodium_mg=scaled_sodium,
        )


def _add_optional(a: float | None, b: float | None) -> float | None:
    """None means 'unknown', not zero -- adding a known to an unknown stays unknown."""
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)


class Food(BaseModel):
    id: str
    name: str
    brand: str | None = None
    serving_desc: str
    serving_g: float | None = None
    serving_basis: ServingBasis
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float | None = None
    sodium_mg: float | None = None

    @property
    def per_serving(self) -> MacroTotals:
        return MacroTotals(
            kcal=self.kcal,
            protein_g=self.protein_g,
            carbs_g=self.carbs_g,
            fat_g=self.fat_g,
            fiber_g=self.fiber_g,
            sodium_mg=self.sodium_mg,
        )


class LogEntry(BaseModel):
    """`macros_snapshot` is denormalised on write: editing a food's macros later must not
    silently rewrite last month's dashboard."""

    id: str
    date: date
    food_id: str
    food_name: str
    servings: float
    macros_snapshot: MacroTotals
    serving_basis: ServingBasis
    meal: str | None = None
    logged_at: datetime | None = None
    source: LogSource = LogSource.MANUAL
    was_edited: bool = False


class MealItem(BaseModel):
    food_id: str
    servings: float | None = None  # None = "set this per day" (rice)


class SavedMeal(BaseModel):
    id: str
    name: str
    items: list[MealItem] = Field(default_factory=list)


class DayTemplate(BaseModel):
    id: str
    name: str
    meal_ids: list[str] = Field(default_factory=list)
    items: list[MealItem] = Field(default_factory=list)


class AdherenceResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    kcal_percent: float
    protein_percent: float
    carbs_percent: float
    fat_percent: float
    protein_target_met: bool
    reasons: list[Reason] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# body
# ---------------------------------------------------------------------------


class WeightEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    weight_kg: float
    source: str = "manual"


class DexaScan(BaseModel):
    """High-quality anchor point. Only the first four fields feed the math."""

    date: date
    total_mass_kg: float
    fat_mass_kg: float
    lean_mass_kg: float
    bone_mass_kg: float | None = None
    body_fat_pct: float
    visceral_fat: float | None = None
    regional: dict[str, float] | None = None
    notes: str | None = None

    def reconciles(self, tolerance_kg: float = 1.5) -> bool:
        """fat + lean + bone should approximate total mass. Guards a misread decimal."""
        parts = self.fat_mass_kg + self.lean_mass_kg + (self.bone_mass_kg or 0.0)
        return abs(parts - self.total_mass_kg) <= tolerance_kg


class Composition(BaseModel):
    """`measured` is the guard that stops an estimate rendering as a scan."""

    model_config = ConfigDict(frozen=True)

    date: date
    weight_kg: float
    fat_mass_kg: float
    lean_mass_kg: float
    body_fat_pct: float
    measured: bool
    anchor_scan_date: date | None = None
    p_fat_used: float | None = None
    reasons: list[Reason] = Field(default_factory=list)


class ScanComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_date: date
    to_date: date
    days_between: int
    weight_change_kg: float
    fat_change_kg: float
    lean_change_kg: float
    body_fat_pct_change: float


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------


class Baseline(BaseModel):
    """Rolling, personal, and excludes the current day -- otherwise a metric is partly
    compared against itself. Insufficient data returns None rather than a baseline built
    from four readings."""

    model_config = ConfigDict(frozen=True)

    metric: str
    mean: float
    sd: float
    n: int
    window_days: int
    computed_on: date


class Deviation(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric: str
    current: float
    baseline: float
    difference: float
    difference_percent: float
    z_score: float | None
    status: Status
    window_days: int
    n: int


class TrendResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    slope_per_day: float
    slope_per_week: float
    r_squared: float
    n: int
    window_days: int


class PlateauResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_plateau: bool
    window_days: int
    slope_per_week: float
    sd: float
    n: int
    reasons: list[Reason] = Field(default_factory=list)


class PeriodComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric: str
    window_days: int
    current_mean: float
    previous_mean: float
    difference: float
    difference_percent: float
    current_n: int
    previous_n: int


class CorrelationResult(BaseModel):
    """Refuses to return below n=30. At 40 data points correlation hunting manufactures
    findings, so the guard lives in the function rather than in a UI footnote."""

    model_config = ConfigDict(frozen=True)

    metric_a: str
    metric_b: str
    r: float
    n: int


# ---------------------------------------------------------------------------
# energy
# ---------------------------------------------------------------------------


class BmrResult(BaseModel):
    """Carries the formula used AND why -- never a silent switch between formulas."""

    model_config = ConfigDict(frozen=True)

    kcal: float
    formula: BmrFormula
    reasons: list[Reason] = Field(default_factory=list)


class BalanceResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    burned_kcal: float
    consumed_kcal: float
    balance_kcal: float
    state: BalanceState
    reasons: list[Reason] = Field(default_factory=list)


class MaintenanceEstimate(BaseModel):
    """Observation, never a control. It tells you what your body appears to be doing;
    changing a target stays an explicit act."""

    model_config = ConfigDict(frozen=True)

    kcal: float
    days_used: int
    mean_intake_kcal: float
    weight_slope_kg_per_week: float
    garmin_mean_expenditure_kcal: float | None = None
    difference_vs_garmin_kcal: float | None = None
    reasons: list[Reason] = Field(default_factory=list)


class ACWR(BaseModel):
    model_config = ConfigDict(frozen=True)

    acute: float
    chronic: float
    ratio: float | None


# ---------------------------------------------------------------------------
# the daily snapshot
# ---------------------------------------------------------------------------


class Activity(BaseModel):
    provider_id: str
    kind: ActivityKind
    type_raw: str
    start: datetime | None = None
    duration_min: float | None = None
    calories: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    #: seconds in HR zones 1-5, if the provider reports them
    zone_seconds: list[float] | None = None


class Energy(BaseModel):
    resting_kcal: float | None = None
    active_kcal: float | None = None
    total_kcal: float | None = None


class ActivityMetrics(BaseModel):
    steps: int | None = None
    step_goal: int | None = None
    distance_m: float | None = None
    intensity_minutes: float | None = None
    workout_minutes: float | None = None
    activities: list[Activity] = Field(default_factory=list)


class Heart(BaseModel):
    resting_hr: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    hrv_ms: float | None = None


class Sleep(BaseModel):
    duration_min: float | None = None
    score: float | None = None
    start: datetime | None = None
    end: datetime | None = None
    deep_min: float | None = None
    light_min: float | None = None
    rem_min: float | None = None
    awake_min: float | None = None

    @property
    def has_stages(self) -> bool:
        return any(v is not None for v in (self.deep_min, self.light_min, self.rem_min))


class RecoveryMetrics(BaseModel):
    body_battery_high: float | None = None
    body_battery_low: float | None = None
    body_battery_current: float | None = None
    stress_avg: float | None = None
    respiration_avg: float | None = None
    spo2_avg: float | None = None


class Fitness(BaseModel):
    vo2max: float | None = None


class MeasuredMetrics(BaseModel):
    """Straight from the provider, unmodified. Every field Optional."""

    energy: Energy = Field(default_factory=Energy)
    activity: ActivityMetrics = Field(default_factory=ActivityMetrics)
    heart: Heart = Field(default_factory=Heart)
    sleep: Sleep = Field(default_factory=Sleep)
    recovery: RecoveryMetrics = Field(default_factory=RecoveryMetrics)
    fitness: Fitness = Field(default_factory=Fitness)
    #: dotted field path -> provider name, recording what this sync actually returned.
    #: Absence here is how "field coverage" becomes an observability metric.
    provenance: dict[str, str] = Field(default_factory=dict)


class RecoveryResult(BaseModel):
    """OURS, not Garmin's. The FR165 has no Training Readiness; this is our composite
    against personal baselines and is labelled as derived everywhere it appears."""

    model_config = ConfigDict(frozen=True)

    status: Status
    score: float | None = None
    inputs_used: list[str] = Field(default_factory=list)
    reasons: list[Reason] = Field(default_factory=list)


class DerivedMetrics(BaseModel):
    """Ours. Each value carries formula/inputs so the UI can label it honestly."""

    bmr: BmrResult | None = None
    balance: BalanceResult | None = None
    recovery_status: RecoveryResult | None = None
    composition: Composition | None = None
    baselines: dict[str, Baseline] = Field(default_factory=dict)
    deviations: dict[str, Deviation] = Field(default_factory=dict)
    load: ACWR | None = None
    engine_version: str = "0.1.0"
    reasons: list[Reason] = Field(default_factory=list)


class NutritionTotals(BaseModel):
    consumed: MacroTotals = Field(default_factory=MacroTotals)
    target: MacroTarget | None = None
    remaining: MacroTotals | None = None
    adherence: AdherenceResult | None = None
    entry_count: int = 0


class BodyMetrics(BaseModel):
    weight_kg: float | None = None
    weight_ema_kg: float | None = None
    composition: Composition | None = None


class DailyHealthSnapshot(BaseModel):
    """One local calendar day. `measured` and `derived` are structurally separate."""

    date: date
    measured: MeasuredMetrics = Field(default_factory=MeasuredMetrics)
    derived: DerivedMetrics = Field(default_factory=DerivedMetrics)
    nutrition: NutritionTotals = Field(default_factory=NutritionTotals)
    body: BodyMetrics = Field(default_factory=BodyMetrics)
