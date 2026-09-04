# RESUME-COMPLETE.md — copy for the finished system

**This describes the project as it will exist when all seven phases ship** — full AWS
deployment, React PWA, LLM layer, DEXA support, public demo. Use [RESUME.md](RESUME.md)
until then; that one describes what exists today.

**One condition:** every `[BRACKETED]` slot is a number you measure at ship time, not
something to guess. §9 is a fill-in checklist so none of them go out unresolved.

---

## 1. The one-liner

> **Adaptive Health & Nutrition Platform** — a serverless personal health data platform
> that continuously ingests wearable data, fuses it with nutrition and body-composition
> inputs, computes deterministic energy, recovery and body trends against personal
> baselines, and layers an explainable LLM analyst over validated metrics. Built on AWS
> with full infrastructure-as-code, running at under $2/month.

Header-line version:

> **Adaptive Health & Nutrition Platform** — serverless wearable data platform, deterministic
> health engine, and an LLM confined to interpretation. Python · AWS CDK · React · Bedrock

---

## 2. Resume bullets

### Five bullets (recommended for a project this size)

> **Adaptive Health & Nutrition Platform** · Python, AWS (Lambda/S3/DynamoDB/CDK), React, TypeScript, Bedrock
> [live demo](https://fitness.YOURDOMAIN.com/?demo=1) · [github](https://github.com/YOU/garmin-dashboard)
>
> - Designed and shipped an **end-to-end serverless health data platform** on AWS — scheduled wearable ingestion → immutable S3 landing zone → normalization → DynamoDB → HTTP API → mobile-first React PWA — fully defined in **AWS CDK** and deployed via **GitHub Actions with OIDC federation (zero long-lived credentials)**, running at **~$1.50/month** on a workload idle 99% of the time.
> - Built a **deterministic health engine** ([N] modules, ~[N]k LOC) computing energy balance, macro adherence, rolling 7/14/30/90-day personal baselines, recovery scoring, weight trend estimation and body-composition modelling — **[N] tests at [N]% statement coverage with zero mocks**, enabled by a domain layer whose purity is enforced by an AST-parsing architecture test.
> - Enforced a strict **calculation/LLM boundary architecturally**: the model receives only computed metrics and a closed [N]-code structured reason trace — never raw records — and answers historical questions through **typed tool-use over the calculation engine**, so every figure it reports traces to a deterministic function. Extracted values (nutrition labels, scan reports) are re-validated against independent arithmetic.
> - Implemented **two nested self-calibrating feedback loops** that learn personal physiological constants from measured outcomes — deriving true maintenance calories from intake versus weight trend, and solving fat/lean partitioning from successive DEXA scans — quantifying the wearable's systematic overestimation of resistance-training expenditure instead of assuming it away.
> - Engineered for **explainability and graceful degradation**: every derived number carries a machine-readable reason trace rendered in both UI and prose, insufficient data returns an explicit null rather than an estimate, and **field-coverage** monitoring (not HTTP status) detects silent upstream data loss — after discovering endpoints returning HTTP 200 with fully null payloads.

### Four bullets

> - Shipped an end-to-end **serverless health data platform** on AWS (Lambda, S3, DynamoDB, API Gateway, Cognito, CloudFront, EventBridge) — 100% infrastructure-as-code in **CDK**, deployed by **GitHub Actions via OIDC with no static credentials**, at **~$1.50/month**.
> - Built a **deterministic calculation engine** ([N] modules, **[N] tests / [N]% coverage, zero mocks**) computing energy balance, personal rolling baselines, recovery scoring and body-composition trends; domain purity enforced by an AST-parsing architecture test.
> - Confined an LLM to **interpretation by architecture** — fed only computed metrics and a closed [N]-code reason trace, answering queries through typed tool-use over the engine, with extracted values re-validated against independent arithmetic.
> - Built a **mobile-first React/TypeScript PWA** with offline logging, Cognito OIDC auth, and a **public synthetic-data demo mode** so the system is explorable without exposing real health data.

### Three bullets

> - Shipped a full **serverless health data platform** on AWS — wearable ingestion, immutable raw store, normalization, API and React PWA — 100% IaC in CDK, CI/CD via GitHub OIDC, **~$1.50/month** at 99% idle.
> - Built a **deterministic health engine** ([N] tests, **[N]% coverage, zero mocks**) computing energy balance, rolling personal baselines, recovery scoring and self-calibrating body-composition models; every derived value carries a structured reason trace.
> - Constrained an LLM to interpretation architecturally — only computed metrics and reason traces as input, typed tool-use for historical queries, independent arithmetic re-validating anything it extracts.

### Two bullets

> - End-to-end serverless health platform on AWS (CDK, Lambda, S3, DynamoDB, Cognito, CloudFront; GitHub OIDC CI/CD) with a **[N]%-covered deterministic calculation engine** and a mobile-first React PWA — **~$1.50/month**.
> - LLM restricted to interpretation by design: computed metrics and structured reason traces only, typed tool-use over the engine for historical queries, independent arithmetic validating every extraction.

### One bullet

> **Adaptive Health & Nutrition Platform** — serverless AWS health data platform (CDK, Lambda, S3, DynamoDB, React PWA) with a [N]%-covered deterministic calculation engine and an LLM architecturally confined to interpreting pre-computed metrics.

---

## 3. Portfolio description (3–4 sentences)

> A serverless personal health platform built around my Garmin watch. A scheduled job
> ingests wearable metrics into an immutable S3 landing zone, a normalization layer maps
> them onto a canonical domain model in DynamoDB, and a pure-Python engine computes energy
> balance, macro adherence, recovery status and body-composition trends against my own
> rolling baselines — every derived number carrying a structured explanation of how it was
> produced. A React PWA surfaces it, and an LLM analyst sits on top.
>
> The organizing constraint is that **anything reliably calculable is calculated by tested
> code; the LLM only interprets.** It receives computed metrics and reason traces, never raw
> records, and answers historical questions through typed tool calls into the engine — so
> every number it reports traces back to a deterministic function. The whole stack is
> infrastructure-as-code, deploys through OIDC-federated CI with no stored credentials, and
> costs about $1.50 a month.

---

## 4. Full project page

### What it is

A personal health dashboard built around Garmin data, with nutrition and energy balance
layered on top and an LLM added last as an analysis layer. It is **observational, not
prescriptive** — it reports what happened and how it compares to my own normal. It does not
plan workouts, set my targets, or let a language model near arithmetic.

**[Try the live demo](https://fitness.YOURDOMAIN.com/?demo=1)** — full interface on
synthetic data, no account needed.

### Architecture

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
 fitness.<domain>         │                        │
 React PWA · ?demo=1      └── Cognito JWT          ├─► calculation engine ──► metrics + traces
                                                   └─► Bedrock (tool-use only)

Observability: CloudWatch structured logs/metrics · data-freshness alarm · field-coverage
metric · SNS email · AWS Budgets.   CI/CD: GitHub Actions → OIDC role → cdk deploy.
```

### The three layers, and why the split matters

**1 · Acquisition.** Raw provider responses land in object storage *before* parsing,
Hive-partitioned by provider and date. Two consequences: a parser bug becomes a replay
rather than a re-fetch, and the normalized store is never the only copy of the data. A
nightly recompute pass rebuilds every derived record from raw — so the replay path is
exercised continuously instead of being theoretical.

**2 · Deterministic engine.** Pure Python: no I/O, no network, no clock. Energy balance,
macro totals against effective-dated targets, rolling baselines, a recovery composite,
weight EMA and regression trend, body composition, and self-calibrating maintenance
estimation. Every derived value emits a structured reason trace. It imports nothing from
AWS or HTTP, and an architecture test parses the AST of every module to keep it that way.

**3 · LLM interpretation.** Added only after the engine worked, and given only the traces.
LLM arithmetic errors are *invisible* — a wrong calorie figure reads exactly as confidently
as a right one — so the model is architecturally prevented from producing numbers.

### The LLM layer, in detail

Four capabilities, all bounded:

| Capability | How it's constrained |
|---|---|
| **Daily observation** | renders the day's reason trace into prose; cached on a bucketed state hash so routine days reuse a response |
| **Weekly review** | code produces the report (averages, adherence, trend, period comparison); the model explains it |
| **Ask My Health Data** | the model gets **typed tools, not data** — `ask_energy_balance(start, end)`, `ask_baseline(metric, window)`, `ask_correlation(a, b, days)` — which are the engine's own functions exposed. It selects; code computes; it phrases. Every number in an answer traces to a tool result, and the UI can show which tools ran |
| **Natural-language food logging** | maps text onto the personal food library and emits `food_id` + `servings` against a closed enum; application code retrieves the macros. Proposals are drafts requiring explicit confirmation |

Cost and reliability discipline: deterministic-first (fuzzy match before any model call,
template before any model call), bucketed-state caching, model tiering, a hard monthly
token budget with a kill switch, and a templated fallback for every reason code — **so the
entire application remains fully usable with the LLM switched off.** That is the test of
whether the layering is real.

### Engineering decisions worth defending

| Decision | Reasoning |
|---|---|
| Measured and derived metrics are **separate types**, not one model with a source flag | a flag gets forgotten; a separate field cannot be written into by accident, so a computed score can never be presented as the device's own |
| **Removed** the managed ETL + query analytics tier | one user producing one record per day is ~365 records/year — a single range query returns the full history and pure functions aggregate it in memory. No analytics problem, so no analytics tier. Knowing where that flips (~50 users, or per-second data) is the point |
| Provider password **never enters the cloud** | MFA cannot run in Lambda, so tokens are seeded locally and the runtime holds only a refreshable bundle. Worst case in a full compromise is a revocable token, not a reusable credential — the constraint produced the stronger design |
| Domain purity enforced by a **test**, not a convention | an AST parser rejects any AWS/HTTP/provider import in the engine, plus `open()`, `print()` and `datetime.now()` — a clock call makes a pure function untestable |
| Insufficient data returns **null**, never an estimate | a baseline from four readings is worse than no baseline; the absence propagates to the UI as "still building baseline (12 of 15 days)" |
| Correlation **refuses** below n=30 | at 40 data points correlation hunting manufactures findings, so the guard lives in the function where no caller — including the LLM tool layer — can skip it |
| Effective-dated targets, append-only | overwriting a macro target would make every historical dashboard silently wrong |
| **Field coverage**, not HTTP status, as the health signal | two upstream endpoints return 200 with fully null bodies; a monitor watching status codes would call the pipeline healthy while the dashboard sat empty |

### The most interesting problem

The device provides no synthesized recovery score — that feature is reserved for higher
tiers of the vendor's product line. It does expose every underlying input. So the engine
computes its own composite from sleep duration, sleep score, HRV, resting heart rate and
Body Battery, each measured against a personal rolling baseline, using an **averaged vote
model rather than a weighted formula** — so a missing input reduces confidence instead of
silently counting as neutral. The result is labelled as derived everywhere it appears,
never as the vendor's metric.

### The second most interesting problem

The wearable's calorie estimate is heart-rate-derived, which systematically **overstates
resistance training** — heart rate stays elevated between sets without matching oxygen
consumption. The tempting fix is a correction factor. That would be wrong: it hides the
very bias worth measuring. Instead the engine derives observed maintenance from intake and
measured weight trend (`maintenance = mean_intake − weight_slope × 7700`) and reports the
gap against the device's own estimate.

A second loop does the same for body composition: between DEXA scans, composition is
modelled from a literature partitioning ratio; two scans solve for the **actual** personal
ratio and retire the assumption. Two nested loops learning two different personal
constants — **a system that measures its own error and reports it, without ever taking the
wheel.** Both return null rather than guessing below their data thresholds.

### Frontend

Mobile-first React + TypeScript PWA on CloudFront with Origin Access Control. Seven
screens — Today, Energy, Nutrition, Activity, Recovery, Body, Trends — built on one
information rule: **every headline number carries a comparison against the user's own
baseline**, because a metric without that context is not information. Offline-capable
logging with a local queue, since the gym has no signal. Cognito Hosted UI for auth.
TypeScript client generated from the API's OpenAPI schema, so types stay in sync across
the stack.

A `?demo=1` mode swaps the data adapter for synthetic fixtures — the full interface,
explorable in ten seconds, with no account and no exposure of real health data.

---

## 5. Numbers

### Architecturally determined — safe to state

| Metric | Value |
|---|---|
| AWS services, all IaC | 9 (Lambda, S3, DynamoDB, API Gateway, EventBridge, Cognito, CloudFront, CloudWatch, Bedrock) |
| Infrastructure as code | 100% — CDK; stack destroyable and rebuildable into an empty account |
| Long-lived cloud credentials | **0** — GitHub OIDC federation for deploys, token-only for the provider |
| Wearable endpoints mapped | 17 (7 tier-1, required; 10 tier-2, enrichment) |
| Baseline windows | 7 / 14 / 30 / 90-day rolling |
| Dashboard screens | 7, mobile-first |
| Self-calibrating feedback loops | 2 (maintenance calories; fat/lean partitioning) |
| Running cost | **~$1.50/month** at 99% idle |
| Mocks required for engine tests | **0** |

### Measure at ship time — fill these in

| Metric | Command / method |
|---|---|
| `[N]` tests | `pytest` |
| `[N]`% statement coverage | `pytest --cov=backend/core` |
| `[N]` core modules | count `backend/core/*.py` |
| `[N]`k LOC implementation / `[N]`k tests | `wc -l` |
| `[N]` reason codes | `len(list(ReasonCode))` |
| `[N]` ms p95 API latency | CloudWatch API Gateway metrics, after a week of real use |
| `[N]` ms Lambda cold start | CloudWatch Logs `Init Duration` |
| `[N]` days of history backfilled | your actual backfill run |
| `$[N]`/month LLM spend | your token metric; the design targets < $0.50 |
| `[N]`% LLM cache hit rate | your cache metric; bucketed hashing should make this high |

---

## 6. Skills demonstrated

**Languages & frameworks:** Python 3.12, Pydantic v2, FastAPI, pytest, Hypothesis, ruff, TypeScript, React, Vite

**Cloud & infrastructure:** AWS Lambda (container images), S3, DynamoDB (single-table design), API Gateway HTTP API, EventBridge Scheduler, Cognito, CloudFront + OAC, CloudWatch, KMS, ACM, AWS Budgets, **AWS CDK**, GitHub Actions with **OIDC federation**

**Engineering practice:** domain-driven design, ports-and-adapters, dependency inversion, property-based testing, architecture-as-test enforcement, immutable raw-data landing zones, replay-based recovery, effective-dated records, idempotent ingestion, single-table access-pattern modelling, structured logging, SLO-oriented alarming, PWA offline-first design

**Data & AI:** time-series aggregation, rolling baselines, exponential moving averages, linear regression trend estimation, correlation with sample-size guards, self-calibrating feedback loops, **LLM tool-use architecture**, hallucination mitigation via structured-input constraints, schema-constrained generation, prompt-injection defence, token-cost engineering (caching, model tiering, budget enforcement, graceful degradation)

**Security:** OAuth token lifecycle management, MFA-compatible credential seeding, credential-free cloud runtime, least-privilege IAM, secret-free CI, health-data privacy handling (no PII in logs, structure-only reporting, synthetic-data demo isolation)

---

## 7. Interview prep

**"Walk me through the architecture."**
> Four stages. EventBridge triggers a containerized Lambda a few times a day; it pulls from
> the wearable API and writes raw JSON to S3, partitioned by provider and date, before
> anything parses it. A normalizer maps that onto a canonical domain model in DynamoDB — a
> model shaped by what my engine needs, deliberately not by the provider's JSON, so I don't
> inherit their gaps. A FastAPI Lambda behind API Gateway serves it, with Cognito validating
> JWTs before my code runs. A React PWA on CloudFront renders it. The whole thing is a CDK
> app, deployed by GitHub Actions through an OIDC role, so there are no static AWS keys
> anywhere.

**"Why not let the LLM do the calculations?"**
> Because its arithmetic errors are invisible. A wrong calorie figure reads exactly as
> confidently as a right one, and in a tool that reports energy balance a silently wrong
> number is the worst possible failure. So the boundary is architectural, not a prompt
> instruction: the model receives only finished metrics and structured reason traces. For
> historical questions it gets typed tools rather than data — it picks which to call, my
> code computes, it phrases the result. And anything it extracts, like a nutrition label or
> a scan report, is re-validated against independent arithmetic. LLM as extractor, code as
> validator.

**"Why AWS for a single-user app?"**
> The workload shape. Scheduled ingest plus a low-traffic read API is idle about 99% of the
> time — textbook scale-to-zero. I needed managed scheduling with retries and a DLQ, an
> immutable raw landing zone, and infrastructure-as-code with least-privilege IAM under one
> identity. And I *removed* a service tier once I did the arithmetic: at ~365 records a year
> there was no analytics problem, so there's no analytics tier. Around 50 users, or
> per-second data instead of daily summaries, that flips and I'd move the read path to
> containers with Postgres.

**"What was the hardest part?"**
> Absence of data, not arithmetic. The watch gets left on the charger, weigh-ins get
> skipped, HRV needs three weeks to establish a baseline. So every function has a defined
> answer to "I don't have that", and it's always null rather than a fabricated number —
> there's a dedicated test file for exactly that. The subtlest instance: two upstream
> endpoints return HTTP 200 with well-formed bodies and every value null. "The endpoint
> succeeded" isn't "the metric is available", so field coverage became the health signal
> instead of status codes.

**"How do you know your numbers are right?"**
> The engine is pure functions with no I/O, so tests need zero mocks. Table-driven
> arithmetic against hand-computed values, property-based invariants with Hypothesis —
> things like consumed-plus-remaining always reconstructing the target, and a smoothed
> weight never leaving the range of actual weigh-ins — plus snapshot tests over the reason
> traces so logic drift is caught. And the system cross-checks itself: two independent BMR
> formulas that must agree within a few percent, and a feedback loop comparing predicted
> against measured weight change.

**"What would you do differently?"**
> Write the discovery probe before the architecture document, not after. Several
> assumptions in my first design were wrong — including which auth library the client
> actually used — and an afternoon of probing would have caught them. That's why the plan
> now has a Phase 0 whose only job is understanding the data before anything depends on its
> shape.

**"How would you scale it?"**
> The data layer already partitions by user and identity resolves from the auth token in
> one place, so multi-user is mostly configuration. The real blockers are elsewhere: the
> unofficial provider API needs per-user credentials, which you can't ask users for, so a
> multi-user version needs an official OAuth integration — that's a product constraint, not
> a scaling one. Technically, the in-memory aggregation is what breaks first, and that's
> where the analytics tier I removed comes back — deliberately, with a measured reason
> rather than as a default.

**"What are you most proud of?"**
> That the constraints produced the design rather than fighting it. MFA can't run in
> Lambda, so tokens are seeded locally — and now the provider password never exists in the
> cloud at all. The watch won't give me a recovery score, so I compute one from its raw
> inputs against my own baselines. The device overestimates my lifting calories, so instead
> of a fudge factor the system measures its own error against my weight trend and reports
> the gap. Each of those started as a limitation.

---

## 8. What still shouldn't go on the resume

Even with everything shipped:

- **Personal health outcomes.** No body-fat percentages, no weight loss. It's a systems project, and health details aren't a professional credential.
- **Scale you don't have.** "Processes 10k requests/sec" would be a fabrication. The workload shape *is* the interesting answer — 99% idle is precisely why serverless fits.
- **Vendor-specific claims you can't support.** "Beat Garmin's algorithms" — you built a different, explainable metric from the same inputs. That's a better claim and it's true.
- **"AI-powered" as a headline.** The LLM is deliberately the thinnest layer. Leading with it inverts the actual engineering, and a good interviewer will find that out in one question.

---

## 9. Fill-in checklist

Before this copy leaves your machine, resolve every slot:

- [ ] `[N]` tests → `pytest`
- [ ] `[N]`% coverage → `pytest --cov=backend/core`
- [ ] `[N]` core modules
- [ ] `[N]`k LOC implementation and tests
- [ ] `[N]` reason codes
- [ ] `[N]` ms p95 API latency (needs a week of real traffic)
- [ ] `[N]` ms cold start
- [ ] `[N]` days backfilled
- [ ] `$[N]` monthly LLM spend
- [ ] `[N]`% cache hit rate
- [ ] `YOURDOMAIN` → your real subdomain, and confirm the demo link works signed out
- [ ] `github.com/YOU/...` → your real repo, and confirm it's public
- [ ] Re-read §8 once
