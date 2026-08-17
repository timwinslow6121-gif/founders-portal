# Founders Agent Portal

### Scope, current status, and proposal

**Prepared for:** Brian Freeman
**From:** Tim Winslow
**Date:** August 2026

---

> **⚠ DRAFT — two things before sending: (1) confirm the rate citations in
> Section 3 say what this document claims, (2) delete this banner and the notes
> section at the end.** Everything else is complete and verified from the live
> system.

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

### The portal isn't the whole of it

Alongside the portal, I have also been handling the agency's day-to-day technology:

- **The agency website** — maintenance and updates
- **Google Workspace** — email accounts, domain settings, user administration
- **The Google Business profile**
- **General technical support for agents** — the questions that come up week to
  week

Individually these are small. Together they are the agency's IT function, and they
have been unpaid. **I have stopped maintaining the website**, which is the honest
reason it hasn't been updated recently — not neglect, but a decision to stop doing
that particular job for free while the rest of this was unresolved.

I would rather fold this work into a defined role than continue doing it ad hoc.

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
> beginning **1 September 2026**, cancellable with 90 days' notice

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

**The portal:** production hosting oversight, backups, security updates, bug
fixes, carrier file-format maintenance, reasonable small improvements, data-import
support, and system administration.

**Agency IT:** website maintenance, Google Workspace and email administration,
the Google Business profile, and day-to-day technical support for agents.

**Not included (quoted separately):** major new modules, substantial new
integrations, entirely new business systems, a website rebuild or redesign, or
significant scope expansions.

That distinction matters because carrier formats change without warning — Aetna
switched file formats mid-year, Devoted mislabels its files, UHC changed a payment
convention. Each of those breaks imports until someone fixes it, usually the week
commissions are due.

---

## 5. What this means for my book

**Nothing changes.** I remain a producing agent, my book stays mine, and my
customers keep their servicing agent.

This work has been done alongside my book for five months and my production
reflects that. I'm not asking to write less business or to be carried — I'm asking
to be paid for the second job I'm already doing.

---

## 6. Ownership and license

I built this system on my own time, outside my agent responsibilities, and I
retain ownership of it. What Founders is purchasing is the permanent right to use
it.

> **Founders receives a perpetual, irrevocable, agency-wide license** to use the
> portal to operate its business — including all agency data, which is and remains
> Founders' property.
>
> **Tim Winslow retains ownership of the software and its source code**, including
> the right to license or offer it to other agencies.

**Why this is the right structure for Founders, not just for me:**

The license is perpetual and irrevocable. If our arrangement ends tomorrow, the
portal keeps running and Founders keeps using it — permanently, at no further
cost. That is the outcome that actually matters to the agency.

What the agency does *not* need is title to a Flask application. Owning the source
outright would mean owning the obligation to maintain it — hiring developers who
understand carrier commission processing, or paying a firm the rates in Section 3.
A license gets Founders the certainty without the liability.

**Founders' data is Founders'.** The customer records, policies, commission
history and book of business are the agency's property, exportable at any time.
Nothing in this proposal touches that.

**On the broader direction:** the system was designed from the start as a
Medicare-agency platform, with Founders as the first working implementation
(`PRODUCT_VISION.md`, March 2026). If it is ever offered to other agencies, that
is separate from this agreement and takes nothing away from Founders' license.
Founders would remain the reference implementation — and would benefit from
improvements funded by that work.

---

## 7. Continuity

Not a threat — a planning fact you should have.

The portal is load-bearing: commission recaps, the agency book, carrier
reconciliation and daily agent workflow all run on it. One person built it and one
person maintains it — along with the email, the website and the day-to-day
technical support. A commission-processing defect could cost several thousand
dollars before anyone noticed, and Section 2 shows that isn't hypothetical.

**On timing:** AEP is the argument for settling this now rather than after. The
portal is not new software being introduced — agents have used it daily for
months and it already runs the commission recaps and the agency book. What AEP
actually brings is the season when carrier files change without warning, volume
spikes, and a broken import lands the same week commissions are due. Section 2's
examples all happened in ordinary months. Going into AEP with no maintenance
arrangement is the risk; having one is the mitigation.

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

**Nothing left to fill except the rate citations** (below) — the document is
otherwise complete and sendable.

**On the start date — I put 1 September and I'd argue against offering January.**
You raised January in case Brian doesn't want new software close to AEP. But the
portal ISN'T new software to him: agents have used it daily for months, and
Sections 1–2 establish it as already load-bearing. Offering a January start
contradicts your own case — it invites him to think of this as a risky rollout to
postpone rather than an existing system to fund.

The AEP argument runs the other way, and Section 7 now makes it: AEP is when
carrier formats change, volume spikes, and a broken import lands the week
commissions are due. No-maintenance-during-AEP is the risk.

If he genuinely balks at September, **October is the concession to make, not
January** — it keeps you covered for AEP. Hold January in reserve and only if he
ties it to something (a signed agreement now, dated start later). Don't open with
a delay he hasn't asked for.
**⚠ SECTION 6 — GET A LAWYER ON THIS CLAUSE BEFORE SIGNING ANYTHING.**

I've written it as a **perpetual license, not a sale**: you keep ownership and the
right to offer the system to other agencies; Founders gets an irrevocable right to
use it forever. That is the structure that protects the MAMS direction.

Two things you should know honestly:

1. **"I built it on my own time" is your argument, but it is not automatically the
   legal conclusion.** Software built by an employee, using the employer's data,
   deployed on the employer's server, touching the employer's business processes,
   can be contested — doctrines vary by state and by whether you're W-2 or
   1099. **I am not a lawyer and this is not legal advice.** An hour of a business
   attorney's time before signing is cheap relative to what this becomes worth if
   MAMS goes anywhere.

2. **What helps you:** `docs/PRODUCT_VISION.md` is dated **March 2026** — the same
   month the repository started — and explicitly names Founders as the "testing
   ground" for a white-label product. That is contemporaneous evidence of
   independent commercial intent from day one, not a story assembled afterward.
   Do not delete or rewrite that file.

**Do not let the ownership clause get settled verbally in the meeting.** If Brian
says "sure, whatever" — get it in the written agreement anyway. Ambiguity is only
free until the thing is worth money.

**On the license framing with Brian:** lead with what he gets (the portal keeps
running forever, no further cost, data is his) rather than with what you keep. He
has no use for owning source code — owning it would mean owning the maintenance
obligation. If he pushes for full ownership, the honest question back is: "What
would you do with the source that a permanent license doesn't already let you do?"

**Section 1, the IT paragraph:** I included the website sentence plainly — that you
stopped because you got tired of doing it free. It's true, it explains a visible
fact he may already have noticed, and it makes the ask concrete rather than
abstract. If it reads as too pointed for your relationship with him, soften it to
"I've had to deprioritize it" — but don't cut it, because the website's state is
the most visible evidence that unpaid work doesn't get done indefinitely.

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
