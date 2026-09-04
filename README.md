# Adaptive Health & Nutrition Dashboard

A personal health data platform built around a Garmin Forerunner 165. It ingests wearable
data, combines it with nutrition and body-composition inputs, and computes energy balance,
recovery status and body trends against personal rolling baselines.

**Observational, not prescriptive.** It reports what happened and how that compares to your
own normal. It does not plan workouts, set your targets, or let a language model near
arithmetic.

---

## The organizing constraint

> Anything that can be reliably calculated is calculated by tested code.
> The LLM only interprets.

```
LAYER 1 — ACQUISITION        LAYER 2 — DETERMINISTIC ENGINE      LAYER 3 — LLM
────────────────────         ──────────────────────────────      ─────────────
Garmin API                   energy balance                      explain
  ↓                          macro totals & adherence            find patterns
raw JSON (immutable)         personal baselines (7/14/30/90d)     summarise
  ↓                          recovery composite                  answer questions
canonical model              weight EMA & regression trend
  ↓                          body composition
food log · weight log        observed maintenance
                             reason traces
                                      │
                                      └──► finished numbers + traces ──► LLM
```

LLM arithmetic errors are *invisible* — a wrong calorie figure reads exactly as confidently
as a right one. In a tool that reports energy balance, a silently wrong number is the worst
possible failure. So the boundary is architectural, not a prompt instruction: the model
receives only computed metrics and structured reason traces, never raw records.

---

## Status

| Phase | State |
|---|---|
| 0 · Provider discovery | **done** — probe run against a real FR165, response shapes mapped |
| 1 · Domain models & calculation engine | **done** — 11 modules, 99% coverage |
| 1b · Garmin → canonical normalizer | **done** — field paths discovered by the probe, 100% covered |
| 2 · Nutrition + local dashboard | next |
| 3 · AWS data pipeline | designed, not built |
| 4 · API + React PWA | designed, not built |
| 5 · Historical analytics | designed, not built |
| 6 · DEXA body composition | model support in place, UI pending |
| 7 · LLM interpretation layer | designed, not built |

---

## Target architecture

```
EventBridge Scheduler ──► Ingest Lambda ──► S3  raw/<provider>/dt=YYYY-MM-DD/*.json
  (4x/day + nightly)      container image        │  immutable landing zone
                          reserved conc. = 1     │
                          token bundle only      ▼
                                  │        Normalizer (pure) ──► DynamoDB (single table)
                                  │                                    ▲
                                  └── nightly recompute ───────────────┘
                                      (full replay from raw)

CloudFront + S3 ──► API Gateway HTTP API ──► API Lambda (FastAPI + Mangum)
 React PWA                │                        │
                          └── Cognito JWT          ├─► calculation engine ──► metrics + traces
                                                   └─► LLM (tool-use only)
```

All infrastructure as code (AWS CDK). Deploys via GitHub Actions with OIDC federation, so
no long-lived AWS credentials exist. Projected running cost: **~$1.50/month** on a workload
idle ~99% of the time.

---

## Design decisions worth explaining

**Measured and derived metrics are separate types.** `snapshot.measured` holds provider
data unmodified; `snapshot.derived` holds ours, with the formula and inputs that produced
it. A provenance *flag* gets forgotten — a separate field cannot be written into by
accident, so a computed score can never be presented as the device's own.

**Raw responses are stored before parsing.** A parser bug becomes a replay, not a
re-fetch, and the normalized store is never the only copy of the data.

**The domain layer's purity is enforced by a test.** `backend/core/` imports nothing from
AWS, HTTP or the provider libraries — and `tests/test_architecture.py` parses the AST of
every module to prove it, also rejecting `open()`, `print()` and `datetime.now()`. A clock
call makes a pure function untestable.

**Insufficient data returns `None`, never an estimate.** A baseline computed from four
readings is worse than no baseline. The absence propagates to the UI as *"still building
baseline (12 of 15 days)"*. HRV in particular needs about three weeks.

**Correlation refuses below n=30.** At 40 data points, correlation hunting manufactures
findings, so the guard lives inside the function where no caller can skip it.

**The device's calorie estimate is not silently corrected.** Heart-rate-derived expenditure
systematically overstates resistance training — HR stays elevated between sets without
matching oxygen consumption. A fudge factor would hide the bias, so instead the engine
derives observed maintenance from intake versus measured weight trend and reports the gap.
The system measures its own error rather than assuming it away.

**Field coverage, not HTTP status, is the health signal.** Two FR165 endpoints return HTTP
200 with well-formed bodies and every value null. "The endpoint succeeded" is not "the
metric is available" — a monitor watching status codes would call the pipeline healthy
while the recovery screen sat empty.

**The provider password never enters the cloud.** MFA cannot run in a Lambda, so tokens are
seeded locally and the runtime holds only a refreshable bundle. Worst case in a full
compromise is a revocable token, not a reusable credential. The constraint produced the
stronger design.

---

## The engine

| Module | Responsibility |
|---|---|
| `models.py` | canonical domain types; the measured/derived split |
| `reasons.py` | closed 34-code explanation vocabulary, every code templated |
| `units.py` | SI ↔ display, the only conversion site in the codebase |
| `baselines.py` | rolling personal baselines; everything else leans on this |
| `energy.py` | BMR (formula selected by available data), TDEE, energy balance |
| `nutrition.py` | totals, effective-dated targets, adherence, 4/4/9 validation |
| `weight.py` | time-weighted EMA, regression trend, plateau vs. water discrimination |
| `recovery.py` | derived recovery composite against personal baselines |
| `body_composition.py` | DEXA anchors, modelled estimates, partitioning solve |
| `trends.py` | period comparison, correlation with sample-size guard |
| `calibration.py` | observed maintenance, lean-mass guardrail |

The provider layer:

| Module | Responsibility |
|---|---|
| `providers/base.py` | the port: `Endpoint`, `ProviderCapabilities`, `RawPayloads`, `MetricsProvider` |
| `providers/garmin.py` | 17-endpoint registry as data; day fetch with per-endpoint failure isolation |
| `providers/garmin_mapping.py` | pure Garmin JSON → canonical model, with provenance and tier-1 field coverage |
| `providers/introspect.py` | structure-only response discovery used by the probe |

Every derived value emits a `Reason` carrying its own numbers, window and sample size — so
nothing downstream recomputes, and the UI's "Why?" affordance and the LLM layer consume the
same object.

---

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev,cli]"
.venv/bin/python -m pytest
```

Run the linter:

```bash
.venv/bin/python -m ruff check backend/ scripts/
```

Discover what your own watch exposes (needs your Garmin credentials; handles MFA
interactively and caches a token bundle locally afterwards):

```bash
.venv/bin/python -m pip install -e ".[garmin]" && .venv/bin/python scripts/garmin_probe.py
```

The probe writes full responses to `fixtures/raw/` (gitignored — real health data) and a
**structure-only** report of field names, types and presence to `docs/`. A test asserts the
report generator never emits a value, which is what makes it safe to keep alongside real
data.

---

## Layout

```
backend/
  core/          pure domain: engine, models, reason vocabulary. No AWS, no I/O, no clock.
  providers/     the provider port + Garmin fetch adapter and JSON→canonical mapping
  adapters/      persistence (in progress)
  tests/         15 files
scripts/
  garmin_probe.py   Phase 0 discovery tool
seed/
  food-library.yaml           working library — PROVISIONAL values, replace from labels
  food-library.template.yaml  pristine all-null template
fixtures/
  raw/           real probe output (gitignored)
  sample/        anonymized fixtures for parser tests (committed)
infra/           AWS CDK app (not started)
```

---

## Testing

234 tests, 99% statement coverage across `backend/core` and `backend/providers`, ~1s to run, **zero mocks** — a
direct consequence of the purity boundary rather than extra effort.

```bash
.venv/bin/python -m pytest --cov=backend/core --cov-report=term-missing
```

The approach:

- **Table-driven arithmetic** against hand-computed values — both BMR formulas, macro maths, unit conversions.
- **Property-based invariants** (Hypothesis) — consumed + remaining always reconstructs the target; a smoothed weight never leaves the range of actual weigh-ins; the baseline `None` boundary is exactly the documented minimum.
- **Golden fixtures** — parser tests run against saved real responses, including their missing fields.
- **Snapshot tests over reason traces** — asserts exactly which codes fire for a given input, catching silent logic drift.
- **A dedicated missing-data suite** — watch on the charger, weigh-in skipped, no DEXA, three days of history, a date before any history exists. This is where health dashboards actually break: not in the arithmetic, but in the absence of data.
- **An architecture test** — AST-parses the domain layer to enforce purity.

---

## Notes

- Nutrition values in `seed/food-library.yaml` are **provisional** published figures, flagged `provisional: true`, intended to be replaced from real product labels. A test enforces that every entry reconciles with `4P + 4C + 9F`, so a typo fails the build.
- Detailed design, product and planning documents are kept local and are not tracked in this repository.
