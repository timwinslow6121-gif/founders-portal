# AEP Pipeline — Implementation Spec for the Founders Portal

**Status:** design spec, v7 — **amended 2026-09-18** against the live portal schema and
production data. Amendments are marked ⚠ inline; they correct assumptions that would not have
compiled or would have produced silently wrong triage. Original reasoning is otherwise intact.
**Companion file:** `aep-pipeline-v7.html` — a self-contained, runnable prototype. It is the
reference for *behaviour and wording*, not for architecture. See §2.
**Target:** Flask 3.0 + SQLAlchemy + Alembic + PostgreSQL 16, Jinja2 templates, vanilla JS.
**Scale:** ~5,495 customers across 9 agents. Timbo's own book is ~500.

---

## 1. What this feature is, in one paragraph

During AEP (Oct 15 – Dec 7) every Medicare client needs their 2027 coverage settled, and every
agent is trying to do that for hundreds of people at once. This feature answers three questions
and nothing else:

1. **Who needs me right now?** — a short, ordered list of work, not a board to browse.
2. **Am I going to finish in time?** — one number: how many are settled out of how many.
3. **Where is this one person?** — everything about one customer, on one screen.

It is deliberately **not** a general-purpose CRM view. The portal already has customer records,
carriers, commissions and comms. This is a *seasonal work queue* that reads those records and
writes a small amount of workflow state back.

---

## 2. Read this before you open the prototype

The prototype is a single HTML file with an in-memory array of fake customers. **Its
architecture will not survive contact with the portal** and you should not port it literally.

### Take from the prototype

- Every piece of **copy** — card titles, button labels, toast text, empty states. The wording
  was iterated specifically so a non-technical agent reads it without training. Do not
  "improve" it into CRM jargon. There is no "pipeline stage", "SOA", "lead scoring" or
  "disposition" anywhere in the UI, and that is on purpose.
- The **information architecture** — three tabs, the one-at-a-time working mode, the person
  sheet, the settings/setup split.
- The **decision rules** — what makes someone Tier 1, what counts as settled, what each work
  queue contains. These are specified precisely in §5 and §6 below; the prototype is just a
  working illustration of them.
- The **interaction contract** — one screen asks one question, primary actions are one tap,
  and the system never asks for something it can already know.

### Do NOT take from the prototype

| Prototype does | Portal must do | Why |
|---|---|---|
| Holds all customers in a JS array | Query Postgres with `LIMIT`/cursor | 5,495 rows cannot be shipped to the browser, filtered client-side, and re-rendered on every action |
| `renderAll()` re-renders the whole page | Repaint only the row/card that changed | Same DOM problem the commission Fidelity view already hit and solved |
| Computes tier in JS on every read | Compute tier in SQL (§5.4) | Needs to be sortable, countable and filterable across the whole book |
| `seedExtras()` fabricates calls, blockers and helpers | Real rows from Quo webhooks and agent input | It is demo scaffolding — delete it |
| No auth, one global `state.agent` | `current_user` from Google OAuth, agency scoping in every query | §8 |
| Rules live in a `RULES` object in memory | `pipeline_config` + `plan_rating` + `sar_rule` tables | Rules are set once by Timbo and read by nine agents |

**Follow the Fidelity precedent.** The commission Fidelity view returns JSON from
`fidelity_row()` and repaints in place rather than rendering hidden forms per row. This feature
has exactly the same shape — many rows, in-place updates, no page reload — so use the same
pattern rather than inventing a new one. Every mutating endpoint in §7 returns the updated row
plus the affected counters so the JS can repaint without a refetch.

---

## 3. Domain model and the vocabulary decisions

### 3.1 Stage — five values, and why not more

```
contact    "Needs a call"        nobody has reached them yet (letter/blast only, or tries with no answer)
scheduled  "Appointment set"     booked in Acuity or Calendly
deciding   "Thinking it over"    you met them, no decision yet
submitted  "Waiting on carrier"  application sent, not confirmed
done       "Finished"            2027 coverage is settled, one way or another
```

**Why five.** Earlier drafts had seven. In a single 45-minute appointment a customer goes from
"needs analysis" through "plan review" to "app submitted" — three drags for one meeting. Agents
will not do that, so the middle stages collapse into `deciding`. Conversely, four is too few:
`submitted` has to be separate because an unconfirmed application is the thing that silently
costs commission when it falls through.

**Why "stalled" is not a stage.** Stalled is a *property of how long someone has been in a
stage*, not a place they sit. If it were a column you could not tell someone you met yesterday
from someone you met nine days ago, and a customer could not be both "deciding" and "stalled".
It is computed (§6.2) and shown as a badge.

**Why channels are not stages.** Contact happens by letter, ringless voicemail, text, phone,
walk-in, or in person, in any order and any number of times. There is no fixed sequence, so
channels are rows in an append-only `touch` log, never positions in a funnel.

### 3.2 Outcome — three values

`done` always carries an outcome:

```
enrolled  they took a new plan through you
kept      they reviewed and are staying on their current plan
lost      closed for this year (unreachable, not a fit, went elsewhere)
```

**"Kept" is a win, not a loss.** Both competing mockups grouped "no change" with "closed lost".
For a renewal book the most common good outcome is that a client reviews their plan and stays
put. Counting that as a loss makes the whole season look like a failure and, worse, makes the
finish-line number wrong.

### 3.3 Touch levels — sent / tried / reached

Every touch row carries a level:

```
sent     letter, RVM blast, bulk email/text — they may not know you exist yet
tried    outbound call with no answer, personal text with no reply
reached  they answered, called in, walked in, or showed up to an appointment
```

Only `reached` counts as real two-way contact. This matters for the coverage number (§4) and
for the "not contacted at all" filter, which is the group that quietly runs out of days.

### 3.4 Authorized contact — a person, not a phone number

A child or spouse very often handles a parent's Medicare, and that child may be a Medicare
client themselves. So the helper is a **record with a link**, not a note or an extra phone
number on the parent:

- `authorized_contact` has a `linked_customer_id` for when they are also a client
- `may_discuss_coverage` is a boolean the agent sets, because whether you can legally talk to
  them about the parent's plan is a real question, not a UI detail
- search matches the helper's name and number, so when the daughter calls from her own phone
  you find the mother

---

## 4. The one number that matters

Header of the Today tab:

> **185 of 526 settled for 2027.**
> 341 to go, 41 days left. That is about 9 a day.
> *166 of them have not been contacted at all.* ← links to the "Not contacted" filter

**Why "settled" and not "talked with".** An earlier version measured people the agent had
spoken to. That over-counts: a conversation in October with someone who then vanishes is not
progress. The number that has to reach 100% by Dec 7 is coverage settled — `stage = 'done'`,
any outcome.

**Why the second line stays.** "Settled" is the finish line but it is a lagging indicator; by
the time it moves you have already done the work. "Not contacted at all" is the leading
indicator and the group most at risk. Two numbers, one big and one small — not one, and not a
dashboard.

**Why a per-day pace figure.** It converts a number an agent ignores into a decision they can
act on this morning. Round up; never show a decimal.

**Real denominators, measured 2026-09-18 (active policies by servicing agent):**

| Agent | Book | | Agent | Book |
|---|---|---|---|---|
| Brian Freeman | 1,365 | | Tim Winslow | 553 |
| Rebekah Long | 1,155 | | Betty Marlowe | 98 |
| Chris Foster | 770 | | Anjana Patel | 75 |
| Justin Basinger | 741 | | *(unassigned)* | 18 |
| Mike Lauzurique | 693 | | Don Long (retired) | 5 |

The prototype's 526 is close to Tim's own 553. **Brian's 1,365 over 41 days is ~34/day** — the
pace line will read very differently for him, and that is the honest number. Counts must exclude
deceased customers, or the denominator is wrong from day one.

---

## 5. Priority — Tier 1 / 2 / 3

### 5.1 Why tiers and not a score

An earlier version used a 0–100 point score with weights. It was rejected because the weights
were invented, the number was not explainable to the person being prioritised, and nobody could
say what 54 vs 56 meant. Tiers are set by **rules the agency configures**, and every tier can be
explained in one sentence to the agent looking at it.

### 5.2 The rules, in evaluation order

Renewals:

1. **Plan is ending in their county** → Tier 1. A service area reduction means they get
   auto-assigned or lose coverage. Driven by the `sar_rule` table: `(plan_id, county)`.
2. **NC State Health Plan retiree who has not confirmed their opt-out call** → Tier 1.
   Retirees on the 70/30 Plan must call the State themselves during *its* open enrollment
   (Oct 12–30, 2026 for 2027) or they are enrolled in the Humana group PPO. Dates are
   configurable because the State can move the window. Once `shp_confirmed_at` is set they drop
   to their plan's rating.
3. **Plan rated "major"** → Tier 1. *"Off by default"* means **no plan carries a `major`
   rating until Timbo sets one** — it is not a rule that can be switched off. `plan_rating.rating`
   is nullable and starts NULL for every plan, so rule 6 catches everyone until ratings are
   entered. There is no `major_enabled` flag; do not build one.
4. **Plan rated "some changes"** → Tier 2.
5. **Plan rated "little change"** → Tier 3.
6. **Plan not rated** → Tier 2, so nobody is skipped before the ratings are filled in.

New leads:

7. **`sep_end` within `sep_days` (default 30)** → Tier 1, ranked by days remaining.
8. **`sep_end` further out, or in the past** → Tier 2.
9. **No `sep_end`** → Tier 2.

Always:

10. **Manual override** beats every rule above. Stored with a reason and the user who set it.

### 5.3 Two decisions worth defending

**"Major plan change" must be opt-in per plan, not automatic.** A big benefit cut is bad but
has no hard deadline beyond Dec 7 itself. If every plan with meaningful changes were Tier 1,
Tier 1 would be several hundred people and would stop meaning anything — the whole value of the
tier is that it is small and deadline-driven. So the control exists (a "Major" button per plan
in setup) and Timbo decides, plan by plan, once the real 2027 data lands. Show a confirmation
toast with the affected count, because clicking it moves dozens of people at once.

**Lead urgency comes from a date, not a category.** Earlier versions had a switch that made
"losing employer coverage" and "moved into the area" leads Tier 1 as a class. That is the wrong
shape: "losing employer coverage" is not urgent, but "employer coverage ends Nov 30" is. So the
lead form captures an optional `sep_end` date and urgency is derived from days remaining. This
also handles turning-65 windows with no extra rule, and it degrades honestly — a lead with no
date on file is Tier 2 and the reason text says so.

### 5.4 Where tier is computed

**Compute it in SQL, in a view. Do not store it on the customer row.**

```sql
CREATE VIEW customer_priority AS
SELECT c.id AS customer_id, ... CASE ... END AS tier,
       ... AS rank, ... AS reason_code,
       cp.plan_id, cp.county            -- ingredients, not a sentence (see below)
FROM customers c
JOIN pipeline_state ps   ON ps.customer_id = c.id
JOIN current_plan   cp   ON cp.customer_id = c.id     -- see §5.4.1
LEFT JOIN plan_rating pr ON pr.plan_id = cp.plan_id
LEFT JOIN sar_rule   sr  ON sr.plan_id = cp.plan_id AND sr.county = cp.county
CROSS JOIN pipeline_config cfg
WHERE c.agency_id = :agency_id AND c.deceased_date IS NULL;
```

⚠ **Corrected against the live schema (2026-09-18).** Table is `customers`, not `customer`.
There is **no `customers.current_plan_id`** — the original join was against a column that does
not exist. Two further gates the original omitted: `agency_id` scoping (mandatory portal-wide)
and excluding deceased customers (`deceased_date IS NULL`, migration 043 — a deceased customer
must never enter a work queue).

### 5.4.1 Resolving "their current plan" — measured, not assumed

The portal reaches a plan through `policies`, not a column on the customer:

`customers.id` ← `policies.customer_id` (`status='active'`) → `policies.plan_id` → `plans.id`

Measured on production, agency 1:

| | count |
|---|---|
| customers | 5,495 |
| …with ≥1 **active** policy | 5,435 |
| …whose active policy is **linked to a plan** (`plan_id NOT NULL`) | **5,405** |
| …with **two** active policies | **27** |

So `current_plan` is a helper view, and the 27 multi-policy customers need a deliberate rule:

```sql
CREATE VIEW current_plan AS
SELECT DISTINCT ON (p.customer_id)
       p.customer_id, p.plan_id, p.id AS policy_id,
       COALESCE(NULLIF(trim(c.county), ''), NULLIF(trim(p.county), '')) AS county
FROM policies p
JOIN customers c ON c.id = p.customer_id
WHERE p.status = 'active' AND p.plan_id IS NOT NULL
ORDER BY p.customer_id,
         CASE WHEN plan_lane(...) = 'primary_medical' THEN 0 ELSE 1 END,
         p.effective_date DESC NULLS LAST, p.id DESC;
```

**Pick the primary-medical policy, not the newest.** The 27 split as: medigap+pdp 15, mapd+mapd
4, mapd+pdp 2, dvh+medigap 1, ma+mapd 1, pdp+pdp 1, plus 3 with an unlinked partner. AEP triage
is about the **Part C / Part D** plan, so a customer holding Medigap + PDP must be triaged on the
PDP. `app/plan_lane.py` already classifies this (`primary_medical` / `medigap` / `ancillary`) and
is the existing seam — use it rather than inventing a rule. The 15 medigap+pdp customers would be
triaged on the **wrong** plan under a naive "newest effective date" pick.

⚠ **`Policy.plan_type` must NOT be used for this.** It holds *carrier* vocabulary — 2,133 active
UHC policies are typed `MA` but only ~15 are genuinely MA-only (documented data trap in
CLAUDE.md). Derive the lane from the linked `Plan`, never from `Policy.plan_type`.

### 5.4.2 County: 352 customers cannot match a SAR rule

`sar_rule` joins on county. Measured: **5,111 of 5,495 customers have a county; 352 of the
missing ones still hold an active policy.** Only **1** can be recovered from `policies.county`.

So ~350 customers are structurally invisible to rule 1 — the highest-priority rule in the whole
design. **A SAR rule must therefore report its own blind spot**: when Timbo adds a rule for
`(plan, county)`, the confirmation toast states both the matched count *and* how many customers
on that plan have no county on file. Silence there would read as "nobody affected".

⬜ Backfilling county from ZIP is a separate task, not part of this build.

**Why a view rather than a stored column.** Tier has to be sortable, countable and filterable
across the whole book, so it cannot be computed per-request in Python. But it also changes the
moment Timbo edits a rule — and editing rules is a normal, frequent action, especially around
Sept 28 when the real plan data arrives. A stored column would need invalidation on every rule
change and would be wrong in the window before the recompute finishes. A view is always correct
and, at 5,495 rows with indexes on `current_plan_id` and `county`, costs nothing.

If the book ever passes ~100k rows, switch to a materialised view refreshed on rule change.
Not before.

`reason_code` is an enum the template maps to plain-language text; do not build the sentence in
SQL. `rank` is a secondary sort within a tier (state opt-outs closest to their deadline first,
then plan-ending, then everything else).

⚠ **An enum alone is not enough.** The prototype's `autoTier` returns interpolated detail —
*"H5525-035 is not offered in Cabarrus County for 2027"*, *"State opt-out, 6 days left"* — and a
bare code cannot carry the plan, the county or the days remaining. The view therefore returns
**ingredients**, and Jinja composes the sentence:

```
reason_code    sar | shp_pending | shp_closed | rating_major | rating_some | rating_little
               | unrated | sep_urgent | sep_future | sep_closed | no_deadline | override
plan_id        FK, for the carrier + CMS code
county         text, for the SAR sentence
days_left      int, nullable — SHP deadline or SEP end
```

One customer can have a **primary** reason and secondary context (the prototype appends *"State
retiree, opt-out confirmed"* as a green chip after the primary reason). v1 returns one
`reason_code` plus these ingredients; the confirmed-opt-out chip is derived in the template from
`pipeline_state.shp_confirmed_at`, not a second reason row.

### 5.5 Sorting

Everywhere a list of people is ordered: `tier ASC, rank ASC, <queue-specific key>`.

---

## 6. The work queues

### 6.1 The queue list

Today shows one card per queue, in this order. **Empty queues are hidden.** Each card shows a
title, one sentence, a count, and a primary button that starts one-at-a-time mode.

| id | Card title | Contains | Urgent |
|---|---|---|---|
| `shp` | "State retirees to call, N days left" | `shp_flag AND shp_confirmed_at IS NULL`, only while the State window is open | yes |
| `catchup` | "Write down what happened" | a call or appointment with no outcome recorded | yes |
| `today` | "Appointments today" | `stage='scheduled' AND appt::date = today` | no |
| `waiting` | "Things you are waiting on" | `waiting_due <= today` | yes |
| `callfirst` | "People to call first" | `stage='contact' AND attempts=0 AND tier=1` | yes |
| `undecided` | "Thinking it over" | `stage='deciding'` and stalled, with no open blocker | yes |
| `noreply` | "People who have not called back" | `stage='contact'` and stalled | no |

A customer appears in **at most one** queue. Two lists telling an agent to call the same person
is how they stop trusting the lists.

⚠ **The prototype does not actually achieve this, and hand-written exclusions will not either.**
Verified by extracting the prototype's own logic and running it over its 526-customer book:

```
queue counts: {shp:30, catchup:9, today:6, waiting:8, callfirst:14, undecided:16, noreply:55}
customers in MORE THAN ONE queue: 2
    shp + today  ->  Charles Starnes, Kenneth Peeler   (stage=scheduled, shp=true)
```

Cause: `callfirst` and `noreply` carry `&& !(shpOpen() && shpPending(c))`, but `today`,
`catchup`, `waiting` and `undecided` do not, and each queue independently filters the whole book
(`aep-pipeline-v7.html:962`). Every queue added later must remember to exclude every
higher-priority queue — an O(n²) invariant maintained by hand, which is why it is already broken
at n=7.

**Build it structurally instead: assign each customer exactly one queue in a single pass,
ordered by priority.**

```sql
CREATE VIEW customer_queue AS
SELECT customer_id,
       (CASE WHEN <shp>       THEN 'shp'
             WHEN <catchup>   THEN 'catchup'
             WHEN <today>     THEN 'today'
             WHEN <waiting>   THEN 'waiting'
             WHEN <callfirst> THEN 'callfirst'
             WHEN <undecided> THEN 'undecided'
             WHEN <noreply>   THEN 'noreply'
        END) AS queue_id
FROM pipeline_state ps JOIN customers c ON c.id = ps.customer_id
WHERE c.agency_id = :agency_id AND c.deceased_date IS NULL;
```

A `CASE` is first-match-wins, so exclusivity is guaranteed by the structure rather than by each
predicate remembering its predecessors. Each queue's predicate then states only its own
condition. Queue order in the `CASE` **is** the priority order, in one readable place.

Counts come from `SELECT queue_id, count(*) FROM customer_queue GROUP BY queue_id`, which by
construction sums to the number of people with any work — a number the Today header can state
honestly.

**Acceptance check 1 becomes mechanical:** no customer_id appears twice in `customer_queue`.
That is now a property of the schema, not a test that can silently regress.

### 6.2 Stalled, per stage

```
contact    attempts >= 2 AND first_try_at <= today - 5 days
scheduled  appointment start < today AND no outcome recorded
deciding   stage_since <= today - 3 days
submitted  submitted_at <= today - 10 days AND not confirmed AND no problem flagged
```

Tune these in `pipeline_config`; the 5/3/10 figures are starting guesses, not research.

### 6.3 One-at-a-time mode

The primary button on each card opens a full-screen view showing **one person**: name, what
they are on now, one sentence on why they are on this list, a large call button that dials, and
three to five plain-language outcome buttons. Tapping one records it and advances to the next
person, with a progress bar reading "4 of 12 done".

**Why this is the primary interaction.** The agents who will use this currently record nothing.
Asking them to find a person, open them, and choose a status is four or five actions per
customer times hundreds of customers, and it will not happen. One tap will. Browsing is the
fallback, not the default.

Requirements: a Skip button that does not lose the person; the list is snapshotted when the mode
opens so it does not reshuffle under the agent's finger; closing and reopening starts fresh.

---

## 7. Data model and API

### 7.1 Assumptions — VERIFIED against production, 2026-09-18

Checked directly against `app/models.py` and the live database. Use these names.

| Spec assumed | Actually | Note |
|---|---|---|
| table `customer` | **`customers`** | plural throughout |
| primary key | `customers.id` | ✅ |
| display name | `full_name` (+ `first_name`/`last_name`, `preferred_name`) | `full_name` is denormalised and indexed for search; `address_as()` gives the conversational name |
| phone | `phone_primary`, `phone_secondary` | ✅ |
| city / county / state | `city`, `county`, `state`, `zip_code` | ⚠ county blank on 384 (§5.4.2) |
| owning agent FK | **`primary_agent_id`** → `users.id` | not `agent_id` |
| current plan | ❌ **no such column** | resolve via `policies` — §5.4.1 |
| client-vs-lead | ❌ **does not exist** | see below |

**There is no lead record type.** `deal_stage` is `'Active'` on all 5,495 rows and `source` is
`bob` (3,019) / `commission_import` (1,972) / NULL (504) — provenance, not lifecycle. The spec's
"Renewals vs New leads" split (§5.2) therefore has nothing to branch on today.

`pipeline_state.track` (`renewal` | `lead`) carries it: backfill every existing customer as
`renewal`, and `POST /pipeline/api/leads` creates `track='lead'`. This keeps the distinction in
the pipeline's own table rather than overloading `deal_stage`, whose meaning is already
established elsewhere in the portal.

**Fields the pipeline must respect, not duplicate:** `deceased_date` (mig 043 — excluded from
every queue and every count), `sms_consent_at`, `manually_edited`, and `field_provenance`. Any
pipeline write to a customer field goes through `app/customer_provenance.py`, never directly.

**Do not create a parallel customer table.** Every new table below FKs to `customers.id` and
carries `agency_id`.

### 7.2 New tables (Alembic revision `046`)

```
pipeline_state        1:1 with customer. agency_id, track(renewal|lead), stage, outcome,
                      stage_since, attempts, first_try_at, intake_status, waiting_what,
                      waiting_due, sep_end, sep_reason, shp_flag, shp_confirmed_at,
                      tier_override, tier_override_note, tier_override_by, tier_override_at
touch                 append-only. customer_id, agent_id, level(sent|tried|reached), channel,
                      direction, occurred_at, detail, source(quo|acuity|manual|system),
                      external_id (unique, nullable), duration_s, outcome_recorded_at
appointment           customer_id, agent_id, starts_at, mode, source, external_id,
                      outcome_recorded_at
application           customer_id, agent_id, plan_id, submitted_at, via, confirmed_at,
                      problem, problem_at, resolved_at
scope_form            customer_id, captured_at, method, products (jsonb), captured_by
authorized_contact    customer_id, name, relationship, phone, may_discuss_coverage,
                      linked_customer_id (nullable FK to customer)
plan_rating           plan_id (PK), rating (1|2|3, nullable), note, updated_by, updated_at
sar_rule              plan_id, county, state, created_by, created_at
pipeline_config       single row. season_start, season_end, shp_enabled, shp_start, shp_end,
                      sep_days, stall_contact_days, stall_deciding_days, stall_submitted_days,
                      rules_status (draft|final), updated_by, updated_at
```

Indexes: `pipeline_state(stage, stage_since)`, `pipeline_state(waiting_due)`,
`pipeline_state(sep_end)`, `touch(customer_id, occurred_at DESC)`,
`touch(external_id)` unique, `appointment(agent_id, starts_at)`.

⚠ **Corrected:** `customers.primary_agent_id` and `customers.county` are **already indexed**
(`app/models.py`); do not re-add them. `customer(current_plan_id)` does not exist — the
equivalent is `policies(customer_id)` and `policies(plan_id)`, **both already indexed**. So this
migration adds indexes on its own new tables only.

Every new table carries `agency_id` (FK `agencies.id`, indexed) per the portal's multi-tenant
rule — a missing `agency_id` is a cross-tenant data leak.

`touch.external_id` unique is the idempotency key for Quo webhook retries — Quo will deliver
the same event twice.

### 7.3 Endpoints

Blueprint `pipeline_bp`, prefix `/pipeline`, registered with the existing three-line pattern in
`app/__init__.py`.

**Reads**

```
GET  /pipeline/                         Jinja shell, extends base.html, no customer data inline
GET  /pipeline/api/today                counters + each queue's count + its first 12 rows
GET  /pipeline/api/queue/<id>?cursor=   one queue, 25 rows at a time
GET  /pipeline/api/people?q=&chip=&cursor=   the browse list, own book, 25 at a time
GET  /pipeline/api/search?q=            agency-wide, max 6 own + 4 others (§8)
GET  /pipeline/api/customer/<id>        everything the person sheet needs, one call
GET  /pipeline/api/leads/dupe-check?name=&phone=
GET  /pipeline/api/rules                config + ratings + SAR rules (admin)
```

**Writes** — all return `{customer: <row json>, counters: {...}}`

```
POST /pipeline/api/customer/<id>/outcome   {action}  the outcome buttons
POST /pipeline/api/customer/<id>/touch     {level, channel, detail}
POST /pipeline/api/customer/<id>/waiting   {what, due}  | DELETE clears it
POST /pipeline/api/customer/<id>/scope     {method, products[]}
POST /pipeline/api/customer/<id>/sep       {sep_end, sep_reason}
POST /pipeline/api/customer/<id>/helper    {name, relationship, phone, may_discuss, linked_id}
POST /pipeline/api/customer/<id>/tier      {tier|null, note}
POST /pipeline/api/customer/<id>/note      {text}
POST /pipeline/api/leads                   {..., force:bool}  409 + matches if dupes and !force
POST /pipeline/api/rules/plan/<plan_id>    {rating}
POST /pipeline/api/rules/sar               {plan_id, counties[]}  | DELETE
POST /pipeline/api/rules/config            {sep_days, shp_*, ...}
```

**Response shape rule:** every mutation returns the full updated customer row in the same shape
the list endpoints use, plus the counters that changed. The JS replaces that one row's markup
and updates the badge numbers. No refetch, no reload.

### 7.4 Gates the server enforces

These are validated server-side, not just in the UI:

- Moving to `deciding` or `submitted` requires a `scope_form` row. **The 48-hour wait is gone as
  of Oct 1, 2026 — confirmed by Tim, 2026-09-18**, so same-day is fine; but the scope form must
  still exist before any plan-specific discussion, and must be written for in-person
  appointments. Return `409` with a `needs_scope` code; the client opens the scope modal and
  retries.
- Moving to `done` requires an outcome.
- Bulk email / text / RVM sends skip anyone without written consent on that channel, and the
  response reports how many were skipped and why.

⚠ **Measured 2026-09-18: `sms_consent_at` is set on 4 of 5,495 customers, and 30 have an email
address.** A bulk-send feature would therefore skip ~99.9% of the book. **RVM is out entirely**
(Tim: non-compliant without explicit permission). Build the *gate* — it is three lines and
prevents a compliance incident — but **do not build bulk sending in v1**; there is nobody to
send to. Letters remain the mass channel, and they are logged as `touch` rows at level `sent`.

---

## 8. Auth and agency scoping

- All routes require the existing Google OAuth session, restricted to
  `@foundersinsuranceagency.com`.
- **Default scope is the signed-in agent's own book.** Today, People, Follow-ups and all
  counters are `WHERE customer.agent_id = current_user.agent_id`.
- **Search is agency-wide** — this is a deliberate exception. A walk-in at a shared pharmacy
  office is often another agent's client, and the failure mode of a scoped search is an agent
  creating a duplicate record for someone who is already in the system. Results put the
  signed-in agent's own customers first but always reserve slots for other agents' (6 own + 4
  others), otherwise a common surname buries the very result the search exists to surface.
- **Opening another agent's customer is allowed and clearly labelled.** The sheet shows a
  banner: *"Dana's customer. You can look, and log what you did, but the follow-up stays on
  their list."* Logging a touch is permitted; changing stage, outcome or tier is not. Agent of
  record is a compliance fact, not a display preference.
- **Duplicate detection is agency-wide** regardless of scope, for the same reason.
- `?agent=` overrides scope for admins only. Rules/setup endpoints are admin-only.

---

## 9. Front end

### 9.1 Structure

```
templates/pipeline/index.html      extends base.html, renders the shell and an empty <main>
templates/pipeline/_person.html    optional server-side partial for the sheet
static/js/pipeline.js              one file, vanilla, no framework
static/css/pipeline.css            or fold into base.html tokens
```

Do not inline customer data into the template. The shell renders, then `pipeline.js` fetches
`/pipeline/api/today`. Everything after that is JSON + targeted repaint.

### 9.2 Design tokens

Use the tokens already in `base.html :root` and the existing light/dark handling
(`prefers-color-scheme` plus the `data-theme` toggle). The prototype ships its own token block
purely so it runs standalone — **delete it and map to the portal's tokens**:

| Prototype token | Portal |
|---|---|
| `--accent` | Founders Blue `#266EA5` |
| `--brand-green` | Founders Green `#65BB84` |
| everything else | existing portal tokens |

**Contrast note:** Founders Blue on white is 5.45:1 and is safe for body text and buttons.
Founders Green on white is 2.34:1 — **it fails for text**. Use it only as a fill (the progress
meter, success chips with dark text). Text that needs to read as "good" uses a darkened green
(`#166B37`, 6.3:1). Keep this distinction; it is the one place the brand palette and
accessibility disagree.

### 9.3 Non-negotiable UI rules

These came out of usability discussion with the agents who will actually use it:

- Body text 17px. Nothing below 13px anywhere.
- Every tap target ≥ 46px tall.
- Real `<button>`, `<a href>`, `<input>` + `<label>`. No click handlers on divs.
- Phone numbers are `tel:` links everywhere they appear, including on list rows. An agent
  should never have to open a record just to dial.
- The three tabs are the entire navigation. Settings and priority setup live behind a gear.
- Plain language only. Bad: "SOA", "disposition", "pipeline stage", "lead score". Good: "scope
  form", "what came of it", "where they stand", "call first".
- A single "Find someone" control reachable from every screen — that is the walk-in and the
  out-of-the-blue call, and it is the case agents hit constantly.

### 9.4 Performance

- Today ships counters + 12 rows per card. Never the whole book.
- Queue and People paginate at 25 with a cursor.
- Search debounces 200ms, requires 2 characters, returns max 10.
- Mutations repaint one row. Never re-render the list.

---

## 10. Quo integration (build after the UI works)

Quo's versioned webhook API (`2026-03-30`) is richer than the older UI suggests — it adds
`call.answered`, `call.missed`, `call.voicemail.completed`, `call.menu.selected` and the
`task.*` family, plus signature validation and delivery retry.

Event → effect:

| Event | Writes |
|---|---|
| `call.ringing` | screen pop with the customer's card (caller is in `participants.external`) |
| `call.menu.selected` | routes a main-line call to the right agent via `phoneMenuSelectionName` |
| `call.completed` | a `touch` row; `answered` + duration > 30s ⇒ `reached`, else `tried` |
| `call.missed` / `call.voicemail.completed` | a `touch` row plus a `catchup` queue item |
| `call.recording.completed` | persist the file for 10-year retention (do not rely on the URL) |
| `call.summary.completed` | a *suggested* outcome shown for one-tap confirmation, never auto-applied |
| `message.received` / `message.delivered` | `touch` rows, `reached` / `sent` |

Rules to hold to:

1. **Validate signatures. Treat the envelope `id` as an idempotency key** — retries are normal.
2. **Events arrive out of order.** Transcript and summary can land long after the call, in
   either order. Key on `callId` and update.
3. **`lookupStatus: "unavailable"` means unknown, not "no match"** — never create a contact
   from it.
4. **Never auto-create a lead from an unknown inbound number.** Family phones, spouses' cells
   and pharmacy phones make the false-positive rate high, and duplicates are worse than misses.
   Park unmatched calls in a list a human sorts, with options: link to an existing person, add
   as that person's authorized contact, create a new lead, or suppress permanently.
5. **`contact.deleted` never deletes a portal record** — archive the link only.
6. Rate limit is 10 req/sec per key.
7. **Notifications are in-app and quiet.** No SMS — agents are with customers and checking a
   phone is rude. Suppress prompts during a live call and during a booked appointment window;
   surface them afterward as a batch ("3 calls since 1pm need a note").

**Calendar:** never write to an agent's personal iCloud calendar. Publish a separate read-only
per-agent ICS feed they subscribe to once. Keep event titles bare ("Call Barbara K.") — the
feed syncs through iCloud and must not carry health or plan details.

---

## 11. Out of scope for v1

Deliberately excluded, with reasons:

- **The kanban board and the wide data table.** They exist (see `aep-pipeline-v4.html`) and are
  genuinely useful to Timbo and to a manager, but they are the wrong default for an agent who
  does not want to feel like they are using a CRM. Ship the simple version as the default and
  put these behind an "advanced view" setting later.
- **Agency-wide analytics.** Agents see their own numbers; nobody browses other agents' books
  except an admin.
- **The full person-to-person relationship model.** v1 has a single `authorized_contact` per
  customer with an optional link. Full household modelling can wait.
- **Merge tooling for duplicates.** v1 prevents them at creation; merging existing ones is a
  separate job.
- **Commissions.** Already a separate module.

---

## 12. Acceptance checks

Verify these against the prototype's behaviour:

1. Today shows only non-empty queues, urgent ones first, and nobody appears in two queues.
2. The header reads "N of M settled for 2027" with a working pace figure and a clickable
   "not contacted at all" count.
3. One-at-a-time mode advances on every outcome, has a working Skip, and ends with a summary.
4. Marking a plan "Major" in setup moves exactly the customers on that plan to Tier 1 and the
   toast reports the count.
5. Clearing a lead's `sep_end` drops them from Tier 1 to Tier 2; changing `sep_days` from 30 to
   60 raises the Tier 1 count.
6. The person sheet shows **On now** and **For 2027** as two separate labelled facts, and
   someone who enrolled in a new plan shows the old plan under "On now" and the new one under
   "For 2027".
7. Search finds another agent's customer, labels it with their name, and opening it shows the
   ownership banner with stage controls disabled.
8. Adding a lead whose phone matches an existing customer shows the duplicate warning with the
   reason ("Same phone number"), and the override path preserves what was already typed.
9. Moving anyone to `deciding` or `submitted` without a scope form on file is refused by the
   API, not just hidden in the UI.
10. Nothing on any screen uses a word an agent would have to be taught.

---

## 13. Suggested build order

1. Migration `046` + models + the `current_plan`, `customer_priority` and `customer_queue` views.
   Backfill `pipeline_state` for every non-deceased customer as `stage='contact'`,
   `track='renewal'`. **`046` is correct and confirmed** — heads `044` (users.npn) and `045`
   (agencies.npn) shipped 2026-09-18.
2. Read endpoints + the Jinja shell + the Today tab. Verify counts against the real book.
3. The person sheet and its mutations.
4. One-at-a-time mode.
5. People and Follow-ups tabs.
6. Setup screen and the rules endpoints (admin-only).
7. Quo webhooks — start in **listen-only mode** for a week: log every call and message, match
   against the book, and count how many inbound calls match a known number, how many hit the
   main line vs personal numbers, and how many unmatched callers leave a voicemail. That data
   decides how much unmatched-call tooling is actually worth building.

---

## 14. Open questions for Timbo

**Answered 2026-09-18:**

- ✅ **The 48-hour SOA wait is gone as of Oct 1, 2026** — confirmed by Tim. §7.4 records it as
  confirmed rather than assumed.
- ✅ **Q5 — flag letters that no longer match.** Yes, in scope, not an open question. Brian's
  letter set is already segmented per plan with a SAR variant, so a rule added after a mail drop
  means those people hold the wrong letter and nobody would otherwise know. Implemented as a
  small reconciliation list (§6.1 does **not** gain a queue for it — it is an admin report, since
  the fix is a new mailing, not an agent action).

**Still open:**

1. Confirm the real 2027 plan data and which plans get "Major" (expected Sept 28). Everything in
   the prototype except **Humana 335-002 ending in Cabarrus** is invented. 📌 Partial data now
   exists: `docs/Medicare 2027 Plan Info/…MASTER.csv` has 2027 rows for 95 plans, but **4,030 of
   4,072 covered policies are `Source=FL` (first look, untrusted)** — usable to *speed up* rating,
   never to set one automatically.
2. Confirm the NC State Health Plan **Medicare-retiree** window specifically. The prototype uses
   Oct 12–30, 2026. This drives a Tier 1 rule and a countdown shown to agents, so a wrong date is
   visible and damaging.
3. Stall thresholds: 5 / 3 / 10 days — keep or tune? (`pipeline_config`, changeable later.)
4. Should a state retiree who misses the opt-out deadline stay Tier 1 or drop? Prototype keeps
   them Tier 1.
5. **Who gets `major` ratings, and when?** Rule 3 is inert until ratings are entered; if nothing
   is rated by Oct 15 every renewal is Tier 2 and Tier 1 contains only SAR + SHP customers. That
   may be the right soft launch, but it should be a decision rather than an accident.
