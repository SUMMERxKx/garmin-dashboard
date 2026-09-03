# LEARNING.md — the companion to PLAN.md

_What each thing in the plan actually is, why it's there, and how much of it you genuinely need to
know. Read alongside [PLAN.md](PLAN.md) (architecture), [PRODUCT.md](PRODUCT.md) (what it does) and
[ENGINE.md](ENGINE.md) (the calculations). It changes nothing about any of them._

**Updated for the v5 reframe.** Two things got *removed* from the stack — Athena and Glue (the data is
too small to need them) and Secrets Manager (designed out). That's two fewer subjects, and it's the
normal direction of travel once a design gets clearer: the tool list shrinks.

---

## 0. Read this part first

The plan lists roughly 20 named tools. That number is why it feels heavy. Here is the honest
accounting of what that actually means:

- **~7 of them you will touch for five lines each and never think about again.** ACM, KMS, Budgets, EventBridge Scheduler, API Gateway, CloudFront, SES. In CDK these are literally a few lines apiece. They are *named* in the plan because architecture docs name things, not because each one is a subject you must study.
- **~6 are ordinary Python libraries.** If you can code, you can read their README and be productive in twenty minutes. That is not a euphemism — Mangum is one function call.
- **~4 are genuinely worth real learning time.** CDK, IAM, DynamoDB single-table design, and Cognito. That's it. Those four are where your actual study budget goes.
- **The rest is code you already know how to write** — Python functions, HTTP handlers, a React page, math on numbers.

The document looks big because it is *written down*. Every project has this much surface area; most
of it lives undocumented in someone's head. You are seeing the whole thing at once, at the start,
which is the most intimidating possible moment to see it.

**Nobody holds all of this in their head.** A senior engineer reading PLAN.md would also not know
three or four of these well, and would do exactly what you're about to do: read the docs when they
reach that line. The skill isn't recall — it's knowing what to search for and recognizing when
something smells wrong. You already have the part that's hard to teach: you can code.

One more reframe. **You are not learning 25 tools. You are learning one idea — "rent compute and
storage per-request instead of running a server" — and then meeting the specific products that
implement it.** Once Lambda clicks, most of the rest is variations on the same shape.

---

## 1. The map: things you already know, wearing new names

The fastest way to kill the unfamiliarity is to translate. Almost nothing here is a new concept.

| The plan says | You already know this as |
|---|---|
| **Lambda** | A function. AWS rents you a machine for the 800ms it runs, then throws it away. |
| **S3** | A folder of files, with HTTP instead of a filesystem. `raw/garmin/dt=2026-08-30/sleep.json` is a path. |
| **DynamoDB** | A giant persistent Python dict, where the key is two parts (`PK`, `SK`) so you can ask for ranges. |
| **API Gateway** | nginx. It maps a URL to your code and checks the auth token. |
| **EventBridge Scheduler** | cron, that someone else keeps running. |
| **Cognito** | The login you'd otherwise hand-roll with sessions and bcrypt. |
| **CloudFront** | A CDN — a reverse-proxy cache in front of your files. |
| **IAM** | Unix file permissions, extended to every action in the entire cloud. |
| **KMS** | A keyring service. You never see the key; you ask KMS to encrypt/decrypt on your behalf. |
| **ACM** | Let's Encrypt, managed and auto-renewing. |
| **CDK** | A build script that emits infrastructure JSON. You write Python; it prints CloudFormation. |
| **Docker image** | A zip of an entire tiny OS, so "works on my machine" becomes "ships my machine." |
| **CloudWatch** | `print()` plus a place the prints go, plus graphs and an alarm. |
| **SES** | `smtplib`, as a service. |

Read that table twice. **There is one genuinely new idea in the whole stack** — that infrastructure
is code you write and deploy, rather than buttons you click. Everything else is a thing you already
understand with a billing model attached.

---

## 2. The whole API surface you'll actually touch

This is the section that kills imposter syndrome fastest. Here is essentially every call you will
make against these services across the entire project.

**S3** — 3 calls:
```python
s3.put_object(Bucket=..., Key=..., Body=json.dumps(data))
s3.get_object(Bucket=..., Key=...)["Body"].read()
s3.list_objects_v2(Bucket=..., Prefix="raw/garmin/dt=2026-08-30/")
```

**DynamoDB** — 4 calls, and the fourth is rare:
```python
table.put_item(Item={...})
table.get_item(Key={"PK": ..., "SK": ...})
table.query(KeyConditionExpression=Key("PK").eq(...) & Key("SK").begins_with("DAY#2026-08-30"))
table.update_item(...)   # only where you need atomic increments
```
Note what's missing: no `JOIN`, no `WHERE age > 30`, no `ORDER BY` beyond the sort key. That
limitation *is* DynamoDB. See §5.

**garminconnect** — about 8 calls:
```python
api = Garmin(); api.login(tokenstore=...)
api.get_stats(date)                 # steps, calories, BMR
api.get_activities_by_date(a, b)    # list of workouts
api.get_activity_hr_in_timezones(activity_id)   # the HR-zone splits §5.6 needs
api.get_sleep_data(date)
api.get_hrv_data(date)
api.get_rhr_day(date)
api.get_body_composition(a, b)      # your manual weigh-ins
```

**FastAPI** — the same shape as every web framework ever:
```python
@app.get("/api/day/{date}")
def get_day(date: str) -> DayResponse: ...
```

**Mangum** — genuinely, in full:
```python
handler = Mangum(app)
```
That's the entire library. It translates the event dict Lambda receives into the request object
FastAPI expects. When someone says "we use Mangum," this is what they mean.

That's the real surface area. Roughly twenty function calls. Everything else in the plan is
**configuration** — which is what CDK is for, and why CDK is worth learning properly while most of
the services aren't.

---

## 3. Depth guide — where to actually spend time

Three levels:
- **Skim** — read the README/quickstart, copy the pattern, move on. You will not think about it again.
- **Working** — you need a real mental model, because you *will* have to debug it.
- **Deep** — this is where your learning budget goes. Budget hours, not minutes.

| Thing | Depth | Meet it in | Why that depth |
|---|---|---|---|
| garminconnect / garth | **Working** (auth only) | Phase 0 | The calls are trivial; the OAuth token lifecycle is the part that will confuse you. |
| Pydantic | **Working** | Phase 1 | This is your data contract everywhere. Worth knowing properly. |
| pytest | **Working** | Phase 1 | You'll live in it. |
| Typer | Skim | Phase 1 | Decorators over functions. 15 minutes. |
| Docker | **Working** (just enough) | Phase 2 | You need `FROM`, `COPY`, `CMD`, and how to build for `linux/arm64`. Not the whole ecosystem. |
| **CDK** | **DEEP** | Phase 2 | Your single biggest investment. §4. |
| **IAM** | **DEEP** | Phase 2 | The hardest, most confusing part of AWS. §6. |
| Lambda | **Working** | Phase 2 | Handler signature, cold starts, timeouts, memory→CPU coupling. |
| S3 | Skim → Working | Phase 2 | Three calls. Bucket policies get fiddly. |
| **DynamoDB** | **DEEP** | Phase 2 | Single-table design is a genuinely different way of thinking. §5. |
| EventBridge Scheduler | Skim | Phase 2 | It's cron with a JSON body. |
| boto3 | **Working** | Phase 2 | AWS's Python SDK. Learn its *shape* once; each service is then just method names. |
| Lambda Powertools | Skim | Phase 2 | Three decorators: logger, tracer, metrics. |
| FastAPI | Skim → Working | Phase 3 | Easy if you've used any web framework. |
| Mangum | Skim | Phase 3 | One line. |
| API Gateway | Skim | Phase 3 | CDK writes it. You'll touch CORS once and swear. |
| **Cognito** | **DEEP-ish** | Phase 3 | Not conceptually hard — just genuinely unpleasant DX. §7. |
| React / Vite / TS | depends on you | Phase 3 | If you've done frontend, skim. If not, this is a real second track. |
| CloudFront | **Working** | Phase 3 | Caching and invalidation will bite you at least once. §8. |
| ACM | Skim | Phase 3 | Two DNS records. One gotcha: must be `us-east-1`. |
| CloudWatch | Skim | Phase 4 | Logs and one alarm. |
| GitHub Actions + OIDC | **Working** | Phase 4 | YAML is easy; the trust policy is the part to understand. §9. |
| hypothesis | Skim | Phase 4 | Optional. Nice-to-have. |
| SES | Skim | Phase 5 | One gotcha: sandbox mode. §10. |

**Four Deeps out of twenty.** That's the real scope of what you're taking on.

---

## 4. CDK — the one genuinely new idea

**The problem it solves.** You could click through the AWS console to create a bucket, a table, a
function. Six months later you cannot remember what you clicked, you cannot code-review it, you
cannot recreate it, and you cannot tell what changed. Infrastructure as code makes your
infrastructure a file in git.

**What CDK actually is.** You write Python. CDK runs your Python and it *prints a giant JSON file*
(a CloudFormation template) describing the resources you want. CloudFormation then makes reality
match that JSON. That's the whole thing.

The mental model that makes it click: **your CDK code doesn't create anything. It's a program whose
output is a config file.** So a `for` loop over three bucket names emits three bucket definitions.
That's why it's Python and not YAML — you get loops, functions, and types when generating config.

```python
bucket = s3.Bucket(self, "RawData", encryption=s3.BucketEncryption.KMS_MANAGED)
fn = lambda_.DockerImageFunction(self, "Ingest", code=..., timeout=Duration.minutes(5))
bucket.grant_read_write(fn)     # <-- this line writes IAM policy for you. See §6.
```

**The four commands you'll use:**
```bash
cdk diff     # what would change if I deployed?  -- run this constantly
cdk deploy   # make it so
cdk destroy  # tear it all down
cdk synth    # just print the JSON, don't deploy
```

**Things that will confuse you, stated up front:**
- **`cdk bootstrap`** — one-time per account/region. It creates a bucket and roles CDK needs to function. It fails cryptically if you skip it.
- **Constructs come in L1/L2/L3 "levels."** L1 (`CfnBucket`) is a raw 1:1 CloudFormation mapping. L2 (`Bucket`) is the friendly one with sane defaults and `grant_*` helpers. **Use L2.** When a tutorial shows `Cfn`-prefixed classes, it's either old or doing something unusual.
- **Deploys are slow** — 1–3 minutes even for a tiny change. This is normal and it's the main downside versus a `git push` platform. For fast iteration, test the Python locally and deploy in batches.
- **Drift.** If you change something in the console by hand, CDK doesn't know, and the next deploy may stomp it. Rule: once a resource is in CDK, never touch it in the console.

**Why CDK over Terraform here:** same language as your backend, so one venv and one mental model, and
the `grant_*` helpers generate least-privilege IAM automatically — which is exactly the part you'd
otherwise get wrong. Terraform is more common in industry and worth learning eventually; if an
interviewer asks, *that* is the honest answer, not "CDK is better."

---

## 5. DynamoDB — why the data model looks weird

The `PK` / `SK` table in PLAN.md §4 probably looked arbitrary. It isn't, and this is the concept
most worth actually understanding.

**In Postgres**, you design tables around your *data* (a `days` table, an `activities` table), then
write whatever query you want later. Flexibility first.

**In DynamoDB**, you design around your *queries*. You must know what you'll ask before you design.
There's exactly one efficient access pattern: "give me one item by exact key" or "give me a range of
items sharing a partition key." No joins, no filtering on non-key attributes without scanning
everything.

That sounds like a downside. Here's the trade you're buying: predictable single-digit-millisecond
reads at any data size, zero servers, zero connection pooling, and ~$0 when idle. (Connection
pooling matters more than it sounds — Lambdas scale to many concurrent instances, and each one
opening a Postgres connection is a classic way to exhaust a database.)

**Single-table design** is the trick that makes it work. Instead of one table per entity, everything
lives in one table and the *key shape* encodes the type:

```
PK              SK                          
USER#deep       DAY#2026-08-30#GARMIN       ← today's metrics
USER#deep       DAY#2026-08-30#ACT#12345    ← a workout
USER#deep       DAY#2026-08-30#FOOD#0812    ← breakfast
USER#deep       DAY#2026-08-30#WEIGHT       ← weigh-in
USER#deep       FOOD#chicken-breast         ← library item
```

Now look at what one query does:

```python
table.query(KeyConditionExpression=Key("PK").eq("USER#deep") & Key("SK").begins_with("DAY#2026-08-30"))
```

**That single request returns the entire day** — metrics, workouts, every food entry, the weigh-in —
sorted, in one round trip. In Postgres that's four queries or three joins. That's the payoff, and
it's why the keys are shaped the way they are.

**The rule to internalize:** write down your access patterns *before* the schema. For this project
there are about five ("render today," "get the food library," "last 30 days of weight," "goal in
force on date X," "last 28 days of activities for load"). Once they're written, the key design
follows almost mechanically — and PLAN.md §4 is just that exercise already done.

**Honest caveat, and the resolution:** if you wanted a genuinely ad-hoc query ("every day I ate over
200 g protein *and* slept badly"), DynamoDB can't express it. The original plan answered that with
Athena over the S3 raw data.

**v5 removed Athena instead**, and the reasoning is worth understanding because it's a good example of
letting the numbers decide. One user producing one snapshot a day is **365 items a year — a few
hundred KB.** A single range query returns the whole year inside DynamoDB's 1 MB page limit, and the
pure functions in `core/` then compute baselines, correlations and comparisons in memory in
microseconds. There is no analytics problem to solve, so there's no analytics tier.

The lesson generalizes: **"which database scales better" is the wrong question until you've worked out
how much data you actually have.** Most personal projects never reach the volume where the interesting
tradeoffs begin. Knowing the threshold where it *would* flip (PLAN.md §6 puts it around 50 users, or
per-second data instead of daily summaries) is what makes the choice defensible rather than lucky.

---

## 6. IAM — the part everyone finds hardest, so let's be honest about it

**IAM is the most confusing thing in AWS** and it's where you will lose the most time to
`AccessDenied`. It's not you.

**Mental model:** every action in AWS is denied unless something explicitly allows it. A *policy* is
a list of `(Effect, Action, Resource)` rules. A *role* is a bag of policies that a thing can wear
temporarily. Your Lambda doesn't have a password; it *wears a role*, and AWS hands it short-lived
credentials automatically.

```json
{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::my-bucket/raw/*"}
```

That's it. Read: "this identity may call GetObject on objects under `raw/` in that bucket." Every
IAM policy is that, repeated.

**Why CDK saves you here.** Writing those by hand is where people give up and slap on `s3:*` and
`Resource: "*"` — which works and is also exactly the thing a security-minded interviewer will spot.
Instead:

```python
bucket.grant_read_write(fn)
table.grant_read_write_data(fn)
```

CDK generates the tightly-scoped policy for you. So you get least-privilege as a *side effect of
using the tool properly*, which is why "least-privilege IAM" is a claim you can actually defend in
PLAN.md §2 rather than a phrase you're borrowing.

**When you hit `AccessDenied`** (you will, repeatedly), the debugging order is:
1. Read the error — it names the exact action and resource. It's more helpful than it looks.
2. Check you granted that *specific* action, not a neighboring one (`s3:GetObject` ≠ `s3:ListBucket`; listing a bucket and reading an object are different permissions, which surprises everyone once).
3. Check the resource ARN matches — bucket-level (`arn:...:bucket`) and object-level (`arn:...:bucket/*`) are different ARNs.
4. If KMS is involved, you need permission on **both** the bucket *and* the KMS key. This one catches everybody.

**Do not learn IAM up front.** It doesn't stick in the abstract. Learn it by hitting denials in
Phase 2 and reading the errors. Three or four of those and the model clicks.

---

## 7. Cognito — setting expectations honestly

Cognito is not conceptually hard: it's a user directory that issues JWTs. API Gateway validates the
JWT before your Lambda ever runs, so your API code just trusts the claims.

**But its developer experience is the worst in this stack**, and I'd rather you hear that from the
plan than conclude you're the problem. The docs are sprawling, the console has two overlapping
concepts (user pools vs identity pools — **you only need user pools**), and the hosted-login UI is
awkward to style.

**Keep it minimal:** one user pool, one app client, the Hosted UI for login (so you write zero login
code), and `Amplify UI` or `oidc-client-ts` on the React side to handle the redirect dance. One user.
No social login, no custom flows, no Lambda triggers, no identity pools.

If it becomes a time sink disproportionate to the rest, that's a known failure mode and not a
personal one. It is still the right call for the resume — "I integrated managed OIDC auth" is worth
more than a hand-rolled JWT you'd have to defend the security of.

---

## 8. CloudFront — the one that will confuse you once

CloudFront caches your files at edge locations worldwide. Two things to know now so they don't cost
you an afternoon:

1. **Invalidation.** Deploy new frontend files and users may still get the old ones — CloudFront is still serving its cache. You must explicitly invalidate (`/*`) after each deploy. Put it in the CI script and forget it. First 1,000 invalidation paths per month are free.
2. **The `us-east-1` certificate rule.** CloudFront only reads ACM certs from `us-east-1`, no matter where your stack lives. If your stack is in `ca-central-1`, the cert still goes in `us-east-1`. This is a real constraint, not a mistake in the plan (PLAN.md §7, §11.4).

Also: an SPA needs a 403/404 → `/index.html` error mapping, or refreshing on `/day/2026-08-30` gives
a blank page. Standard, one line in CDK, but the symptom is baffling if you don't expect it.

---

## 9. GitHub OIDC — worth understanding, because it's a good interview answer

**The old way:** create an AWS access key, paste it into GitHub secrets. It works. It's also a
long-lived credential sitting in a third-party system forever, and it's what a lot of tutorials
still show.

**The OIDC way:** GitHub Actions mints a short-lived signed token describing *"this is a run from
repo `you/garmin-dashboard`, branch `main`."* AWS is configured to trust GitHub as an identity
provider, and to let that specific claim assume a specific role. Actions gets credentials valid for
about an hour. **No permanent secret exists anywhere.**

The piece to actually get right is the trust policy condition:

```json
"StringLike": {"token.actions.githubusercontent.com:sub": "repo:you/garmin-dashboard:ref:refs/heads/main"}
```

The classic mistake is leaving that as `repo:*` — which means *anyone's* GitHub repo can assume your
role. Scope it to your repo and branch.

If you can explain this trade — long-lived static key vs. short-lived federated token — you're ahead
of most people who list "CI/CD" on a resume.

---

## 10. Small gotchas that would otherwise eat an evening

- **SES starts in sandbox mode.** You can only send to *verified* addresses. Since the weekly review emails only go to you, just verify your own address — you never need to request production access. People burn hours on this.
- **Lambda memory controls CPU.** They're the same dial. A function that feels slow at 256MB may be *cheaper* at 1024MB because it finishes 4× faster. Counterintuitive; worth knowing.
- **Lambda container images must match the target architecture.** On an Apple Silicon Mac, build for `linux/arm64` and set the Lambda to `arm64` (which is also ~20% cheaper). Mismatch gives an opaque runtime error.
- **DynamoDB `Decimal`.** boto3 returns numbers as `decimal.Decimal`, not `float`. Your JSON serializer will crash on it the first time. Convert at the repo boundary.
- **Timezones.** Garmin returns a mix of local dates and UTC timestamps. Decide *now* that a "day" means your local calendar day, convert once at ingest, and never think about it again. Getting this wrong makes late-night workouts land on the wrong day — a bug you'll find weeks later and hate.
- **DynamoDB's page limit is 1 MB.** A range query returning more than that silently paginates — you get a `LastEvaluatedKey` and a partial result. At one snapshot a day you'd need ~3 years to approach it, but handle pagination anyway rather than assuming a query returned everything.

---

## 11. The domain math, demystified

None of this is advanced. The formulas are small; they only look intimidating written as acronyms.

**BMR (Mifflin–St Jeor)** — calories to stay alive at rest:
```
male:   10×kg + 6.25×cm − 5×age + 5
female: 10×kg + 6.25×cm − 5×age − 161
```

**TDEE** — total daily burn = BMR + activity + TEF. **TEF** (thermic effect of food) is the ~10% of
intake spent digesting. Protein is highest; the 10% flat rate is a fine approximation.

**Deficit math:** ~7,700 kcal ≈ 1 kg of fat. A 500/day deficit ≈ 0.45 kg/week. This is the number
the §5.9 loop calibrates, because the 7,700 constant and Garmin's calorie estimates both carry real
error for any individual.

**TRIMP (Banister)** — training load from one session. Instead of just duration, weight each minute
by how hard your heart was working:
```
TRIMP = Σ (minutes_in_zone × zone_weight)     # weights roughly 1,2,3,4,5 for zones 1-5
```
So 30 minutes at threshold outranks 60 minutes easy. That's the entire insight.

**ACWR (acute:chronic workload ratio)** — `7-day average load ÷ 28-day average load`. Around 1.0 you're
training consistently. Above ~1.5 you've ramped hard and injury risk climbs. This is the thing
PLAN.md §5.6 builds because the FR165 won't give it to you.

**EMA (exponential moving average)** — a weighted average that favors recent values:
```python
ema = alpha * today + (1 - alpha) * ema_yesterday
```
One line. Used for weight trend (kills daily water-weight noise) and for acute/chronic load. When
someone says "EWMA," this is it.

That's every formula in the project. Five of them, none longer than a line.

---

## 12. What to learn *when* — do not front-load

The single worst thing you could do is spend three weeks on AWS courses before Phase 0. It won't
stick without something to attach it to, and it delays the part that teaches fastest: building.

**Before Phase 0** — nothing. Seriously. Install Python, `pip install garminconnect`, log in, print
some JSON. That's the whole prerequisite, and it's the highest-information hour in the project
because it tells you what the data actually looks like.

**Before Phase 1** — Pydantic basics (30 min) and a pytest refresher if it's been a while. That's it.
Phase 1 is pure Python; it's the part you're already qualified for, and it's where the *interesting*
work is (the engine).

**Before Phase 2** — this is the real study block, and the only one:
- CDK: the official *CDK Workshop* (Python track), 2–3 hours. Do it hands-on, don't read it.
- DynamoDB: watch/read one thing on single-table design. Alex DeBrie is the canonical source.
- Docker: just enough for a Lambda base image.
- IAM: nothing up front. Learn it from the denials.

**Before Phase 3** — FastAPI's tutorial (fast). Cognito docs when you get there, and budget extra
patience for it (§7).

**Before Phase 4/5** — nothing. By then you'll be reading docs on demand, which is the actual
end-state skill.

**Total genuine study: roughly one focused afternoon, plus one Cognito evening.** Everything else is
just-in-time.

---

## 13. How to learn a library in 20 minutes (the method)

You said you don't know many libraries. That's a fixable, mechanical gap — here's the loop:

1. **Read the README's first code block.** Not the docs site. The README example is the 80% case, chosen by the author as most representative.
2. **Type it out and run it.** Don't copy-paste. Typing surfaces the bits you skimmed.
3. **Break it on purpose.** Pass a wrong argument, read the error. Error messages teach the mental model faster than prose.
4. **Find the 5 functions you'll use** and ignore the rest of the API entirely. §2 above is that exercise, pre-done, for this project.
5. **Only then read prose docs**, and only for the specific thing that confused you.

Most libraries are one idea plus API surface. Mangum is "translate a Lambda event into an ASGI
request." Typer is "turn function signatures into CLI flags." Pydantic is "validate a dict against a
class." Once you have the one-sentence version, the API is just names.

---

## 14. Self-check questions

If you can answer these in your own words at the end of each phase, you've learned it. If not,
that's the specific thing to go read — much better than a vague feeling of not knowing.

**Phase 0/1**
- Why does the plan store raw JSON in S3 *before* parsing it into the database?
- Why are goals effective-dated records instead of one editable field?
- Why an EMA of weight rather than the actual number?

**Phase 2**
- What does `cdk deploy` actually do, in two steps?
- Why does the ingest Lambda have reserved concurrency of 1? (Hint: PLAN.md §6.1, token refresh.)
- Why can one DynamoDB query return an entire day?
- Why is the Garmin password not stored anywhere in AWS?

**Phase 3**
- Where is the JWT validated — your code, or before it?
- Why must the certificate be in `us-east-1`?

**Phase 4/5**
- What does GitHub Actions present to AWS instead of an access key?
- What would you change if this had 10,000 users instead of 1?

That last one is the interview question, and PLAN.md §2 already has your answer.

---

## 15. The reframe worth keeping

You said you know what's happening and also don't. That's the accurate feeling of **holding the
architecture but not the mechanics** — and it's the correct order to have them in. Mechanics are
cheap and searchable; architecture is the expensive part, and you already have it, because you asked
the right questions in the last round (can I reuse the domain, do I need MFA, is the goal
changeable). Those were *architectural* questions, and two of them changed the plan.

The tools in PLAN.md aren't a prerequisite list. They're a **map of what you'll have learned** when
it's done. You are not behind for not knowing them yet — that's the project, not the entry fee.

Build Phase 0 tonight. It's one `pip install` and one login, and it'll make half of this concrete.
