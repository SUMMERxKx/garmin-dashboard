# Garmin Health Dashboard

A personal health dashboard built on top of a Garmin Forerunner 165: it pulls a day of
watch data, interprets it, stores it, and draws it.

The point is not another chart of your steps. It is to answer a question a watch cannot:
**how much do you actually burn?** Garmin estimates it, and the estimate is wrong in ways
you can measure — 45 minutes of lifting at 124 bpm scored as 312 active kcal, because
heart rate stays high between sets without the oxygen cost behind it. Compare what you
*ate* against what your weight actually *did*, and the difference tells you your real
maintenance. Everything here exists to make that comparison possible and honest.

> **Status.** The acquisition path, storage, the food and body logs, a tested baseline
> engine, a local API that reads and writes, and a six-page dashboard are built and
> working. The cloud, and the energy-balance calculation that closes the loop, are not.
> See [Roadmap](#roadmap).

---

## How it fits together

```
  Garmin Connect
        │  login.py          one authenticated client
        │  endpoints.py      the 17 calls worth making, and why each one
        ▼
   fetch.py                  walk the list; collect responses AND failures
        │
        ▼
   raw_files.py  ──────────► fixtures/raw/garmin/dt=YYYY-MM-DD/*.json
        │                    the archive. Never edited, never deleted.
        │  ◄─── read back from disk, never from the network
        ▼
   normalize.py              17 Garmin shapes → one DailySnapshot
        │
        ▼
   store/                    SQLite, shaped exactly like the DynamoDB it will become
        │
        ▼
   engine/                   baselines: what is normal FOR YOU  (pure functions)
        │
        ▼
   api/dashboard_json.py     the wire contract
   api/payload.py            one function builds the payload …
   api/export.py             … written to a file, or
   api/server.py             … served by FastAPI, which also accepts the two manual entries
        │
        ▼
   dashboard/                React, Vite, Tailwind — six pages; draws, does not judge
```

**The property everything else rests on:** the raw response is saved *before* anything
interprets it. Get the interpretation wrong and it is a replay, not lost history — fix
the mapping, re-run `import`, and corrected history appears for every day already on
disk. That is only possible because nothing ever writes back over the archive.

---

## Running it

```bash
python -m venv .venv && .venv/bin/pip install -e ".[garmin,cli,dev]"

.venv/bin/pip install -e ".[api]"                        # FastAPI and uvicorn

.venv/bin/python -m backend.garmin.run_fetch --days 30   # pull 30 days from Garmin
.venv/bin/python -m backend.cli.main import              # interpret and store them

.venv/bin/uvicorn backend.api.server:app --port 8000     # terminal 1: the API
cd dashboard && npm install && npm run dev               # terminal 2: http://localhost:5173
```

Without the API running, the dashboard falls back to a file you write with
`python -m backend.api.export`; the sidebar says which source it got, and the Log page
disables its forms rather than pretending to save.

The first fetch asks for your Garmin email, password and two-factor code, then saves a
token bundle to `.garmin_tokens/` and stops asking. Run it in a real terminal — the
two-factor prompt needs a human.

### Everyday commands

| Command | What it does |
|---|---|
| `main.py today` | one day, laid out to read (defaults to *yesterday*) |
| `main.py days --days 14` | one line per stored day, to see a span |
| `main.py weigh 75.0` | record this morning's weigh-in |
| `main.py ate 2100` | record the whole day's calories as one number |
| `main.py log whey-protein 1` | log a food |
| `main.py template normal-day` | log a whole day in one command |
| `main.py body` | DEXA scan, and what has changed since |

### Checks

```bash
.venv/bin/python -m pytest          # 69 tests
.venv/bin/python -m ruff check .
cd dashboard && npm run build && npx oxlint src
```

---

## Layout

```
backend/
  garmin/     login, the endpoint list, fetching, the raw archive, normalising
  store/      one table, a partition key and a sort key — DynamoDB's shape on SQLite
  food/       the YAML food library and the day's log
  body/       weigh-ins and DEXA scans
  engine/     baselines: what is normal FOR YOU, and the report the dashboard reads
  api/        the wire contract, the payload builder, the exporter, and the FastAPI server
  cli/        one module per group of commands; main.py is parser and dispatch only
  tests/

dashboard/src/
  data/       the contract mirrored in TypeScript; the fetch (API, then file); the two writes
  lib/        formatting, deriving series out of days, hash routing, the colour tokens
  components/ nav/ the sidebar · ui/ panels, tiles, charts · pages/ the six screens
```

---

## Decisions worth knowing

These are the ones that shape everything else. Each is written up properly in the
module that implements it.

**`None` is not `0`.** A night with no HRV reading and a night with an HRV of zero are
different facts, and averaging them together is how a dashboard quietly starts lying.
Missing crosses the wire as `null`, with its key intact, all the way to the browser.

**The archive is separate from the working copy.** Raw JSON on disk is the truth;
the database is a rebuildable cache. `import` is safe to run as many times as you like.

**SQLite is shaped like DynamoDB.** One table, `pk`, `sk`, and the record as JSON. It is
an odd way to use SQLite and entirely deliberate: moving to AWS swaps one class, and the
access patterns get proven now, while changing them is still free.

**Baselines refuse to guess.** A baseline built from four readings looks exactly as
authoritative on screen as one built from thirty, so below a documented minimum the
answer is `None`. Calling a reading unusual needs *both* a standard deviation of distance
*and* a 3% proportional change — the second condition exists because the first alone
misfires on steady metrics, where a one-beat move is "two and a half standard deviations"
and means nothing.

**The screen shows, it does not score.** There is no invented readiness number. Compressing
HRV, resting heart rate and sleep into one figure would throw away the useful part —
*which* signal moved — in exchange for false precision.

**A day's calories may be assumed; a weight never is.** A day with nothing typed or
logged is scored as the same as the last day that was — the diet genuinely is the same
most days — but the figure crosses the wire as `source: "carried"` with the day it came
from, and is drawn hollow and tagged *assumed*. The label is the whole licence for the
rule. Weight gets no such rule, because an invented weigh-in would be indistinguishable
from a real one afterwards and every later calculation would count it as "no change".

**Judgements are made in Python and sent, never made in the browser.** "Below your
30-day normal" is computed by the tested engine and arrives finished in a `baselines`
block. The browser chooses a colour for it. It never chooses the word.

**A missed morning stays missed.** Nothing carries a weight forward. A fabricated reading
would be indistinguishable from a real one afterwards, and every later calculation would
count it as "no change". The chart breaks the line instead.

**Serving basis travels with every food.** 100 g of dry rice becomes ~250–300 g cooked.
Logging cooked weight against dry macros over-counts by 2.5–3×, which is larger than an
entire daily deficit. Nothing in the project ever converts between bases — a mismatch
stays visible rather than being silently absorbed.

---

## What the FR165 cannot do

Confirmed against 31 days of real responses, so nobody has to re-derive it:

- **No VO₂ max, Training Status or Training Readiness.** Garmin reserves these for its
  more expensive watches. `max_metrics` returns `[]`; `mostRecentVO2Max` is `null` on
  every single day. Any recovery figure has to be built from HRV, resting heart rate,
  sleep and Body Battery — and labelled as ours, never as Garmin's.
- **HTTP 200 does not mean there is data.** Two endpoints return 200 with every field
  null, which is why the health signal is *how many fields were filled in*, not the
  status code.
- **No body composition input.** A DEXA scan is the only direct measurement of what the
  weight is made of, which makes each scan an anchor rather than one reading among many.

---

## Roadmap

| | |
|---|---|
| ✅ | Fetch, archive, normalise, store |
| ✅ | Food library, day log, weigh-ins, DEXA |
| ✅ | Baseline engine, with tests |
| ✅ | Dashboard: six pages, every metric against its own baseline |
| ✅ | A local write API — weigh-ins and a day's calories from the browser |
| ✅ | Running: pace per run and kilometres per week |
| ◻️ | Food logging item by item from the browser |
| ◻️ | DynamoDB and a scheduled fetcher on AWS |
| ◻️ | **Observed maintenance** — the calculation this is all for |

Observed maintenance needs roughly four weeks of daily weigh-ins and daily food logs
before it can say anything. That is a data problem, not a code problem, and the clock
only starts when the logging does.

---

## Privacy

Nothing personal is in this repository, and the `.gitignore` is written to keep it that
way: no raw Garmin responses, no database, no tokens, no DEXA reports, no food library
carrying a real routine, and no exported dashboard data. Every number in the code is
either synthetic or a documented constant.
