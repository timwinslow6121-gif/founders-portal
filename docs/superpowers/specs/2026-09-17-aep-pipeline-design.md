# AEP pipeline + interaction timeline — design

**Status:** approved, not yet built
**Date:** 2026-09-17
**Author:** Tim + Claude
**Demo deadline:** Sept 28 (Brian, then agency training Sept 28-29)
**Real deadline:** Oct 15 — AEP opens and agents must be able to run the season on this

## The problem

Agents have no system of record for who they have talked to. Today:

- `customer_notes` = **0 rows**. `customer_contacts` = **0 rows**.
- 380 Quo calls sit in `unmatched_calls`, all `resolved=False`, none linked to a customer.
- Every touch — call, text, letter, appointment, decision — lives in an agent's head,
  a paper binder, or Acuity.

During AEP each agent runs 10+ in-person appointments, 10+ calls and constant texts,
with the next appointment starting seconds after the last. Conversations are forgotten
before they can be written down.

## What the portal already has

This is not a greenfield build. Verified on production 2026-09-17:

| Asset | State |
|---|---|
| `CustomerNote` | right shape already — `note_type`, `contact_method`, `duration_minutes`, `source_url`, plus `quo_call_id`, `calendly_event_id`, `twilio_msg_sid`, `retell_call_id`. Never written to. |
| `Customer.deal_stage` | exists, defaults `"Active"` |
| `Customer.deceased_date` | shipped 2026-09-16 — deceased members are already suppressible |
| `Customer.sms_consent_at` | exists |
| `Customer.stub` / `.source` | exists — leads can be created without an MBI |
| `plan_service_areas` | **5,019 county rows across 120 plans** — SAR detection is answerable from data |
| Quo webhook | receives correctly; the customer/agent resolution is broken |
| Calendly webhook | already wired |

## Data reality — what constrains scope

Verified counts, production, 2026-09-17:

| | count | of 5,495 |
|---|---:|---|
| customers with a phone | 5,067 | 92% |
| with county | 5,111 | 93% |
| with a primary agent | 5,485 | 99.8% |
| active policies linked to a plan | 5,440 / 5,473 | 99.4% |
| **with an email address** | **30** | **0.5%** |
| **with a pharmacy** | **88** | **1.6%** |
| **with medicaid_level** | **1** | **0.02%** |
| **plans with `year=2027`** | **0** | — |

The last four are why several attractive features are out of scope. A demo that shows
an empty panel costs more trust than a demo with fewer panels.

## Decisions

### Stages

Five, matching the real path Tim described:

| Stage | Meaning |
|---|---|
| `needs_contact` | letter sent or not, no successful contact yet |
| `scheduled` | appointment booked |
| `deciding` | met, no decision yet |
| `submitted` | application in, awaiting carrier |
| `done` | enrolled · kept current plan · closed |

`done` carries an **outcome**: `enrolled`, `kept`, `lost`, `unreachable`, `deceased`.
`kept` and `enrolled` are both wins and are counted separately — a renewal is not a sale
but it is a retained member.

### Triage is plan-driven, with per-customer overrides

Tier 1 is computed, not guessed:

1. **SAR** — the customer's plan is not offered in their county for 2027. Derived from
   an explicit rule (`plan × counties`), not inferred from benefit data.
2. **NC State Health Plan retiree** who has not confirmed their opt-out call. Their
   window is **Oct 12–30**, closing five weeks before Medicare AEP ends, and inaction
   auto-moves them off the 70/30 plan.

Tier 2/3 come from a **per-plan rating entered by a human** (Tim or AJ) after reading
the ANOC. Unrated plans count as Tier 2 so nobody is silently deprioritised.

⚠ **The portal cannot compute ANOC severity.** There are zero 2027 plan rows, and 2027
first-look benefit data is not trustworthy (BCBS revises between first look and CMS
approval — established August 2026). Change descriptions are typed by a human.

Any customer's tier can be overridden by hand, with a required note, and shows an
asterisk wherever it appears.

### Consent: SMS only

RVM blasts are **out entirely** (Tim, 2026-09-17) — non-compliant without explicit
permission, and operationally harmful: they generate a callback spike the agency cannot
staff, from members who could not hear the message and are returning a missed call.

Email is out because 30 of 5,495 customers have an address.

So consent reduces to the `sms_consent_at` field that already exists.

### Interactions are source-agnostic

One table. `source` is a field (`manual`, `quo`, `calendly`, `letter`, `voice_note`),
so adding Voxo or Acuity later is a new writer, not a redesign.

### Capture must be faster than not capturing

The binding constraint is not features, it is that an agent will not do this 10 times a
day during their worst week unless it is nearly free. Therefore:

- capture lives **on the customer profile**, always visible, no modal, no navigation
- outcome buttons match the **real** first-touch results, including the three distinct
  failure modes: voicemail left · inbox full, texted instead · **landline only, cannot
  text**
- it must work on a phone — an agent standing up from a table is not opening a laptop
- the next day's work queue is built from yesterday's captures, so skipping one costs
  the agent something

## Design

### 1. Data model (migration 044)

```python
class CustomerInteraction(db.Model):
    id             = Integer, pk
    agency_id      = FK agencies.id, indexed, not null
    customer_id    = FK customers.id, indexed, not null, ondelete CASCADE
    agent_id       = FK users.id, indexed, nullable   # nullable: see the Quo fix
    occurred_at    = DateTime, indexed, not null
    channel        = String(24)   # call | sms | letter | appointment | note | voice_note | enrollment
    direction      = String(12)   # inbound | outbound | n/a
    outcome        = String(32)   # see OUTCOMES below
    body           = Text         # what was said / next step
    source         = String(16)   # manual | quo | calendly | letter_batch | voice_note
    source_ref     = String(128), indexed   # provider id; unique per source
    duration_sec   = Integer
    media_url      = String(512)  # voice note / recording
    created_by_id  = FK users.id
    created_at     = DateTime
    __table_args__ = UniqueConstraint(source, source_ref)   # idempotent webhooks
```

`OUTCOMES` (the real ones, from Tim's description):
`no_answer_vm` · `no_answer_vm_full_texted` · `no_answer_landline_only` ·
`reached_happy` · `reached_wants_review` · `appointment_booked` · `no_show` ·
`met_undecided` · `enrolled` · `kept_plan` · `closed_lost`

**Why a new table rather than extending `CustomerNote`:** `CustomerNote` is
agent-authored commentary with a `note_text` and a `resolved` flag. Interactions are
events with an outcome and a source. Overloading one table would make both harder to
query. `CustomerNote` stays for freeform notes and its existing webhook id columns are
left alone.

Also on `Customer` (migration 044):

```python
    pipeline_stage    = String(24), indexed, default 'needs_contact'
    pipeline_outcome  = String(24), nullable
    stage_since       = Date          # drives every "stalled N days" calculation
    tier_override     = Integer, nullable
    tier_override_note = Text
    is_state_retiree  = Boolean, default False, indexed
    state_optout_confirmed_at = DateTime, nullable
    letter_variant    = String(32), nullable
    letter_sent_on    = Date, nullable
```

`Customer.deal_stage` is left untouched — it is an existing lifecycle field with
different semantics, and repurposing it would silently change existing behaviour.

New `PlanAepRating` (migration 044):

```python
    plan_id        = FK plans.id, unique per (plan_id, year)
    year           = Integer          # 2027
    tier           = Integer, nullable   # NULL = unrated = treated as Tier 2
    change_note    = Text             # human-typed ANOC summary
    letter_variant = String(32)       # which member letter this plan gets
    rated_by_id    = FK users.id
    rated_at       = DateTime
```

New `PlanServiceReduction` (migration 044): `(plan_id, county, year)` — the SAR rule.
Seeded by hand from carrier notices; **not** inferred from benefit data.

### 2. Triage resolution

One accessor, the single place a tier is decided:

```python
def tier_for(customer) -> (tier:int, reasons:list[Reason])
```

Order: manual override → SAR → unconfirmed state retiree → plan rating → unrated (2).
Returns reasons so the UI can explain itself, which is what makes agents trust it.

### 3. The Quo fix

Three defects, all verified:

1. **`quo_user_id` is set on 1 of 11 agents.** The Quo API returns 5 users; seed them.
   Brian, Mike, Betty, Anjana and Alex have **no Quo account at all** — Brian is on a
   Cannon-owned Voxo line.
2. **`if customer and agent_id`** discards a matched customer when the agent does not
   resolve. Relax to: log whenever the *customer* resolves; attach the agent when known.
3. **`to_number` is never stored** (null on all 380 rows). The main line
   **704-500-2128 is going on billboards** — inbound there is a *prospect*, and must be
   identifiable rather than buried in `unmatched_calls`.

Also add `User.quo_phone_number` and match on it as a fallback: Chris Foster's Quo
account was created 2026-09-16, so an opaque ID is not a durable sole key.

### 4. Views

**Today** — "N things need you", built from the stage + date math. Sections:
appointments today · outcome not logged · call first (Tier 1, never tried) ·
undecided 3+ days · state opt-outs (while the window is open) · no reply after 2 tries.

**Board** — the five stages, drag to move. Stalled cards first, then by tier.

**Table** — the existing customer-list filters plus stage/tier, bulk letter logging.

**Agency** — per-agent book composition, reached %, stalled count. This is the Brian view.

**Triage rules** — SAR rules, plan ratings, state-retiree window, manual overrides.

### 5. Letters en masse

Select by plan (optionally × county), record `letter_variant` + `letter_sent_on` on
every matched customer, and write one `letter` interaction each. This is what gives the
board its starting state: everyone who got a letter is awaiting a reaction.

Matches Brian's existing letter set, which is already segmented per plan with a
per-county SAR variant and a cross-plan state-retiree variant.

## Out of scope, with reasons

| | why |
|---|---|
| **RVM blasts** | out entirely — compliance and callback-spike (Tim) |
| **Email send / email consent** | 30 of 5,495 customers have an address |
| **Acuity sync** | 11+ accounts, one per location; Tim is consolidating to one agency account. Revisit after. |
| **Voxo (Brian's line)** | blocked on Cannon IT (Mike Cooper). Slots in as a new `source`. |
| **Appointment recording** | consent, storage and retention need their own decision. Voice notes cover the actual need. |
| **Group meetings / webinar capacity** | Betty's binder and the QR signup already work; replacing them mid-AEP is a liability |
| **Store / location views** | 88 of 5,495 customers have a pharmacy |
| **D-SNP / LIS segmentation** | `medicaid_level` set on 1 customer |
| **Automatic ANOC severity** | zero 2027 plan rows; first-look data is unreliable |
| **Carrier enrollment confirmation feeds** | no API; manual, or later via confirmation-email parsing |

## Build order

Ordered so that stopping early leaves a coherent product, not a half-wired one.

**Tier 1 — the spine**
1. Migration 044 + models
2. Interaction timeline + fast capture on the profile
3. Stage board + move actions
4. Today view
5. Triage rules (SAR, plan ratings, override) + `tier_for`

**Tier 2 — the differentiators**
6. Quo linkage fixed + backfill the 380 unmatched where the number matches
7. State-retiree flag + Oct 30 clock
8. Table + bulk letter logging
9. Agency view

**Tier 3 — stretch**
10. SOA capture
11. Voice notes
12. After-the-sale milestones

## Dependencies on Tim, not on code

- **ANOC change notes + tier ratings for the top ~20 plans.** The portal cannot compute
  these. Without them the triage page is empty at demo time.
  Tim has most 2027 carrier **first-look** material (Google Drive). That makes typing
  the notes *faster* — comparing real numbers beats reading ANOCs cover to cover — but
  it does **not** make severity computable. First-look data is explicitly untrusted in
  this codebase: BCBS revised benefits between first look and CMS approval in 2026 and
  the agency was burned by it, which is why `plan_provenance.py` treats first-look as
  `unverified` and lets CMS overwrite it. A tier is a judgment about whether a customer
  should come in; that judgment stays human.
- **SAR list** — which plans are leaving which counties (Humana 335 / Cabarrus is known).
- **State-retiree list** — `is_state_retiree` starts empty; Brian's letter set implies
  the list exists somewhere.
- **Confirm the SOA timing rule.** The mockup asserts "since Oct 1 2026 there is no
  48-hour wait". That is a compliance claim and must be verified with AJ, not shipped on
  a mockup's word.

## Testing

- `tier_for` returns each tier for the right reason; override wins; unrated → 2
- SAR only fires for a customer whose county is in the rule
- State retiree is Tier 1 until `state_optout_confirmed_at` is set, then takes the plan rating
- Stage transitions record an interaction and update `stage_since`
- A deceased customer never appears in a work queue (`is_contactable`)
- Quo webhook: a matched customer logs an interaction **even when the agent is unknown**
- Quo webhook is idempotent on `(source, source_ref)`
- Letter batch writes exactly one interaction per customer and is re-runnable
- Money is untouched by all of it
