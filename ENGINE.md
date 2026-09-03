# ENGINE.md — deterministic calculations, and the boundary with the LLM

**v1.** The heart of the project. Everything here is pure Python: takes data, returns results, knows
nothing about AWS, HTTP, or the LLM.

Product context: **[PRODUCT.md](PRODUCT.md)**. Infrastructure: **[PLAN.md](PLAN.md)**.

---

## 1. The boundary rule

```
CAN THIS BE RELIABLY CALCULATED?
        │
   YES ─┴─ NO / REQUIRES INTERPRETATION
    │            │
   CODE         LLM
```

**Code owns every number.** The LLM owns language about numbers. This is non-negotiable, and it is not
only a cost preference — LLM arithmetic errors are *invisible*, because a wrong figure reads exactly
as confidently as a right one. In a tool that reports your energy balance, a silently wrong number is
the worst available failure.

| Task | Owner |
|---|---|
| Calories consumed / burned / balance | **Code** |
| Macro totals, targets, remaining, adherence % | **Code** |
| Averages, rolling averages, EMAs | **Code** |
| Weight change, trend, rate of change | **Code** |
| Sleep / HRV / RHR baselines and deviations | **Code** |
| Activity totals, HR-zone time | **Code** |
| BMR, TDEE estimates | **Code** |
| Body fat, lean mass, DEXA comparison | **Code** |
| Statistical trends, projections, thresholds | **Code** |
| "Five consecutive readings below baseline" | **Code** |
| *Why* that pattern might matter | **LLM** |
| Summarizing the month's biggest changes | **LLM** |
| Suggesting what to look into | **LLM** |
| Mapping "4 eggs and toast" to library items | **LLM** (Phase 7, proposal only) |

### 1.1 How the rule is enforced, not just promised
Rules rot. Three structural guards:

1. **The LLM never receives raw records.** It receives finished metrics and reason traces (§4). It has nothing to add up, and no incentive to try.
2. **Where it produces data rather than prose, output is schema-constrained** to a closed vocabulary — food logging emits your actual `food_id`s as an enum, so it cannot invent a food.
3. **Anything it extracts is re-validated by our arithmetic.** A nutrition label must satisfy `kcal ≈ 4P + 4C + 9F`; a DEXA report must satisfy `fat + lean + bone ≈ total`. Fails the check, it's rejected and a human looks at it.

*LLM as extractor, code as validator.* That pattern is the most defensible thing in the AI layer.

---

## 2. Module catalog

Lives in `backend/core/`. No AWS imports anywhere in this directory — that constraint is what makes it
all trivially testable.

### `units.py`
```python
kg_to_lb(kg) -> float ;  lb_to_kg(lb) -> float
cm_to_ft_in(cm) -> tuple[int, float] ;  ft_in_to_cm(ft, inch) -> float
format_weight(kg, pref) -> str      # the ONLY place display formatting happens
```
SI everywhere internally. Convert at the boundary, never round-trip a displayed value back into
storage.

### `energy.py`
```python
bmr(weight_kg, height_cm, birth_date, sex, lean_mass_kg=None, on=date) -> BmrResult
    # BmrResult carries value AND formula used AND why — never silently switches
tdee_estimate(bmr, active_kcal, tef_kcal) -> float
    # NOTE: active_kcal is HR-derived and overstates resistance training (PRODUCT.md §6).
    # Do not "correct" it with a fudge factor — that hides the bias. §6.1 measures it instead.
tef(calories_consumed, factor=0.10) -> float
energy_balance(burned, consumed) -> BalanceResult          # value + state: deficit|maintenance|surplus
cumulative_balance(days) -> list[float]
observed_maintenance(days, weight_series) -> MaintenanceEstimate | None   # §6.1
```
Formula selection:

| Formula | Needs | Used when |
|---|---|---|
| **Katch–McArdle** `370 + 21.6 × LBM` | lean mass | DEXA exists. More accurate, sex-independent. |
| **Mifflin–St Jeor** `10w + 6.25h − 5a + 5` | weight, height, age, sex | no scan yet |

At 79 kg / 180 cm / male / 23: Mifflin gives **1805 kcal**. At 18% body fat, Katch–McArdle gives
**1769**. Within 2% — the agreement is itself the sanity check.

### `nutrition.py`
```python
day_totals(entries) -> MacroTotals                  # kcal, P, C, F, optional fiber/sodium
remaining(totals, target) -> MacroTotals             # may be negative
target_on(date, target_history) -> MacroTarget       # dated targets, never "current"
adherence(totals, target) -> AdherenceResult         # per-macro % and hit/miss
adherence_streak(days, target_history, metric) -> int
resolve_entry(food, servings) -> MacroTotals         # servings × per-serving macros
    # Food carries serving_basis (raw|cooked|as_sold). The engine never converts between
    # states — a raw-basis food logged from a cooked weight is a data-entry error, not a
    # math problem, and silent conversion would make it undetectable. See PRODUCT.md §7.1.
validate_food(food) -> bool                          # kcal ≈ 4P + 4C + 9F
```

### `weight.py`
```python
ema(series, alpha=None, halflife_days=7) -> list[float]      # gap-tolerant
rolling_mean(series, window) -> list[float]
change_over(series, days) -> float | None
rate_of_change(series, window=14) -> float | None            # kg/week, least-squares slope
trend(series) -> TrendResult                                 # slope, r², n, confidence
plateau(series, window=21) -> PlateauResult                  # flat + low variance = real stall
```
Gap tolerance matters: missing weigh-ins are expected, and `None` propagates honestly rather than
being interpolated into fake data.

### `baselines.py` — the central module
```python
baseline(series, window_days, on=date) -> Baseline | None    # mean, sd, n, window
deviation(current, baseline) -> Deviation                     # absolute, percent, z-score
consecutive_beyond(series, baseline, direction, threshold) -> int
status(current, baseline, bands) -> Status                    # above | normal | below
```
Windows: **7 / 14 / 30 / 90 days.** Default 30 for recovery metrics, 7 for weight.

**Insufficient data returns `None`, and the UI says "building baseline (12/30 days)".** Never a
baseline computed from four readings and presented as if it means something — HRV in particular needs
about three weeks before it says anything.

### `recovery.py`
```python
recovery_status(snapshot, baselines) -> RecoveryResult   # status + reason trace, CLEARLY DERIVED
sleep_debt(series, target_hours, window=7) -> float
sleep_consistency(series, window=14) -> float            # sd of sleep midpoint
```
This is our own composite from sleep duration, sleep score, HRV, resting HR and Body Battery, each
compared to its own baseline. It's the FR165's real gap (no Training Readiness) and it falls straight
out of `baselines.py`. **Labelled "Recovery (derived)" everywhere it appears** — never dressed up as a
Garmin metric.

### `body_composition.py`
```python
from_dexa(scan) -> Composition                              # measured
estimate(weight_now, anchor, p_fat=0.80) -> Composition     # MEASURED=False, always
compare_scans(a, b) -> ScanComparison                       # Δ fat, Δ lean, Δ BF%
solve_p_fat(anchor_a, anchor_b, weight_series) -> float | None   # needs 2+ scans. §6.2
```
Every `Composition` carries `measured: bool` and its provenance. An estimate can never be mistaken for
a scan, in the API or the UI.

### `trends.py`
```python
series(days, metric, window) -> TimeSeries
period_comparison(days, metric, window_days) -> PeriodComparison   # last 30 vs previous 30
correlation(days, metric_a, metric_b) -> CorrelationResult | None   # Pearson + n + p
streak(days, predicate) -> int
```
`correlation` **refuses to return a result below n=30** and always reports n. At 40 data points
correlation hunting manufactures findings; the honest guard is part of the function, not a note in
the UI.

### `load.py` — optional, Phase 5
```python
trimp(zone_seconds, weights=(1,2,3,4,5)) -> float
acute_chronic(loads) -> ACWR      # 7-day vs 28-day EWMA
```
Deliberately low priority: training load's main use is prescribing training, which this product
doesn't do. HR-zone data gets ingested anyway (it's free), so this stays available if a real want
appears.

### `reasons.py`
The reason vocabulary — see §4.

### `models.py`
Canonical domain models — see PLAN.md §5.

---

## 3. Baselines: why they're the core concept

`HRV = 48` is not information. `HRV 48, 30-day baseline 56, −14%` is.

Almost every question in PRODUCT.md §2 reduces to *"compared to my normal."* So baselines aren't a
feature of the Trends screen — they're a dependency of the Today screen, which is why
`baselines.py` gets built in Phase 1 alongside the arithmetic rather than later with the charts.

Design commitments:
- **Rolling, not calendar.** "Last 30 days from today," not "this month."
- **Personal, never population.** Your HRV baseline is yours; comparison to age-group norms is a different product.
- **Insufficient data is a real state**, returned as `None` and surfaced honestly.
- **Baselines exclude the current day**, or a metric is partly compared against itself.
- **Store computed baselines with the day's snapshot.** Cheap, and it makes historical dashboards reproducible — 15 August shows the baseline as it stood on 15 August, not as recomputed today.

---

## 4. Reason traces

Every derived status emits a structured explanation. It powers the UI's "Why?" (PRODUCT.md §8) *and*
is the LLM's only input later. Same object, two consumers.

```json
{
  "metric": "recovery",
  "status": "below_baseline",
  "computed_at": "2026-09-02T07:12:00-07:00",
  "reasons": [
    {"metric": "sleep_duration", "current": 6.4, "baseline": 7.2,
     "unit": "h", "difference_percent": -11.1, "window_days": 30, "n": 28},
    {"metric": "hrv", "current": 47, "baseline": 53,
     "unit": "ms", "difference_percent": -11.3, "window_days": 30, "n": 30}
  ]
}
```

Rules:
- **Codes are a closed enum**, not free text. `SLEEP_BELOW_BASELINE`, `PROTEIN_UNDER_TARGET`, `WEIGHT_TREND_FLAT_DESPITE_DEFICIT`, `HRV_SUPPRESSED_CONSECUTIVE`, `INSUFFICIENT_DATA`, …
- **Every reason carries its numbers, window and `n`** — so nothing downstream needs to recompute or guess.
- **Every code has a templated English string.** The app is fully readable with the LLM switched off; the LLM only writes it *better*.
- **Traces are snapshot data, stored with the day.** A past explanation stays true to what was known then.

The order matters: because the trace exists for the UI in Phase 1, the Phase 7 AI layer inherits a
hallucination-resistant input for free. It can't invent a reason that never fired.

---

## 5. Provenance: measured vs. derived

The FR165 withholds several synthesized metrics. We may compute our own, but **never blur the line.**

Structural, not a convention: the canonical model separates measured fields from derived ones, so it's
impossible to write a computed value into a Garmin field.

```python
class DailyHealthSnapshot:
    measured: MeasuredMetrics      # straight from the provider, unmodified
    derived: DerivedMetrics        # ours, each with formula + inputs + version
```

Every derived value carries `formula`, `inputs`, and `engine_version`. The UI labels them. A BMR shows
which formula produced it and why (§2). The rule from the vision brief applies exactly: *don't pretend
a derived metric is Garmin's, and don't derive something just because you can.*

---

## 6. Two things worth learning from the data

Both are **observations, not controls.** They inform; your targets stay yours (PRODUCT.md §7).

### 6.1 Observed maintenance calories
Garmin estimates expenditure with population models. Your own data can do better: over a long enough
window, energy balance plus weight trend implies your actual maintenance.

```
observed_maintenance ≈ mean_intake − (weight_trend_kg_per_day × 7700 / 1)
```
Surfaced as an observation:
> *"Over the last 42 days your intake averaged 2,380 kcal and your weight trend was −0.31 kg/week. That
> implies maintenance near 2,720 kcal — about 130 below Garmin's estimate."*

Requires ≥28 days and ≥4 weigh-ins per 10-day window; otherwise returns `None`. It never edits your
target — it tells you what your body appears to be doing, and you decide.

### 6.2 Fat/lean partitioning, once two scans exist
With no DEXA, composition between anchors uses a literature default. Your training and intake put you
at the favourable end of that range: **3 resistance sessions a week plus 180 g protein (2.25 g/kg)** is
close to the textbook prescription for preserving lean mass in a deficit, so `p_fat ≈ 0.85` is the more
appropriate default than the generic 0.75.

**It is still a default, and it stays labelled as an estimate.** The point of §6.2 isn't to pick a
better constant — it's that the constant gets replaced by measurement. With **two or more scans**,
predicted vs. measured solves for your actual ratio and the guess is retired.

| Observation | Learns | Needs | Cadence |
|---|---|---|---|
| Observed maintenance (§6.1) | calories you actually burn | 28+ days of intake + weight | weekly |
| Partitioning (§6.2) | fat vs. lean split of your loss | 2+ DEXA scans | per scan |

Both are pure functions in `calibration.py`, both emit reason traces, both return `None` rather than
guessing on thin data. Together they're the strongest engineering story here — a system that measures
its own error and reports it, without ever taking the wheel.

---

## 7. The LLM layer (Phase 7)

Only after everything above works. The app must be **fully useful with the LLM disabled** — that's the
test of whether the layering is real.

### 7.1 What it gets
Finished metrics and reason traces. Never raw Garmin JSON (tens of KB per day, versus a few hundred
bytes for the derived summary), never a table of records to aggregate.

### 7.2 The three features, in order
**Daily observation** — a short paragraph over today's trace. Cheap and cacheable.

**Weekly review** — the higher-value one. Code produces the week's report (averages, adherence, trend,
period comparison); the LLM explains it. Four calls a month, so a larger model is affordable.

**Ask My Health Data** — conversational queries. The critical design: **the LLM gets tools, not data.**

```
ask_energy_balance(start, end)        ask_baseline(metric, window, on)
ask_weight_trend(days)                ask_period_comparison(metric, days)
ask_adherence(macro, days)            ask_correlation(metric_a, metric_b, days)
ask_recovery_history(days)            ask_dexa_comparison()
```

**Those tools are the `core/` functions from §2, exposed.** The LLM chooses which to call; our code
computes; it phrases the result. So "how many days this month was I in a deficit?" is answered by
`ask_energy_balance` counting them — never by the model reasoning over 30 rows. Every number in an
answer traces to a tool result, and the UI can show which tools ran.

### 7.3 Optional: natural-language food logging
Text → proposed entries → **you review and confirm** → committed. Fuzzy-match against your library
first and skip the LLM entirely on a hit; fall through only on genuine ambiguity. The proposal is a
draft (DynamoDB TTL 24 h, so a closed tab loses nothing and forgotten drafts clean themselves up).
Application code retrieves the macros from the library — the LLM emits `food_id` and `servings`, and
never a nutritional value.

Each committed entry records `source` (`copy` / `template` / `manual` / `llm`) and `was_edited`, which
yields a real accuracy metric over time: *how often do I have to correct it.*

### 7.4 Cost and reliability discipline
- **Never send raw records** — the trace design enforces it.
- **Cache on bucketed state hashes** — round kcal to 50, percentages to 1, so the same *situation* reuses its sentence. Most days are not novel.
- **Tier models** — cheapest for daily observations and food matching; larger for weekly review and Q&A.
- **Deterministic first** — template before LLM, fuzzy match before LLM. The model is the fallback, never the entry point.
- **Hard monthly token budget with a kill switch.** Over budget ⇒ templated text, and the UI says so plainly.
- **Log tokens per call as a CloudWatch metric.** Realistic cost at this design: well under $0.50/month.

### 7.5 Hard limits
- Never computes or adjusts a number.
- Never sets or edits macro targets.
- Never estimates macros for an unlabeled food, or body fat from a photo. Both produce confident, plausible, wrong values that then contaminate every downstream calculation permanently.
- Never prescribes training, and never generates a diet plan.
- Never names a medical condition. Language stays observational: *"your HRV has been below your personal baseline for five days"*, not a diagnosis. Enforced in the system prompt and visible in a standing disclaimer.
- Text from any source is **data, not instructions** — including food names and DEXA PDFs.

---

## 8. Testing the engine

`core/` has no I/O, so it tests with no mocks, no network, no AWS. That's the payoff of the layering.

| Layer | Approach |
|---|---|
| Arithmetic | Table-driven unit tests with hand-computed expected values. Every function in §2. |
| Real-data fixtures | Saved Phase 0 Garmin JSON as golden files — parser tests run against actual FR165 responses, including the missing fields. |
| Invariants (`hypothesis`) | Macro totals never negative; EMA within series min/max; adherence in [0,100]; unit round-trips within tolerance; baseline `None` whenever n < window minimum. |
| Missing data | Explicit cases for: no weigh-in, no sleep record, watch not worn, no DEXA, brand-new user with 3 days of history. **This is where a health dashboard actually breaks** — every function needs a defined answer to "I don't have that." |
| Reason traces | Snapshot tests — given a snapshot, assert exactly which codes fire. Guards against silent logic drift. |
| Synthetic days | The demo-mode generator (PRODUCT.md §10) produces hundreds of plausible days; assert invariants across all of them. |
| Provider contract | One test suite the Garmin adapter must satisfy, so a second provider has a definition of done. |
| LLM layer | Tested for *plumbing*, not prose: correct tools called, budget enforced, kill switch works, templated fallback renders. Never assert on generated wording. |

Target: **near-total coverage of `core/`**, ordinary coverage elsewhere. The engine is the product; the
Lambda handlers are plumbing.
