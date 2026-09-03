# IDEAS.md — the LLM layer, and a menu of things to explore

_Companion to [PLAN.md](PLAN.md), [PRODUCT.md](PRODUCT.md) and [ENGINE.md](ENGINE.md). **This is a
menu, not a backlog** — the right move is to pick two or three, not to feel behind on twenty._

> **Post-v5 status.** The reframe promoted several of these into the plan proper and cut others. What
> moved **in**: reason traces (ENGINE.md §4), observed-maintenance as an observation (ENGINE.md §6.1),
> plateau-vs-water detection, correlations with honest `n`, demo mode, DEXA comparison. What was
> **cut**: the food-combination optimizer, carb periodization, anything prescriptive, and social
> features. What's **deferred to Phase 7**: everything LLM in §2 below. The design detail in §2 still
> stands — it's now implemented in ENGINE.md §7; read this section for the *reasoning*, that one for
> the contract. §3 remains a genuine menu.

---

## 1. The rule, and how to actually enforce it

You said it exactly right: **anything mathematically calculable is ours; the LLM only makes it
nicer.** That's not just a cost preference, it's the correct architecture — LLMs are bad at
arithmetic in a way that's *invisible*, because a wrong number reads as confidently as a right one.
In a tool that tells you what to eat, a silently wrong calorie figure is the worst possible failure.

The problem is that "we agreed the LLM won't do math" is a promise, and promises rot. So enforce it
structurally, three ways:

**1. The LLM never receives raw numbers it could be tempted to combine.** It receives a *reason
trace* (PLAN.md §5.8) — already-computed conclusions with already-computed values:

```json
{"code": "SURPLUS_FROM_TRAINING", "extra_kcal": 620, "activity": "cycling"}
{"code": "HIGH_ACUTE_LOAD", "acwr": 1.62, "carb_delta_g": 40}
{"code": "ADD_FOODS", "items": [{"name": "whey", "servings": 1.5}, {"name": "banana", "servings": 1}]}
```

It renders that into a sentence. It cannot invent a reason that didn't fire, and it has nothing to
add up.

**2. Structured output, constrained to a closed vocabulary.** Where the LLM produces data rather than
prose (food logging, §2.1), it emits a schema whose enums are your actual `foodId`s. It cannot return
a food that isn't in your library.

**3. We verify anything it extracts with our own arithmetic.** When it reads a nutrition label
(§2.4), our code checks `kcal ≈ 4P + 4C + 9F` and rejects the extraction if it doesn't reconcile.
The LLM proposes; deterministic code disposes.

That last pattern — *LLM as extractor, code as validator* — is the single most valuable thing to be
able to describe in an interview. Everyone has "I called an LLM" on their resume now. Almost nobody
can explain how they bounded it.

---

## 2. LLM features, ranked by whether they're worth it

### 2.1 Natural-language food logging — **build this one**
> "had two eggs, toast and a coffee"  →  `[{eggs, 2}, {toast-slice, 1}, {coffee-black, 1}]`

This is the highest-value LLM use in the entire project, and it isn't close. **Logging friction is
what kills every nutrition app.** Not accuracy, not features — the fact that entering food takes
ninety seconds and you're hungry. Getting it to five seconds is the difference between a tool you use
in March and one you abandoned in January.

And it's a perfect fit for the rule: this is **entity resolution, not arithmetic**. The LLM maps text
to IDs; your code looks up macros and sums them. Zero math.

Design:
- Prompt contains your ~20-item library (tiny — a few hundred tokens).
- Output is a constrained schema: `[{food_id: <enum of your ids>, servings: float}]` plus `unmatched: [str]`.
- **Try deterministic fuzzy matching first.** "eggs" hits `eggs` by string similarity — no LLM call at all. Only fall through to the LLM when fuzzy matching is ambiguous or the phrasing is complex. This is both cheaper and faster for the common case.
- `unmatched` items prompt "add this to your library?" → §2.4.
- **Voice is free from here:** the phone's built-in speech-to-text feeds the same text pipeline. Talk to your watch-adjacent app after a meal, done. No extra LLM cost.

Cost: a few hundred tokens on the cheapest model, only on fuzzy-match misses. Cents per month.

### 2.2 Reason-trace narration — **build this, it's nearly free**
Turn the trace into a coach voice:

> *"Big ride today — you're up 620 on the burn. Load's been climbing (ACWR 1.6), so I've pushed carbs
> rather than fat. Whey shake, banana, and a cup of rice gets you most of the way."*

The whole feature is one small prompt over the trace. **Cache aggressively, and bucket the cache
key:** hash the reason codes plus *rounded* values (kcal to the nearest 50, ACWR to 0.1). The same
*situation* then reuses the same sentence even when numbers differ slightly, which for a routine
lifestyle means most days hit cache. Expect a handful of real calls a week.

Always keep a **templated fallback string** for every reason code. If the LLM is down, over budget,
or slow, the app renders the template and nothing breaks. The LLM is a garnish, and the app must be
fully usable without it.

### 2.3 Q&A over your own data via tool use — **the best resume item here**
> "why is my target lower this week?"

The LLM gets **tools, not data**: `get_calibration_history(weeks)`, `get_weight_trend(days)`,
`get_adherence(days)`, `get_load_summary(days)`. It decides *which* to call; your code computes and
returns numbers; it phrases the answer.

This is the modern agent pattern done with actual discipline, and the discipline is the interesting
part. The system prompt forbids arithmetic explicitly, every number in the answer must have come from
a tool result, and the UI can show which tools were called. That last touch — surfacing the tool
trace — turns "trust me" into something inspectable.

Build this *after* §2.1 and §2.2. It's the most impressive and the least necessary.

### 2.4 Adding foods — text, or a photo of the label
> "add my protein bar: 20g protein, 24g carbs, 8g fat"

Or point the camera at a nutrition label and let vision extract it.

The guard is the point: **our code recomputes `4P + 4C + 9F` and compares to the stated kcal.** Within
tolerance, accept. Outside it, reject and ask the user — because either the model misread the label
or the label itself is odd, and both deserve a human glance. Same check applies to typed entry, which
catches your own typos too.

**Same pattern, second application: DEXA report extraction.** Drop in the scan PDF, vision pulls out
fat mass, lean mass, bone mineral, BF% and regional splits, and our code checks that
`fat + lean + bone ≈ total mass` before accepting it. DEXA reports are a fixed layout per clinic, so
this works well — and the arithmetic guard means a misread decimal point gets caught rather than
poisoning both calibration loops (PLAN.md §5.11). See PRODUCT.md §4.1.

Explicitly *not* allowed: asking the LLM to estimate macros for a food with no label. It will produce
confident, plausible, wrong numbers, and those numbers then pollute every downstream calculation
forever. If there's no label, the user types it or it doesn't go in. (A future barcode lookup against
**OpenFoodFacts** — free and open — is the right answer to this, not a guess.)

### 2.5 Weekly narrative review — **cheap, high satisfaction**
Once a week, turn the week's computed summary into a few paragraphs, emailed via SES. Four calls a
month, so you can afford a larger model. Input is the compact numeric summary — never raw data.

This is where an LLM genuinely adds something a chart doesn't: noticing that adherence dropped on the
two days after poor sleep is a *narrative* observation, and prose carries it better than a graph.
Your code finds the correlation; the LLM writes the sentence.

### 2.6 Token discipline — the actual mechanisms
Since you care about this, here's the concrete list rather than good intentions:

- **Never send raw Garmin JSON.** A day's raw payload is tens of KB; the derived summary is a few hundred bytes. The trace-based design already enforces this.
- **Cache on bucketed state hashes** (§2.2). Most days are not novel.
- **Tier the models.** Cheapest tier for narration and food matching; a larger one only for the weekly review and Q&A.
- **Deterministic-first.** Fuzzy match before LLM call; template before LLM call. The LLM is the fallback, not the entry point.
- **A hard monthly token budget with a kill switch**, stored as a counter. Over budget ⇒ templates only, and the UI says so honestly.
- **Log every call's token count** to CloudWatch as a metric. You can't manage what you don't measure, and it's a nice thing to have a graph of.

Realistic cost at this design: **well under $0.20/month.** The discipline isn't really about the
money — it's that a cached, template-backed, deterministic-first design is also *faster* and *more
reliable*, and those matter more.

### 2.7 What the LLM must never do
Worth writing down, because these are the tempting ones:
- Compute or adjust calories, macros, or the deficit.
- Choose the food combination — the optimizer (§5.7) does that; the LLM only phrases the result.
- Estimate macros for an unlabeled food (§2.4).
- Interpret health data as medical advice. Constrain it in the system prompt and keep the disclaimer visible.
- Take free-text from any source and have it treated as instructions. Food names are user input; if friend data or web content ever enters a prompt, it's **data, not instructions**. Low risk at one user, but the habit is worth forming now.

---

## 3. Non-LLM ideas worth exploring

Grouped, with an honest read on value.

### 3.1 Insight — these make the tool smarter about *you*

**Body-composition narrative.** Once §5.11's modeled fat/lean split exists, the LLM has something
genuinely worth saying: *"lean mass has held flat for six weeks while fat mass dropped 2.1 kg"* is a
real narrative from real math, and it's the sentence that tells you the cut is working. This is the
"more processing" you were after — note that it became possible because the *math* got richer, not
because the LLM got more latitude.

**Refeed / diet-break scheduler.** After N weeks in deficit, with suppressed HRV, declining adherence,
and a stalled weight trend, recommend a planned maintenance week. This is real physiology (metabolic
adaptation is well documented) and almost no consumer app does it well because it requires exactly the
data you'll have: intake, output, recovery, and adherence over time. **Highest genuine-value idea on
this list.**

**Plateau vs. water.** Distinguish a real stall from water retention using the EMA plus its variance —
a whoosh after a high-sodium weekend looks like progress and isn't; three flat weeks with low variance
is a real plateau. Prevents the classic mistake of slashing calories during a fake stall.

**TDEE drift chart.** Plot your learned `metabolic_multiplier` over the cut. Watching adaptation happen
to *your* body, measured rather than assumed, is the most compelling single screen the app could have.

**Correlation explorer.** Which inputs actually predict your weight trend — sleep, load, steps, protein?
Simple correlations, not ML. **Be honest in the UI about n and confounds**, or you'll build a machine
for generating spurious findings from 40 data points.

**Weekend drift.** Most cuts fail Friday to Sunday. Quantify the gap between weekday and weekend
adherence. Uncomfortable, useful.

**Protein distribution.** Not just daily total but spread across meals. Cheap to compute, genuinely
actionable.

### 3.2 Product — these make it something you keep using

**What-if simulator.** "If I run 10k tomorrow, what should I eat?" Falls straight out of the engine
being pure — you're calling the same function with a hypothetical day. Nearly free, demos beautifully.

**Offline-first PWA.** Log at the gym with no signal, sync later. This is the difference between a tool
that works and one that works *where you actually are*. Real engineering (service worker, a local
queue, conflict handling) with a real payoff.

**Morning brief push.** Weight prompt + today's target + a recovery note, as a notification. Turns a
site you must remember into a habit that finds you.

**Barcode scanning via OpenFoodFacts.** Free, open, no API key. The honest solution to unlabeled foods,
and much better than letting an LLM guess (§2.4).

**Grocery list.** Generate the week's shopping from your templates and targets. Small feature, oddly
satisfying, and it closes the loop from plan to real life.

**Race / event countdown mode.** Point at a date and let targets shift over the block. Only worth it if
you actually race.

### 3.3 Engineering — these make it worth showing

**Replay tool: rebuild DynamoDB entirely from S3 raw.** A single command that wipes the derived store
and reconstructs it from immutable raw payloads. **Build this one.** It's a few hours, it *proves* the
raw-first design in PLAN.md §2 is real rather than aspirational, it makes schema changes fearless, and
in an interview "I can rebuild my entire database from the landing zone, here's the command" is a
genuinely strong moment.

**Synthetic data generator.** Needed for demo mode (PLAN.md §7) and it makes your tests far better —
generate 200 plausible days and assert engine invariants across all of them.

**Ingest anomaly detection.** Garmin occasionally returns nonsense (0 kcal, a 40 bpm resting HR spike,
a duplicate activity). Detect and quarantine rather than corrupting the derived store. Cheap
insurance, and it's the kind of thing that separates a demo from a system.

**Data export.** One endpoint that dumps everything as JSON/CSV. An hour of work, looks professional,
and it's the right thing to do with your own health data anyway.

**OpenAPI → generated TypeScript client.** FastAPI emits the spec for free; generate the frontend
client from it. Types stay in sync across the stack automatically. Small effort, real everyday payoff.

**Cost dashboard.** A CloudWatch dashboard of spend by service. Being able to say "here's my
architecture, and here's exactly what each piece costs" is unusually convincing.

### 3.4 Social — later, and read PLAN.md §8.4 first
Friend leaderboards, shared training blocks, accountability streaks. All fine ideas, all gated on the
real blocker: **you can't ask friends for their Garmin password.** Social realistically means Strava
as provider #2. Reserve the key shapes now (PLAN.md §8.3), build none of it yet.

---

## 4. Deliberately not doing

Worth naming so they stop occupying space:

- **A full food database.** 800k items, fuzzy search, portion normalization — enormous, solved by others, and irrelevant when you eat twenty things.
- **Native mobile apps.** The PWA covers it.
- **Real-time streaming from the watch.** Garmin syncs in batches; there's nothing to stream.
- **ML for calorie prediction.** You have one subject and a few hundred days. The EMA-plus-feedback controller in PLAN.md §5.9 will outperform anything learned from that, and it's explainable. *Not* using ML here, and being able to say why, is the more sophisticated position.
- **A meal-photo calorie estimator.** Wildly inaccurate, and it violates §2.7 in the most damaging way.

---

## 5. If I could only pick three

Given the goals — a tool you'll actually use, and a project that holds up in an interview:

1. **Natural-language food logging (§2.1).** Nothing else matters if you stop logging in week three. This is the feature that determines whether the whole project survives contact with real life.
2. **The replay tool (§3.3).** A few hours, and it converts the central architectural claim of PLAN.md from a paragraph into a demonstrable command.
3. **Refeed / diet-break scheduling (§3.1).** The thing your app would do that no other app does, built on data only you have assembled.

Then **reason-trace narration (§2.2)** as a fourth, because it's nearly free once the trace exists.

Everything else on this page can wait, possibly forever, and that's fine — a menu you didn't order
from isn't a debt.
