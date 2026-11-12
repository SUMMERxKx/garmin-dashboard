# Garmin Health Dashboard

A personal health dashboard built on top of a Garmin Forerunner 165. It pulls a day of
watch data, interprets it, stores it, and draws it.

The point is not another chart of your steps. It is to answer a question a watch cannot:
**how much do you actually burn?** Garmin estimates it, and the estimate is wrong in ways
you can measure. 45 minutes of lifting at 124 bpm scored as 312 active kcal, because
heart rate stays high between sets without the oxygen cost behind it. Compare what you
*ate* against what your weight actually *did*, and the difference tells you your real
maintenance. Everything here exists to make that comparison possible and honest.

> **Status.** Running on AWS and fetching by itself. DynamoDB, S3, two Lambda functions, a
> scheduled Garmin fetcher, EventBridge and a CloudFront distribution behind a login are
> all described in `infra/` and deployed with one command. A custom domain is supported and
> optional. A model writes a short reading of each day and is never allowed to produce a
> number. The daily energy balance and its running total are done. What is left is
> **observed maintenance**, the step that sets that balance against what your weight did.
> See [Roadmap](#roadmap).

---

## How it fits together

```
  Garmin Connect
        │  login.py          one authenticated client
        │  endpoints.py      the 17 calls worth making, and why each one
        ▼
   fetch.py                  walk the list, collect responses AND failures
        │
        ▼
   raw_files.py  ──────────► fixtures/raw/garmin/dt=YYYY-MM-DD/*.json
        │                    the archive. Never edited, never deleted.
        │  ◄─── read back from disk, never from the network
        ▼
   normalize.py              17 Garmin shapes → one DailySnapshot
        │
        ▼
   store/                    SQLite on a laptop, DynamoDB in AWS. One env var picks
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
        ├──► ai/factsheet.py      finished figures, written out as a sheet
        │    ai/interpret.py      a model reads the sheet, and every number it
        │                         writes back is checked against it
        ▼
   dashboard/                React, Vite, Tailwind. Six pages, and it draws without judging
```

In AWS the last two steps become a Lambda behind a CloudFront distribution that also
serves the built dashboard, so the browser talks to one origin and the front-end code is
byte-identical to the one that runs against Vite's proxy on a laptop. A custom domain and
its certificate are both read from the environment and both optional, together. A clone
without them deploys unchanged and keeps the CloudFront address.

```
  browser ──► CloudFront ──► session_gate.js at the edge ──► login page, or onward
                   ├── /api/*  ──► Lambda function URL (FastAPI via mangum) ──► DynamoDB
                   │                    │                                  └──► Parameter Store
                   │                    └──► Bedrock, Nova Lite, ca-central-1
                   └── /       ──► S3, private, read through an access control

  EventBridge ──► fetcher Lambda ──► Garmin ──► S3 (raw) + DynamoDB (interpreted)
       4x a day        logs in with a token, never a password
```

There is no API Gateway. CloudFront calls the API Lambda through its function URL. That URL
is technically open, so the function refuses any request that lacks a secret header, and
CloudFront is the only thing that sends it. Anyone who finds the URL gets a 403.

**The property everything else rests on:** the raw response is saved *before* anything
interprets it. Get the interpretation wrong and it is a replay, not lost history. Fix
the mapping, re-run `import`, and corrected history appears for every day already on
disk. That is only possible because nothing ever writes back over the archive.

---

## What runs in AWS

Five services are provisioned by the two CDK stacks in `infra/`, and two more are used at
runtime. Everything is in `ca-central-1` (Montreal) unless a custom certificate says otherwise.

| Service | What it is for | Stack |
|---|---|---|
| **DynamoDB** | One table, `pk` and `sk`, pay per request, point-in-time recovery, kept on delete | `HealthDashboardData` |
| **S3** | The raw Garmin archive (kept on delete, moves to Glacier Instant Retrieval after 90 days) and a second private bucket for the built website | `HealthDashboardData` and `HealthDashboardApp` |
| **Lambda** | Two functions: the API (FastAPI through mangum, 512 MB, 30 s) and the fetcher (512 MB, 300 s). Each has its own build package | `HealthDashboardApp` |
| **CloudFront** | One distribution for site and API, with a CloudFront Function (`session_gate.js`) and a KeyValueStore that holds the cookie signing secret | `HealthDashboardApp` |
| **EventBridge** | A rule that runs the fetcher at 01:00, 07:00, 13:00 and 19:00 UTC, each time fetching the last 3 days | `HealthDashboardApp` |
| Systems Manager Parameter Store | The login password, the Garmin token bundle, and an optional Anthropic API key. The stack grants access but does not own the values | runtime |
| Bedrock | The day's reading, through the Canadian `ca.amazon.nova-lite-v1:0` inference profile. The API role may call only Nova models | runtime |

The two stacks are split on purpose. The data stack holds the table and the raw archive and
should be touched rarely. Everything in the app stack can be destroyed and rebuilt from this
repository, so a careless `cdk destroy` on the app cannot reach the data.

---

## Running it

```bash
python -m venv .venv && .venv/bin/pip install -e ".[garmin,cli,api,aws,dev]"

.venv/bin/python -m backend.garmin.run_fetch --days 30   # pull 30 days from Garmin
.venv/bin/python -m backend.cli.main import              # interpret and store them

.venv/bin/uvicorn backend.api.server:app --port 8000     # terminal 1: the API
cd dashboard && npm install && npm run dev               # terminal 2: http://localhost:5173
```

Without the API running, the dashboard falls back to a file you write with
`python -m backend.api.export`. The sidebar says which source it got, and the Log page
disables its forms rather than pretending to save.

The first fetch asks for your Garmin email, password and two-factor code, then saves a
token bundle to `.garmin_tokens/` and stops asking. Run it in a real terminal, because the
two-factor prompt needs a human.

On a laptop the day's reading calls Bedrock with whatever AWS credentials are configured.
Without access the Overview page says the reading is unavailable and everything else works.

### Everyday commands

Run these as `.venv/bin/python -m backend.cli.main <command>`.

| Command | What it does |
|---|---|
| `today` | one day, laid out to read (defaults to *yesterday*) |
| `days --days 14` | one line per stored day, to see a span |
| `import` | read saved raw responses into the database, safe to re-run |
| `weigh 75.0` | record this morning's weigh-in |
| `weights` | recent weigh-ins and the change between them |
| `ate 2100` | record the whole day's calories as one number |
| `log whey-protein 1` | log a food |
| `meal morning` | log one saved meal |
| `template normal-day` | log a whole day in one command |
| `copy-yesterday` | copy yesterday's entries onto today |
| `foods` | list the food library and check it for mistakes |
| `body` | DEXA scan, and what has changed since |

### Putting it online

```bash
.venv/bin/pip install -e ".[infra,aws,api]"
.venv/bin/python -m scripts.deploy
```

You need the AWS CDK command line, AWS credentials, and Node 20, 22 or 24 (the deploy script
stops early on anything else). `scripts.deploy` builds the dashboard, builds both Lambda
packages with `scripts/build_lambda.py` (no Docker, it fetches Linux wheels), runs
`cdk deploy --all`, writes the signing secret to the edge, and creates a login password in
Parameter Store if there is none. Secrets are read from `docs/personal/`, which is gitignored,
and generated there if missing. To use your own domain, set `GARMIN_DASHBOARD_DOMAIN` and
`GARMIN_CERTIFICATE_ARN` together. The certificate must be in us-east-1.

Two one-off scripts finish the move from the laptop:

```bash
.venv/bin/python -m scripts.move_to_aws --dry-run   # count what would move, write nothing
.venv/bin/python -m scripts.move_to_aws             # copy the database and the archive up
.venv/bin/python -m scripts.upload_garmin_token     # let the fetcher log in without a password
```

`move_to_aws` needs `GARMIN_DASHBOARD_TABLE` and `GARMIN_DASHBOARD_BUCKET` set to the names
the data stack prints. Both scripts are safe to run again. Re-run `upload_garmin_token` only
if the scheduled fetch starts failing every day.

### Checks

```bash
.venv/bin/python -m pytest          # 167 tests
.venv/bin/python -m ruff check .
cd dashboard && npm run build && npx oxlint src
```

---

## Layout

```
backend/
  garmin/     login, the endpoint list, fetching, the raw archive, normalising,
              and the Lambda that runs the fetch on a schedule
  store/      one table, a partition key and a sort key. DynamoDB's shape on SQLite
  food/       the YAML food library, the day's log, and typed daily intake
  body/       weigh-ins and DEXA scans
  engine/     baselines: what is normal FOR YOU, and the report the dashboard reads
  ai/         the fact sheet, the model call, and the check that it invented no numbers
  api/        the wire contract, the payload builder, the exporter, sign-in, and the
              FastAPI server
  cli/        one module per group of commands, main.py is parser and dispatch only
  tests/

infra/        the AWS setup as code: two stacks, and the edge function that guards them
scripts/      move data to AWS, upload the Garmin token, build the Lambda packages, deploy

dashboard/src/
  data/       the contract mirrored in TypeScript, the fetch (API, then file), the day's
              reading, the two writes
  lib/        formatting, deriving series out of days, hash routing, the colour tokens
  components/ nav/ the sidebar · ui/ panels, tiles, charts · panels/ the reading ·
              pages/ the six screens
```

Data domains, as the code splits them: **garmin** (what the watch recorded), **food** and
**body** (what you ate and weighed, which the watch cannot know), **engine** (judgements
about your own history), and **ai** (a reading of the finished figures).

---

## What the dashboard measures

**Nine metrics get a baseline** (`SNAPSHOT_METRICS` in `backend/engine/report.py`). Each is
compared with your own 7-day and 30-day windows.

| Group | Metrics |
|---|---|
| Recovery | HRV last night, resting heart rate, body battery charged, average stress |
| Sleep | total sleep minutes, sleep score |
| Energy | steps, total kilocalories, active kilocalories |

**Six pages:** Overview, Energy, Recovery, Activity, Body and Log. Overview also carries the
day's reading.

**Energy balance is done.** The Energy page shows intake against Garmin's burn, a daily
balance, and a running total. It is labelled a *balance* and never a deficit, because both
sides carry error. `main.py today` prints the same thing for one day.

**Recovery is shown, not scored.** The Recovery page draws each overnight signal against its
own 30-day band, and there is deliberately no single recovery number.

---

## The day's reading

`GET /api/insight` returns a short headline and a few observations about the span, written
by Amazon Nova Lite on Bedrock. Here is how it works.

1. `ai/factsheet.py` turns the payload into a compact text sheet of finished figures. It
   covers eight of the baseline metrics, the last 7 days of energy balance, weight, and
   training.
2. `ai/interpret.py` sends the sheet to the model with a prompt that forbids new numbers,
   advice and diagnosis. Temperature is 0.
3. Every number in the reply is checked against the sheet. One that is not on it means the
   whole reading is thrown away and the page says so.
4. The reading is stored against a fingerprint of the sheet, so opening the dashboard ten
   times costs one model call and a new weigh-in or fetch is what triggers a new one.

The prompt asks for at most four observations and a headline of up to eight words. If an
Anthropic API key exists in Parameter Store the same prompt goes to Anthropic's API instead,
and removing the key switches back to Bedrock. Only the headline, observations and
fingerprint reach the browser. The model name and token counts go to the log.

---

## Decisions worth knowing

These are the ones that shape everything else. Each is written up properly in the
module that implements it.

**`None` is not `0`.** A night with no HRV reading and a night with an HRV of zero are
different facts, and averaging them together is how a dashboard quietly starts lying.
Missing crosses the wire as `null`, with its key intact, all the way to the browser.

**The archive is separate from the working copy.** Raw JSON on disk is the truth,
and the database is a rebuildable cache. `import` is safe to run as many times as you like.

**SQLite is shaped like DynamoDB.** One table, `pk`, `sk`, and the record as JSON. It is
an odd way to use SQLite and entirely deliberate, and it paid off. Moving to AWS was one new
class and one environment variable, with the same tests run against both stores.
`GARMIN_DASHBOARD_TABLE` set means DynamoDB, unset means the local file, and nothing else
in the codebase knows which it got.

**Baselines refuse to guess.** A baseline built from four readings looks exactly as
authoritative on screen as one built from thirty, so below a documented minimum the
answer is `None`. Calling a reading unusual needs *both* a standard deviation of distance
*and* a 3% proportional change. The second condition exists because the first alone
misfires on steady metrics, where a one-beat move is "two and a half standard deviations"
and means nothing.

**The screen shows, it does not score.** There is no invented readiness number. Compressing
HRV, resting heart rate and sleep into one figure would throw away the useful part, which is
*which* signal moved, in exchange for false precision.

**A model may read the numbers, and may not produce one.** The reading is written from a
fact sheet this code builds out of already-finished values, and every figure it writes back
is checked against that sheet. That check, not the prompt, is what makes this safe next to
health data. A model asked to do arithmetic sounds equally certain whether it is right or
wrong, so it is never asked, and not believed when it does it anyway.

**A day's calories may be assumed, and a weight never is.** A day with nothing typed or
logged is scored as the same as the last day that was, because the diet genuinely is the same
most days. But the figure crosses the wire as `source: "carried"` with the day it came
from, and is drawn hollow and tagged *assumed*. The label is the whole licence for the
rule. Weight gets no such rule, because an invented weigh-in would be indistinguishable
from a real one afterwards and every later calculation would count it as "no change".

**The password is changed in AWS, not in the code.** It lives in Parameter Store,
encrypted, and the stack deliberately does not manage it, since a stack that owned that value
would overwrite it on the next deploy. The session cookie carries its own signed expiry,
so there is no session table anywhere and the check can happen at the edge.

**Judgements are made in Python and sent, never made in the browser.** "Below your
30-day normal" is computed by the tested engine and arrives finished in a `baselines`
block. The browser chooses a colour for it. It never chooses the word.

**A missed morning stays missed.** Nothing carries a weight forward. The chart breaks the
line instead.

**Serving basis travels with every food.** 100 g of dry rice becomes ~250 to 300 g cooked.
Logging cooked weight against dry macros over-counts by 2.5 to 3 times, which is larger than an
entire daily deficit. Nothing in the project ever converts between bases, so a mismatch
stays visible rather than being silently absorbed.

---

## What the FR165 cannot do

Confirmed against 31 days of real responses, so nobody has to re-derive it:

- **No VO₂ max, Training Status or Training Readiness.** Garmin reserves these for its
  more expensive watches. `max_metrics` returns `[]` and `mostRecentVO2Max` is `null` on
  every single day. Any recovery figure has to be built from HRV, resting heart rate,
  sleep and Body Battery, and labelled as ours, never as Garmin's.
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
| ✅ | Energy balance: intake against burn, per day and as a running total |
| ✅ | A write API for weigh-ins and a day's calories from the browser |
| ✅ | Running: pace per run and kilometres per week |
| ✅ | DynamoDB, S3, a Lambda API and CloudFront, described in `infra/` with one command to deploy |
| ✅ | Online behind a login page, with the API reachable only through the distribution |
| ✅ | A scheduled fetcher, so new days arrive without the laptop |
| ✅ | A custom domain, with the hostname and its certificate both read from the environment |
| ✅ | A model's reading of the day, checked line by line against the figures it was handed |
| ◻️ | Food logging item by item from the browser |
| ◻️ | **Observed maintenance**, the calculation this is all for |

Observed maintenance is not built yet. The inputs are all there (daily intake, Garmin's burn
and weigh-ins), but nothing yet turns them into a maintenance estimate. It also needs roughly
four weeks of daily weigh-ins and daily food logs before it can say anything. That is a data
problem as much as a code problem, and the clock only starts when the logging does.

---

## Privacy

Nothing personal is in this repository, and the `.gitignore` is written to keep it that
way: no raw Garmin responses, no database, no tokens, no DEXA reports, no food library
carrying a real routine, and no exported dashboard data. Every number in the code is
either synthetic or a documented constant.
