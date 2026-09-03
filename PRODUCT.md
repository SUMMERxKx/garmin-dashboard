# PRODUCT.md — what this is, what it shows, in what order

**v2** — rewritten against the product vision brief.

**Doc set:** this file is product definition, MVP, screens, and which Garmin data earns its place.
Deterministic calculations and the code/LLM boundary: **[ENGINE.md](ENGINE.md)**. Architecture and
infrastructure: **[PLAN.md](PLAN.md)**. Teaching companion: **[LEARNING.md](LEARNING.md)**. Idea menu:
**[IDEAS.md](IDEAS.md)**.

---

## 1. What this is

**A personal health dashboard built around Garmin data, with nutrition and energy balance layered on
top, and an LLM added at the end as an analysis layer.**

It is **observational and analytical.** It tells you what happened and how that compares to your own
normal. It does not tell you what to train, does not generate diet plans, and does not decide your
targets for you.

**What it is not:**
- Not a workout planner. No cutting programs, no bulking programs, no "today you should do X."
- Not an AI coach. The LLM never produces a number.
- Not primarily a calorie tracker. Nutrition is one input to energy balance, not the point.
- Not a medical tool. It surfaces patterns relative to your baseline. It never names a condition.

**The one-line version of the engineering:** a personal health data platform that ingests wearable
data, combines it with nutrition and body measurements, computes deterministic energy, recovery and
body trends against personal baselines, preserves raw history, and adds an LLM only as an explainable
reasoning layer over already-validated metrics.

---

## 2. The MVP: five questions

The first usable version answers exactly these, and nothing else matters until it answers them well:

1. **What is Garmin telling me about my body today?**
2. **How many calories have I burned today?**
3. **What have I eaten today, and where are my macros?**
4. **Am I currently in a deficit or a surplus?**
5. **How does my recovery look relative to my recent baseline?**

Plus three actions: `Log Food`, `Copy Yesterday`, `Log Weight`.

Question 5 is the one that makes it more than a readout — it requires baselines, which is why
baselines are a first-class concept (ENGINE.md §3) rather than a chart feature.

---

## 3. Information hierarchy

The dashboard's job is to make a number *mean* something. The rule, applied everywhere:

```
CATEGORY          what part of my body/day is this about
    ↓
HEADLINE NUMBER   large, one per category, no units clutter
    ↓
COMPARISON        vs. my own baseline — the part that creates meaning
    ↓
DETAIL            on tap, not by default
```

So never this:
```
HRV   48 ms
```
Always this:
```
HRV
48 ms
30-day baseline 56 · −14%
```

Three consequences:
- **Every headline metric has a comparison line.** If a metric has no meaningful baseline, it probably doesn't belong on the top screen.
- **Categories before numbers.** Six labelled sections beat thirty labelled values.
- **Detail is one tap down.** The top screen is a glance, not a report.

**Colour carries state, never decoration** — above baseline / normal / below baseline, and one accent
for the current energy-balance state. No metric gets a colour just to look alive.

---

## 4. Screens

| Screen | Answers | Contents |
|---|---|---|
| **Today** | all five MVP questions | The compact overview in §5. The only screen that must be perfect. |
| **Energy** | Q2, Q4 | Burned vs consumed, balance, intraday expenditure curve, balance history |
| **Nutrition** | Q3 | Macro rings vs target, day's entries, log/copy/templates, adherence |
| **Activity** | Q1 | Steps, distance, active calories, activities with duration/HR/zones, intensity minutes |
| **Recovery** | Q5 | Sleep (duration, stages, score), HRV, resting HR, Body Battery, stress — each vs. baseline, with the derived recovery status and its reason trace |
| **Body** | — | Weight, EMA, weekly/monthly change, rate of change, DEXA (or an empty state that invites one), composition estimates clearly labelled |
| **Trends** | — | 7 / 30 / 90 / 365-day series for every category, period-over-period comparison |

Seven screens. **Mobile-first** — Today and Nutrition must work one-handed.

Everything else discussed previously (correlations, projections, what-if, weekly review) lives inside
Trends or arrives in Phase 5+. Not on Today.

---

## 5. The Today screen

```
GOOD MORNING · WEDNESDAY 2 SEPTEMBER

──────────────────────────────
ENERGY BALANCE

     Burned      2,421 kcal
     Consumed    1,930 kcal
     ─────────────────────
     Balance      −491 kcal        deficit

──────────────────────────────
NUTRITION

  Calories   1,930 / 2,400
  Protein      151 / 180 g
  Carbs        214 / 260 g
  Fat           61 / 70 g

  [ Log Food ]   [ Copy Yesterday ]

──────────────────────────────
ACTIVITY

  Steps            13,842      +21% vs 30d
  Active cal          617      +18% vs 30d
  Training         58 min

──────────────────────────────
RECOVERY                  Near baseline  ⓘ

  Sleep            7h 04m      −14m vs 30d
  Sleep score          81
  HRV               51 ms      −9% vs baseline
  Resting HR        53 bpm     baseline 53
  Body Battery         72

──────────────────────────────
BODY

  Weight            78.6 kg
  7-day average     78.9 kg
  30-day change     −1.4 kg
  DEXA              Not recorded   [ Add ]

  [ Log Weight ]

──────────────────────────────
AI INSIGHT                    (Phase 7)

  Activity is above normal today while recovery
  sits close to baseline. Energy balance is
  approximately −490 kcal and protein is 29 g
  below today's target.
──────────────────────────────
```

Notes on what the mock encodes:
- **Energy balance is first**, because it's the question with the shortest shelf life.
- **Every number that has a baseline shows it.** The ⓘ on Recovery opens the reason trace (§8).
- The **AI Insight block is last and is absent until Phase 7.** The screen must be complete without it — the LLM is the final layer, not the frame.
- Weight, sleep and Body Battery are shown even when today's value is missing; an empty state (`—`) is honest and better than hiding the row.

---

## 6. Garmin data to ingest

Selected against the six questions, not against what the API exposes. **The Forerunner 165 does not
provide everything Garmin's higher-end watches do**, so availability below is either *confirmed*, or
*verify in Phase 0* — and Phase 0's whole job is to settle that column.

| Data | Endpoint (`garminconnect`) | Feeds | FR165 |
|---|---|---|---|
| Steps, distance, intensity minutes | `get_stats` / `get_user_summary` | Activity | ✅ |
| Active / resting / total calories | `get_stats` | **Energy — the core input** | ✅ |
| Activities: type, duration, calories, avg/max HR | `get_activities_by_date` | Activity | ✅ |
| HR zone time per activity | `get_activity_hr_in_timezones` | Activity; optional load metrics later | ✅ |
| Resting heart rate | `get_rhr_day` | Recovery | ✅ |
| Intraday heart rate | `get_heart_rates` | Activity detail | ✅ |
| Sleep duration, stages, score | `get_sleep_data` | **Recovery — core** | ✅ |
| HRV | `get_hrv_data` | **Recovery — core** | ✅ (needs ~3 weeks to baseline) |
| Body Battery | `get_body_battery` | Recovery | ✅ |
| Stress | `get_stress_data` | Recovery | ✅ |
| VO2 max | `get_max_metrics` | Trends | ✅ |
| Weight / body composition | `get_body_composition` | Body — picks up weight typed into Garmin Connect | ✅ (manual entries only; no scale) |
| Respiration | `get_respiration_data` | Recovery detail | ❓ verify |
| Pulse Ox / SpO2 | `get_spo2_data` | Recovery detail | ❓ verify |
| Training Readiness / Status / Load | `get_training_readiness` etc. | — | ❌ **not on FR165** |
| Floors climbed | `get_floors` | — | ❌ no barometric altimeter |

**Deliberately not ingested:** anything that doesn't answer one of the six questions. Golf metrics,
race predictors, GPS tracks, per-second streams. They're available and irrelevant.

**One honest caveat about calories on lifting days.** Garmin's active-calorie estimate is HR-driven,
and heart rate is a poor proxy for energy cost during resistance training — HR rises between sets
without matching oxygen consumption. So expect **expenditure to be overstated on push/pull/legs days**
and comparatively accurate on your 10 km run. This is a property of the device, not something to fix in
software, and it's worth surfacing in the UI rather than hiding.

The consolation is structural: **the observed-maintenance calculation (ENGINE.md §6.1) corrects for it
automatically**, because it's anchored to your actual weight trend rather than to Garmin's numbers. If
Garmin systematically overestimates by 150 kcal on three days a week, that bias shows up as a gap
between Garmin's implied maintenance and your measured one. The system finds its own calibration error
— which is a much better answer than pretending the input is exact.

**On derived metrics:** where the FR165 withholds a synthesized score, we may compute our own — but
it is **labelled as ours, never presented as Garmin's** (ENGINE.md §5). The one clearly worth deriving
is a **recovery status** from sleep/HRV/RHR/Body Battery against personal baselines, because that's
the FR165's real gap and it falls straight out of the baseline engine. Training load (TRIMP/ACWR) is
*possible* from HR-zone data but demoted to optional: its main use is prescribing training, which this
product deliberately doesn't do. Ingest the zone data anyway — it's free and keeps the option open.

---

## 7. Nutrition: optimized for repetition, not search

Your diet is repetitive. So the fast path is **not** a food search.

```
Open Nutrition
      ↓
[ Copy Yesterday ]          ← one tap, day is populated
      ↓
adjust:  rice 200 g → 250 g
         remove banana
         add protein shake
      ↓
done — totals recalculate instantly
```

**No LLM involved.** This is a deterministic feature and it is the headline nutrition capability.

Logging paths, in priority order:
1. **Copy Yesterday** — one tap. Expected to be the most-used control in the app.
2. **Copy from a specific day** — pick any recent day.
3. **Saved meals** — Breakfast / Lunch / Post-Workout / Dinner, each a set of foods.
4. **Saved days** — "Normal Training Day", "Rest Day", "High Carb Day". Optional; never a forced category.
5. **Manual entry** — pick from library, set servings.
6. **Natural language** — *Phase 7 only*. See §12.

### 7.1 Seed library — and the accuracy trap in it
Your current pattern becomes the starting library and four saved meals, scaffolded in
[`seed/food-library.template.yaml`](seed/food-library.template.yaml):

| Food | Serving basis | Typical portion |
|---|---|---|
| Whey protein | as sold | 1 scoop |
| Milk, 0% | as sold | 500 mL |
| Yogurt | as sold | 180 g |
| Oats | **dry** | 40 g |
| Frozen berries | as sold | — |
| Chicken breast | **raw** | ~200 g |
| Rice | **dry** | varies daily |
| Frozen vegetables | as sold | — |

Saved meals: Breakfast (whey + milk), Yogurt & oats, Afternoon (chicken + rice), Dinner (chicken +
rice + vegetables). Plus a "Normal Day" template. **All quantities editable; rice is deliberately left
unset** because your portion varies.

**The trap — `serving_basis` is the highest-impact field in the whole nutrition system.** Cooking
changes weight, not macros:

- **200 g raw chicken cooks down to ~150 g.** Weigh it cooked, apply raw macros, and you *under-count* protein and calories by roughly a third.
- **100 g dry rice becomes ~250–300 g cooked.** Weigh it cooked, apply dry macros, and you *over-count* by 2.5–3×.

At your volumes that second one is a several-hundred-calorie daily error — larger than your entire
deficit, and it would make the energy balance screen quietly worthless. So every food carries an
explicit `raw | cooked | as_sold` basis, the UI shows it next to each entry, and the rule is: **decide
once per food which state you weigh in, and record the label on that same basis.**

**Nutrition values come from your actual product labels**, collected during implementation. The
template leaves them `null` on purpose — a guessed macro value contaminates every downstream
calculation permanently, which is the same principle that keeps the LLM away from arithmetic
(ENGINE.md §1.1).

**Food library fields** — name, serving size + basis, calories, protein, carbs, fat. Optionally fiber and sodium
(fiber because it's on every label you already read; sodium because it explains day-to-day water
weight, which makes weight jumps interpretable). Macros are the priority; **no micronutrients** —
they'd require a real food database and that's the tail wagging the dog.

**Macro targets are yours.** You set calories, protein, carbs, fat. The system may *show* a computed
suggestion, but it never overwrites what you chose. Targets are **dated and history-aware**:

```
Aug 1 – Aug 31   2400 kcal · 180 P · 260 C · 70 F
Sep 1 onward     2500 kcal · 180 P · 285 C · 70 F
```

A dashboard for 15 August is scored against August's target, not today's. This is an append-only
record, not an editable field — see PLAN.md §14, it's one of the decisions that's painful to retrofit.

**Starting target, effective 2026-09-03:** 2,350 kcal · 180 P · 260 C · 65 F, goal cutting. The macros
total 2,345 kcal, so the target is internally consistent. Protein is 2.25 g/kg at 80 kg — at the top of
the evidence-based range, which is the right place to be while cutting with resistance training. Fat at
0.81 g/kg clears the hormonal floor comfortably.

**The app will never change these on its own.** It may *show* that your weight trend disagrees with
them (ENGINE.md §6.1), and later the LLM may say so in words, but any change is an explicit act by you
that appends a new dated record.

### 7.2 A fixed target against variable expenditure
Worth knowing before you read your own dashboard, because it will look strange otherwise. Your target
is fixed at 2,350 while your expenditure swings with training:

```
rest day        TDEE ~2,400   →  balance  ~−50 kcal    (basically maintenance)
push/pull day   TDEE ~2,750   →  balance  ~−400 kcal
10 km run day   TDEE ~3,100   →  balance  ~−750 kcal
```

Same food, wildly different daily deficits. That's not a flaw — it's what the energy balance screen
exists to reveal. But it means **the weekly average is the number that matters**, and a single day's
balance is close to noise. So the Energy screen leads with the 7-day rolling average balance and shows
the daily figure beneath it, not the other way round.

---

## 8. Explainability as a product feature

Every interesting number is explainable, and the explanation is in the UI — not just in the LLM's
mouth. Tapping the ⓘ on a derived status shows the inputs that produced it:

```
RECOVERY: BELOW NORMAL

Why?

  Sleep         6h 24m    vs 7h 12m baseline    −11%
  HRV             47 ms   vs 53 ms baseline     −11%
  Resting HR      57 bpm  vs 53 bpm baseline    +4 bpm
  Body Battery    58      vs 71 baseline        −18%

Baselines: 30-day rolling, computed 2026-09-02
```

The same structure is what the LLM receives later (ENGINE.md §4). Build it for the UI in Phase 1 and
the AI layer inherits it for free — which is the point of doing it early.

---

## 9. Weight and body composition

**Weight** — manual, one field, three seconds, pre-filled with the last value. Missing a day is fine:
the EMA tolerates gaps and the UI never nags. Stored as history, never as a profile field.

Shown: raw value, 7-day average, weekly change, monthly change, rate of change. **Trend over
individual readings, always** — a single weigh-in is mostly water.

**DEXA** — no scan yet, and the model supports it now anyway. Empty state:
```
BODY COMPOSITION
Weight  78.6 kg      7-day  78.9 kg
DEXA    No scan recorded      [ Add DEXA Scan ]
```
After one: body fat %, fat mass, lean mass, scan date. After two or more: a comparison, which is where
it gets genuinely valuable —
```
DEXA #1  18.8% BF      DEXA #2  15.9% BF
Change   −3.4 kg fat   +0.2 kg lean
```

**Why this matters more than weight:** you do resistance training, so weight loss does not equal fat
loss. Down 3 kg could be 3 kg of fat or 2 kg of fat and 1 kg of lean mass — a good cut and a bad one,
identical on the scale. DEXA is the only input here that can tell them apart.

Between scans, composition is **estimated and labelled as an estimate** — never displayed as if
measured (ENGINE.md §6). With no scan at all, the Body screen shows weight and trend only, and says
so.

---

## 10. Demo mode

`fitness.<domain>/?demo=1` serves the full dashboard on **synthetic data** — every screen, charts, AI
insights, no real health information. Swaps the data adapter for a fixture; no auth path, no access to
real records.

Worth building because most portfolio projects are a dead GitHub link, and this one is a health app
whose real data must stay private. The synthetic generator also makes the test suite much stronger
(ENGINE.md §8).

---

## 11. Postponed

Not in scope, listed so they stop taking up room:

**Explicitly excluded by the vision:** workout-plan generation, cutting/bulking programs, prescriptive
training advice, social features, friends, competitions, leaderboards, multiple users, many wearable
providers, meal planning, recipe generation, medical diagnosis, gamification, AI doing arithmetic.

**Cut from the previous plan** (see PLAN.md §15 for why): the food-combination optimizer that told you
what to eat, carb periodization, recovery-modulated automatic targets, friend-sharing data models, and
Athena/Glue analytics.

**Deferred, not cancelled:** natural-language food logging (Phase 7), correlations (Phase 5),
projections (Phase 5), training load metrics (optional, Phase 5), second provider (only if a real need
appears).

---

## 12. Where the LLM shows up, and when

Phase 7, after everything above works. It receives finished numbers and reason traces, and it
produces language. Three features, in order of value:

1. **Daily observation** — a short paragraph on the Today screen explaining what the numbers say.
2. **Weekly review** — the more valuable one; a week of computed report data turned into prose.
3. **Ask My Health Data** — conversational questions answered through safe query tools that compute the answer deterministically and hand it back for phrasing.

Then, optionally, **natural-language food logging** — which maps text onto your existing library and
proposes entries for your confirmation; application code retrieves the actual macros. The LLM never
touches a nutritional value.

Full architecture, tooling, caching, budget and safety rules in ENGINE.md §7.

---

## 13. Profile — locked

Nothing in the personal profile is open any more. Design can proceed end to end.

```
Sex               male
Birth date        2003-05-01
Height            180 cm
Weight            ~80 kg  (stored as history, never a fixed field)
Timezone          America/Vancouver
Watch             Garmin Forerunner 165
Goal              cutting
Target            2,350 kcal · 180 P · 260 C · 65 F   (effective 2026-09-03)
Training          3× resistance (push/pull/legs) + 1× lower-body/running prep + 1× ~10 km run
DEXA              none yet; model supports it now
Nutrition         repetitive foods, daily quantities vary
```

**Two things are collected during implementation rather than decided now**, and neither blocks
anything:

1. **Exact food nutrition** — from your actual product labels, into [`seed/food-library.template.yaml`](seed/food-library.template.yaml). Needed before Phase 2 produces real numbers; the schema and workflow don't depend on the values.
2. **Exact FR165 field availability** — discovered experimentally in Phase 0 (PLAN.md §13). The Recovery screen is designed to degrade gracefully either way (§6).

**Training program is out of scope.** The app never models sets, reps or volume, and never prescribes a
session. Training data serves activity totals, expenditure, recovery context, frequency trends, and
body-composition interpretation — nothing more.
