# WALKTHROUGH.md — what the code does, top to bottom

**Written so you can explain this to someone else.** Every file, every function, every
design decision, and why each one is the way it is.

Numbers used in examples are illustrative, not from your actual health data.

| Doc | Purpose |
|---|---|
| [PRODUCT.md](PRODUCT.md) | what it does for a user |
| [ENGINE.md](ENGINE.md) | the calculation contract |
| [PLAN.md](PLAN.md) | architecture and phases |
| **WALKTHROUGH.md** | **this file — the code itself** |
| [LEARNING.md](LEARNING.md) | the tools, and how deep to learn each |

---

## 0. The sixty-second version

> It's a personal health dashboard. A scheduled job pulls my Garmin data, I log food
> against a small library of things I actually eat, and a deterministic engine computes
> energy balance, recovery status and body-composition trends against my own historical
> baselines. Every derived number carries a structured explanation of how it was
> produced. An LLM gets added at the very end, and it only ever turns those finished
> numbers into sentences — it never calculates anything.

If you say one more thing, say this:

> The interesting constraint is the split. Anything that can be reliably calculated is
> calculated by code with tests. The LLM only interprets. That's enforced structurally,
> not by policy — it physically never receives raw records.

---

## 1. The three layers

```
LAYER 1 — ACQUISITION            LAYER 2 — DETERMINISTIC ENGINE      LAYER 3 — LLM
────────────────────             ──────────────────────────────      ─────────────
Garmin API                       energy balance                      explain
  ↓                              macro totals & adherence            find patterns
raw JSON (immutable)             personal baselines (7/30/90d)        summarise
  ↓                              recovery composite                  answer questions
canonical model                  weight EMA & trend
  ↓                              body composition
food log (mine)                  observed maintenance
weight log (mine)                reason traces
                                         │
                                         └──► finished numbers + traces ──► LLM
```

**Why the separation matters:** LLM arithmetic errors are *invisible*. A wrong calorie
figure reads exactly as confidently as a right one. In a tool that reports your energy
balance, a silently wrong number is the worst possible failure. So the LLM is handed
conclusions, never inputs.

---

## 2. What exists today

| Built | Not built yet |
|---|---|
| All 11 engine modules, 99% covered | The normalizer (`garmin.py::normalize`) |
| The provider port + Garmin fetch adapter | Persistence (DynamoDB / SQLite) |
| Phase 0 probe, **already run** | The API (FastAPI) |
| Seed food library (provisional values) | Any frontend |
| 183 tests, ruff clean | Anything AWS |

Phase 0 is done. Phase 1 is done. Phase 2 is next.

---

## 3. Repo map

```
pyproject.toml                  deps, pytest/ruff config, package declaration
README.md                       setup + how to run
seed/
  food-library.template.yaml    pristine all-null template
  food-library.yaml             working file, PROVISIONAL values
fixtures/
  raw/garmin/dt=YYYY-MM-DD/     real probe output — GITIGNORED (health data)
  sample/                       anonymised fixtures for tests (committed)
docs/
  fr165-fields.md               probe report: field names + types, NO values
scripts/
  garmin_probe.py               Phase 0 discovery tool
backend/
  core/                         PURE. no AWS, no HTTP, no I/O, no clock.
    models.py                   canonical domain types
    reasons.py                  the closed explanation vocabulary
    units.py                    SI <-> display, the only conversion site
    baselines.py                rolling personal baselines  ← everything leans on this
    energy.py                   BMR, TDEE, energy balance
    nutrition.py                totals, dated targets, adherence
    weight.py                   EMA, trend, plateau detection
    recovery.py                 the derived recovery composite
    body_composition.py         DEXA anchors + estimates
    trends.py                   period comparison, correlation
    calibration.py              observed maintenance, guardrails
  providers/
    base.py                     the port (Protocol) + capabilities
    garmin.py                   endpoint registry + fetch adapter
    introspect.py               response discovery (used by the probe)
  tests/                        15 test files
```

**One rule about `backend/core/`:** it imports nothing from AWS, HTTP, or the provider
libraries. That's not a convention — `tests/test_architecture.py` parses the AST of every
file in it and fails the build otherwise. It's what makes the engine testable with zero
mocks.

---

# PART 1 — `scripts/garmin_probe.py`

## 1.1 Why this script exists before anything else

The Forerunner 165 is a mid-range watch. It does **not** report Training Readiness,
Training Status or Training Load — those start at the FR265. But nobody publishes a
machine-readable list of what it *does* report, and `garminconnect` is an unofficial
library wrapping an undocumented API.

So writing field-extraction code first would mean guessing at JSON shapes. The probe
replaces guessing with evidence. It is the entire content of "Phase 0".

## 1.2 Top of file — paths and constants

```python
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))          # so `backend.*` imports work when run as a script

TOKEN_DIR    = REPO / ".garmin_tokens"           # gitignored, mode 0700
FIXTURE_ROOT = REPO / "fixtures" / "raw" / "garmin"
REPORT       = REPO / "docs" / "fr165-fields.md"
```

Two deliberate destinations:

- **`fixtures/raw/`** gets the *full* responses. Gitignored, because they contain real health data and this repo may end up public.
- **`docs/fr165-fields.md`** gets a **structure-only** report — field names, types, presence, never a value. Safe to commit.

`_rel()` is a small helper that prints repo-relative paths, falling back to absolute
rather than raising if the report is redirected elsewhere.

## 1.3 `connect()` — the authentication flow

This is the most security-relevant function in the codebase, and the design came out of a
constraint.

```python
TOKEN_DIR.mkdir(mode=0o700, exist_ok=True)
has_bundle = any(TOKEN_DIR.iterdir())

if has_bundle:
    email_arg = password = None                    # ← the whole point
else:
    email_arg = ... input()
    password  = getpass("...")                     # never echoed, never stored
```

Then a single call does everything:

```python
client = Garmin(email=email_arg, password=password, prompt_mfa=prompt_mfa)
client.login(tokenstore)
del password
```

**What `login(tokenstore)` actually does** (I read the library source rather than assuming):

1. Loads a saved token bundle from the path, if one exists.
2. Proactively refreshes the access token if it is close to expiry — avoiding the SSO endpoint entirely.
3. If no usable bundle, falls back to a credential login, calling `prompt_mfa` for the code.
4. Persists the resulting bundle back to the path.
5. If cached tokens are rejected by the API, discards them and does a full re-login.
6. Sets `self.password = None` after success, so the plaintext doesn't linger on the heap.

**The property that matters:** once the bundle exists, *no password is needed at all.* This
is exactly what the production design depends on — the ingest Lambda will hold only a token
bundle, so **the Garmin password never enters the cloud**. Worst case in a total AWS
compromise is a revocable token, not a reusable credential.

And note where that design came from: MFA is interactive, and Lambda can't be interactive.
The constraint forced the better architecture. That's a good thing to be able to say out
loud.

> **Correction worth knowing:** earlier drafts of the plan said this library used `garth`
> for OAuth. As of garminconnect 0.3.11 that is no longer true — it depends on `curl_cffi`,
> `requests` and `ua-generator`, and manages tokens itself. The *design* survived; only the
> mechanism moved. Which is why the plan now says to pin the version.

## 1.4 `probe_day()` — fetch and save

Calls `GarminProvider.fetch_day(on)` (Part 2), then writes one JSON file per endpoint:

```
fixtures/raw/garmin/dt=2026-09-02/user_summary.json
                                 /sleep.json
                                 /hrv.json           ... 17 files
```

The console output distinguishes three outcomes per endpoint, which turns out to matter a
lot:

```
[tier 1] user_summary        ok      42 top-level item(s)
[tier 2] max_metrics         EMPTY   (no data for this day)
[tier 2] respiration         FAILED  GarminConnectConnectionError: 404
```

## 1.5 The discovery trick — `summarize()` and `find_metrics()`

These live in `backend/providers/introspect.py` so they're unit-testable.

**The naive approach** would be to read known field paths:

```python
sleep_minutes = payload["dailySleepDTO"]["sleepTimeSeconds"] / 60   # a guess
```

If the guess is wrong you get a `KeyError` and learn nothing. So instead:

```python
def summarize(obj, prefix="", depth=0, max_depth=3) -> list[tuple[str, str]]:
    """Field paths and TYPE NAMES. Never values."""
```

It walks the whole response tree emitting `("dailySleepDTO.sleepTimeSeconds", "int")`
pairs. Two details:

- **Lists are sampled at index 0 only.** One element is enough to learn a shape, and walking a 1,440-point intraday heart-rate series would bury the signal.
- **`None` becomes the literal type `"null"`.** This distinction turns out to be critical — see §1.7.

Then `find_metrics()` searches those paths for *key fragments* rather than exact paths:

```python
METRIC_PATTERNS = {
    "sleep duration": ("sleeptimeseconds", "sleepdurationseconds", "totalsleepseconds"),
    "HRV":            ("hrv", "lastnightavg", "weeklyavg", "hrvsummary"),
    ...
}
```

For each leaf key it lowercases, strips underscores and `[]`, and checks whether any
pattern is a substring. So the probe *reports where each metric actually lives* instead of
failing when a guess is wrong. That inversion — search instead of assert — is the whole
idea of the script.

## 1.6 `write_report()` and the privacy property

Produces three sections in `docs/fr165-fields.md`:

1. **Metric availability** — each metric of interest and the endpoint/path where it was found, or **not found**.
2. **Endpoint outcomes** — ok / empty / failed, per endpoint.
3. **Response structure** — the type tree for each endpoint, capped at 60 fields.

Then it checks the tier-1 list and shouts if any is missing:

```python
missing_tier1 = missing_tier_1(hits)   # sleep duration, HRV, resting HR,
                                       # body battery, total calories, steps
```

**The privacy property is tested**, not just intended:

```python
def test_summarize_never_emits_a_value():
    payload = {"restingHeartRate": 53, "note": "SECRET-VALUE-12345"}
    rendered = "\n".join(f"{p}: {k}" for p, k in summarize(payload))
    assert "SECRET-VALUE-12345" not in rendered
    assert "53" not in rendered
    assert "restingHeartRate: int" in rendered
```

That's what makes the report committable from a repo holding real health data.

## 1.7 What the probe actually found — and the trap it exposed

Run against your FR165 for 2026-08-31 → 2026-09-02:

**Available, tier 1 — the dashboard is viable as designed:**

| Metric | Real path |
|---|---|
| total / active / resting calories | `user_summary.totalKilocalories`, `.activeKilocalories`, `.bmrKilocalories` |
| steps, distance, intensity minutes | `user_summary.totalSteps`, `.totalDistanceMeters`, `.moderateIntensityMinutes` |
| sleep duration | `sleep.dailySleepDTO.sleepTimeSeconds` |
| **sleep score (numeric)** | `sleep.dailySleepDTO.sleepScores.overall.value` |
| sleep stages | `.deepSleepSeconds`, `.lightSleepSeconds`, `.remSleepSeconds`, `.awakeSleepSeconds` |
| sleep start/end | `.sleepStartTimestampLocal`, `.sleepEndTimestampLocal` |
| **HRV** | `hrv.hrvSummary.lastNightAvg` (+ `weeklyAvg`, `status`, and Garmin's own `baseline`) |
| resting HR | `user_summary.restingHeartRate` |
| body battery | `user_summary.bodyBatteryHighestValue` / `ChargedValue` / `DrainedValue` |
| stress | `user_summary.averageStressLevel` |
| **respiration** (bonus) | `user_summary.avgWakingRespirationValue` |
| weight | `daily_weigh_ins.dateWeightList[]` |

**Confirmed unavailable:**

| Metric | Evidence |
|---|---|
| Training Readiness | endpoint returns `[]` |
| Training Status | endpoint returns 200 with **every field `null`** |
| VO2 max | `max_metrics` returns `[]`; `training_status.mostRecentVO2Max` is `null` |
| SpO2 / Pulse Ox | endpoint returns a full envelope with **every value field `null`** |

### The trap

Look at that table again. `training_status` and `spo2` both came back **"ok"** in the
endpoint-outcomes table — HTTP 200, a well-formed body, plenty of top-level keys. And both
are completely empty of data.

**So "the endpoint succeeded" is not the same as "the metric is available."** A monitoring
system that alarms on HTTP errors would report this pipeline as perfectly healthy while it
silently produced a dashboard with no recovery data on it.

This is precisely why the design has two things that might otherwise look like
over-engineering:

- **`provenance: dict[str, str]`** on the canonical model, recording which fields a sync actually populated.
- **"field coverage" as an observability metric** rather than endpoint success (PLAN.md §12).

That call was made before the probe ran. The probe justified it. Good example of a design
decision paying rent.

### Two consequences for the engine

1. **The derived recovery composite is not optional.** With no Training Readiness and no Training Status, `core/recovery.py` computing our own status from sleep/HRV/RHR/Body Battery against personal baselines is the *only* way to get a recovery number. It has to be labelled as ours, but it's load-bearing.
2. **Garmin ships its own HRV baseline** (`hrvSummary.baseline`). We still compute our own, because every other metric needs one and consistency beats mixing sources — but Garmin's `status` is worth storing as a measured field so the two can be compared. That comparison is genuinely interesting: it's a free check on whether our baseline logic is sane.

---

# PART 2 — the provider layer

## 2.1 `base.py` — the port

```python
@runtime_checkable
class MetricsProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities
    def fetch_day(self, on: date) -> RawPayloads: ...
    def normalize(self, raw: RawPayloads) -> Any: ...
```

A `Protocol` rather than an abstract base class: structural typing, so nothing has to
inherit from anything. `@runtime_checkable` lets a test assert conformance.

**Why bother with a port for one provider?** Not for pluggability — the plan explicitly
rejects a plugin registry. It's for one thing: it forces the canonical model to be shaped
by **what the engine needs**, not by what Garmin returns. Normalise to a provider's JSON
and you inherit that provider's gaps permanently.

And the FR165 tests the abstraction for free: it reports no training load, so the engine
*already* has to handle "provider doesn't supply this" from day one.

Three supporting types:

- **`Endpoint`** — a frozen dataclass: name, method, arg style, tier, what it feeds.
- **`ProviderCapabilities`** — what this device actually supplies, *discovered* rather than assumed. `caps.has("hrv")`.
- **`RawPayloads`** — exactly what came back, before parsing, plus a per-endpoint error map.

## 2.2 `garmin.py` — the registry as data

```python
ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint("user_summary", "get_user_summary", ArgStyle.DATE, 1, "energy+activity", "..."),
    Endpoint("sleep",        "get_sleep_data",   ArgStyle.DATE, 1, "recovery", "..."),
    ...
    Endpoint("training_readiness", "get_training_readiness", ArgStyle.DATE, 2, "-",
             "expected unavailable: FR265 and up"),
)
```

17 endpoints, selected against the six dashboard questions — *not* against what the API
exposes. Golf metrics, race predictors and per-second GPS streams are all available and
all irrelevant.

Three things this shape buys:

- **The probe is generic.** It iterates the registry; adding an endpoint is one line, no new code.
- **Tiers are explicit.** Tier 1 must be enough to render the dashboard alone; tier 2 only enriches.
- **The "expected empty" endpoints are probed anyway**, so the FR165 gap is *proven* rather than assumed. And it paid off — that's how we learned `training_status` returns 200-with-nulls.

There's also a test that catches registry typos without a network call:

```python
def test_endpoint_methods_exist_on_the_real_client():
    from garminconnect import Garmin
    missing = [e.method for e in ENDPOINTS if not hasattr(Garmin, e.method)]
    assert not missing
```

## 2.3 `fetch_day()` — failure isolation

```python
for endpoint in ENDPOINTS:
    try:
        method = getattr(self._client, endpoint.method)
        if endpoint.args == ArgStyle.DATE:
            payloads[endpoint.name] = method(cdate)
        elif endpoint.args in (ArgStyle.RANGE, ArgStyle.START_END):
            payloads[endpoint.name] = method(cdate, cdate)
        else:
            payloads[endpoint.name] = method()
    except Exception as exc:
        errors[endpoint.name] = f"{type(exc).__name__}: {exc}"
```

A broad `except` is usually a smell. Here it's the requirement: **one endpoint returning
404 must not cost the other sixteen.** No HRV before the baseline forms is a normal
Tuesday, not an outage. The errors are collected and reported, not swallowed.

## 2.4 `normalize()` — deliberately unimplemented

```python
def normalize(self, raw: RawPayloads) -> Any:
    raise NotImplementedError(
        "Normalization is written against real FR165 fixtures in Phase 0, not against "
        "guessed response shapes. Run scripts/garmin_probe.py first."
    )
```

With a test asserting it raises. This is Phase 0 discipline made executable: you cannot
accidentally ship field extraction built on assumptions. **Now that fixtures exist, this is
the next thing to write** — and it'll be written against `sleepScores.overall.value`, a path
discovered rather than guessed.

---

# PART 3 — the engine, module by module

Everything below is pure: takes data, returns data. No I/O, no clock, no network.

## 3.1 `models.py` — the canonical types

The most important thing here is a *structural* guarantee:

```python
class DailyHealthSnapshot(BaseModel):
    date: date
    measured: MeasuredMetrics      # from the provider, unmodified
    derived:  DerivedMetrics       # ours: formula + inputs + engine_version
    nutrition: NutritionTotals
    body: BodyMetrics
```

**Why two separate fields instead of one flat model with a `source` flag?** Because a flag
gets forgotten. A separate field *cannot* be written into by accident. If a computed
recovery score can only live in `derived`, then no refactor six months from now can quietly
present it as a Garmin metric. The plan required "never pretend a derived metric is
Garmin's"; this is that requirement expressed as a type.

Other decisions embedded here:

| Field | Decision | Why |
|---|---|---|
| `Profile.birth_date` | store birth date, never `age` | `age: 23` is silently wrong within a year and corrupts every BMR after |
| `Profile.timezone` | IANA string, never a UTC offset | offsets change twice a year; "which day did that 11pm workout belong to" is a bug found weeks later |
| `WeightEntry` | history, never a profile field | a single mutable `weight` destroys every trend the product exists to show |
| `MacroTarget.effective_from` | append-only, dated | overwriting makes every historical dashboard wrong, silently |
| `LogEntry.macros_snapshot` | denormalised on write | editing a food's label later must not rewrite last month's totals |
| `Food.serving_basis` | `raw` / `cooked` / `as_sold` | see §3.6 — this is the biggest accuracy risk in the whole system |
| `Composition.measured: bool` | required | an estimate can never render as a DEXA scan |
| every `MeasuredMetrics` field | `Optional` | a watch on the charger is a normal Tuesday |

`MacroTotals` is a frozen value object with `__add__` and `.scale()`, so summing a day is
`sum(entries)`. One subtlety:

```python
def _add_optional(a, b):
    """None means 'unknown', not zero -- adding a known to an unknown stays unknown."""
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)
```

Fiber and sodium are optional. If one food doesn't report fiber, the day's fiber total is
partly unknown, and silently treating it as zero would be a lie.

## 3.2 `reasons.py` — the explanation vocabulary

```python
class ReasonCode(StrEnum):
    SLEEP_BELOW_BASELINE = "SLEEP_BELOW_BASELINE"
    HRV_SUPPRESSED_CONSECUTIVE = "HRV_SUPPRESSED_CONSECUTIVE"
    WEIGHT_TREND_FLAT_DESPITE_DEFICIT = "WEIGHT_TREND_FLAT_DESPITE_DEFICIT"
    BMR_FORMULA_KATCH_MCARDLE = "BMR_FORMULA_KATCH_MCARDLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ...   # 34 codes
```

A `Reason` carries its own numbers so nothing downstream has to recompute:

```python
Reason(code=ReasonCode.HRV_BELOW_BASELINE, metric="hrv", current=47, baseline=53,
       unit="ms", difference_percent=-11.3, window_days=30, n=30)
```

and renders itself from a template table:

```
"HRV was 47 ms, 11.3% below your 30-day baseline of 53."
```

**Four properties, each tested:**

1. **Codes are a closed enum.** Free-text reasons would defeat the purpose.
2. **Every code has a template** — `test_every_code_has_a_template`. The app is fully readable with the LLM switched off; the LLM only writes it *better*.
3. **No template leaks a placeholder** — `test_every_template_renders_without_placeholders_leaking` renders all 34 with a full detail dict and asserts no stray `{` survives.
4. **`Reason` is frozen.** Traces are snapshot data; a past explanation must stay true to what was known then.

The `_fmt` helper exists for one reason: `round(52.20000000001, 1)` renders as `52.2`, not
`52.200000000000003`. Small thing, but the alternative shows up in the UI.

**Why this module is the load-bearing one for Layer 3:** the reason trace is the LLM's
*only* input. It receives already-computed conclusions with already-computed values. It has
nothing to add up, and it cannot invent a reason that never fired. The hallucination
resistance is architectural, not prompt-engineered.

And note the ordering: the trace is built in Phase 1 for the *UI's* "Why?" button. The AI
layer in Phase 7 inherits it for free. Same object, two consumers.

## 3.3 `units.py` — one conversion site

SI everywhere internally: kg, cm, kcal, grams, minutes. Two rules:

1. **Never do math on display units.** The engine only ever sees kg.
2. **Never round-trip.** 79 kg → 174.2 lb → 79.01 kg. Store canonical, format for display, never parse a displayed value back into storage.

One function is worth pointing out:

```python
def format_protein_target(grams_per_kg, pref):
    if pref is UnitPreference.IMPERIAL:
        return f"{grams_per_kg * KG_PER_LB:.2f} g/lb"      # 1.02 g/lb
    return f"{grams_per_kg:.2f} g/kg"                       # 2.25 g/kg
```

A lifter using imperial thinks in g/lb. Showing them g/kg is the tell that units were
bolted on afterwards.

## 3.4 `baselines.py` — the module everything leans on

**The core insight of the whole product:** `HRV = 48` is not information. `HRV 48, 30-day
baseline 56, −14%` is.

Almost every question the dashboard answers reduces to *"compared to my normal."* So
baselines are a dependency of the **Today** screen, not a feature of the Trends screen —
which is why this gets built in Phase 1 alongside the arithmetic.

### The window is half-open

```python
def window_values(series, on, window_days, *, exclude_on=True):
    start = on - timedelta(days=window_days)
    ...
    if day > on or (exclude_on and day >= on):
        continue
```

**`on` is excluded.** If today's HRV were included in the baseline it compares against,
the metric would be partly compared against itself, which flattens every deviation. Subtle,
and it took a test to make me state it explicitly.

### Insufficient data returns `None`

```python
def default_min_n(window_days: int) -> int:
    return max(3, window_days // 2)      # 30-day window needs 15 readings
```

```python
if len(values) < required:
    return None
```

A baseline computed from four readings, presented as if it means something, is worse than
no baseline. HRV in particular needs about three weeks before it says anything. So the
absence is a real state that propagates to the UI as *"still building your baseline
(12 of 15 days)"* — via `baseline_building_reason()`.

### The band has a floor

```python
def band_for(base, *, min_relative=0.03):
    """One SD, but never tighter than 3% of the mean."""
    return max(base.sd, abs(base.mean) * min_relative)
```

Without the floor, a freakishly stable week gives `sd ≈ 0`, and then *every* trivial wobble
flags as a deviation. Tested directly: 30 days of identical values, then 101 against a
baseline of 100 reads `NORMAL`, and 110 reads `ABOVE`.

### `status_of` reports direction, not judgement

Whether "above" is good is the caller's business — higher HRV is good, higher resting HR is
not. That semantic lives in `recovery.py`, not here. Keeping them separate is why this
module stays reusable.

### `consecutive_beyond` — gaps break runs

```python
value = by_day.get(day)
if value is None:
    break
```

Five readings spread over three weeks is **not** a five-day streak. A missing day breaks
the run rather than being skipped over. Same principle appears in `trends.streak`.

## 3.5 `energy.py` — BMR, TDEE, balance

### Formula selection is recorded, never silent

```python
if lean_mass_kg is not None:
    kcal = 370.0 + 21.6 * lean_mass_kg          # Katch-McArdle
    ... reasons=[Reason(code=BMR_FORMULA_KATCH_MCARDLE, ...)]
age = profile.age_on(on)
offset = 5.0 if profile.sex == "male" else -161.0
kcal = 10.0*weight_kg + 6.25*profile.height_cm - 5.0*age + offset   # Mifflin-St Jeor
```

| Formula | Needs | Used when |
|---|---|---|
| **Katch–McArdle** `370 + 21.6 × LBM` | lean mass | a DEXA exists. More accurate, and sex-independent. |
| **Mifflin–St Jeor** | weight, height, age, sex | no scan yet |

Worked with your numbers — 80 kg, 180 cm, male, 23:

```
Mifflin-St Jeor:  10(80) + 6.25(180) - 5(23) + 5  =  800 + 1125 - 115 + 5  =  1815 kcal
Katch-McArdle:    at 18% BF, LBM 65.6 kg -> 370 + 21.6(65.6)              =  1787 kcal
```

They land within 2%, and a test asserts that. **The agreement is the sanity check** — if
they diverged wildly, one of the inputs would be wrong.

`BmrResult` carries `formula` *and* a reason explaining the choice. When you get your first
DEXA and the number steps by ~30 kcal, the dashboard will say why instead of just changing.

### The resistance-training caveat is surfaced, not corrected

```python
def tdee_estimate(bmr_kcal, active_kcal, consumed_kcal=None, *, include_tef=True):
    """NOTE: `active_kcal` from Garmin is heart-rate-derived and overstates resistance
    training -- HR stays elevated between sets without matching oxygen cost. Do NOT
    apply a fudge factor here; that would hide the bias."""
```

This is a real problem with your data specifically: 3 of your 5 weekly sessions are
resistance training, and Garmin will inflate those days. The tempting fix is a correction
factor. **That would be wrong**, because a fudge factor hides the very signal
`calibration.observed_maintenance` exists to measure (§3.11).

Instead, `energy_balance()` attaches a reason when lifting is present:

```python
lifting = resistance_minutes(activities)
if lifting > 0:
    reasons.append(Reason(code=RESISTANCE_CALORIES_UNRELIABLE,
                          metric="active_kcal", detail={"minutes": round(lifting)}))
```

→ *"Expenditure includes 58 min of resistance training, where Garmin's heart-rate-based
estimate tends to run high."*

### The maintenance band

```python
MAINTENANCE_BAND_KCAL = 100.0
```

`|balance| ≤ 100` reads as maintenance rather than a deficit. This matters more than it
looks for your setup — a rest day at ~2400 TDEE against a fixed 2350 target is a 50 kcal
gap, which is *maintenance*, not a deficit. A test asserts exactly that case. Reporting it
as "deficit: −50" would be technically true and practically misleading.

## 3.6 `nutrition.py` — and the biggest accuracy risk in the system

### `serving_basis`: the field that matters most

```python
def resolve_entry(food: Food, servings: float) -> MacroTotals:
    """The engine never converts between raw and cooked weight. A raw-basis food logged
    from a cooked weight is a data-entry ERROR, not a math problem, and silent conversion
    would make it undetectable."""
    return food.per_serving.scale(servings)
```

Why this is the highest-stakes decision in the nutrition model:

```
100 g dry rice  ->  ~250-300 g cooked
```

Weigh your rice cooked, apply dry-weight macros, and you over-count by **2.5–3×**. On
200 g of rice a day that's several hundred calories — **larger than your entire deficit**.
The dashboard would show a deficit while you ate at maintenance, and you'd conclude the
whole system was broken.

```
200 g raw chicken  ->  ~150 g cooked
```

Same error in the opposite direction: about a third *under* on protein.

So: every food declares its basis, the basis travels with each logged entry, the UI shows
it, and the engine refuses to convert. If the numbers ever look wrong, a mismatch is
*visible* rather than baked in.

### Dated targets

```python
def target_on(on: date, targets: Sequence[MacroTarget]) -> MacroTarget | None:
    applicable = [t for t in targets if t.effective_from <= on]
    return max(applicable, key=lambda t: t.effective_from) if applicable else None
```

A dashboard for 15 August is scored against August's target, not today's. Returns `None`
for a date before any target existed, rather than inventing one.

### The 4/4/9 validator

```python
def validate_food(food: Food) -> bool:
    expected = implied_kcal(food.protein_g, food.carbs_g, food.fat_g)
    tolerance = max(15.0, expected * 0.10)
    return abs(food.kcal - expected) <= tolerance
```

Protein and carbs are 4 kcal/g, fat is 9. The tolerance is deliberately loose — labels
round, and fiber is counted differently in different jurisdictions. **The goal isn't
policing label rounding, it's catching a misplaced decimal point** (a 10× error). Tested
both ways: a real label passes, `165 → 1650` fails.

This same guard is what will bound the LLM later. When vision reads a nutrition label or a
DEXA report, *our arithmetic* validates the extraction. **LLM as extractor, code as
validator** — that's the pattern worth naming out loud.

## 3.7 `weight.py` — trend over readings, always

### The EMA is time-weighted

Manual weigh-ins mean gaps. A plain EMA assumes even spacing, which is wrong here: a
reading after five days should move the average more than one taken the next morning.

```python
gap = max((day - previous_day).days, 1)
alpha = 1.0 - 0.5 ** (gap / halflife_days)
current = current + alpha * (value - current)
```

With a 7-day half-life: a 1-day gap gives α ≈ 0.094, a 7-day gap gives α = 0.5, a 14-day
gap gives α = 0.75. Correct handling of irregular sampling, in three lines. Tested
directly by comparing a tight-gap series against a loose-gap one.

### Trend is least-squares, with `r²`

```python
slope = sxy / sxx
r_squared = sxy**2 / (sxx * syy)
```

`r²` is reported so the UI can say how much to trust the slope. A test builds a perfectly
linear 28-day decline at −0.06 kg/day and asserts the recovered slope is −0.42 kg/week with
`r² ≈ 1.0`.

### Plateau vs. water — the distinction that prevents a real mistake

```python
flat = abs(result.slope_per_week) < 0.1      # FLAT_SLOPE_KG_PER_WEEK
is_plateau = flat and sd <= 0.8              # NOISY_SD_KG
```

Three outcomes, and the middle one is the point:

| Slope | Scatter | Verdict |
|---|---|---|
| flat | low | `PLATEAU_DETECTED` — a genuine stall |
| flat | **high** | `LIKELY_WATER_FLUCTUATION` — **we decline to call it** |
| moving | any | `WEIGHT_TREND_DOWN` / `_UP` |

When day-to-day scatter is bigger than the signal, the honest answer is "I can't tell."
That refusal prevents the classic mistake of slashing calories during a fake stall caused
by a high-sodium weekend.

## 3.8 `recovery.py` — our own composite, because the watch won't

The FR165 has no Training Readiness. It reports every *input* — so we build the score.

### A voting model, not a weighted formula

```python
_INPUTS = {
    "sleep_duration_min": (True,  SLEEP_BELOW_BASELINE),      # higher is better
    "sleep_score":        (True,  SLEEP_SCORE_BELOW_BASELINE),
    "hrv_ms":             (True,  HRV_BELOW_BASELINE),
    "resting_hr":         (False, RHR_ABOVE_BASELINE),        # higher is WORSE
    "body_battery_high":  (True,  BODY_BATTERY_BELOW_BASELINE),
    "stress_avg":         (False, STRESS_ABOVE_BASELINE),
}
```

Each available input with a baseline votes −1 / 0 / +1. Then:

```python
net = sum(votes) / len(votes)
score = max(0.0, min(100.0, 50.0 + 50.0 * net))
status = BELOW if net <= -0.34 else ABOVE if net >= 0.34 else NORMAL
```

**Why the mean of votes rather than a weighted sum?** Because inputs go missing. Dividing
by the number of inputs that *actually had baselines* means a missing metric reduces
confidence rather than silently counting as neutral. Weighted formulas quietly break when
a term is absent.

Three graceful-degradation behaviours, each tested:

- **Some inputs missing** → uses the subset that has baselines, and reports `inputs_used` so the UI can say which.
- **No baselines yet** → `Status.UNKNOWN`, `score=None`, plus `BASELINE_BUILDING` reasons. A brand-new user gets an honest "building baseline", not a fabricated 72.
- **Watch not worn** → `METRIC_MISSING` reasons for the metrics we'd have expected.

And the consecutive-streak check on top:

```python
streak = consecutive_beyond(hrv_series, hrv_base, direction=Status.BELOW, on=on)
if streak >= 3:
    reasons.append(Reason(code=HRV_SUPPRESSED_CONSECUTIVE,
                          detail={"consecutive_days": streak}))
```

One bad HRV night is noise. Four in a row is a signal, and it's the kind of pattern a
single-day readout can't express.

## 3.9 `body_composition.py` — anchors, estimates, and a second feedback loop

**The argument for why this exists:** scale weight cannot tell you whether a cut is
working. Down 3 kg could be 3 kg of fat, or 2 kg of fat and 1 kg of lean mass — a good cut
and a bad one, *identical on the scale*. You lift three times a week, so this distinction
is the whole game, and nothing on the watch can make it.

### DEXA scans are anchors; everything between is an estimate

```python
delta = weight_kg - anchor.total_mass_kg
fat_mass = max(0.0, anchor.fat_mass_kg + delta * p_fat)
lean_mass = max(0.0, weight_kg - fat_mass)
```

```python
DEFAULT_P_FAT = 0.85
```

`p_fat` is the fraction of weight change that is fat. 0.85 rather than the generic 0.75
because 3 resistance sessions/week at 2.25 g/kg protein is close to the textbook
prescription for preserving lean mass in a deficit. **It is still a guess**, and
`Composition.measured=False` guarantees it can never render as a measurement.

### With no scan at all, we return `None`

```python
anchor = latest_scan_before(scans, on)
if anchor is None:
    return None
```

You have no DEXA yet, so the Body screen shows weight and trend only. Inventing a body-fat
percentage from height and weight would be a guess dressed as a measurement. Refusing is
the feature.

### `solve_p_fat` — the guess gets retired

```python
weight_delta = second.total_mass_kg - first.total_mass_kg
if abs(weight_delta) < 0.5:
    return None                     # ratio undefined, not zero
return (second.fat_mass_kg - first.fat_mass_kg) / weight_delta
```

Two scans give your **actual** partitioning ratio. So the system has two nested
self-calibrating loops learning two different personal constants:

| Loop | Learns | Corrected by | Cadence |
|---|---|---|---|
| Observed maintenance (§3.11) | calories you actually burn | weight trend vs. energy balance | weekly |
| Partitioning (`solve_p_fat`) | fat vs. lean split of your loss | DEXA vs. modelled composition | per scan |

That's the strongest engineering story in the project: **a system that measures its own
error and reports it, without ever taking the wheel.**

## 3.10 `trends.py` — and a guard that refuses to be useful

```python
MIN_CORRELATION_N = 30

def correlation(series_a, series_b, metric_a, metric_b, *, min_n=MIN_CORRELATION_N):
    shared = sorted(set(a) & set(b))
    if len(shared) < min_n:
        return None
```

Pearson r over days where **both** metrics were recorded. And it returns `None` below 30
points.

**Why the guard is in the function and not in a UI footnote:** at 40 data points,
correlation hunting manufactures findings. An r of 0.6 on twelve days is noise wearing a
number's clothes. Putting the minimum inside the function means no caller can skip it —
including the LLM tool layer in Phase 7, which is exactly the caller most likely to ask for
a correlation over sparse data.

`period_comparison` is the "compare this month to last month" primitive: two adjacent
windows, means, difference, percent, and both `n`s so thin periods are visible.

## 3.11 `calibration.py` — what the system learns about you

### Observed maintenance

```python
maintenance = mean_intake - result.slope_per_day * KCAL_PER_KG_FAT   # 7700
```

The derivation: if you eat 2350/day and lose 0.05 kg/day, that loss represents
0.05 × 7700 = 385 kcal/day you burned beyond what you ate. So maintenance ≈ 2350 + 385 =
2735 kcal.

Run against a 42-day window, it produced exactly that — and against a Garmin estimate of
2900, a **difference of −165 kcal**. That number *is* the resistance-training bias from
§3.5, measured rather than assumed. This is why the fudge factor would have been wrong: it
would have hidden the thing worth knowing.

### It refuses on thin data

```python
MIN_DAYS = 28
MIN_WEIGH_INS = 12

if len(intake_values) < min_days or len(weigh_ins) < min_weigh_ins:
    return None
```

A maintenance figure from nine weigh-ins would be confidently wrong, and this number is
meant to be trusted *over* Garmin's. Tested with a 6-weigh-in series → `None`.

### `flat_despite_deficit`

Weight flat for 21 days while the logged balance averages −450? That usually means an
*input* is off, not that physics broke. Surfacing it beats quietly averaging it away.

### `lean_mass_guardrail`

```python
LEAN_LOSS_THRESHOLD_KG_PER_WEEK = 0.1
if result.slope_per_week < -threshold:
    return Reason(code=LEAN_MASS_LOSS_ELEVATED, ...)
```

→ *"Estimated lean mass is falling at 0.21 kg/week, faster than the 0.1 kg/week
guideline."*

Not caution for its own sake. This is the failure mode scale weight hides completely, and
the reason body composition is a first-class feature rather than a stat.

---

# PART 4 — one day, end to end

Illustrative numbers.

```
1. INGEST (Phase 3, not built)
   EventBridge fires -> Lambda -> GarminProvider.fetch_day(2026-09-02)
      -> 17 raw JSON payloads -> S3 raw/garmin/dt=2026-09-02/*.json
      -> normalize() -> DailyHealthSnapshot.measured -> DynamoDB

2. YOU LOG FOOD (Phase 2, next)
   "Copy Yesterday" -> 11 LogEntry rows, each with macros_snapshot + serving_basis
   adjust rice 100 g -> 125 g dry; totals recompute

3. YOU WEIGH IN
   WeightEntry(2026-09-02, 79.4 kg, source="manual")

4. THE ENGINE RUNS  (all pure, all tested)
   nutrition.day_totals(entries)          -> 2055 kcal, 207 P, 242 C, 22 F
   nutrition.target_on(date, targets)     -> 2350 / 180 / 260 / 65
   nutrition.remaining(...)               -> +295 kcal, -27 P, +18 C, +43 F
   nutrition.adherence(...)               -> PROTEIN_TARGET_MET, CALORIES_UNDER_TARGET

   energy.bmr(profile, 79.4, date)        -> 1811 kcal  [MIFFLIN_ST_JEOR, no DEXA]
   energy.energy_balance(2421, 2055)      -> -366 kcal, DEFICIT
                                             + RESISTANCE_CALORIES_UNRELIABLE (58 min)

   baselines.baseline(hrv, 30d, date)     -> mean 52.2, sd 3.1, n 29
   baselines.deviation(47, base)          -> -5.2 ms, -9.9%, z -1.7, BELOW
   recovery.recovery_status(...)          -> BELOW, score 16.7, 3 inputs used
                                             + HRV_SUPPRESSED_CONSECUTIVE (4 days)

   weight.ema_on(series, date)            -> 79.6 kg
   weight.trend(series, date)             -> -0.42 kg/week, r2 0.68
   weight.plateau(series, date)           -> not a plateau, WEIGHT_TREND_DOWN

   body_composition.composition_on(...)   -> None  (no DEXA yet)
   calibration.observed_maintenance(...)  -> 2735 kcal, 165 below Garmin's estimate

5. THE API SERVES IT (Phase 4, not built)   GET /api/day/2026-09-02

6. THE DASHBOARD RENDERS IT (Phase 4)
   headline numbers + a comparison line each + an (i) opening the reason trace

7. THE LLM NARRATES IT (Phase 7)
   input = the reason traces above, nothing else
   "You were more active than usual today. Energy balance is about -370 kcal and protein
    cleared its target. Recovery is below normal -- HRV has been under baseline four days
    running and sleep was short. Worth prioritising sleep tonight."
   ^ every number came from step 4. The LLM computed nothing.
```

---

# PART 5 — the tests, and what each one protects

183 tests, 99% coverage on `backend/core`, 0.7 s to run.

| File | Protects |
|---|---|
| `test_architecture.py` | `core/` purity — AST-parses every module, fails on boto3/garminconnect/fastapi/requests imports, and on `open()`, `print()`, `datetime.now()` |
| `test_reasons.py` | every code has a template; no template leaks a placeholder; traces are immutable |
| `test_units.py` | known conversions, round-trip exactness, g/lb for imperial |
| `test_energy.py` | both BMR formulas against hand arithmetic; the 2% agreement; formula choice always explained; maintenance band; the lifting caveat |
| `test_nutrition.py` | 4/4/9 validator both ways; dated target boundaries; remaining reconstructs target; editing a food can't rewrite history |
| `test_baselines.py` | `on` excluded from its own baseline; `None` below min_n; the 3% band floor; gaps break streaks |
| `test_weight.py` | time-weighted EMA; recovered slope; plateau vs. water vs. trend |
| `test_recovery.py` | metric-aware direction; degradation to available inputs; UNKNOWN for new users; consecutive suppression |
| `test_body_composition.py` | reconciliation guard; estimates never marked measured; `None` without a scan; `solve_p_fat` |
| `test_trends.py` | the n≥30 correlation refusal; period comparison; streak breaks |
| `test_calibration.py` | maintenance derivation; the Garmin-overestimate quantification; refusal on thin data |
| `test_missing_data.py` | **every module's answer to "I don't have that"** |
| `test_invariants.py` | property-based: macro addition laws, remaining+consumed==target, EMA within range, baseline `None` boundary, BMR plausibility |
| `test_providers.py` | registry integrity; methods exist on the real client; failure isolation; `normalize` refuses to guess; **`summarize` never emits a value** |
| `test_seed_data.py` | seed profile/targets; every food declares a basis; 4/4/9 on the filled file; meal/template references resolve |

**`test_missing_data.py` deserves special mention.** It's the file that tests nothing
interesting and matters most. Watch on the charger, weigh-in skipped, no DEXA, user three
days old, a date before any history exists. **This is where health dashboards actually
break** — not in the arithmetic, but in the absence of data. Every function needs a defined
answer to "I don't have that", and it must never be a fabricated number.

---

# PART 6 — design decisions, each in one line

| Decision | Defence |
|---|---|
| Code does the math, LLM only interprets | LLM arithmetic errors are invisible; a wrong calorie reads as confidently as a right one |
| `measured` / `derived` as separate types | a provenance flag gets forgotten; a separate field cannot be written into by accident |
| Reason traces in Phase 1, not Phase 7 | built for the UI's "Why?"; the AI layer inherits hallucination resistance for free |
| `core/` purity enforced by a test | the claim is only true if something checks it; also keeps the AWS layer swappable |
| Store birth date, not age | `age: 23` is wrong within a year and corrupts every BMR after |
| IANA timezone, not UTC offset | offsets change twice a year; day-boundary bugs surface weeks later |
| Weight as history, not a profile field | a mutable `weight` destroys every trend the product exists to show |
| Targets append-only and dated | overwriting makes every historical dashboard silently wrong |
| `macros_snapshot` denormalised | editing a food's label must not rewrite last month |
| `serving_basis`, never auto-converted | cooked-vs-dry rice is a 2.5-3x error, bigger than the whole deficit; a mismatch must stay visible |
| Baselines exclude the current day | otherwise the metric is partly compared against itself |
| `None` on insufficient data, everywhere | a baseline from four readings is worse than no baseline |
| Correlation refuses below n=30 | at 40 points, correlation hunting manufactures findings |
| Recovery votes are averaged, not weighted | a missing input should reduce confidence, not count as neutral |
| No fudge factor for Garmin's lifting calories | it would hide the exact bias `observed_maintenance` exists to measure |
| Plateau declines to call it when scatter is high | prevents cutting calories during a fake, water-driven stall |
| `normalize()` raises until fixtures exist | Phase 0 discipline made executable |
| Endpoint registry as data, not code | the probe stays generic; adding an endpoint is one line |
| Probe searches for keys instead of reading paths | a wrong guess teaches you nothing; a search tells you where the field is |
| Report is structure-only | so it's committable from a repo holding real health data — and it's tested |
| No analytics tier (no Athena/Glue) | 365 items/year fits in one query; the pure functions already had to exist |
| Password never enters the cloud | MFA can't run in Lambda, so tokens are seeded locally — the constraint forced the better design |

---

# PART 7 — how to explain it to a person

**If they ask what it is:**

> A personal health dashboard. It ingests my Garmin data on a schedule, I log food against
> a small library, and a deterministic engine computes energy balance, recovery and body
> composition against my own baselines. An LLM sits on top purely as an analyst — it never
> produces a number.

**If they ask what's interesting about it:**

> Three things. First, the code/LLM split is enforced structurally: the model only ever
> receives finished numbers and structured reason traces, so it can't invent a figure or a
> justification. Second, it self-calibrates — it compares its own predictions against my
> measured weight trend and reports its error, so it discovers that Garmin overestimates
> my lifting days by about 165 calories instead of me having to assume it. Third, my watch
> doesn't report a recovery score at all, so I compute one from sleep, HRV, resting HR and
> Body Battery against my personal baselines — and label it as mine, not Garmin's.

**If they ask about the hard parts:**

> The interesting bugs aren't in the arithmetic, they're in the absence of data. The watch
> gets left on the charger, weigh-ins get skipped, HRV needs three weeks to establish a
> baseline. So every function has a defined answer to "I don't have that", and it's always
> `None` rather than a fabricated number. There's a whole test file for it.
>
> Also: `training_status` returns HTTP 200 with every field null. So "the endpoint
> succeeded" isn't the same as "the metric is available" — which is why field coverage is
> the observability metric rather than endpoint success.

**If they ask about AWS:**

> The workload is a scheduled ingest plus a low-traffic read API — idle 99% of the time,
> which is the textbook scale-to-zero case. I needed managed scheduling with retries, an
> immutable raw landing zone so a parser bug is a replay rather than a re-fetch, and
> infrastructure as code with least-privilege IAM, all under one identity. I also removed a
> service tier once I did the arithmetic: one user producing one snapshot a day is ~365
> items a year, so a single range query returns the whole history and the pure functions
> compute over it in memory. There was no analytics problem, so there's no analytics tier.
> At about 50 users, or per-second data instead of daily, that flips and I'd move to
> Postgres behind Fargate.

**If they ask why not just use an app:**

> Because no app combines my wearable data, my actual intake, and body composition into one
> explainable model — and none of them will tell me they're probably wrong about my lifting
> days.

---

## Glossary

| Term | Meaning |
|---|---|
| **BMR** | basal metabolic rate — calories to stay alive at rest |
| **TDEE** | total daily energy expenditure = BMR + activity + TEF |
| **TEF** | thermic effect of food — ~10% of intake spent digesting |
| **Mifflin–St Jeor** | BMR from weight, height, age, sex |
| **Katch–McArdle** | BMR from lean body mass; more accurate, sex-independent |
| **LBM** | lean body mass = total weight − fat mass |
| **DEXA** | dual-energy X-ray absorptiometry — the gold-standard body-composition scan |
| **p_fat** | fraction of weight change that is fat rather than lean tissue |
| **EMA / EWMA** | exponential moving average — weights recent readings more heavily |
| **HRV** | heart rate variability — beat-to-beat variation; a recovery proxy |
| **RHR** | resting heart rate |
| **Body Battery** | Garmin's 0–100 energy-reserve metric |
| **Baseline** | your own rolling average for a metric over 7/14/30/90 days |
| **Deviation** | today's value against that baseline — absolute, percent, z-score |
| **Reason trace** | structured explanation of how a derived number was produced |
| **Provenance** | which fields a given sync actually populated |
| **Serving basis** | whether a food's macros refer to raw, cooked or as-sold weight |
| **Tier 1 / Tier 2** | metrics the dashboard requires vs. metrics that only enrich it |
