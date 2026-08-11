# Founders Agent Portal

### Scope, current status, and proposal

**Prepared for:** Brian Freeman
**From:** Tim Winslow
**Date:** August 2026

---

> **⚠ DRAFT — review before sending.** Items marked `[BRACKETED]` need Tim's
> input. Notes at the end. Everything else is verified from the live system and is
> checkable.

---

## 1. Where the agency's book and commissions live now

Five months ago, the agency's book of business and commission records lived across
carrier spreadsheets, downloaded statements, manual reconciliation, and
institutional knowledge held in people's heads.

Today they live in one system. As of this week it holds:

| | |
|---|---|
| Active policies | **5,608** |
| Customers | **5,458** |
| Commission transactions | **14,687** |
| Commission dollars tracked | **$273,660** |
| Carrier statements processed | **29** |
| Agents using it daily | **10** |

It runs the whole path from carrier file to agent paycheck: book-of-business
imports from 7 carriers, commission statement processing for 6, the per-agent
commission recap, customer and policy master records, carrier and plan reference
data, and the phone-system integration — on a secured production server with
restricted sign-in, an audit trail, and nightly encrypted off-site backups.

**This is not a reporting tool. It is part of the agency's financial controls.** It
helps determine who gets paid what.

---

## 2. What it has already caught and prevented

The value isn't the screens. It's that the system catches money problems that no
one could see by hand, and removes work people were doing manually every month.
These are specific and dated — AJ can confirm any of them.

**Commission errors that balanced perfectly and were therefore invisible.**
United Healthcare pays two different Part D commissions and sometimes bundles the
agency's override into the same figure. The portal was reading those bundled rows
as a single agent commission. Statement totals still tied to the penny, so nothing
looked wrong — it had been mis-handled **since May**. Found and fixed in August,
with a guard added so any unrecognized Part D amount now stops for review instead
of being paid silently.

**Recurring manual work, eliminated.** AJ had been hand-splitting those same rows
every month — **26 May, 4 June, 3 July**. That is now automatic.

**Repeated overpayments, and the cause fixed.** Two incidents (**38 rows on 1
Aug**, **16 rows on 3 Aug**) traced to one root cause: the commission edit screen
didn't display the agent's contract rate, so a correct rate was being overwritten.
The screen now shows the rate and refuses an off-contract save without explicit
confirmation.

**Rolled-up business made visible.** Commissions written by retired agents roll to
you. The system recorded who was *paid* but discarded whose book it came from —
for one month of UHC alone that was **121 transactions, $3,173 of business,
$1,587 to you**, previously invisible.

**Traceability restored.** This month I found and fixed a defect that was breaking
the link between commission payments and the customers they belong to — **509
payments** reconnected, with a safety check that refuses any link whose name
doesn't match. That check caught a genuine mis-match and left it for a human
rather than guessing.

**The book itself made trustworthy.** Carrier-by-carrier reconciliation against
the authoritative books of business, duplicate customer records collapsed, and
plan data corrected against CMS source files — including finding **82 plans
labeled as having no drug coverage when they do.**

Every one of these was invisible before, because there was no system to see them
in.

---

## 3. What replacing this would involve

If Founders commissioned this from an outside firm tomorrow, they would be quoting
against: 33 application modules; 19 carrier-specific import and commission
workflows; 42 database migrations; 785 automated tests; sign-in and permissions;
production infrastructure; backups, security and auditing; commission accounting
logic; customer and policy master records; phone integration; reconciliation and
exception handling — plus five months of iterative work against real production
data.

Reproducing that would reasonably represent **800–1,200 hours** of development,
integration, testing, deployment and implementation.

Published 2026 U.S. rates put small development firms around **$90–$160/hour** and
mid-market firms higher.¹ At a conservative blended rate of **$125/hour**, the
estimated external replacement cost is:

> ## Approximately $100,000–$150,000

**I am not proposing that Founders pay that amount.** It is context for what has
been built and what replacing it would involve.

It also understates the real difficulty. An outside developer can write a file
parser. What they cannot do without extracting it from you and AJ first is know
how UHC commissions actually work, what an override is, why a particular amount
looks suspicious, how retired-agent business rolls up, when two customer records
are really the same person, or what the agency needs during AEP. That knowledge is
most of what makes this system correct — and it is already in it.

---

## 4. Proposal

Two things to compensate: the system already delivered, and the work required to
keep it running.

> ### Development fee: $35,000
> for the production system delivered through August 2026
>
> ### Maintenance and development: $2,000/month
> beginning [DATE], cancellable with 90 days' notice

At $35,000, the internal development fee is roughly a quarter of the estimated
external replacement cost. The monthly figure is **$24,000/year** against outside
development retainers that commonly start at $5,000–$10,000/month.²

**If a single payment is difficult, an alternative:**

| | Option A — Purchase | Option B — Financed |
|---|---|---|
| Upfront | $35,000 | $10,000 |
| Then | $2,000/mo maintenance | $3,000/mo × 10 months, then $2,000/mo |

Option B totals $40,000 over the first ten months, reflecting the financing.

### What the monthly covers

**Included:** production hosting oversight, backups, security updates, bug fixes,
carrier file-format maintenance, reasonable small improvements, data-import
support, and system administration.

**Not included (quoted separately):** major new modules, substantial new
integrations, entirely new business systems, or significant scope expansions.

That distinction matters because carrier formats change without warning — Aetna
switched file formats mid-year, Devoted mislabels its files, UHC changed a payment
convention. Each of those breaks imports until someone fixes it, usually the week
commissions are due.

---

## 5. What this means for my book

**[TIM — choose one and write it in your own words. Don't leave all three.]**

- *Keeping the book as-is:* "No change. This has been done alongside my book for
  five months and my production reflects that. I'm asking to be paid for the
  second job I'm already doing."
- *Shifting toward development:* "Yes, deliberately — [what you'd propose, and
  what happens to your AOR/servicing]."
- *Leaving it open:* "That depends on what the agency needs. I'd rather settle the
  developer role first, then talk about the right mix."

Either way, my existing customers keep their servicing agent and nothing changes
for them without your sign-off.

---

## 6. Ownership

**[TIM — this needs deciding before the meeting. There is currently no written
agreement, no license, and no IP terms anywhere. See the notes.]**

Suggested position:

> On payment of the development fee, Founders owns the deployed system and its
> source code for use in operating the agency's business. [Any terms you want
> around the white-label direction in PRODUCT_VISION.md go here.]

Ownership transferring on payment is what makes the fee an asset purchase rather
than rented access — which is the stronger framing for you, and the fairer one for
Founders.

---

## 7. Continuity

Not a threat — a planning fact you should have.

The portal is load-bearing: commission recaps, the agency book, carrier
reconciliation and daily agent workflow all run on it. One person built it and one
person maintains it. A commission-processing defect could cost several thousand
dollars before anyone noticed — Section 2 shows that isn't hypothetical.

I'd rather keep building it. I'm asking that it be compensated as the work it is.

---

**Sources:** ¹ FullStack, *2026 Software Development Price Guide*; Arc.dev
developer cost comparison. ² Leanware, software development retainer pricing.
*(Figures provided by Tim Winslow; independently verifiable.)*

---
---

## ⚠ NOTES FOR TIM — REMOVE BEFORE SENDING

**Negotiation position** (do not put this table in the document):

| | Ask | Good outcome | Reluctant floor |
|---|---|---|---|
| System | **$35,000** | $30,000 | $25,000 |
| Monthly | **$2,000** | $1,750–2,000 | $1,500 |

Opening at $35k gives room to land at $30k. Don't open at $30k hoping for $30k.

**Still to fill:**
- `[DATE]` — proposed maintenance start (1 September was discussed).
- **Section 5** — pick one option, delete the others.
- **Section 6 — the one to think hardest about.** I checked: there is **no
  LICENSE file, no IP clause, and no written agreement anywhere in the project.**
  You built this on your own time on infrastructure you administer. That ambiguity
  cuts both ways and is better named by you than discovered mid-negotiation.
  Specifically decide: does "Founders owns the deployed system" include the
  white-label product described in `PRODUCT_VISION.md`? If you intend to pursue
  that, carve it out explicitly — selling the agency system is not the same as
  selling the right to commercialize it elsewhere. Consider a lawyer's eye on the
  final agreement; it's a real asset transfer.

**On the citations:** the rate figures and sources are yours, not independently
verified by me. They're attributed in a footnote so Brian can see where they came
from. If he checks one and it doesn't say what the document claims, that costs
more credibility than the number gains — worth confirming each link says what you
expect before sending.

**Deliberately excluded:** commit counts, lines of code, developer-months. They
read as effort rather than value, and mean nothing to a non-technical reader. The
785 tests and 42 migrations appear once, in Section 3, as scope a firm would quote
against — not as a headline.

**Structure note:** Brian reaches "this is critical infrastructure" (Sections 1–2)
and "replacing it costs six figures" (Section 3) *before* he sees $35,000 in
Section 4. Keep that order.

**Verification:** every non-bracketed fact came from the live system or project
record on 7 Aug 2026. The scale table is a direct database query. The Section 2
incidents carry dates AJ can confirm.
