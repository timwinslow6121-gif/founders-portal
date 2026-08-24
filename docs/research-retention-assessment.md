# Retention research — what to trust, what to use, what to ignore

Assessment of `Medicare Client Retention Research Plan.md` (Gemini Deep Research,
Aug 2026). **Read this before quoting anything from that file to Brian or building
against it.**

**Bottom line:** genuinely useful, and it did the most important thing right — it
told you plainly that the "four touches a year" advice is vendor marketing with no
study behind it. But ~half the 51 citations are vendor/broker blogs, and two are
visibly irrelevant. Use the sourced findings; discard the rest.

---

## ⚠ Source-quality warning

**Two citations do not support the claim they are attached to.** The assertion that
P&C contact-frequency research doesn't transfer to Medicare is footnoted to:

- a **lottery CRM marketing** article (Optimove)
- an **auto-dealership lease-expiration alert** blog post

Neither is about insurance retention. The underlying *claim* is reasonable, but the
citations are decorative. Treat that as a signal for the whole document: **verify any
number before it leaves your desk.**

Of 51 sources: ~24 authoritative-ish (CMS, GAO, eCFR, Pew, AARP, NIH, Deft Research),
~27 vendor/broker/marketing blogs. The regulatory sections are the best-sourced; the
retention-benchmark sections are the weakest.

---

## ✅ USE — well-sourced and directly relevant

**1. The first 90 days are the flight risk.** New members who just switched are
**2–3× more likely to switch again** in their first year. 15.6% of MA members change
plans within one year; 49.2% within five. *(Deft Research — a real healthcare market
research firm, the strongest source in the document.)*

**2. Post-January discovery is the churn trigger.** Members who learn about plan
changes **after Jan 1** are **4× more likely** to switch during OEP than those told
beforehand. Fewer than 60% of seniors even remember receiving their ANOC. *(Deft.)*
→ **This is the single most useful finding for the portal.** It converts ANOC work
from an administrative chore into a retention mechanism with a measured effect size.

**3. 2025 was unusually bad and 2026 looks worse.** Largest annual NPS drops Deft has
recorded (−9 MA, −10 Medigap), 15% OEP switching, and a record **21% of seniors
intending to switch ahead of AEP 2026**. → Directly supports "this AEP will be
harder than last."

**4. Channel preference is age-banded, not uniform.** 91% of 65+ own a smartphone and
SMS has overtaken email for 50+ *(AARP/Pew)* — but **65% of adults 75+ need help
setting up a new device** *(Pew)*, and 71% of beneficiaries say direct mail feels more
trustworthy for plan information. → **A portal-only or SMS-only strategy fails on the
75+ half of the book.** Design for mail + SMS + phone, segmented by age band.

**5. Readability is a real, measurable gap.** Medicare materials routinely score
10th–14th grade; the recommended target is 6th–7th. *(GAO, NIH.)* → A plain-language
generator is a legitimate portal feature, not a nicety.

---

## 🔴 USE — and treat as build constraints, not suggestions

**The CMS compliance section is the most valuable part of the document**, and it is
well-cited (eCFR, CMS manuals, Hall Render, Federal Register). It is also more
restrictive than expected:

- **Mentioning *any* widely available benefit — dental, vision, hearing, OTC, premium
  reduction — reclassifies a message from "communication" to "marketing."** A
  cheerful "don't forget to use your OTC benefit!" blast is **retention marketing**,
  requires the TPMO disclaimer, and must be filed and approved through the carrier or
  FMO. This kills the naive version of the drip-campaign feature.
- **One-to-one consent** (FCC/TCPA + CMS): a generic web-form opt-in covering
  "insurance partners" is not valid. Consent must name Founders specifically.
- **Permission to Contact expires at 12 months.** A compliant CRM must auto-expire
  consent and suppress outreach on day 366. → That's a scheduled job and a
  `consent_expires_at` column, not a policy document.
- **Unsolicited marketing SMS, DMs and voicemails are prohibited outright.**
- **Unsolicited *email* is allowed** under CAN-SPAM with a working opt-out — but only
  if it contains no benefit or premium detail without prior consent.
- **10-year retention** on SOAs, consent records, and recorded telephonic marketing
  appointments — even when no enrollment results. Storage must be tamper-evident and
  audit-retrievable.

⚠ **Verify these against the actual CY2025/CY2026 Final Rules and your FMO's
compliance guidance before building.** The claims are plausible and mostly
well-cited, but this is the area where being wrong is expensive.

---

## ⭐ The network-disruption playbook — the best practical answer in the document

Directly usable for the **UHC ⇄ Tryon** situation (deadline 1 Oct 2026):

1. **T-minus 45–60 days:** factual, calming brief to affected enrollees. State that
   negotiations are under way and that these **usually settle at the last hour**.
   Tell clients *not* to cancel appointments or panic-switch, and to wait for
   guidance.
2. **Explain continuity-of-care rights** (42 CFR §422.112(b)(5)): a member in an
   active course of treatment can usually keep seeing the provider at in-network
   cost-sharing for a transition period (often 90 days). Most beneficiaries don't
   know this, and it defuses the most frightened callers.
3. **If it actually terminates:** affected enrollees typically get an **SEP** to
   change plans mid-year. Prepare that message in advance, keyed to the termination
   date.
4. **Carriers must notify affected enrollees ≥30 days before termination.** If you
   wait for the carrier's letter, you lose the narrative — it's dense, legalistic,
   and generates exactly the call flood you're trying to prevent.

**The compliance line, quoted because the wording matters:**

> ❌ Non-compliant: *"Tryon Medical is leaving UHC, call me to switch to Humana."*
> ✅ Compliant: *"We are monitoring the UHC and Tryon Medical negotiations. If a
> resolution is not reached, you may be eligible for a Special Enrollment Period to
> review other options. We will contact you on October 1st with next steps."*

→ **That second sentence is a template. It is educational, retains you as the trusted
advisor, and does not market a competing plan.**

---

## ⚠ DO NOT USE without independent verification

- **"75–80% industry retention, 90%+ elite."** Sourced to broker blogs and an agency
  M&A site with an interest in the number. Plausible, unverified.
- **"Acquiring a client costs 5–7× retaining one."** The classic recycled marketing
  statistic. No primary source given.
- **LTV ≈ $1,835 over five years** ($611 initial + 4 × $306). The *commission caps*
  are real and CMS-published; the LTV arithmetic is the document's own, and it
  ignores chargebacks, splits, and your actual contract rates. **Your own ledger
  computes this correctly — use that instead.**
- **"1.1 policies/client industry average vs 2.0+ elite."** No credible source.

---

## What this changes for the proposal

**Keep the proposal as it is.** The current wording — *"about four touchpoints a
year, all one-way, none carrying a reply path"* — is your own verified fact and needs
no citation. Adding a contested industry number would weaken a document whose
strength is that every figure is measured.

**One optional addition**, if you want outside validation in the room rather than on
the page:

> Members who learn about plan changes after January 1 are four times more likely to
> switch during OEP than those informed beforehand. *(Deft Research, 2026 Medicare
> Member Onboarding Study)*

That is the best-sourced, most on-point finding in the whole document, and it makes
the ANOC/proactive-communication argument for you.

---

## What this changes for the portal roadmap

| Finding | Portal implication |
|---|---|
| First 90 days = 2–3× flight risk | A **new-member onboarding sequence** (day 30 / 60 / 90) is the highest-ROI campaign to build first |
| Post-Jan-1 discovery = 4× OEP churn | **ANOC list generation + plain-language change summary** moves from chore to retention feature |
| Benefit mentions trigger CMS marketing rules | Campaign builder needs a **compliance mode**: flag benefit language, attach TPMO disclaimer, block unapproved sends |
| PTC expires at 12 months | `consent_expires_at` + a scheduled suppression job |
| 10-year retention on SOA/consent | Tamper-evident document storage with audit retrieval |
| 75+ can't be reached digitally | Campaigns must **segment by age band** and support a mail path, not just email/SMS |
| Network disruption playbook | Filter book by carrier + provider group → generate affected list → send the compliant template above |

**Sequencing note:** the compliance constraints are not a later phase. Establish the
marketing-vs-communications boundary *first*, because it determines what the campaign
feature is allowed to do at all.
