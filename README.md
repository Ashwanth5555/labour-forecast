# Sodexo Healthcare — Labor Forecasting & Workforce Intelligence

A working proof of concept that ingests enterprise workforce data, forecasts how much
labor each site needs, and turns that into decisions a manager can act on.

Everything on screen is computed from the database at request time. There are no
hardcoded numbers, no mocked chart data, and no invented AI answers anywhere in the
application.

---

## Contents

1. [How to run it](#1-how-to-run-it)
2. [What the data looks like](#2-what-the-data-looks-like)
3. [Page by page](#3-page-by-page)
4. [How the forecasting works](#4-how-the-forecasting-works)
5. [What this build does *not* do](#5-what-this-build-does-not-do)
6. [Actual output, page by page](#6-actual-output-page-by-page)

---

## 1. How to run it

Three processes. Start them in this order.

**Mock enterprise API** (stands in for UKG / Workday / POS / Payroll / ERP):

```bash
cd "D:/demo/Labour_AI forecast/mock_api_sodexo" && "../.venv/Scripts/python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8200
```

**Backend** (ingestion, forecasting engine, analytics, AI services):

```bash
cd "D:/demo/Labour_AI forecast/backend_sodexo" && "../.venv/Scripts/python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8300 --reload
```

**Frontend**:

```bash
cd "D:/demo/Labour_AI forecast/frontend_sodexo" && npm run dev -- --port 5183 --host 127.0.0.1
```

Then open `http://127.0.0.1:5183`.

### Signing in

The application requires a login. Three accounts are seeded automatically on backend
startup — no setup step:

| Username | Password | Role |
|---|---|---|
| `admin` | `Admin@2026` | Administrator |
| `manager` | `Manager@2026` | Location Manager |
| `analyst` | `Analyst@2026` | Data Analyst |

All three see the same pages; the role is recorded and shown in the header, but nothing is
restricted by it yet. **Sign out** is at the top right of every page.

The session is held in `sessionStorage`, so closing the tab signs you out and reopening the
app asks again. Tokens otherwise expire after 8 hours (`JWT_EXPIRE_MINUTES`).

To change a password:

```bash
cd "D:/demo/Labour_AI forecast" ; ./.venv/Scripts/python.exe scripts/seed_users.py --username admin --password "NewPassw0rd!"
```

Three things to know before this goes anywhere but a local machine:

- **These are demo credentials in a public README.** Rotate them with the command above.
- **`JWT_SECRET` has a known default** (`app/core/config.py`). Anything beyond a local run
  must set it in `.env.sodexo` — with the default in place, a token signed by any other copy
  of this project is accepted. Changing it also invalidates every issued token, which is how
  you force everyone to sign in again.
- **CORS is still `allow_origins=["*"]`** from the POC setup, and tokens are held in browser
  storage rather than an httpOnly cookie. Both are fine for localhost and neither is
  appropriate for a deployment.

Passwords are stored as bcrypt hashes; the plaintext is never written to the database, the
logs, or any API response.

### First run, in order

1. **Overview → Sync Data from API.** Nothing works before this; it pulls all 16 source
   endpoints into the canonical database.
2. **Labor Forecasting → Model Training → Train All Models.** Expect roughly 6–10 minutes
   at the 180-day default. Until this finishes, every forecasting page will say there is
   no trained model yet.
3. Everything else is then live.

Restart the backend after any Python change — it does not always hot-reload cleanly, and a
stale process serving old code has been the cause of most "why hasn't this updated"
moments.

---

## 2. What the data looks like

**Four forecast series** — two locations × two departments:

| Series | Demand signal |
|---|---|
| Community Hospital / Food & Nutrition | `occupied_beds` |
| Regional Medical Center / Food & Nutrition | `occupied_beds` |
| Community Hospital / Retail & Café | `transaction_count` |
| Regional Medical Center / Retail & Café | `transaction_count` |

**What is being predicted:** `required_manpower` — staff-hours needed.

**Grain matters, and it differs by page.** This is the single most important thing to
understand about the app:

| Source table | Native grain | What that allows |
|---|---|---|
| `fact_census`, `fact_cafe_sales` | hourly | hour-of-day analysis, forecasting |
| `fact_punch` | timestamped | hour-of-day punch analysis |
| `fact_timecard`, `fact_attendance` | **daily** | no hourly cost or attendance is possible |

So Labor Analytics offers Day / Week / Month but **not hourly** — labor cost simply does
not exist at hourly resolution in the source. Time Punch Analytics *does* offer hourly,
because punches carry timestamps. The app states this on-screen rather than quietly
inventing precision.

---

## 3. Page by page

### Overview

One action: **Sync Data from API**. It reports how many sources loaded and how many
records, and remembers the last sync across page navigations (it reads real ingestion
state from the database rather than component state).

---

### Data Quality

Per-source health for all 16 endpoints: records received, loaded, rejected, and freshness.

**What to look for:** any non-zero *rejected* count. A healthy sync shows zero rejects
across every source.

---

### Labor Analytics

Laid out as a **Power BI–style report page**: a filter bar, a row of KPI tiles with
sparklines and period-over-period deltas, then a dense grid of small visuals. Every
visual is clickable and filters the rest of the page.

#### Filter bar

| Control | Options |
|---|---|
| **Period** | Last 30 / 60 / 90 days, or All data |
| **Location** | All, or one site |
| **Department** | All, or one department |
| **View by** | Day / Week / Month — re-buckets every time series |

The period is anchored to the **newest timecard date in the data**, not to today. The
dataset ends 2026-07-31, so "Last 30 days" means 2026-07-02 → 2026-07-31. The bar shows
the resolved window and the comparison window next to it.

Active filters appear as **removable chips** — click the ✕ to clear one, which matters
because most filters get set by clicking a chart rather than by using a dropdown.

#### KPI tiles

Four tiles: **Total Labor Cost** (accent tile), **Overtime Cost**, **Attendance Rate**,
**Labor Utilization**. Each shows a label, the number for the window, and a **sparkline** of
that metric's own trend. Nothing else — no delta badge, no secondary figure.

That is deliberate. The tiles previously also carried a period-over-period arrow and a
sub-line (`-24.8% vs budget`, `544 OT hours`, `4.2% absent · 9.5% late`, `22.4Kh of 22.8Kh`),
which made the strip the busiest thing on a page whose job is the charts below it. Every one
of those figures is still on the page — absence and lateness in **Attendance Mix**, hours in
**Scheduled vs Actual**, overtime in **Overtime Trend** — just in the visual built for it.

The one figure with no other home is **total cost vs budget**; it now appears only as the
per-site *Cost vs budget* measure in the manager scorecard. Say the word if it should come
back as a fifth tile.

**The tile values do not change with the View by selector.** They are window totals;
re-bucketing a trend cannot change a sum. Only the sparklines and the charts re-bucket.

#### What "cost vs budget" actually means

```
labor_cost_vs_budget_pct = (actual labor cost − budgeted labor cost) / budgeted labor cost × 100
```

- **Actual cost** is `SUM(fact_timecard.total_cost)` over every timecard row in the window
  and filters — regular pay plus the overtime premium, per employee per day.
- **Budget** is `SUM(fact_labor_budget.labor_budget)` for every `(location, department,
  year, month)` row whose **month appears anywhere in the window**.
- **Negative means under budget.** −24.8% reads "we spent 24.8% less than budgeted".

Worked from the current data, whole range:

```
actual  $711,238.93
budget  $960,697.00
        (711,238.93 − 960,697.00) / 960,697.00 × 100 = −26.0%
```

The per-site figure on each scorecard card is the same formula narrowed to that
location/department pair.

**One caveat worth knowing before you quote the number.** The budget is monthly, but the
window is a range of days, and the code takes the *whole* month's budget for any month the
window touches. So "Last 30 days" (2 Jul → 31 Jul) compares **30 days of cost against 31
days of July budget**, and the 60-day window compares 60 days of cost against June + July
(61 days). That inflates the budget side by roughly 2–3% and makes the underspend look
slightly larger than it is: the real figure for Last 30 days is nearer −22% than −24.8%.

The −26% itself is genuine — the budgets in this dataset are simply generous — but the
comparison is not day-for-day. Pro-rating the monthly budget by the number of days the
window actually covers is a small change; say the word and I will make it.

#### Period-over-period deltas

`kpi_deltas` and `kpi_delta_units` are still computed and returned by
`/api/analytics/summary`, so restoring the arrows on the tiles is a one-line change. How they
are worked out:

`_previous_window()` takes the selected window, measures its length, and returns the
equal-length span ending the day *before* it starts. Both windows are then pushed through
the same `_headline_totals()` query with the same location/department filters, so nothing
but the dates differs.

For **money and hours** the delta is a percent change:

```
Total Labor Cost, Last 30 days
  current   2026-07-02 .. 2026-07-31   $359,881.64
  previous  2026-06-02 .. 2026-07-01   $351,357.29
  delta     (359,881.64 - 351,357.29) / 351,357.29 x 100 = +2.4%

Overtime Cost
  current   $12,980.14
  previous  $12,887.29
  delta     (12,980.14 - 12,887.29) / 12,887.29 x 100 = +0.7%
```

For metrics that are **already a percentage** the delta is in percentage **points**, and the
tile prints `pt`:

```
Attendance Rate
  current   86.3%
  previous  86.7%
  delta     86.3 - 86.7 = -0.4 pt
```

Dividing here would have shown `-0.5%`, which reads as half a percent of absence when the
real movement is four tenths of a point — a different claim. Any metric whose name ends in
`_pct` is compared in points; everything else is compared proportionally. The unit travels
with the number as `kpi_delta_units` so the tile never has to guess.

#### The visual grid

| Visual | Type | Click behaviour |
|---|---|---|
| **Cost by Location** | donut with the window total in the centre | slice or legend entry filters to that site |
| **Cost by Department** | vertical columns, value labels, cost centre printed under each column | column filters to that department |
| **Overtime Hours by Department** | vertical columns, value labels | column filters to that department |
| **Cost by Site × Department** | stacked vertical columns — one column per site, split by department | segment or legend entry filters to that department |
| **Labor Cost Trend** | gradient area | — |
| **Scheduled vs Actual Hours** | two lines (grey dashed = scheduled, solid = actual) | — |
| **Overtime Trend** | gradient area | — |
| **Efficiency** | utilization % and OT share %, with a 100% reference line | — |
| **Attendance Mix** | present / absent / late % | — |
| **Cost by Location over Time** | one line per site | legend entry filters to that site |
| **Hours by Department** | grouped vertical columns — grey = rostered, solid = actually worked | — |
| **Cost per Hour Worked** | line with a dashed window-average reference | — |
| **Productivity** and **Shift Utilization** | compact tables | — |

Horizontal bars were the first attempt here and were wrong for this data: with only two
departments they rendered as two enormous half-empty stripes. Vertical columns with value
labels read correctly at that cardinality. A separate "Cost by Site & Department" ranked
list was also dropped — with two departments and two cost centres its numbers were literally
the same two figures as **Cost by Department**, printed a third time. **Cost by Site ×
Department** replaces it with a genuine cross-tab, and the cost centre now appears as a
sub-label on the department columns instead of as its own panel.

Each panel title carries a small colour spine matching its chart, and the KPI tiles are
tinted per metric family (blue for cost, orange for overtime, green for attendance, teal for
utilization) so the eye can find a metric without reading every label.

Cross-filtering behaves the way it does in Power BI: clicking the already-selected slice
**clears** the selection, and non-selected slices **dim** rather than disappearing, so you
can always see what else you could click.

Where a visual is filtered, the panel header shows its own clear chip.

#### Manager scorecard

One score out of 100 per location/department, sites **ranked**, with each site's focus
measure called out.

**How the score is worked out** — stated on the page, not hidden:

| Measure | Scores 100 at | Scores 0 at | Target |
|---|---|---|---|
| Overtime | 0% | 15% | ≤ 5% |
| Punch accuracy | 0% | 10% | ≤ 2% |
| Cost vs budget | −5% | 20% | ≤ 0% |

Each measure is scored by where it falls between its best and worst case; the site score
is the average of the three. Each bar shows its own `83/100` alongside the raw percentage,
so the total is traceable, and the dashed mark on each bar is the target.

**Schedule adherence is deliberately not scored.** All four sites sit at 84.7–87.6%, so
against any sensible target it marked every site "off target" every time and separated
nobody — it cost a quarter of the score while carrying no information. It is still
computed and returned as `schedule_adherence_pct` for anyone who wants it; it simply does
not feed the score any more.

Scoring across a range rather than pass/fail against one target is also deliberate: with a
single hard target, overtime and budget both pin at 100, squashing every total into a
meaningless band. Range scoring spreads real differences out.

The bars are monochrome on purpose. Sixteen coloured bars competed with the charts and
told you nothing the bar length didn't. Colour is reserved for **off target**.

The scorecard shows the scale table and the four site cards, and nothing else. Two banner
rows used to sit under the table — one per measure that *every* site missed, plus one for
sites more than 15% under budget — and in this dataset all three fired at once, so the panel
opened with three grey advisory rows before any actual score. The same facts are still
readable from the cards: a measure every site misses shows as *off target* on all four, and
the budget figure is on each card.

`underspend_review` and `underspend_review_pct` are still returned by
`/api/analytics/summary` if that flag is ever wanted on screen again.

The scale table is headed **Scores 100 / Scores 0 / Target** rather than the raw anchor
values, and the panel note no longer spells out "plain average, unweighted" — the per-bar
`83/100` readouts already make the arithmetic followable without the statistics vocabulary.

The scorecard is **operational only** — it rates how a site is running, never an
individual person.

---

### Time Punch Analytics

The same Power BI–style treatment: filter bar, KPI tiles with sparklines, then a grid of
clickable visuals feeding a detail table.

#### Filter bar

Location, Department, **View by** (Hour of day / Day / Month), and an employee search box.
Selections made by clicking a chart appear as removable chips alongside, with a
**clear all** link.

#### KPI tiles

**Total Punches** (accent tile, sparkline of punch volume), **Exception Rate** (sparkline of
the issue rate), **Missed Punches**, **Manual Edits**, and **In Selection** — a live count of
how many flagged issues your current clicks have narrowed the page down to. Label and number
only, same as the other dashboards.

The combined *Missed / Duplicate* tile was split in two: one tile reading `267 / 50` needed a
sub-line to say which number was which, and the sub-lines are gone. Duplicate-punch counts
are in **By Issue Type**.

#### The visual grid

| Visual | Type | Click behaviour |
|---|---|---|
| **By Severity** | donut with the flagged total in the centre | segment or legend entry keeps only that severity |
| **By Issue Type** | vertical columns with value labels and angled short names | column drills the table into that issue type |
| **Top Employees** | ranked bars, current selection only | — |
| **Issues by Hour / Day / Month** | line; the hourly view adds issue **rate** as a dashed line | — |
| **By Location** | vertical columns with value labels | column filters the page to that site |
| **By Department** | vertical columns with value labels | column filters the page to that department |

Axis ticks use shortened rule names (*Payroll Exception*, *Suspicious Pattern*, *Manual
Edits*) because the full names are too long to sit under a column; the tooltip always shows
the full name.

Cross-filtering follows the Power BI convention that **a visual never filters itself**:
the type chart honours the severity and search selection, the severity donut honours the
type and search selection, and the table honours everything. That way you can click
straight from one type to another without clearing first.

On the hourly view, a spike at shift-change usually means a **device or process** problem,
not individuals — the panel says so.

#### Alerts

Surfaced without you having to go looking: high-severity volume, any single issue type
exceeding 30% of all flags, and employees with repeat flags.

#### Watchlist — removed from the page

There was a panel listing employees whose flag *rate* was rising in the recent third of the
window. It is gone from the UI. Two reasons: it named individual employees on a dashboard
anyone can open, which is a governance problem rather than a design one; and its own layout
was broken — the Recent, Earlier and Why columns collided, rendering "7" and "12" as "712".

The rule is still in the backend and `/api/punch-analytics/anomalies` still returns
`watchlist`, so it can be brought back if it is ever wanted, ideally behind a manager-only
view. **Top Employees** on the same page covers the same ground for the current selection
without the trend claim.

#### Detail drawer

Click any table row for Problem / Expected / Actual / Variance / Rule Triggered / Root
Cause / Potential Impact / Recommended Action.

Buddy-punch patterns are labelled **"Suspicious Punch Pattern — Review Required"** and
never as an accusation.

---

### Labor Forecasting

Eight sub-pages in the sidebar, in workflow order.

#### Demand Drivers & Feature Mapping

The target column and every input column, per series. **Input columns are clickable** —
turning one off persists to the database and changes what the next training run uses. The
badge shows "10 of 11 inputs selected".

#### Data Analysis

| Chart | What it shows |
|---|---|
| **Historical demand trend** | daily average with a 7-day smoothed line over it |
| **Demand curve by hour of day** | the meal-service shape — peaks at 07:00, 12:00, 17:00 |
| **Demand by day of week** | weekday vs weekend |
| **Seasonal demand** | by season |
| **Demand drivers at a glance** | holiday / promotion / event lift as plain percentages |

Every chart carries a one-line finding computed from the same data, e.g. *"Busiest at 7:00
(6.86) · quietest at 1:00 (2)."*

#### Data Pre-processing

What happens between raw data and training: total history, training window, resolved
seasonality, forecast horizon, input matrix shape, the validation plan, and **a preview of
the first 10 rows actually fed to the models** — with `required_manpower` last, as the
target column.

#### Model Training

Pick a **training window** (120 / 180 / 365 / 730 days, default 180) and hit **Train All
Models**. While it runs:

- a pulsing **LIVE** badge and a progress bar (`n / 52 model runs`)
- a **live activity feed** of models as they complete, newest first
- the just-finished row glows briefly in the comparison table
- **champion cards** per series once selection completes

The leaderboard shows all 13 models per series with status, runtime, train/test rows, and
every metric. Models that cannot run are marked `not_applicable` **with a reason** rather
than silently dropped.

If you navigate to this page mid-run, it detects the running job and resumes live polling.

#### Forecast Explorer

**The main chart — this is what the lines mean:**

| Line | Meaning |
|---|---|
| **Grey, solid — "Actual"** | what actually happened, across the full history |
| **Orange, solid — "Backtest prediction"** | what the model predicted for periods where the answer was already known. Drawn only over the most recent third, so it reads as "here is the window we validated against" rather than two lines fighting end to end |
| **Green, dashed — "Future forecast"** | the 7 days beyond the last actual. Dashed because nothing here is verified yet |
| **Vertical dashed line — "Forecast begins"** | the boundary between known and predicted |

Controls: **Model** (defaults to the current champion, named explicitly, with every other
model selectable), **View** (Full timeline / Backtest focus / Forecast focus), and
**Granularity** (Half-day / Daily total / Weekly average).

**How to read it honestly:** compare orange against grey in the overlap. If the orange line
is flatter than the grey — hugging the middle while grey swings above and below — the model
is predicting near the average rather than tracking the pattern, and a high accuracy number
is coming from a stable series rather than a skilful model. This is measurably the case for
the Food & Nutrition series; see [section 5](#5-what-this-build-does-not-do).

#### Drift Monitoring

Answers "can I still trust this model?"

**Demand signal chart** — the real-world driver, day by day. Its key:

| Element | Meaning |
|---|---|
| Solid black line | the signal each day (e.g. occupied beds) |
| Grey dashed | previous 30-day average |
| Orange dashed | last 7-day average |
| Shaded band, right | the last 7 days |

When the two dashed averages sit on top of each other, demand has not moved and the models
are still trained on the right pattern. **Regular dips are weekends** — verified: every dip
in the sample window falls on a Saturday or Sunday, dropping from 86–87 beds midweek to
80–82 at weekends.

The card header states how strongly the signal actually tracks staffing, measured at the
model's own grain — and warns you when it is weak rather than asserting it is *the* driver.

**"Has the shape of the day changed?"** — staff needed per hour, last 7 days vs previous 30.
Lines on top of each other means the daily rhythm is unchanged. Peaks moving or changing
height means busy periods are shifting and the roster *shape* needs revisiting, not just
headcount.

Status thresholds are stated plainly: within 15% = **Stable**, 15–30% = **Watch**, beyond
30% = **Drift Detected** (retrain).

#### Staffing Impact

**Required vs scheduled headcount** — lines for the two curves, plus colour-coded bars for
the gap itself (red = understaffed, gold = overstaffed, green = balanced).

**Click any point to drill down.** The panel shows Required / Scheduled / Gap / Status for
that hour, the typical value for that hour across the window, and a plain reading —
*"Short 3 staff this hour. Across the window this hour ran short 9 times out of 14 — a
recurring gap worth fixing in the roster template."* That distinction between a one-off and
a pattern is what changes the decision.

**Seasonality signal** — average required headcount by hour of day, the recurring shape
behind the gap.

Note the window: it uses the most recent period where **both** real demand and real schedule
data exist. Future schedules do not exist yet, which is precisely the gap forecasting fills.

#### Model Performance

**MAPE by model**, as vertical columns, champion in green, on a 0-based auto-scaled axis.

Why MAPE and not accuracy: accuracy values (91.8–94.3%) plotted on a fixed 0–100 axis made
every bar look identical. MAPE sits near zero, so the same differences render as genuinely
different bar heights — the champion is visibly the *shortest* bar.

The table below shows Accuracy, MAPE, MAE, RMSE and Bias per model.

---

### AI Recommendations

Same dashboard treatment as the two analytics pages: filter bar, KPI tiles, a row of
clickable visuals, then the recommendation cards.

#### KPI tiles

**Actions To Take** (accent tile — how many actions the current selection holds), **Do These
First** (the High-priority count), **Sites Affected**, and **Biggest Theme** (the category
generating the most actions). Label and number only, no sparklines: a recommendation set is a
snapshot of the present, not a series over time.

#### The visual grid

| Visual | Type | Click behaviour |
|---|---|---|
| **By Priority** | donut with the action count in the centre | keeps only that priority |
| **By Category** | vertical columns with value labels | keeps only that category |
| **Actions by Site** | vertical columns, busiest highlighted | filters to that site and department |

Cross-filtering follows the same convention as the other pages — a visual never filters
itself, clicking the selected item clears it, non-selected columns dim to 28%.

#### The cards

Sorted **High → Low priority**, each with a left spine coloured by priority. Every card
answers four questions in plain language, then shows its working:

> **Short of staff on Friday 24 Jul morning** — Regional Medical Center / Retail & Cafe
> **What's happening** — About 19 people are needed on shift that morning, but only 11 are rostered — short by 8 people.
> **What to do** — Move 4 people across from Community Hospital / Retail & Cafe Services, then find cover for 4 people.
> **Why it matters** — The shift is fully covered instead of running short by 8 people.
>
> **Why this is flagged**
> - Forecast says 19 people needed on shift.
> - Roster currently has 11 people on.
> - Community Hospital / Retail & Cafe Services has 4 people spare at the same time.
> - Compared over the last 14 days of forecast demand against the published roster.

#### What was removed from the card, and why

**The savings figure (`~$242`) is gone.** For a staffing gap it was
`shortfall × avg_hourly_rate × 1.5`, presented as *"saved"*. That is not a saving — it is a
rough guess at what covering the gap would **cost**, and rostering the missing people spends
that money rather than saving it. A number that confidently wrong is worse than no number.

**The confidence bar is gone, and it was broken.** The API returns `confidence` as an integer
percent (`70`), but the card computed `Math.round(rec.confidence * 100)` — so every card read
**7000%**. Beyond the bug, the values were mostly fixed constants (`70` for staffing, `60`
for cost) rather than a measured quantity, so the bar implied a rigour that was not there.

Both fields are still in the API response, so either can come back — the savings figure would
need relabelling as a cost first.

**Evidence was always empty.** An earlier note in this file claimed the evidence list "was in
the API response all along and was never rendered". That was wrong: the engine set
`"evidence": []` on every rule, so the block never appeared. Each rule now populates it with
the actual figures it fired on, phrased for a manager rather than named after a database
field.

**Overtime actions are capped at the top 3.** Every High-risk employee produced a near
identical card; five in a row pushed the staffing, cost and attendance actions off the page.
The mix is now 4 staffing / 3 overtime / 2 adherence rather than 5 near-duplicates first.

---

### AI Assistant

Chat over the application's own data. Uses OpenAI when `OPENAI_API_KEY` is set in
`.env.sodexo`, and falls back to a template summariser over the same retrieved facts when it
is not — the answers stay grounded either way.

Six deliberate behaviours:

- **On-topic only.** Off-topic questions are declined and redirected *before* any retrieval,
  so out-of-scope questions cost almost nothing.
- **Routed by meaning, with a keyword safety net.** A cheap model call picks which services
  to query, so *"who might quit?"* reaches the risk models even though it contains none of
  their keywords. If that call returns nothing — out of scope, or a transient failure — the
  deterministic keyword router still answers, so a routing hiccup degrades the answer instead
  of breaking it. The response reports which path ran, in `routed_by`.
- **Scoped to what you asked about.** "the cafe" returns the two café series, not all four;
  *"the cafe at Regional Medical"* narrows to exactly one. Employee-level questions scope the
  same way, so *"who is highest risk at the cafe?"* ranks café staff rather than filtering the
  global top five and hoping a café employee is in it.
- **Follow-ups keep their context.** *"why?"*, *"is it over budget?"*, *"who is highest risk
  there?"* inherit the site and subject from the previous turns. A self-contained question
  such as *"which department is over budget?"* deliberately does **not** inherit scope — it is
  asking about all of them.
- **Structured output.** One direct opening sentence carrying the deciding number, then up to
  4 bullets that each carry a real figure with its unit, then a `**Next step:**` line only
  where the facts support a specific action. Under 140 words. The page renders the bold and
  bullets rather than showing one wall of text, and lists the services each answer was built
  from underneath it.
- **Grounded, and checked in code where the prompt is not enough.** Facts go to the model as
  real JSON at `temperature=0`. A "next step" that only says *monitor / continue / maintain*
  is stripped after generation rather than trusted to the instruction, because a closing line
  that recommends nothing is worse than no closing line.

It answers from structured facts pulled from the same services the pages use — never raw
database access, and never numbers it made up.

#### Three routing bugs that were fixed

1. **`is_greeting` used `startswith`.** So "**hi**ghest cost department" was answered with
   the greeting, and anything opening with "help" was too. Greeting detection now requires
   the *whole* message to be pleasantries (or a genuine "what can you do").
2. **Topic keywords were substring matches with no ranking.** Every topic whose keyword
   appeared anywhere was retrieved, so "overtime" alone pulled in both cost and risk. Terms
   are now matched as whole words against a tokenised question, each topic is scored by how
   many terms it hits (a multi-word phrase counting double, since "over budget" is stronger
   evidence than a bare "budget"), and only the topics genuinely competitive with the best
   match run — at most three.
3. **A bare date word routed off-topic questions in.** "tomorrow" was a forecast keyword, so
   *"what's the weather tomorrow?"* retrieved forecast facts. Date words on their own no
   longer trigger a topic.

#### The staffing-gap answer said "staff-hours" when it meant people

`required_headcount` and `scheduled_headcount` are **people on shift**. The recommendation
copy described them as "staff-hours", so a perfectly ordinary 10-vs-20 headcount gap read
as nonsense — *"you need about 20 staff-hours but only 10 are rostered"*. The wording is now
*"Forecast demand for that morning is 20 people on shift against 10 rostered — a shortfall of
10 people"*, and the LLM system prompt carries an explicit rule never to call those fields
hours, alongside one forbidding it from restating any of the three figures as another.

---

## 4. How the forecasting works

### Grain: half-day blocks

Models forecast per **12-hour block** (AM 00:00–11:59, PM 12:00–23:59), not per hour. This
was measured, not assumed:

| Grain | Champions | Weakest model | Spread |
|---|---|---|---|
| Daily (24h) | 92.1–97.7% | 89.0% | 1.6–3.3pt |
| **Half-day (12h)** | **90.5–97.5%** | **85.2%** | **1.4–5.6pt** |
| Shift (8h) | 86.4–95.0% | 77.9% | up to 8.5pt |
| Hourly (1h) | 50.6–82.9% | — | — |

Hour-to-hour variation is dominated by irreducible noise on tiny integer targets — a quarter
of Community Hospital's hours sit at exactly 1 required staff, where being off by one is a
100% error. Half-day is the finest grain at which every series' champion still clears 90%.

Hour-of-day detail is still available throughout Data Analysis, Drift Monitoring and
Staffing Impact, which read the raw hourly facts directly.

### Leak-free exogenous inputs

Census and sales columns are strong demand signals, but the **same-period** value is
contemporaneous with the target — using it would leak the answer. Every such column is used
**lagged by exactly one week**, which equals the forecast horizon, so the lag always resolves
to an already-observed actual for every step of the horizon.

### Validation

3-fold rolling-origin cross-validation with expanding windows and 28-day validation folds.
Auto ARIMA and LSTM use a single chronological holdout instead — and because the holdout is
sized to 3× one fold, they are scored on exactly the same 84 test rows, so the leaderboard
stays comparable.

Champion = lowest MAPE among models that completed with valid metrics.

### The 13 models

SARIMAX · SARIMAX+exog · Auto ARIMA · Auto ARIMA+exog · XGBoost · XGBoost+exog ·
Exponential Smoothing (additive, additive-damped, multiplicative, multiplicative-damped) ·
VAR · VAR+exog · LSTM

---

## 5. What this build does *not* do

Read this section before presenting the numbers.

### The models barely beat a flat average on two of four series

Champion accuracy against simply predicting the training average:

| Series | Champion | Flat average | Real gain |
|---|---|---|---|
| Community Hospital / Food & Nutrition | 94.25% | 93.87% | **+0.38pt** |
| Regional Medical Center / Food & Nutrition | 97.67% | 97.30% | **+0.37pt** |
| Community Hospital / Café | 92.11% | 87.54% | **+4.57pt** |
| Regional Medical Center / Café | 96.63% | 88.21% | **+8.42pt** |

The **café** models earn their keep. The **Food & Nutrition** models add almost nothing — their
94–98% accuracy comes from the series being stable, not from the model being skilful. For
Community Hospital / Food & Nutrition the champion captures only 43% of the actual variation
(predicted std 2.02 vs actual 4.68) and correlates 0.387 with the actuals. That is the flat
orange line visible in the Forecast Explorer.

A high accuracy percentage on a stable series is not evidence of a good model. Quote these
numbers with that context.

### The demand signal is weak for Food & Nutrition

Correlation between the demand signal and required staffing, at the model's grain:

| Series | Signal | Correlation |
|---|---|---|
| Community Hospital / Food & Nutrition | occupied_beds | **0.34** (weak) |
| Regional Medical Center / Food & Nutrition | occupied_beds | 0.61 (moderate) |
| Community Hospital / Café | transaction_count | 0.95 (strong) |
| Regional Medical Center / Café | transaction_count | 0.99 (strong) |

Kitchen staffing is set by fixed meal-service windows, not by how full the wards are in a
given block. Bed count drives the day's meal *volume*; it does not drive staff *timing*.

### Not available in this dataset

- **No region dimension** — cost groups by location, department and cost centre only.
- **No hourly labor cost / attendance** — those come from daily timecards.
- **No weather data** anywhere in the source.
- **Promotion and event exist only as booleans** — no campaign name, spend or channel.
- **Employee availability** is an explicit "not available" stub in the mock API.
- **Turnover risk is not modelled** — there is no termination or tenure-end data, so it is
  reported as unsupported rather than faked.

### Deliberately simple, and disclosed as such

- **Drift detection** is a percentage-change threshold, not a statistical test.
- **The punch watchlist** is a trend rule, not a trained classifier.
- **Recommendations** are rule-based. No optimiser.
- **Scorecard anchors and targets** are POC defaults set in this app, not Sodexo policy.

### Synthetic data

All data is generated by the mock API. Patterns are realistic in shape — weekly cycles,
meal-time peaks, weekend dips — but this is not real Sodexo operational data, and accuracy
figures on real data would differ.

---

## 6. Actual output, page by page

Every block below is **real output captured from this application** against the ingested
database, followed by an explanation of what it means. Nothing here is illustrative.

> **One caveat on the forecasting figures.** The stored leaderboard comes from training job
> `JOB-4ea5d6d60b06`, which ran **before** the switch to half-day grain — it has 365 training
> rows (daily), whereas the engine is now configured for 364 half-day rows. Those accuracy
> numbers are therefore *daily-grain* results. Re-run **Train All Models** to refresh them.
> Separately measured half-day results are in [section 4](#4-how-the-forecasting-works).

---

### 6.1 Overview / Data Quality — ingestion

```
sources=160  loaded=839,890  rejected=0

ERP        /mock/erp/locations            COMPLETED  recv=2    loaded=2    rej=0
ERP        /mock/erp/departments          COMPLETED  recv=2    loaded=2    rej=0
Workday    /mock/workday/jobs             COMPLETED  recv=4    loaded=4    rej=0
Workday    /mock/workday/job-skills       COMPLETED  recv=12   loaded=12   rej=0
ERP        /mock/erp/staffing-standards   COMPLETED  recv=2    loaded=2    rej=0
Workday    /mock/workday/workers          COMPLETED  recv=150  loaded=150  rej=0
```

**Reading it:** 839,890 records loaded with **zero rejects** — every row the source offered
was accepted, so nothing silently fell out of the pipeline. `recv` equalling `loaded` on
every line is the check that matters. 160 batch rows means ingestion has been run ten times
over 16 endpoints; the pipeline is idempotent, so repeat syncs do not duplicate facts.

---

### 6.2 Labor Analytics — window totals

```
window: 2026-06-02 to 2026-07-31   (60 days)

total_labor_cost        711,238.93
total_budget            960,697.00
labor_cost_vs_budget    -26.0%
scheduled_hours          45,448.0
actual_hours             44,312.4
variance_hours           -1,135.6
overtime_hours            1,085.0
overtime_cost            25,867.43
overtime_budget          76,856.00
attendance_rate_pct           86.5
labor_utilization_pct         97.5
```

**Reading it:** the operation ran **26% under budget** — flagged rather than praised, because
that scale of underspend usually means a stale budget or uncovered shifts, not brilliant cost
control. Utilization of **97.5%** says staff worked slightly *fewer* hours than rostered
(44,312 actual vs 45,448 scheduled, a 1,136-hour shortfall). Overtime is well contained:
1,085 hours costing $25,867 against a $76,856 overtime budget. **Attendance at 86.5% is the
weak spot** — roughly one shift in seven is absent or late.

#### Period selector and deltas — measured

```
last_days=30    window 2026-07-02..2026-07-31   cost $359,882
                vs prior 30 days 2026-06-02..2026-07-01  (cost was $351,357)

                cost         +2.4%      actual hours  +1.9%
                OT hours     +0.5%      attendance    -0.4 pt
                OT cost      +0.7%      utilization   +1.0 pt
                cost/hour    +0.5%

last_days=60    window 2026-06-02..2026-07-31   cost $711,239   deltas: none
last_days=None  window 2026-06-02..2026-07-31   cost $711,239   deltas: none
```

**Reading it:** at 30 days the API returns real period-over-period movement — July cost
ran 2.4% above June, driven mostly by 1.9% more hours worked rather than by overtime
(+0.5%). Attendance slipped 0.4 of a point. Note the mixed units: cost and hours move in
percent, attendance and utilization in percentage points. These are API values — the tiles
themselves no longer print them.

At 60 days and on "All data" the deltas are `None`, and the tiles show `—`. That is
correct, not a bug: the timecards start on 2026-06-02, so there is no equal-length earlier
window to compare a 60-day period against, and no baseline is fabricated to fill the gap.

#### Grain selector — proof it works

```
daily     cost=60 pts   efficiency=60   attendance=60
weekly    cost= 9 pts   efficiency= 9   attendance= 9
monthly   cost= 2 pts   efficiency= 2   attendance= 2
```

**Reading it:** 60 days re-buckets to 9 weeks and 2 months. The KPI totals above stay
identical across all three — they are sums over the window, and re-bucketing a trend cannot
change a sum.

#### The chart series

```
labor cost         first {2026-06-02, 10,929.35}   last {2026-07-31, 10,481.43}
sched vs actual    {2026-06-02, scheduled 712.0, actual 686.01, variance -25.99}
overtime           {2026-06-02, ot_hours 15.44, ot_cost 367.66}
efficiency         {2026-06-02, utilization 96.3%, ot_share 2.3%, cost_per_hour 15.93}
attendance         {2026-06-02, present 86.5%, absent 5.6%, late 7.9%}
locations          Community Hospital A, Regional Medical Center A
cost centres       CC01, CC02
```

**Reading it:** labor cost is flat across the window (10,929 to 10,481), so the "Labor cost
over time" line should look level with weekly ripples, not trending. Cost per hour worked is
**$15.93**. The by-location and by-cost-centre charts get two lines each.

#### Productivity and shift utilization

```
LOC01/DEP01  meals_served       17,031 over  6,328.0 h  = 2.69 per labor hour
LOC02/DEP01  meals_served       49,598 over 18,192.9 h  = 2.73 per labor hour
LOC01/DEP02  transaction_count  13,019 over  5,233.6 h  = 2.49 per labor hour
LOC02/DEP02  transaction_count  37,651 over 14,557.9 h  = 2.59 per labor hour

shift utilization
LOC01/DEP01 98.0%   LOC01/DEP02 96.1%   LOC02/DEP01 97.1%   LOC02/DEP02 98.2%
```

**Reading it:** productivity is remarkably consistent — 2.49 to 2.73 units per labor hour
across all four, so no site is an outlier on throughput. Shift utilization sits at 96–98% of
the 8-hour rostered shift everywhere, meaning shifts finish slightly early rather than
running over.

#### Manager scorecard

```
scales   overtime 0 to 15 (target <=5)     punch 0 to 10 (target <=2)
         adherence 100 to 75 (target >=90)  budget -5 to 20 (target <=0)

#1 Community Hospital A / Food & Nutrition       score 74.4
   overtime 2.5% (83.3)   punch 3.6% (64.0)   adherence 87.6% (50.4)   budget -21.9% (100)
   21 staff   6,328 h   $105,077        weakest: schedule_adherence

#2 Regional Medical Center A / Retail & Cafe     score 73.4
   overtime 2.5% (83.3)   punch 3.9% (61.0)   adherence 87.3% (49.2)   budget -25.0% (100)
   49 staff   14,558 h   $228,134       weakest: schedule_adherence

#3 Regional Medical Center A / Food & Nutrition  score 72.8
   overtime 2.4% (84.0)   punch 3.7% (63.0)   adherence 86.0% (44.0)   budget -28.6% (100)
   63 staff   18,193 h   $297,550       weakest: schedule_adherence

#4 Community Hospital A / Retail & Cafe          score 67.5
   overtime 2.5% (83.3)   punch 5.2% (48.0)   adherence 84.7% (38.8)   budget -23.4% (100)
   17 staff   5,234 h   $80,478         weakest: schedule_adherence
```

**Reading it:** raw value first, score out of 100 in brackets. Every site is comfortably
inside the overtime target (2.4–2.5% against a 5% limit) and every site is under budget, so
those two measures score 83 and 100 across the board — they do not differentiate anyone.

**Schedule adherence is the real story.** All four sit at 84.7–87.6% against a 90% target, so
all four are off target and it is the weakest measure everywhere. That triggers the systemic
banner: when every site misses the same measure it is a process or target-setting problem, not
four independent management failures.

Site #4 is last because of **punch accuracy at 5.2%** — noticeably worse than the 3.6–3.9% of
its peers — combined with the lowest adherence at 84.7%. It is also the smallest site at 17
staff, which is where the actionable read is: a small team with the worst punch discipline.

All four also run well under budget (−21.9% to −28.6%). The API flags that via
`underspend_review`; the page no longer prints a banner for it.

---

### 6.3 Time Punch Analytics

```
window: 2026-06-02 to 2026-08-01

total_punches                     10,689
exception_rate_pct                   0.6
missed_punches                       267
duplicate_punches                     50
early_clock_ins                        0
late_clock_outs                    1,382
long_breaks                           64
manual_edits                         363
payroll_exceptions                   229
excess_scheduled_hours_employees       0
suspicious_punch_patterns             10

2,075 flagged issues total

by type      Late Clock-Out 1,382    Missed Punch 267    Potential Payroll Exception 229
             Repeated Manual Edits 73    Long Break 64    Duplicate Punch 50
             Suspicious Punch Pattern 10
by severity  High 560    Medium 1,515
```

**Reading it:** the headline `exception_rate_pct` of 0.6% is the *device-flagged* rate, while
the rule engine independently finds 2,075 issues across 10,689 punches — the rules catch far
more than the source system flags, which is the point of the page.

**Late clock-outs dominate at 1,382, which is 67% of everything.** That concentration is
itself the finding: one issue type at two-thirds usually means a process problem — staff not
badging out at shift end — rather than individual behaviour. **Zero early clock-ins** and
**zero employees exceeding scheduled hours** are equally informative: those controls work.

#### Alerts

```
High     560 high-severity issue(s) need review
Medium   'Late Clock-Out' is 67% of all flagged issues
Medium   Worker0037 has 27 flagged punches
Medium   Worker0018 has 26 flagged punches
Medium   Worker0107 has 25 flagged punches
```

#### Watchlist (rising flag rate)

```
Worker0006   12 recent  vs   7 earlier
Worker0018   12 recent  vs  14 earlier
Worker0060   11 recent  vs  13 earlier
```

**Reading it:** Worker0018 appears in both lists but for different reasons — high total volume
(26) *and* a rising rate. Note that Worker0018 shows 12 recent against 14 earlier and still
qualifies: the comparison is by **rate**, and the recent window is a third the length, so 12
in a third of the time is faster than 14 across the remaining two-thirds.

#### Hour-of-day profile

```
00:00    44 issues / 985 punches    = 4.5%
05:00    50 issues / 1,272 punches  = 3.9%
06:00    35 issues / 860 punches    = 4.1%
```

**Reading it:** 14 active hours, because the sites are not open 24/7. Both count and *rate*
are plotted, which matters — a busy hour naturally has more issues, so the rate is what
reveals a genuinely problematic hour.

#### One anomaly in full

```
exception_type      Missed Punch
severity            High
problem             Employee has no matching punch for a scheduled shift.
expected_value      IN and OUT punch
actual_value        Missing punch
rule_triggered      attendance.missed_punch_flag
root_cause          Employee forgot to badge in/out, or the device failed to record it.
potential_impact    Payroll and hours worked cannot be verified for this shift.
recommended_action  Confirm hours with the employee/supervisor and correct the timecard.
```

**Reading it:** every flag carries the rule that fired it, so it is defensible rather than a
black box, plus a root cause and a concrete next step.

---

### 6.4 Labor Forecasting

#### Demand Drivers & Feature Mapping

```
target: required_manpower

Food & Nutrition (11 inputs)
  is_holiday, demand_multiplier, season_Spring, season_Summer, season_Fall, season_Winter,
  occupied_beds, admissions_count, discharges_count, transfers_count, meals_served

Retail & Cafe (10 inputs)
  is_holiday, demand_multiplier, season_Spring, season_Summer, season_Fall, season_Winter,
  promotion_flag, event_flag, sales_amount, transaction_count

not in this dataset
  Weather · Marketing campaign detail · Local event detail · Employee availability
```

**Reading it:** census columns are shown by plain name but fed to the models **lagged one
week** — the same-period value would leak the answer. The "not in this dataset" list is
deliberate: it states what the forecast *cannot* see, so nobody assumes weather is factored in.

#### Data Analysis

```
daily trend      90 points   first {2026-05-03, 2.62}   last {2026-07-31, 2.58, 7d-avg 2.46}
by hour of day   peak 07:00 (6.86)     quietest 01:00 (2.0)
by day of week   Mon 2.71  Tue 2.71  Wed 2.73  Thu 2.73  Fri 2.72  Sat 2.64  Sun 2.66
by season        Winter 2.90   Spring 2.73   Fall 2.69   Summer 2.49
holiday lift     -7.4%
cafe flags       promotion +14.0%    event +13.0%
```

**Reading it:** the hour-of-day peak of **6.86 at 07:00 against 2.0 overnight is a 3.4x
swing** — breakfast service. That intraday spike is exactly why hourly forecasting is hard and
why the engine works at half-day blocks. Day-of-week barely moves (2.64 to 2.73), so weekday
effects are weak *for staffing*. Winter is 16% busier than Summer. Holidays *reduce* demand by
7.4%. Cafe promotions genuinely lift demand **+14%**, which is why promotion_flag is a
worthwhile input there.

#### Data Pre-processing

```
total_history_days        730
training_window_days      182     (364 half-day rows)
resolved_seasonal_period   14 slots  -> Weekly
validation                rolling_origin, 3 folds, 22-day validation window each
input_dataset             364 rows x 13 columns
forecast_horizon            7 days
block_hours                12

preview row 1
  date 2026-01-31 00:00   is_holiday 0   demand_multiplier 1.0   season_Winter 1
  occupied_beds 1248.2   admissions 4   discharges 4   transfers 1   meals_served 126
  required_manpower 33.0
```

**Reading it:** 730 days available, 182 used. The engine picked a **weekly** cycle (14
half-day blocks) over a daily one. `required_manpower` sits **last** in the preview because it
is the target, not an input. `occupied_beds 1248.2` is a 12-hour sum, not a headcount — the
per-hour figure is around 85–87.

#### Model Training — leaderboard (Community Hospital / Food & Nutrition)

```
XGBoost with exogenous variables        94.25%  mape 5.75  mae 3.43  rmse 4.33  bias  0.77   0.53s  CHAMPION
SARIMAX with exogenous variables        94.18%  mape 5.82  mae 3.50  rmse 4.35  bias -0.11   2.34s
VAR with exogenous variables            94.18%  mape 5.82  mae 3.50  rmse 4.38  bias -0.33   0.04s
Auto ARIMA with exogenous variables     94.15%  mape 5.85  mae 3.51  rmse 4.42  bias  0.07  10.48s
Exp Smoothing Additive Damped           93.86%  mape 6.14  mae 3.71  rmse 4.56  bias -0.70   0.30s
Exp Smoothing Multiplicative Damped     93.84%  mape 6.16  mae 3.73  rmse 4.57  bias -0.92   0.28s
Exp Smoothing Additive                  93.76%  mape 6.24  mae 3.80  rmse 4.64  bias -1.53   0.29s
Exp Smoothing Multiplicative            93.76%  mape 6.24  mae 3.80  rmse 4.63  bias -1.54   0.26s
VAR                                     93.62%  mape 6.38  mae 3.75  rmse 4.74  bias  2.62   0.01s
SARIMAX                                 93.51%  mape 6.49  mae 3.83  rmse 4.78  bias  2.47   0.49s
XGBoost                                 92.70%  mape 7.30  mae 4.26  rmse 5.29  bias  4.55   0.39s
LSTM                                    92.69%  mape 7.31  mae 4.25  rmse 5.41  bias  4.47   9.51s
Auto ARIMA                              91.81%  mape 8.19  mae 4.75  rmse 5.89  bias  5.88   2.84s

13/13 completed    train/test rows 337/84   (281/84 for the holdout-evaluated models)
```

Champions across all four series:

| Series | Champion | Accuracy | Range across 13 models |
|---|---|---|---|
| CH / Food & Nutrition | XGBoost + exog | 94.25% | 91.81 – 94.25 |
| RMC / Food & Nutrition | VAR + exog | 97.67% | 96.45 – 97.67 |
| CH / Cafe | XGBoost + exog | 92.11% | 90.53 – 92.11 |
| RMC / Cafe | XGBoost + exog | 96.63% | 93.30 – 96.63 |

**Reading it:** **all 52 combinations completed** — nothing failed or was skipped. Every
champion clears 90%.

Two patterns worth noting. First, the **top four models are all `+exog` variants**, so the
census and sales drivers genuinely help. Second, **look at the bias column** — the leaders sit
at −0.11 to +0.77 (near-unbiased) while the bottom four run +2.47 to +5.88, meaning they
systematically *over*-forecast. Ranking by MAPE happened to pick a low-bias model too.

**Runtimes span 0.01s to 61s.** VAR is effectively instant; Auto ARIMA on the cafe took 61s.
The whole run was **5m 09s for 52 model runs**.

`train_rows` differs by evaluation mode — 337 for the ten CV-evaluated models, 281 for Auto
ARIMA and LSTM on holdout — but **`test_rows` is 84 for every single one**, which is what
makes the comparison fair.

#### Forecast Explorer

```
model        XGBoost with exogenous variables
evaluation   rolling_origin, 3 folds    train 337 / test 84
chart data   84 backtest points    7 future points
boundary     last actual 2026-07-31 00:00  ->  forecast 2026-08-01 to 2026-08-07

future    2026-08-01   56.4   (50.1 to 61.0)
          2026-08-02   59.2   (52.9 to 63.8)
          2026-08-03   60.9   (54.6 to 65.5)
          2026-08-04   57.3   (51.0 to 61.9)
```

**Reading it:** the grey line covers full history, orange covers only the 84 validated points,
green covers 7 future days. The bracketed range is an **80% prediction interval built from
actual backtest residuals** — not a theoretical assumption — so the roughly plus-or-minus 5
staff-hours reflects how wrong this model really was.

Compare the forecast spread (56.4 to 60.9) against the actual spread over the same backtest
window (49 to 74). The forecast is **much narrower than reality** — see
[section 5](#5-what-this-build-does-not-do).

#### Drift Monitoring

```
LOC01_FOOD_NUTRITION  Stable  occupied_beds      r=0.34 (weak)      recent 85.22   prior 85.20    0.0%   age 0d
LOC02_FOOD_NUTRITION  Stable  occupied_beds      r=0.61 (moderate)  recent 249.09  prior 248.99   0.0%   age 0d
LOC01_CAFE            Stable  transaction_count  r=0.95 (strong)    recent 15.59   prior 15.70   -0.7%   age 0d
LOC02_CAFE            Stable  transaction_count  r=0.99 (strong)    recent 44.89   prior 44.33   +1.3%   age 0d
```

**Reading it:** all four are **Stable** — every change is within 1.3%, far inside the 15%
threshold, so the two dashed average lines sit on top of each other on the chart. `age 0d`
means the models were trained today.

The `r` column is the honest part: **occupied_beds correlates only 0.34** with staffing at
Community Hospital, so a shift in it would barely move that forecast. The cafe signals at 0.95
and 0.99 genuinely drive their forecasts. The weak-signal warning banner appears only for the
two Food & Nutrition series.

#### Staffing Impact

```
LOC01_FOOD_NUTRITION   336 pts   understaffed 103   overstaffed 160   balanced  73
LOC02_FOOD_NUTRITION   336 pts   understaffed  97   overstaffed 232   balanced   7
LOC01_CAFE             196 pts   understaffed  42   overstaffed  68   balanced  86
window 2026-07-18 to 2026-07-31
```

**Reading it:** the striking number is **LOC02 Food & Nutrition: only 7 of 336 hours balanced,
with 232 overstaffed** — that site is persistently over-rostered, which lines up with it being
28.6% under budget on cheap hours. LOC01 Cafe is the healthiest at 86 of 196 balanced. The
cafe has 196 points rather than 336 because it is not open 24 hours.

Understaffed and overstaffed hours in the *same* window is the useful insight — it is not a
headcount problem, it is a **distribution** problem, which is exactly what clicking through to
the drill-down exposes.

---

### 6.5 AI Recommendations

```
11 recommendations    Staffing Adjustment 4    Overtime Reduction 5    Schedule Adherence 2

[High] Short of staff on Monday 20 Jul morning
       Regional Medical Center / Food & Nutrition Services
  What is happening   About 20 people are needed on shift that morning, but only 10 are
                      rostered - short by 10 people
                      - a shortfall of 10 hours.
  What to do          Roster 10 more people. No other site has spare staff then, so
                      this needs extra cover.
  Why it matters      Covers the 10-hour gap so the shift is fully staffed.
  ~$242 saved         what you would otherwise pay in last-minute overtime cover

[High] Worker0090 is heading into overtime
       Regional Medical Center A / Food & Nutrition Services
  What is happening   Worker0090 has already worked 6.3 overtime hours, and their recent
                      pattern makes more overtime very likely (98% chance).
  What to do          Hand some of their upcoming shifts to a colleague with spare capacity.
  Why it matters      Avoids up to 6.3 hours paid at the overtime rate.
  ~$44 saved          the extra premium above their normal hourly rate
```

**Reading it:** each card answers three questions in order. Every savings figure states its
own basis — $242 is avoided overtime *cover*, $44 is the overtime *premium* over base rate.
They are computed (hours x rate x multiplier), not invented.

Note the first card says *"No other site has spare people then"* — the engine checked the
paired site for surplus at that exact hour before recommending added cover rather than a
transfer.

---

### 6.6 AI Assistant

One real conversation, three turns, nothing re-stated by the user:

```
Q: what is the demand trend for the cafe at Community Hospital
A: The demand trend for the cafe at Community Hospital is flat with a -3.5% change.
   - Average Recent Demand - 60.58 people/hour.
   - Forecast for Next 7 Days - 58.44 people/hour.
   - Staffing Gap - 0 people, with a required headcount of 3 and scheduled headcount of 3.
   [tools: forecast]

Q: is it over budget
A: No, the labor cost at Community Hospital is not over budget; it is 26% under budget.
   - Total Labor Cost - $711,238.93.
   - Total Budget - $960,697.00.
   - Department Labor Cost (Retail & Cafe Services) - $80,477.91, which is 23.4% under budget.
   [tools: labor_cost]

Q: who is highest risk there
A: The highest risk employees at Community Hospital in the Retail & Cafe Services department are:
   - Worker0025 - 96% risk, High level.
   - Worker0026 - 90% risk, High level.
   - Worker0038 - 88% risk, High level.
   [tools: risk]

Q: what is the weather today
A: That one is outside what I can see - I only read this application's own workforce data.
```

**Reading it:** turn 1 scoped to **one** series out of four, because it named both a
department and a site. Turn 2 said only *"it"* — the site came from the conversation, and the
question was routed to cost without sharing a single keyword with turn 1. Turn 3 said only
*"there"*, and returned **café staff at Community Hospital** rather than the highest-risk
employees company-wide (who are at Regional Medical Center) — employee rows are filtered to
the scope before ranking, so the right people are in the answer by construction rather than by
luck. The weather question was **declined before any retrieval**, so out-of-scope questions
cost almost nothing.
