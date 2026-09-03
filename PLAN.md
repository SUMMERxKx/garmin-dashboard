# PLAN.md — architecture and implementation

**v5** — rewritten against the product vision brief.

**Doc set:** this file is architecture, data models, infrastructure and phases. Product definition,
screens and MVP: **[PRODUCT.md](PRODUCT.md)**. Deterministic calculations and the LLM boundary:
**[ENGINE.md](ENGINE.md)**. Teaching companion: **[LEARNING.md](LEARNING.md)**. Idea menu:
**[IDEAS.md](IDEAS.md)**.

---

## 1. What the reframe changed

The vision brief inverted the priorities — dashboard first, AI last — and made the product
observational rather than prescriptive. Two consequences worth stating before the architecture:

**The system got simpler, not bigger.** Dropping prescription removes the food optimizer, carb
periodization and auto-adjusted targets. And a second look at the data volume removed an entire
analytics tier (§9). The honest summary: **v5 has fewer moving parts than v4 and does more.**

**The centre of gravity moved to `core/`.** The interesting engineering is now the deterministic
engine and its baselines, traces and provenance (ENGINE.md), not the cloud plumbing. The AWS layer's
job is to be reliable and boring.

---

## 2. Architecture

```
EventBridge Scheduler ──► Ingest Lambda ──► S3  raw/<provider>/dt=YYYY-MM-DD/<endpoint>.json
   (4×/day + nightly)     reserved conc.=1        │
                          token in S3 (SSE-KMS)   │  immutable landing zone
                                    │             │
                                    ▼             ▼
                              Normalizer ──► DynamoDB (single table)
                              (pure core)          ▲
                                                   │
CloudFront + S3 ──► API Gateway HTTP API ──► API Lambda (FastAPI + Mangum)
 fitness.<domain>        │                          │
 (+ ?demo=1 fixtures)    └── Cognito JWT            └── core/ engine ──► metrics + reason traces
                                                             │
                                                             └──► Bedrock (Phase 7, tools only)
```

| Concern | Choice | Why |
|---|---|---|
| Ingest | Lambda, container image, **reserved concurrency = 1** | `garminconnect` + deps exceed the 250 MB zip limit. Concurrency 1 is mandatory: two runs racing on a token refresh invalidate each other. |
| Schedule | EventBridge Scheduler | Retries, DLQ, timezone-aware cron. |
| Raw store | S3, `raw/<provider>/dt=YYYY-MM-DD/<endpoint>.json` | Parser bugs become a replay, not a re-fetch. Provider schema changes are recoverable. The normalized DB is never the only copy. |
| Token store | S3 `tokens/<provider>.json`, SSE-KMS, **versioned** | §7. Versioning rolls back a corrupt refresh. **No Secrets Manager** — no password to store, and it was the only fixed monthly cost. |
| App store | DynamoDB, single table, on-demand | Access is key-based and the dataset is tiny (§9). ~$0 idle, no connection pooling against Lambda. |
| API | API Gateway **HTTP API** + Lambda | ~70% cheaper than REST API; no REST-only feature needed. FastAPI + Mangum so the same app runs under `uvicorn` locally. |
| Auth | Cognito user pool, Hosted UI | Real OIDC, no login code. `userId` from the JWT `sub`, resolved in one place. |
| Frontend | Vite + React + TS → S3 + CloudFront (OAC) | Mobile-first PWA. Static, cached at edge. |
| IaC | AWS CDK (Python) | One language with the backend. `grant_*` helpers generate least-privilege IAM as a side effect of correct use. |
| Observability | Lambda Powertools + CloudWatch + SNS | §12. |
| CI/CD | GitHub Actions + OIDC → `cdk deploy` | No long-lived AWS keys. |
| LLM | Bedrock, Phase 7 | Tools-only access to `core/` functions. ENGINE.md §7. |
| Region | `ca-central-1`; ACM cert in `us-east-1` | Health data stays in Canada. CloudFront reads certs only from `us-east-1`. |

**Not used, deliberately:** Athena, Glue, Secrets Manager, Step Functions, SQS, RDS/Aurora, ECS,
Kinesis, API Gateway REST, Cognito identity pools. Each was considered; see §15.

---

## 3. Why AWS

**The workload shape.** A scheduled ingest of 4–6 short jobs a day plus a read API for one person.
Idle ~99% of the time, bursty otherwise. Textbook scale-to-zero.

Four things wanted under one identity and billing boundary:
1. **Managed scheduling with retries and a DLQ**, not a cron box to keep alive.
2. **Credential handling for health data** — specifically an architecture where the provider password never enters the cloud at all (§7).
3. **A raw landing zone** so parser fixes never cost history, which the vision brief calls for directly.
4. **Infrastructure as code with least-privilege IAM** — a CDK app that rebuilds into an empty account; CI via GitHub OIDC with zero static keys.

**Why not Vercel/Railway/Supabase.** Any would host the frontend well — the portfolio is on Vercel and
that's the right tool there. But this needs scheduling, secret handling, object storage and a
database, and assembling four vendors means four auth models and four bills. The integration cost
exceeded the cost of learning one platform properly.

**When I'd choose differently.** Lambda cold starts are real (200–600 ms on a Python container).
DynamoDB requires knowing access patterns up front. At thousands of users with genuinely ad-hoc
analytical queries I'd move the read path to ECS Fargate behind an ALB with Postgres — and §9 explains
exactly the threshold where that flips.

**Honest closer:** the credits made it cheap to learn the platform properly instead of guessing. Run
cost after credits: ~$1/month (§16).

---

## 4. Canonical data model

**Not shaped like Garmin's JSON.** Garmin is one provider that populates our model. The measured/derived
split is structural, so a computed value cannot be written into a provider field (ENGINE.md §5).

```python
class DailyHealthSnapshot:
    date: date                      # local calendar day, America/Vancouver
    measured: MeasuredMetrics       # from the provider, unmodified
    derived:  DerivedMetrics        # ours: formula + inputs + engine_version
    nutrition: NutritionTotals      # from our own log
    body: BodyMetrics

class MeasuredMetrics:
    energy:   Energy      # resting_kcal, active_kcal, total_kcal
    activity: Activity    # steps, distance_m, intensity_minutes, workout_minutes, activities[]
    heart:    Heart       # resting_hr, avg_hr, max_hr, hrv_ms
    sleep:    Sleep       # duration_min, stages{}, score
    recovery: Recovery    # body_battery_high/low/current, stress_avg
    fitness:  Fitness     # vo2max
    provenance: dict[str, str]      # field -> provider, and whether it was present

class DerivedMetrics:
    recovery_status: RecoveryResult | None     # ours, labelled. ENGINE.md §2
    baselines: dict[str, Baseline | None]      # per metric, per window
    deviations: dict[str, Deviation | None]
    load: ACWR | None                          # optional, Phase 5
    reasons: list[Reason]

class Activity:                     # one workout
    garmin_id, type, start, duration_s, calories, avg_hr, max_hr, zone_seconds[5]
```

**Every measured field is `Optional`,** and `provenance` records whether it was present. A watch left
on the charger is a normal Tuesday, not an error — and "which fields did this sync actually return"
becomes a metric (§12).

### Nutrition
```python
class Food:            id, name, brand?, serving_desc, serving_g,
                       serving_basis: raw|cooked|as_sold,     # PRODUCT.md §7.1 — highest-impact field
                       kcal, protein_g, carbs_g, fat_g, fiber_g?, sodium_mg?
class LogEntry:        id, date, food_id, servings, meal?, logged_at,
                       macros_snapshot,          # denormalized at write — history survives a food edit
                       source: copy|template|manual|llm, was_edited: bool
class SavedMeal:       id, name, items[{food_id, servings}]
class DayTemplate:     id, name, items[{food_id, servings}]
class MacroTarget:     effective_from: date, kcal, protein_g, carbs_g, fat_g   # append-only
```

`macros_snapshot` matters: editing a food's macros later must not silently rewrite last month's
dashboard. Denormalize on write.

### Body
```python
class WeightEntry:     date, weight_kg, source: manual|provider
class DexaScan:        date, total_mass_kg, fat_mass_kg, lean_mass_kg, bone_mass_kg,
                       body_fat_pct, visceral?, regional?{arms,legs,trunk}, notes
class Composition:     date, fat_mass_kg, lean_mass_kg, body_fat_pct,
                       measured: bool, anchor_scan_date?, p_fat_used?
```

`Composition.measured` is the guard that stops an estimate from ever rendering as a scan.

---

## 5. DynamoDB table and access patterns

| Entity | PK | SK |
|---|---|---|
| Day snapshot | `USER#<id>` | `DAY#2026-09-02#SNAPSHOT` |
| Activity | `USER#<id>` | `DAY#2026-09-02#ACT#<garminId>` |
| Food entry | `USER#<id>` | `DAY#2026-09-02#FOOD#<ts>` |
| Weight | `USER#<id>` | `DAY#2026-09-02#WEIGHT` |
| Food library | `USER#<id>` | `FOOD#<slug>` |
| Saved meal | `USER#<id>` | `MEAL#<slug>` |
| Day template | `USER#<id>` | `TMPL#<slug>` |
| Macro target | `USER#<id>` | `TARGET#2026-09-01` |
| Profile | `USER#<id>` | `PROFILE` |
| DEXA scan | `USER#<id>` | `DEXA#2027-01-15` |
| Log draft | `USER#<id>` | `DRAFT#<ts>` (TTL 24 h) |
| Sync status | `USER#<id>` | `SYNC#<provider>` |

**Access patterns, enumerated:**

| # | Pattern | Query |
|---|---|---|
| 1 | Render today | `PK=USER#id, SK begins_with DAY#2026-09-02` — snapshot, activities, food, weight in **one round trip** |
| 2 | Food library | `SK begins_with FOOD#` |
| 3 | Meals / templates | `SK begins_with MEAL#` / `TMPL#` |
| 4 | Copy yesterday | pattern 1 for `date−1`, then batch-write today's entries |
| 5 | Target on a date | `SK <= TARGET#<date>`, descending, limit 1 |
| 6 | Trends / baselines over N days | `SK between DAY#<start> and DAY#<end>` |
| 7 | All DEXA scans | `SK begins_with DEXA#` |
| 8 | Sync health | `SK = SYNC#GARMIN` |

Pattern 1 is why the key design looks the way it does — the whole Today screen is one query.

---

## 6. Historical analytics — and the tier we removed

The previous plan had S3 → Glue → Athena for trends. **Reconsidered and removed**, because the data
volume doesn't justify it:

```
1 user × 1 snapshot/day × 365 days  =  365 items  ≈  a few hundred KB/year
```

A DynamoDB `Query` over a date range returns **an entire year in one call**, well inside the 1 MB page
limit. The `core/` engine then computes baselines, rolling averages, period comparisons and
correlations in memory in microseconds.

So: **no Athena, no Glue, no data warehouse, no ETL job.** The "analytics tier" is a range query plus
pure functions that already had to exist for testability. Removing it deletes two services, a crawler
schedule, a per-TB-scanned billing line and a whole category of partition bugs.

Two supporting decisions:
- **Baselines are computed and stored with each day's snapshot** (ENGINE.md §3). Historical dashboards stay reproducible, and the Today screen does no recomputation.
- **A nightly recompute pass** re-derives snapshots from raw S3 — which is also the replay path, so the parser-fix story is exercised every night rather than being theoretical.

**The threshold where this flips:** roughly 50+ users, or per-second time series instead of daily
summaries. Then the range query stops fitting in memory and Athena (or Postgres) earns its place.
Knowing the number is the point — that's the difference between choosing DynamoDB and defaulting to it.

*Considered and rejected:* S3-only with no database (no atomic read-modify-write for food logging);
Aurora Serverless v2 (~15 s cold resume, and SQL's window functions buy nothing once the data fits in
memory); RDS t4g.micro (~$12/month for a workload that idles).

---

## 7. Garmin authentication and token architecture

`garminconnect` wraps `garth` for Garmin's SSO/OAuth. MFA is interactive, which Lambda cannot do —
and that constraint produces the better design:

```
LAPTOP (once)                          AWS (every run)
  login with MFA                         read token bundle from S3
  garth writes token bundle              refresh OAuth2 from long-lived OAuth1
  upload to S3 (SSE-KMS)                 write refreshed bundle back (versioned)
                                         ── no password anywhere in AWS ──
```

- OAuth1 token: long-lived (~1 year). OAuth2 access token: short, refreshed each run.
- **The Garmin password never exists in AWS** — not in Secrets Manager, not an env var, not a parameter. Worst case in a full AWS compromise is a revocable token, not a reusable credential.
- **Reserved concurrency = 1** so two runs can't refresh concurrently and mutually invalidate.
- Bundle written back with S3 object versioning, so a corrupt refresh is one rollback away.
- Re-seed by hand roughly annually, triggered by an alarm (§12).

**Recommendation: enable MFA on the Garmin account.** It holds years of GPS tracks starting and ending
at your home; credential stuffing is the realistic threat. It costs one interactive step about once a
year, and it forces the architecture above.

**Ingest is idempotent** — one deterministic S3 key per (provider, date, endpoint) — and always
re-fetches today *and* yesterday, because watch→cloud sync lags and late data must overwrite cleanly.

---

## 8. API design

`FastAPI` + `Mangum`. Every route resolves identity through one `current_user()` dependency reading
the JWT `sub` — **never a userId from a path, query or body.**

```
GET    /api/day/{date}                 full day: measured, derived, nutrition, body, reasons
GET    /api/today                      convenience alias, local timezone applied server-side
GET    /api/range?metric=&from=&to=    time series for charts
GET    /api/baselines?on=&window=      baselines + deviations
GET    /api/trends/compare?metric=&days=   period-over-period

POST   /api/food/log                   {food_id, servings, meal?}
POST   /api/food/copy                  {from_date, to_date}         ← Copy Yesterday
POST   /api/food/template/{id}/apply   {date}
DELETE /api/food/log/{entry_id}
GET    /api/foods                      library
POST   /api/foods                      create (validated: kcal ≈ 4P+4C+9F)
PUT    /api/foods/{id}
GET/POST  /api/meals  /api/templates

POST   /api/weight                     {date, weight_kg}
GET    /api/weight/trend?days=

GET/POST  /api/dexa                    scans; POST validated (fat+lean+bone ≈ total)
GET    /api/composition?date=          measured or estimate, always flagged

GET/PUT   /api/targets                 dated macro targets (PUT appends, never overwrites)
GET/PUT   /api/profile

GET    /api/sync/status                last successful sync, fields present/missing
POST   /api/sync/trigger               manual re-sync

# Phase 7
POST   /api/ai/daily     POST /api/ai/weekly     POST /api/ai/ask
POST   /api/food/parse                 NL → draft proposal (never commits)
```

Conventions: SI in every payload with units in field names (`weight_kg`, `duration_min`); the client
formats for display. Dates are local calendar days resolved server-side from the profile timezone.
`?demo=1` is handled at the frontend data-adapter level, never by the API.

---

## 9. Repo layout

```
garmin-dashboard/
├── infra/                      # CDK app (Python)
│   └── stacks/{data,ingest,api,web}_stack.py
├── backend/
│   ├── core/                   # PURE. No AWS, no HTTP, no I/O. Heavily tested.
│   │   ├── models.py  units.py  energy.py  nutrition.py  weight.py
│   │   ├── baselines.py  recovery.py  trends.py  body_composition.py
│   │   ├── calibration.py  load.py  reasons.py
│   ├── providers/
│   │   ├── base.py             # Protocol + capabilities + contract tests
│   │   └── garmin.py           # the one implementation
│   ├── adapters/               # dynamo_repo.py  s3_raw.py  token_store.py
│   ├── ingest/handler.py       # fetch → S3 raw → normalize → DynamoDB
│   ├── recompute/handler.py    # nightly replay from raw. §6
│   ├── api/                    # main.py, routes/, deps.py (current_user)
│   ├── ai/                     # Phase 7: tools.py, prompts.py, cache.py, budget.py
│   └── tests/
├── web/                        # Vite + React + TS PWA, demo fixtures
├── .github/workflows/deploy.yml
└── docs/adr/
```

`core/` importing `boto3` is a lint failure, not a code-review note. That boundary is what makes the
engine testable and the AWS layer swappable.

**ADRs to write:** why DynamoDB and no analytics tier (§6); why local token seeding (§7); why measured
and derived are structurally separate (ENGINE.md §5); why the LLM is last and tool-bound (ENGINE.md §7);
why not Athena.

---

## 10. Security

- **No provider password in the cloud** (§7). The strongest single property here.
- **Token bundle:** S3 + SSE-KMS, versioned, bucket policy denying every principal but the ingest role. KMS permission needed on *both* bucket and key.
- **IAM least privilege** via CDK `grant_*`. No `Resource: "*"`, no `s3:*`.
- **Cognito Hosted UI**, JWT validated by API Gateway *before* Lambda runs. Identity from `sub` only.
- **This is health data.** No metric values in logs — log identifiers and shapes, never `weight_kg` or a food diary. Structured logging makes that a schema decision rather than a discipline problem.
- **Demo mode is fixture-backed** and cannot reach real records; it's a frontend adapter swap, so there's no code path from `?demo=1` to the database.
- **HTTPS only**, CloudFront with OAC so the S3 bucket is never public.
- **CI:** GitHub OIDC with the trust policy scoped to `repo:<owner>/<repo>:ref:refs/heads/main`. A wildcard there lets any repo assume the role.
- **Prompt injection:** all text — food names, DEXA PDFs, anything extracted — is data, not instructions (ENGINE.md §7.5).
- **Budget alarm** at $5/month, plus the LLM token cap (ENGINE.md §7.4).

---

## 11. Testing strategy

Full detail in ENGINE.md §8. The architectural point: **`core/` is pure, so it tests with no mocks,
no network and no AWS** — table-driven arithmetic tests, `hypothesis` invariants, golden fixtures from
real Phase 0 Garmin responses, snapshot tests on reason traces, and explicit missing-data cases
(no weigh-in, watch not worn, no DEXA, three days of history). That last category is where health
dashboards actually break.

Outside `core/`: parser tests against saved raw JSON, ingest idempotency (same day twice ⇒ one item),
a provider contract suite, and API route tests with a fake repository. The LLM layer is tested for
plumbing — right tools called, budget enforced, fallback renders — never for wording.

Near-total coverage in `core/`, ordinary coverage elsewhere. The engine is the product; handlers are
plumbing.

---

## 12. Observability

The failure mode that matters is **silent staleness** — ingest breaks, the dashboard keeps showing
Tuesday's numbers, and you trust them. So:

| Signal | Mechanism |
|---|---|
| Ingest success/failure | Powertools metric per run + per endpoint |
| **Data freshness** | Age of the newest snapshot. Alarm > 36 h. The single most important alarm. |
| **Field coverage** | Which canonical fields the sync populated. A silent Garmin schema change shows up as coverage dropping, not as an exception. |
| Token refresh failure | Alarm immediately → SNS email. This is the annual re-seed trigger (§7). |
| Ingest duration, throttles, DLQ depth | Standard Lambda metrics |
| API errors / p95 latency | HTTP API metrics |
| LLM tokens + cost (Phase 7) | Custom metric per call |
| Spend | AWS Budgets at $5/month |
| Correlation | Powertools structured logs with a request id; tracing on |

Plus a **CloudWatch dashboard** with freshness, coverage, ingest outcome and cost — and a `Sync
Status` line in the app itself, because a stale-data warning belongs where you'd actually see it.

---

## 13. Phases

Dependency order. Each phase ends with something usable.

**Phase 0 — Garmin spike.** Local. MFA login, token bundle, pull a real day, save every raw response
as a fixture. No infrastructure. *Exit: you know exactly what the FR165 gives you, and the fixtures are
committed.*

**Phase 0 field checklist.** Probe each, record present/absent/shape. The two tiers matter: the
Recovery screen must be fully functional on tier 1 alone, and tier 2 only enriches the detail view.

| Field | Endpoint | Tier |
|---|---|---|
| Total sleep duration | `get_sleep_data` | **1 — required** |
| Sleep score | `get_sleep_data` | **1 — required** |
| HRV | `get_hrv_data` | **1 — required** |
| Resting heart rate | `get_rhr_day` | **1 — required** |
| Body Battery | `get_body_battery` | **1 — required** |
| Sleep start / end time | `get_sleep_data` | 2 |
| Deep / light / REM / awake durations | `get_sleep_data` | 2 |
| Overnight HRV series | `get_hrv_data` | 2 |
| Stress | `get_stress_data` | 2 |
| Respiration | `get_respiration_data` | 2 — availability unknown |
| Pulse Ox / SpO2 | `get_spo2_data` | 2 — availability unknown |
| Anything else genuinely useful in the responses | — | note it |

Record the outcome in `docs/fr165-fields.md` alongside the fixtures. **The production data model must
not depend on any tier-2 field existing** — every one is `Optional`, and `provenance` records what the
sync actually returned (§4).

**Phase 1 — Domain models and calculations.** Canonical model written from the engine's needs, then
`units`, `energy`, `nutrition`, `weight`, `baselines`, `recovery`, `trends`, `reasons`. Heavy tests.
No LLM, no AWS, no UI. *Exit: `pytest` green and the arithmetic is trustworthy.*

**Phase 2 — Nutrition + local dashboard.** Food library, food log, macro targets (dated), **Copy
Yesterday**, saved meals/templates, weight entry — against Phase 0's local Garmin data. CLI or a
minimal local UI. *Exit: the product is genuinely useful on your own machine.*

**Phase 3 — AWS data pipeline.** CDK: S3 raw + DynamoDB + ingest Lambda + Scheduler + token store +
recompute pass. Backfill 90 days. Observability (§12) lands here, not later — an unobserved pipeline
is a pipeline that lies. *Exit: data arrives on its own and you'd know within a day if it stopped.*

**Phase 4 — Full dashboard.** HTTP API, Cognito, the seven screens in PRODUCT.md §4, mobile-first PWA
on CloudFront at `fitness.<domain>`, unit toggle, the "Why?" affordance. GitHub OIDC CI/CD.
*Exit: you use it daily from your phone.*

**Phase 5 — Historical analytics.** Baseline windows (7/14/30/90), period comparisons, trend charts,
adherence history, energy-balance history, plateau detection, observed maintenance (ENGINE.md §6.1).
Correlations with honest `n`. Optional: training load. Demo mode + portfolio project page.

**Phase 6 — DEXA.** Scan entry, composition visualization, multi-scan comparison, Katch–McArdle once
lean mass exists, partitioning solve at two scans (ENGINE.md §6.2).

**Phase 7 — AI.** Daily observations, weekly review, `Ask My Health Data` over tool-bound queries,
then optionally natural-language food logging. Caching, budget cap, kill switch, templated fallback.
*Exit: turning the LLM off degrades the app gracefully and breaks nothing.*

---

## 14. Decisions that are painful to change later

One-way doors. All cheap now; all expensive once data exists.

| Decision | Why now |
|---|---|
| **Store birth date, not age** | `age: 23` is silently wrong within a year and quietly corrupts every BMR calculation after. |
| **Store the IANA timezone, not an offset** | Offsets change twice a year. "Which day did that 11 pm workout belong to" is a bug found weeks later. |
| **Weight is history, not a profile field** | A single mutable `weight` destroys every trend the product exists to show. |
| **SI canonical, convert only at the boundary** | Mixed-unit storage is unfixable without touching every row. |
| **Canonical model ≠ provider JSON** | Normalize to Garmin's shape and the model inherits Garmin's gaps permanently. |
| **Measured and derived structurally separate** | A provenance *flag* gets forgotten; a separate field cannot be. |
| **Macro targets append-only, effective-dated** | Overwriting makes every historical dashboard wrong, silently and irreversibly. |
| **Reason traces from day one** | Retrofitting explanations means re-deriving why past numbers happened — often impossible. |
| **`<provider>` in every raw S3 key** | Re-partitioning an S3 landing zone later is genuinely painful. |
| **`macros_snapshot` denormalized on log entries** | Otherwise editing a food rewrites last month's totals. |
| **`USER#` prefix + one `current_user()`** | Costs nothing; makes multi-user a one-line change if it ever matters. |
| **Idempotent ingest keys** | Re-fetching today and yesterday is required; without determinism it duplicates. |
| **DEXA in the model before the first scan** | Adding an anchor type later means backfilling composition history. |

Note what's *not* on this list: multi-user auth, friend sharing, a second provider. Those are two-way
doors — the key prefix and the `current_user()` seam are the only insurance needed, and both are free.

---

## 15. Removed from the previous plan

Honest accounting of what the reframe cut, and why:

| Removed | Reason |
|---|---|
| **Athena + Glue analytics tier** | 365 items/year fits in one query and computes in memory (§6). Two services, a crawler, a scan-based bill and a class of partition bugs, all deleted. |
| **Secrets Manager** | No password to store once tokens are seeded locally (§7). Removes the only fixed monthly cost. |
| **Food-combination optimizer** | Told you what to eat. The product is observational — it reports the deficit and you decide. |
| **Carb periodization / recovery-modulated targets** | Same reason. Targets are yours, dated and explicit (PRODUCT.md §7). |
| **Metabolic multiplier auto-adjusting the target** | Survives as an *observation* — "your data implies maintenance near 2,720" — never as a control (ENGINE.md §6.1). |
| **`DayFull` / `DayShared` split, friendship keys** | Social is out of scope. Reserving shapes for a feature that may never exist is speculative complexity. |
| **Multi-provider abstraction ceremony** | Kept: a thin Protocol and one implementation. Dropped: registries, merge-priority config, a second adapter. |
| **TRIMP / ACWR as a headline feature** | Demoted to optional (Phase 5). Its main use is prescribing training, which this product doesn't do. Zone data still ingested — it's free. |
| **Aurora Serverless v2 / RDS** | Considered for SQL window functions; buys nothing once the data fits in memory, and costs either cold-start latency or ~$12/month. |

The pattern: **v5 removed a service tier, a fixed cost, and three prescriptive features, and the
product got better.** That's worth an ADR — "what I took out" is a stronger portfolio signal than a
list of services used.

---

## 16. Cost

| Service | Monthly |
|---|---|
| Lambda (~250 invocations) | $0.00 (free tier) |
| DynamoDB on-demand | < $0.25 |
| S3 (< 1 GB, lifecycle to Glacier IR at 90 d) | ~$0.05 |
| API Gateway HTTP API | < $0.10 |
| CloudFront | ~$0.50 |
| Cognito (1 user) | $0.00 |
| Secrets Manager | $0.00 — designed out |
| Athena / Glue | $0.00 — designed out |
| Bedrock (Phase 7, cached + capped) | < $0.50 |
| **Total** | **~$1.00–1.50/mo** |

---

## 17. Nothing blocking

The personal profile is fully specified (PRODUCT.md §13). Seed data is scaffolded in
[`seed/food-library.template.yaml`](seed/food-library.template.yaml): 8 foods, 4 saved meals, a Normal
Day template, and the starting macro target.

Two values are gathered *during* implementation, and neither blocks architecture or MVP design:

| Gathered | When | Blocks |
|---|---|---|
| Exact food nutrition, from your product labels | as you fill the seed template | Phase 2 showing real numbers — not its schema or workflow |
| Exact FR165 field availability | Phase 0, experimentally | nothing — tier-2 fields are all `Optional` by design (§13) |

Locked: male, 180 cm, born 2003-05-01, ~80 kg (history), America/Vancouver, FR165, cutting,
2,350 kcal · 180 P · 260 C · 65 F effective 2026-09-03, 5 training sessions/week, no DEXA yet,
`ca-central-1`.

**Phase 0 can start now.**
