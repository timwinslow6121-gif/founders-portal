# Customer ⇄ Plan Domain Model — Founders Portal

**Date:** 2026-07-21
**Status:** Domain model (foundation) — NOT an implementation spec. Captures how
Medicare + auxiliary coverage actually works in Founders' book, so every feature
(merge, dedup, plan-history, reconciliation, reporting) builds on one shared,
correct understanding. Refine this on paper first; carve implementation specs
from it.
**Source:** brainstorm with Tim, 2026-07-21 (15+ years / 5,000+ NC customers of
domain knowledge). Extends the "jelly-bean / buckets-first" model already used
for the plan database ([[commission-bob-crosswalk-diagnosis]],
`docs/superpowers/specs/2026-07-06-contract-code-plan-database-design.md`) and
the coverage-slot model ([[policy-coverage-slot-model]]).

---

## 0. The one-line model

**The Customer is the bucket (the person). The Customer owns the MBI. Every plan
the person holds — across all lanes — ties back to that one Customer.** The
system's job is to keep exactly one Customer record per real person, hold the
person's correct current MBI, and attach every real policy (including ones no
enrollment platform can see) underneath, honoring which plans can coexist and
which supersede.

---

## 1. The MBI — the person's key, but MUTABLE

The MBI is "the SSN of Medicare": the only authoritative way to distinguish two
people with the same name. But unlike an SSN, **it changes** — CMS reissues an
MBI on a data breach or a beneficiary's personal request. The system must never
treat the MBI as immutable identity.

### 1.1 MBI format (authoritative, from CMS)
11 characters, no dashes, uppercase. Positional pattern:

| Pos | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
|-----|---|---|---|---|---|---|---|---|---|----|----|
| Type| C | A | AN| N | A | AN| N | A | A | N  | N  |

- `C` = digit **1–9**
- `N` = digit **0–9**
- `A` = a letter **A–Z excluding S, L, O, I, B, Z**
- `AN` = a letter (as above) **or** a digit 0–9

Regex (uppercased input, letter class `[ACDEFGHJKMNPQRTUVWXY]`):
```
^[1-9][ACDEFGHJKMNPQRTUVWXY][0-9ACDEFGHJKMNPQRTUVWXY][0-9][ACDEFGHJKMNPQRTUVWXY][0-9ACDEFGHJKMNPQRTUVWXY][0-9][ACDEFGHJKMNPQRTUVWXY][ACDEFGHJKMNPQRTUVWXY][0-9][0-9]$
```

**Why this matters:** a value that fails this test is **NOT an MBI** — it's a
carrier policy number that landed in the MBI field. Grounding case: Jana Benson's
DVH policy `45039665600` (11 digits — position 2 must be a letter, fails) sat in
the `customer.mbi` column and made the system think she was a second person. The
validator is the guardrail: **only a value passing this format may be trusted /
stored as an MBI; anything else is a policy number and belongs at the policy
level.**

### 1.2 The current MBI
A person may have several MBIs across their history. The **current** MBI = the
one on the person's **current primary-medical plan** (latest effective date, see
§3). That is what `customer.mbi` should hold.

### 1.3 MBI change handling (reissue)
When a new plan/policy arrives carrying an MBI that matches **no** existing
customer, but **name + DOB (+ address)** match an existing customer who has a
**different** MBI → probable reissue.

- **Never auto-adopt.** Every such case goes to a **human-confirm queue** (like
  the duplicates page). Breach events can produce volume — a human confirms.
- On confirm: the customer adopts the new MBI, and the old MBI is retained in an
  **MBI history / alias** so that older files (BOB, commission) carrying the old
  MBI still resolve to the same person.
- The confirm-queue is the *gate*; the MBI history is the *memory*. Both are
  needed: the queue makes the decision safe, the history makes it durable.

Match strength for the queue: **name + DOB + address** (never name-alone, never
DOB-alone — both gave false positives historically; full name+DOB is strong,
address is the tiebreaker). See [[session-handoff-2026-07-13-carriers-page-plantype]].

---

## 2. Plan linking — how a policy finds its Customer

On import (BOB / commission) or manual entry, a policy ties to a Customer by:

1. **Valid MBI present** (passes §1.1) → link by MBI (incl. MBI history/alias).
2. **No MBI** (or the MBI-field value fails §1.1 = it's a policy number) → link
   by **name + DOB** (+ address tiebreak). Same exact name AND same exact DOB is
   a strong, rare match.
3. **No confident match** → **manual-link queue.** NEVER invent an MBI'd stub
   customer (that is the exact mistake that created the Benson/Connelly-class
   mess and the `uhc::0::` synthetic stubs).

Ancillary plans (DVH/HI/Life) are often built for Medicare customers and **do**
carry the MBI — so use it when a valid one is present; fall back to name+DOB only
when there genuinely is none. A policy number that isn't an MBI is stored at the
**policy level** (`member_id` / policy number), never promoted to the customer's
MBI.

---

## 3. Lanes & coexistence — the heart of the model

Every plan belongs to exactly one **lane**. The lane decides two things: whether
a new plan **supersedes** an existing one (auto-term), or **coexists** with it.

| Lane | Plan types | Coexistence within the person | Auto-term on a newer plan? |
|------|-----------|-------------------------------|----------------------------|
| **Primary-medical** | MAPD, MA-only, **PDP** | Exactly **ONE** active at a time | **YES** — but only under the §3.1 rule |
| **Medigap** | Medigap / MS | **Free coexist**, multiples allowed | **NO** — flag redundancy only |
| **External-primary** | SHP / employer / TRICARE / VA / CHAMPVA | Own lane; explains an empty Medicare-medical lane | **NO** |
| **Ancillary** | IDVH / DVH, Hospital Indemnity, Life | **Free coexist**, multiples allowed | **NO** |

### 3.1 Primary-medical supersession — the ONLY auto-term rule
A person can hold exactly **one** active primary-medical plan. PDP and MAPD are
mutually exclusive **with each other** (enrolling in a PDP disenrolls an MAPD and
vice-versa — the one enrollment action that truly auto-cancels), which is why PDP
sits in this lane. Auto-term fires when **ALL** hold:

- **same lane** (both primary-medical), AND
- **different contract code** (a genuinely different plan), AND
- **newer effective date** on the incoming plan.

→ the older plan is termed (superseded). This covers every Part C transition:
**PDP↔MAPD, MAPD↔MAPD, MAPD↔MA-only, MA-only↔MA-only**, including carrier
switches (grounding: Barbara Overcash — old Aetna PLUS *PDP*, crosswalked to
CHOICE end-of-2025, superseded by her new UHC MAPD eff 2026).

**Renewal is NOT supersession.** Same contract code across plan-years
(Gold Plus 2025 → Gold Plus 2026) = ONE continuing enrollment → roll forward,
do **not** term. Only a **different** contract code triggers auto-term.

Mid-year switches (Plan A eff Jan 1 → Plan B eff Mar 1, different codes) are just
supersession with an intra-year date — same rule, term A at B's start. A
chargeback on A is a separate commission fact and does not change that B is the
active plan. (Much of this already exists — the chronological BOB dedup +
AOR-reconciliation `is_current_enrollment` logic; this model names the lane the
existing supersession must stay inside.)

### 3.2 Medigap — should-not-but-does coexist
A Medigap logically should not coexist with an active Part C plan — but Medicare
does **not** auto-cancel it. Happens constantly: a customer with a Medigap
enrolls in an MAPD and forgets to cancel the Medigap, keeps **paying** for it,
and it pays nothing. The reverse is also true (enrolling in Medigap does not
cancel the MAPD — only a PDP can cancel an MAPD).

→ The system **must NOT auto-term a Medigap** (that is real money the customer is
paying — a term is a human/business decision, the customer must call to cancel).
At most, **flag** "active Medigap alongside active Part C" and "2 active
Medigaps" as *you-may-be-overpaying* signals. **Medigap is free-coexist with
multiples allowed**, same as ancillary — it never auto-cancels.

### 3.3 Ancillary — always coexist
IDVH/DVH, Hospital Indemnity, and Life coexist with **anything** and with **each
other**. A person can hold multiple HI / DVH / Life policies with no impact on
any other plan. Never auto-term. (Grounding: Jana Benson holds Medigap **and**
DVH — two legitimate products; the correct state is ONE customer record with
BOTH policies active underneath.)

### 3.4 The MA-only + PDP edge (out of scope)
For ~all cases a customer cannot hold both an MA-only and a PDP. The only
exceptions are PFFS or Medicare MSA plans — in 5,000+ NC customers over 15 years
Founders has never seen it. **Do not build for it.**

---

## 4. External / non-Medicare primary coverage

A meaningful share of customers have their **primary medical outside Medicare**:
State Health Plan retirees (teachers, EMS, judges), military (VA / TRICARE /
CHAMPVA), or employer-sponsored. For these, Founders often does only the
dental / hospital-indemnity, or nothing on the medical side. The
"one active primary-medical plan" expectation must not treat their empty
Medicare-medical lane as a gap.

Represented **two ways (both needed — they are independent signals):**

- **Customer-level flag** (durable attribute): "this person is
  eligible-for / affiliated-with SHP / military / employer coverage." For
  **reporting + identification.** Stays true **even when the customer chose a
  Medicare plan instead** — e.g. a retired state teacher who took a Humana Gold
  Plus MAPD instead of the SHP rebate is still flagged SHP. This is about *who
  they are*, not what they're currently enrolled in. (Also drives the "customers
  who switch Part C yearly for the best rebate" reporting Tim needs.)
- **Optional plan entry** in the External-primary lane: the actual external
  coverage as a line-item, entered manually, when they are actually using it as
  their primary. Explains an empty Medicare-medical lane; sits alongside the
  DVH/HI Founders did for them; never auto-terms and is never auto-termed.

A person can have the flag **without** an external-plan entry (the rebate-MAPD
retiree). The flag and the plan entry are decoupled on purpose.

This is the backlog's "Secondary/retirement coverage flag on customers" item,
now placed inside the model.

---

## 5. Manual plan entry — first-class

Some plans are invisible to every enrollment / BOB / commission feed and must be
enterable by hand, tied to the Customer:

- **Non-commissionable / off-platform enrollments** — e.g. Tim submitted 2
  Wellcare Value Script PDP applications via Medicare.gov today; Founders isn't
  contracted with Wellcare and gets no commission, so there is no BOB row and no
  commission row — nothing connects that enrollment to Founders unless it can be
  entered manually. (This is the backlog's "track non-commissionable PDP
  enrollments" item.)
- **External-primary coverage** (§4) when specifics are known.

Manual entry is a **first-class** path, not a second-class citizen: a
manually-entered plan is a real plan in the customer's plan list, in its correct
lane, subject to the same coexistence rules (a manual PDP in the primary-medical
lane still supersedes an older MAPD, etc.). Ties to the customer by MBI if valid
else name+DOB.

---

## 6. Merge behavior (the original trigger, now corrected)

Two records that are the **same person** (reissued MBI, carrier switch, OR
coexistence split like Benson) collapse into **one** Customer:

1. **One keeper Customer**, all real policies from both records re-homed under it.
2. **Correct current MBI** = the MBI on the person's current primary-medical plan
   (latest eff), validated by §1.1. A non-MBI value (Benson's DVH policy number)
   is **never** taken as the MBI — it stays a policy number at the policy level.
3. **Auto-term ONLY same-lane superseded plans** (§3.1) — a newer primary-medical
   plan terms the older one it replaces.
4. **Keep coexisting products active** — Medigap, DVH, HI, Life all move over and
   stay active; never auto-termed by the merge.

Validation of the two live cases (only 2 same-name+same-DOB+different-MBI groups
exist in the whole book, 2026-07-21):
- **Barbara Overcash** (Aetna PLUS PDP `2WA7KC0TM50` + UHC MAPD `1X88VQ0CP30`,
  same DOB, different carriers) → ONE record; current MBI = UHC (latest eff
  2026); old Aetna PDP superseded → termed. **DO merge.** (Carrier-switch is NOT
  a reason to exclude — the MBI follows the person, not the carrier.)
- **Jana Benson** (UHC Medigap `3DJ9F94VV42` + UHC DVH `45039665600`, same DOB) →
  ONE record (keeper 6247); MBI = the Medigap's `3DJ9F94VV42` (valid); DVH moves
  under it and **stays active** (coexists); `45039665600` recognized as a policy
  number, never treated as an MBI. **DO merge (consolidate), term nothing.**

### 6.1 Correction to the shipped feature
The narrow "reissued-MBI merge override" shipped 2026-07-21 (commits
a53785f..395ea50, live) **terms "the loser's stale-MBI policy"** — which is WRONG
for the coexistence case (it would term Benson's DVH). Under this model, the
merge auto-terms **only same-lane superseded plans**, not "the loser's policy."
The shipped feature is superseded-in-place by this model; the corrected merge is
the first candidate build (§7). Until then, do **not** use the shipped override
on a coexistence pair (Benson).

---

## 7. What's already built vs new

**Already built (fine-tune, don't reinvent):**
- Supersession / chronological dedup / AOR `is_current_enrollment` (2026-06-25,
  Robbie Belk) — the term-older-when-newer engine.
- Plan buckets / contract-code plan DB (Layer 1, mig 035) — the jelly-bean plans.
- `merge_customers` engine (app/customers.py) — reattach/fill/audit, Postgres-safe.
- `coverage_category()` in `app/plan_sections.py` — a type→category seed the lane
  classifier can extend.
- No-MBI dedup clustering + DOB-aware split (app/dedup.py).

**New (the model's missing pieces):**
1. **Lane classifier** — plan_type → {primary_medical, medigap, external, ancillary};
   the brain that gates supersession vs coexistence. (Extends `coverage_category`.)
2. **MBI validator** (§1.1) — used everywhere a value is about to be trusted/stored
   as an MBI.
3. **Corrected merge** (§6) — consolidate person, keep coexisting, term only
   same-lane superseded; fixes Benson/Overcash.
4. **MBI-change confirm queue + MBI history/alias** (§1.3).
5. **First-class manual plan entry** (§5) — Wellcare PDP, external coverage.
6. **External-coverage flag** (§4) — customer-level, for reporting/ID.
7. **Plan display = a simple list/table** of the customer's plans (all lanes),
   rather than rigid labeled slots (Tim's lean). "Medigap or MAPD" is the
   conceptual 'main', but the table just lists them.

---

## 8. Open questions (for the next pass)
- How is a plan's **lane** stored/derived? (from `plan_type` via the classifier,
  or a real column on Plan?) Contract-code plans already carry type.
- Exact **external-coverage taxonomy** (the flag's value set: SHP, TRICARE, VA,
  CHAMPVA, FEHB/postal, employer, other) — the backlog secondary-coverage item
  has a starter list.
- **Life insurance** specifics (term vs whole, does it even belong in the plan
  table or a separate product list?).
- The **manual-entry UI** (ties to the [[add-plan-ui-design]] type-driven form).
- Which slice ships **first** — the strong candidate is the **lane classifier +
  MBI validator + corrected merge** (fixes the two live wrong cases and lays the
  spine), with the rest as follow-on specs.
