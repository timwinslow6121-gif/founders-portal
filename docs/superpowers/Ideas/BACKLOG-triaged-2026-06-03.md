# Founders Portal — Triaged Backlog

> Source: `Foundersportalbrainstormideas.md` (raw idea capture), triaged 2026-06-03.
> Status verified against code + CLAUDE.md build log. Reorder freely — this is yours.
> Legend: ✅ done · 🟡 partial/seeded · ⬜ open

---

## A. Already shipped (verify, don't rebuild)

Per CLAUDE.md build status (Phases 1–5, 2026-04→05 work):

- ✅ BOB importer (6 carriers)
- ✅ Carriers & Plans database + customer-profile plan link
- ✅ Light-mode theme, padding, rounded corners (system-aware dual palette)
- ✅ Customer sort by name / stage / pharmacy
- ✅ Resizable columns (name, MBI, phone, …)
- ✅ Column visibility picker
- ✅ One row per customer; click → all policies on profile
- ✅ Upcoming terminations = 30-day window
- ✅ Dashboard termination/task items hyperlink to customer profile
- ✅ NC Enrollment Windows → SEP quick reference
- ✅ Filtering on customer tables (carrier/plan_type/agent/medicaid + stats strip + CSV export)
- ✅ Plan Data Integrity & Provenance core (2026-06-03 — this session)

---

## B. Open backlog — ordered by importance × feasibility

### Tier 1 — High importance, high feasibility (do soon)

1. ⬜ **AOR-based customer access + OEP overlap** *(THE foundational problem — lines 12–14)*
   - One entry per MBI (dedup) — already enforced.
   - **Problem:** a non-AOR agent who tries to create a duplicate is currently *blocked from viewing* the customer at all. Should instead: block *creation*, but allow *view/search* access (so any agent can answer a main-line call and see who the AOR is).
   - **OEP time-overlap (the hard part):** during OEP, two agents legitimately need the same customer in their books — the *current* AOR (until the term/effective date) AND the *future* AOR (from the new plan's effective date). Both need it in their book + pipeline, scoped by date.
   - **Substrate** for: dashboards, "View as: [agent]", commission scoping, sales pipeline.
   - Feasibility: Medium — `CustomerAorHistory` (effective/end dates) + `_is_current_aor()` already exist to build on.

2. 🟡 **Edit customer information fully** *(line 9)*
   - Partial: edit routes exist (`customers.py` sets `manually_edited=True`). Need an audit of *which* fields are still not editable and close the gaps.
   - Feasibility: High — CRUD extension of existing routes.

3. ⬜ **CSV/Excel customer import** *(line 36)*
   - Agents have books in spreadsheets; without import they re-enter everything.
   - Feasibility: Medium — `upload.py` already parses .csv/.xlsx/.xls (BOB); reuse the machinery for a customer-list import flow with column mapping.

### Tier 2 — High importance, needs careful design

4. 🟡 **Sales pipeline + future-dated AOR** *(lines 4, 14)*
   - Seed exists: `Customer.deal_stage` column. Needs the pipeline UI + the future-dated-AOR logic from item #1 (a future-start customer appears in the future-AOR's pipeline before they're active).
   - Feasibility: Medium-low — entangled with AOR model; design after/with #1.

5. ⬜ **Customer timeline / interaction log** *(line 6)*
   - All updates/interactions/communications on the customer profile. Ties to the AI voice-memo idea (#9).
   - Feasibility: Medium — new model + profile section; some data already exists (notes, comms, AOR history) to aggregate.

6. 🟡 **Reports / filter customers by ANY data point** *(line 11)*
   - carrier/plan/medicaid/C-SNP/D-SNP/county/zip/pharmacy/email/phone.
   - This is **Plan 5 of the provenance work** (the robust filter layer), generalized to customers.
   - Feasibility: Medium — partly designed in the provenance spec.

### Tier 3 — High value, larger / fuzzier (own deep brainstorm)

7. ⬜ **AI voice-memo + daily briefing + Gemini** *(lines 1, 66–81)*
   - Agents record a voice note per appointment (who / what / accomplished) → tied to customer profile or task. Evening end-of-day recap; morning briefing (yesterday's contacts, upcoming to-dos, birthdays).
   - Google Workspace + Gemini already in the stack; cost-sensitivity is the open question.
   - Feasibility: Low-medium, large scope — deserves its own brainstorm. Highest "excitement" value.

8. ⬜ **Campaigns via SMS/email/phone** by plan / T65 / etc. *(line 5)*
   - Feasibility: Medium — comms infra (Quo/SendGrid/Twilio) exists; needs segmentation + scheduling.

### Tier 4 — Polish / UX (batch into one pass)

9. ⬜ Founders logo + modern UI refresh *(line 56)*
10. ⬜ Agent headshots on profiles *(line 56)*
11. ⬜ Minimizable / consolidated sidebar with icons+labels *(line 58)*
12. ⬜ Tooltips *(line 60)*
13. ⬜ User guide *(line 62)*
14. ⬜ Dribbble/Figma CRM + pipeline UI inspiration pass *(line 64)*

### Tier 5 — Infra / testing / smaller

15. ⬜ Test Calendly / Quo / HealthSherpa integrations *(line 3)* — HealthSherpa still blocked on provisioning (CLAUDE.md).
16. ⬜ Gemini general integration question *(line 1)* — overlaps #7.
17. 🟡 Dashboard: remove duplicate top bars *(lines 18–19)* — CLAUDE.md notes duplicate period-banner already removed; verify nothing else duplicates.

---

## C. The strategic read

**Item #1 (AOR access + OEP overlap) is the keystone.** Your own notes (lines 12–14) circle it repeatedly, and it's the substrate the dashboards, "View as," commission scoping, and sales pipeline all sit on. Designing it first makes everything downstream easier. Recommended next brainstorm centers here.

**The "ownership" insight from the provenance work applies again:** in this domain, customers aren't "owned" in the CRM-generic sense — the AOR relationship is *time-bounded and on the policy*. The OEP overlap is exactly where that time-boundedness becomes load-bearing. Design the access model around AOR *intervals*, not a static owner field.
