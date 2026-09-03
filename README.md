# Adaptive Garmin Health & Nutrition Dashboard

Personal health dashboard built around Garmin data, with nutrition and energy balance
layered on top, and an LLM added at the end as an analysis layer only.

**Observational, not prescriptive.** It reports what happened and how it compares to your
own baselines. It does not plan workouts, set your macros, or let an LLM near arithmetic.

## Docs

| File | What it covers |
|---|---|
| [PRODUCT.md](PRODUCT.md) | Product definition, MVP, screens, which Garmin data earns its place |
| [ENGINE.md](ENGINE.md) | Deterministic calculation catalog, reason traces, the code/LLM boundary |
| [PLAN.md](PLAN.md) | Architecture, data models, AWS, phases, one-way doors |
| [LEARNING.md](LEARNING.md) | What each tool is and how much of it you actually need to know |
| [IDEAS.md](IDEAS.md) | Menu of things to explore, not a backlog |

## Status

- **Phase 0 — Garmin spike:** probe script written, awaiting a real run against the watch.
- **Phase 1 — Domain models and calculations:** done. 170 tests, 99% coverage on `backend/core`.
- **Phase 2 onward:** not started.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev,cli,garmin]"
```

## Run the tests

```bash
.venv/bin/python -m pytest
```

With coverage on the engine:

```bash
.venv/bin/python -m pytest --cov=backend/core --cov-report=term-missing
```

Lint:

```bash
.venv/bin/python -m ruff check backend/ scripts/
```

## Phase 0: discover what your watch actually reports

Run this before any normalization code is written. It replaces assumptions about response
shapes with saved evidence.

```bash
.venv/bin/python scripts/garmin_probe.py --days 3
```

First run asks for your Garmin email, password (via `getpass`, never echoed or stored) and
an MFA code if enabled. It writes a token bundle to `.garmin_tokens/`; **every later run
needs only that bundle, never the password** — which is exactly the property the ingest
Lambda depends on (PLAN.md §7).

Outputs:

- `fixtures/raw/garmin/dt=YYYY-MM-DD/*.json` — full raw responses. **Gitignored**: real health data.
- `docs/fr165-fields.md` — field names, types and presence. No values, so it is safe to commit.

## Layout

```
backend/
  core/         pure domain. No AWS, no HTTP, no I/O, no clock. This is the product.
  providers/    the provider port + the Garmin adapter
  tests/
scripts/        garmin_probe.py (Phase 0)
seed/           food library template — fill from your real product labels
fixtures/       raw/ is gitignored; sample/ holds anonymized fixtures for tests
```

`backend/core` importing `boto3`, `garminconnect` or `fastapi` is a **test failure**, not a
code-review note — see `backend/tests/test_architecture.py`. That boundary is what keeps
the engine testable with no mocks and the AWS layer genuinely swappable.

## The one rule

> Anything that can be reliably calculated is calculated by code. The LLM only interprets
> finished numbers.

Enforced structurally, not by convention: the LLM receives only reason traces, its
data-producing output is schema-constrained to a closed vocabulary, and anything it
extracts is re-validated by our own arithmetic. See ENGINE.md §1.1.
