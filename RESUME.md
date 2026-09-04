# RESUME.md — copy-paste blocks for your resume and portfolio

Every number here is verifiable from the repo. §6 lists what you must **not** claim yet, and
§7 preps the questions these bullets invite. Read both before you send anything out.

---

## 1. The one-liner

> **Adaptive Health & Nutrition Platform** — a serverless personal health data platform
> that ingests Garmin wearable data, combines it with nutrition and body-composition
> inputs, computes deterministic energy, recovery and body trends against personal
> baselines, and uses an LLM strictly as an explainable interpretation layer.

Shorter, for a tight header line:

> **Adaptive Health & Nutrition Platform** — wearable data pipeline + deterministic health
> engine, with an LLM confined to interpretation.

---

## 2. Resume bullets

### Four bullets (recommended — this is the standard shape)

> **Adaptive Health & Nutrition Platform** · Python, AWS, Pydantic, pytest · *personal project*
>
> - Built a **deterministic health engine** (11 modules, ~2,200 LOC) computing energy balance, macro adherence, rolling personal baselines, recovery scoring and body-composition trends — **183 tests, 99% statement coverage**, no mocks required.
> - Enforced a strict **calculation/LLM boundary** by architecture rather than policy: the LLM receives only finished metrics and a closed 34-code structured "reason trace", making it unable to produce or alter a number.
> - Reverse-engineered an **undocumented wearable API** with a discovery-driven probe across 17 endpoints, mapping the device's real field availability and uncovering endpoints returning HTTP 200 with null payloads — which redefined the health signal from *endpoint success* to *field coverage*.
> - **Removed an entire analytics tier** (managed ETL + query service) after sizing the workload at ~365 records/year, cutting two services and a per-scan billing line while keeping sub-millisecond in-memory aggregation.

### Three bullets (tighter)

> - Built a deterministic health engine (11 modules, ~2,200 LOC, **183 tests / 99% coverage**) computing energy balance, personal rolling baselines, recovery scoring and body-composition trends from wearable and nutrition data.
> - Confined an LLM to interpretation by architecture — it receives only computed metrics and a closed 34-code reason trace, so it cannot produce or modify a number; any value it extracts is re-validated against independent arithmetic.
> - Reverse-engineered an undocumented wearable API across 17 endpoints; discovered endpoints returning HTTP 200 with null payloads and changed the observability signal from endpoint success to field coverage.

### Two bullets (space-constrained)

> - Deterministic health data platform: wearable ingestion → immutable raw store → canonical model → tested calculation engine (**183 tests, 99% coverage**) → explainable output. Purity of the domain layer enforced by an AST-parsing architecture test.
> - LLM confined to interpretation by design — fed only computed metrics and structured reason traces, never raw records — with extracted values re-validated against independent arithmetic.

### One bullet (if it's a minor entry)

> - **Adaptive Health & Nutrition Platform** — serverless wearable data pipeline and deterministic health engine in Python (11 modules, 183 tests, 99% coverage), with an LLM restricted to interpreting pre-computed metrics via structured reason traces.

---

## 3. Portfolio project description (3–4 sentences)

> A personal health data platform built around my Garmin watch. A scheduled ingestion job
> pulls wearable metrics into an immutable raw store, a normalization layer maps them onto
> a canonical domain model, and a pure-Python engine computes energy balance, macro
> adherence, recovery status and body-composition trends against my own rolling baselines
> — every derived number carrying a structured explanation of how it was produced.
>
> The organizing constraint is that **anything reliably calculable is calculated by tested
> code; the LLM only interprets.** It receives finished metrics and reason traces, never
> raw records, so it cannot produce or alter a figure. The engine is 99% covered by 183
> tests and imports nothing from AWS or HTTP — a boundary enforced by an architecture test
> that parses the AST of every module.

---

## 4. Longer version — for a project page

### What it is

A personal health dashboard built around Garmin data, with nutrition and energy balance
layered on top, and an LLM added last as an analysis layer. It is **observational, not
prescriptive**: it reports what happened and how it compares to my own normal. It does not
plan workouts, set targets, or let a language model near arithmetic.

### Architecture

```
EventBridge Scheduler → Lambda → S3 (immutable raw JSON, partitioned by provider/date)
                                      ↓
                            normalization → canonical model → DynamoDB
                                      ↓
     API Gateway + Lambda (FastAPI) → pure calculation engine → metrics + reason traces
                                      ↓
                          React PWA (CloudFront) · LLM interpretation layer
```

### The three-layer split, and why it matters

1. **Acquisition** — raw provider responses land in object storage *before* parsing. A parser bug becomes a replay rather than a re-fetch, and the normalized store is never the only copy of the data.
2. **Deterministic engine** — pure Python, no I/O, no clock. Energy balance, macro totals, rolling baselines (7/14/30/90-day), recovery composite, weight EMA and trend, body composition, self-calibrating maintenance estimation. Every derived value emits a structured reason trace.
3. **LLM interpretation** — added only after the engine works, and given only the traces. LLM arithmetic errors are *invisible* (a wrong calorie reads as confidently as a right one), so the model is architecturally prevented from producing numbers.

### Engineering decisions worth defending

| Decision | Reasoning |
|---|---|
| Measured and derived metrics are **separate types**, not one model with a source flag | a flag gets forgotten; a separate field cannot be written into by accident, so a computed score can never be presented as the device's own |
| **Removed** the managed ETL + query analytics tier | one user producing one record per day is ~365 records/year — a single range query returns the full history and pure functions aggregate it in memory. No analytics problem, so no analytics tier. Knowing the threshold where that flips (~50 users, or per-second data) is the point |
| Provider password **never enters the cloud** | MFA cannot run in a Lambda, so tokens are seeded locally and the runtime holds only a refreshable bundle. The constraint produced the stronger security posture |
| Domain purity enforced by a **test**, not a convention | an AST parser rejects any AWS/HTTP/provider import in the engine, plus `open()`, `print()` and `datetime.now()` — a clock call makes a pure function untestable |
| Insufficient data returns **`None`**, never an estimate | a baseline computed from four readings is worse than no baseline; the absence propagates to the UI as "still building baseline (12 of 15 days)" |
| Correlation **refuses** below n=30 | at 40 data points, correlation hunting manufactures findings, so the guard lives in the function where no caller can skip it |

### The most interesting problem

The device provides no synthesized recovery score — that feature is reserved for higher
tiers of the product line. It does expose every underlying input. So the engine computes
its own composite from sleep duration, sleep score, HRV, resting heart rate and Body
Battery, each measured against a personal rolling baseline, using an **averaged vote model
rather than a weighted formula** — so a missing input reduces confidence instead of
silently counting as neutral. The result is labelled as derived everywhere it appears,
never as the vendor's metric.

### The second most interesting problem

The wearable's calorie estimate is heart-rate-derived, which systematically **overstates
resistance training** — heart rate stays elevated between sets without matching oxygen
consumption. The tempting fix is a correction factor. That would be wrong: it hides the
very bias worth measuring. Instead the engine derives observed maintenance calories from
intake and measured weight trend (`maintenance = mean_intake − weight_slope × 7700`) and
reports the gap against the device's own estimate. **The system measures its own error
rather than assuming it away** — and returns `None` rather than guessing below 28 days of
data and 12 weigh-ins.

---

## 5. The numbers — all verifiable from the repo

| Metric | Value | Where to verify |
|---|---|---|
| Tests passing | **183** | `pytest` |
| Statement coverage, engine | **99%** (862 statements, 8 uncovered) | `pytest --cov=backend/core` |
| Test suite runtime | **~0.8 s** | `pytest` |
| Engine + provider code | **~2,200 LOC** | `wc -l backend/core/*.py backend/providers/*.py` |
| Test code | **~1,600 LOC** | `wc -l backend/tests/*.py` |
| Core modules | **11** | `backend/core/` |
| Test files | **15** | `backend/tests/` |
| Reason codes, all templated | **34** | `backend/core/reasons.py` |
| Wearable endpoints mapped | **17** (7 tier-1) | `backend/providers/garmin.py` |
| Baseline windows | **7 / 14 / 30 / 90-day** | `backend/core/baselines.py` |
| Projected running cost | **~$1.50/month** | `PLAN.md` §16 |
| Technical documentation | **~3,400 lines** across 7 documents | `wc -l *.md` |

**A ratio worth quoting if asked about testing:** 1,600 lines of tests against 2,200 lines
of implementation, and the engine tests need **zero mocks** — a direct consequence of the
purity boundary.

---

## 6. Do NOT claim these yet

This matters more than the bullets. An unverifiable claim that collapses in an interview
costs more than a missing bullet.

| Don't say | Because | Say instead |
|---|---|---|
| "Deployed on AWS" / "in production" | nothing is deployed; the infrastructure is designed, not built | "serverless architecture designed with IaC (CDK); ingestion and API layers in progress" |
| "Built an LLM-powered dashboard" | the LLM layer is Phase 7, unwritten | "designed an LLM interpretation layer with a hard calculation boundary" — the *design* is real and is the interesting part |
| "Full-stack" / "React dashboard" | there is no frontend yet | leave it out, or "backend and data platform; frontend planned" |
| "Reduced AWS costs by X%" | nothing has ever been billed | "sized the workload and removed an analytics tier the data volume didn't justify" |
| "Improved my body composition by X" | no DEXA scan exists yet | don't put personal health outcomes on a resume at all |
| "Quantified my device's calorie bias at 165 kcal" | that figure came from a **synthetic test fixture**, not your body | "built self-calibration that quantifies device bias against measured weight trend" — the capability is real |
| "Processes X requests/sec" | it's one user, and honesty is cheaper than a fabricated scale story | the workload shape *is* the interesting answer: idle 99% of the time, which is why serverless fits |

**Framing in-progress work honestly:** "Phase 0–1 complete (data discovery and calculation
engine); Phases 2–7 in progress." Reviewers respect a project with a stated roadmap far
more than one implying more than exists — and it gives you something to talk about.

---

## 7. Questions these bullets invite — prep these

**"Why not just let the LLM do the calculations?"**
> Because its arithmetic errors are invisible. A wrong calorie figure reads exactly as
> confidently as a right one, and in a tool that reports energy balance a silently wrong
> number is the worst possible failure. So the boundary is architectural, not a prompt
> instruction: the model receives only finished metrics and structured reason traces, and
> anything it extracts — a nutrition label, a scan report — gets re-validated against
> independent arithmetic. LLM as extractor, code as validator.

**"Why AWS for a single-user app?"**
> The workload shape. A scheduled ingest plus a low-traffic read API is idle about 99% of
> the time, which is the textbook scale-to-zero case. I needed managed scheduling with
> retries, an immutable raw landing zone, and infrastructure as code with least-privilege
> IAM under one identity. And I removed a service tier once I did the arithmetic — at ~365
> records a year there was no analytics problem, so there's no analytics tier. At around 50
> users or per-second data instead of daily summaries, that flips and I'd move the read
> path to containers with Postgres.

**"What was the hardest part?"**
> Absence of data, not arithmetic. The watch gets left on the charger, weigh-ins get
> skipped, HRV needs about three weeks to establish a baseline. So every function has a
> defined answer to "I don't have that", and it's always `None` rather than a fabricated
> number — there's a dedicated test file for it. The subtlest instance: two endpoints
> return HTTP 200 with well-formed bodies and every value null. "The endpoint succeeded"
> isn't "the metric is available", so field coverage became the health signal instead of
> HTTP status.

**"99% coverage — is that real or padded?"**
> Real, and it's a consequence of the design rather than an effort. The engine is pure
> functions with no I/O, no network and no clock, so the tests need zero mocks: table-driven
> arithmetic against hand-computed values, property-based invariants with Hypothesis, and
> snapshot tests over the reason traces. The uncovered lines are defensive branches. The
> more interesting number is the ratio — 1,600 lines of test against 2,200 of
> implementation.

**"How would you scale this to many users?"**
> The data layer already partitions by user and identity resolves from the auth token in
> one place, so multi-user is mostly a config change. The real blockers are elsewhere: the
> unofficial API requires per-user credentials, which you cannot ask users for, so a
> multi-user version would need an official OAuth provider integration. And at scale the
> in-memory aggregation stops fitting, which is where the analytics tier I removed comes
> back — but deliberately, with a measured reason.

**"What would you do differently?"**
> I'd write the discovery probe before the architecture doc, not after. Several
> assumptions in my first design were wrong — including which auth library the client
> actually uses — and an afternoon of probing would have caught them earlier. That's
> exactly why "Phase 0" exists in the plan now: understand the data before building
> anything that depends on its shape.

---

## 8. Skills this project legitimately demonstrates

Use these as keyword anchors — each is genuinely backed by code in the repo.

**Languages & frameworks:** Python 3.12, Pydantic v2, pytest, Hypothesis, ruff, FastAPI *(designed)*

**Cloud & infrastructure:** AWS serverless architecture (Lambda, S3, DynamoDB, API Gateway, EventBridge, Cognito, CloudFront), AWS CDK, GitHub Actions with OIDC federation *(designed)*

**Engineering practice:** domain-driven design, hexagonal/ports-and-adapters, dependency inversion, property-based testing, architecture-as-test enforcement, immutable raw-data landing zones, effective-dated records, structured logging and observability design

**Data & AI:** time-series aggregation, rolling baselines, exponential moving averages, linear regression trend estimation, correlation with sample-size guards, self-calibrating feedback loops, LLM tool-use design, hallucination mitigation through structured input constraints, prompt-injection awareness

**Security:** OAuth token lifecycle management, MFA-compatible credential seeding, least-privilege IAM design, secret-free CI via OIDC, health-data privacy handling (no PII in logs, structure-only reporting)
