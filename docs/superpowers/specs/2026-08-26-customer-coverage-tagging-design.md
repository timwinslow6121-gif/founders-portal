# Customer Coverage & Conditions Tagging — Design

**Date:** 2026-08-26
**Status:** Approved (brainstorm complete) — ready for implementation plan
**Author:** Tim + assistant
**Context:** First build of the customer "fact layer". Driven by an AEP-critical gap Brian named: the agency cannot identify its state retirees. Related backlog item: "Secondary/retirement coverage flag on customers" (logged 2026-07-13, previously nice-to-have; the 2027 State Health Plan changes make it urgent).

## What this builds

A structured, provenance-tracked way to record **what other coverage a customer has** (state retiree, VA, TRICARE, FEHB, employer group, …) and **which qualifying conditions they have** (the C-SNP set) — then filter the book on it.

It answers a question the portal cannot answer today: *"Which of my customers are state retirees?"*

### Why now — the grounding case

For 2027, **all NC state retirees are auto-enrolled into the Humana Group PPO** regardless of their current plan. A client on an MA-only plan + Aetna 70/30 will be **disenrolled from both** unless they call the State (855-859-0966) to opt out. Vesting decides the advice: a **fully vested** retiree gets the Aetna 70/30 at $0 premium; a **non-vested** retiree faces a large premium (~$500/mo reported) and is usually better served by a regular MAPD than by either the Humana Group PPO or the 70/30.

Brian cannot run that outreach because he cannot produce the list. The old proxy — "on BCBS Medical Only or UHC Patriot ⇒ probably a state retiree" — broke in 2025/26; retirees are now spread across Devoted MA-only, Aetna MA-only, HealthSpring giveback and ordinary MAPDs. The only historical record is inconsistent, free-text, timestamped comments in PioneerRx, and that access may be lost.

Compliance raises the stakes: Brian is under active carrier/CMS scrutiny, so *who was contacted, when, and on what basis* needs to be recorded rather than remembered.

### Scope

**In scope:** coverage tagging, condition tagging, profile panel, list filters, bulk tag + CSV import, provenance, audit.

**Out of scope (deliberate):**
- **Outreach tracking** (contacted / opted-out / decision recorded). Tim: "start with 2 then build 3 later." That is an event log, not a tag, and needs its own design.
- **Providers per customer.** Same tagging shape, but `providers` currently ships **empty** — customer↔provider links would be unpopulatable. Revisit once the directory has data.
- **Medications.** Separate project: drug identifiers (NDC/RxNorm), import from HealthSherpa/MedicareCenter, and the pharmacy-reimbursement dimension that drives plan selection. Deserves its own brainstorm.

## Section 1 — Data model

**New `customer_coverages` table** (agency-scoped), one row per customer per coverage type:

- `id`, `agency_id` (FK agencies.id, indexed), `customer_id` (FK customers.id, indexed, ON DELETE CASCADE)
- `coverage_type` (String) — one of:
  `state_retiree` | `county_retiree` | `employer_group` | `federal_fehb` | `va` | `tricare` | `champva` | `condition` | `other`
- `condition_code` (String, nullable) — only when `coverage_type='condition'`: `diabetes` | `chf` | `cardiovascular` | `esrd` | `other`
- `status` (String, not null, default `suspected`) — `confirmed` | `suspected` | `ruled_out`
- `source` (String, not null) — `agent_confirmed` | `customer_stated` | `import` | `inferred`
- `vesting` (String, nullable) — `fully_vested` | `not_vested` | `unknown`; **only valid for `state_retiree` / `county_retiree`**
- `detail_json` (Text, nullable) — type-specific answers, unstructured for now
- `notes` (Text, nullable)
- `recorded_by_id` (FK users.id), `recorded_at`, `updated_by_id` (FK users.id), `updated_at`
- **`UNIQUE(customer_id, coverage_type, condition_code)`**

### Why these choices

**A table, not columns on `Customer`.** Customers genuinely hold multiple coverages simultaneously. Tim's grounding case: a retired postmaster who is also a veteran has FEHB **and** VA **and** Medicare. Retired state employees whose spouse is a veteran carry state-retiree **and** VA/CHAMPVA/TRICARE. Columns cannot express this without breaking on the first real case.

**`status` is the heart of the model.** `suspected` is what a PioneerRx-derived import produces; `confirmed` requires a human. `ruled_out` matters as much as the others — it keeps a checked customer off every future outreach list and records that someone looked. Without it, "not a retiree" is indistinguishable from "not yet asked."

**`UNIQUE(customer_id, coverage_type, condition_code)`** gives one row per fact. Re-tagging updates rather than duplicates, which is what makes the import idempotent and re-runnable.

**`vesting` is a first-class column, not a `detail_json` key**, because it changes the recommendation, needs to be filterable, and is the specific thing agents must establish on a state-retiree call.

**`detail_json` stays deliberately unstructured.** The VA questions agents actually ask — *does the client fill all meds at the VA (⇒ MA-only may fit), do they see civilian doctors, do they have a VA waiver for those, do they use the VA at all (⇒ a strong MAPD fits)* — go here as keys. They earn columns once proven stable in use.

**Conditions ride the same table** rather than getting their own. Identical shape (small controlled vocabulary, agent-entered, tag-and-filter), and C-SNP qualification is a live AEP plan-selection question.

**Open verification item (do NOT encode as a rule):** the TRICARE/CHAMPVA interaction with Part D — whether an MA-only plan leaves drug costs reimbursed — is not established here. Record it as a `[VERIFY]` note; do not build recommendation logic on it.

## Section 2 — UI surface

**1. Customer profile — "Coverage & Conditions" panel.** Placed near the existing Medicaid / language fields, using the same inline-edit pattern agents already know. Renders current tags with status, e.g.
`State retiree — fully vested (confirmed · Tim · Aug 26) · VA (confirmed) · Diabetes (confirmed)`.

**2. Customer list — two new filters.** `Coverage` and `Condition` dropdowns, following the existing Carrier / Plan Type / Medicaid / Language pattern in `app/customers.py`. Filtering to *State retiree* produces Brian's outreach list; the existing CSV export carries it out.

**3. Bulk tagging — two entry points, one action:**
- **From the filtered list** — select rows, apply a tag (how a cross-referenced list gets applied in bulk).
- **CSV import** — match on MBI or customer id, set `coverage_type` + `status=suspected` + `source=import`.

**Suspected tags are visually distinct** (amber chip vs solid) on both profile and list. A suspected tag is a lead, not a fact; an agent quoting one to a client as established would be the same class of error the First Look FL-marker work exists to prevent.

## Section 3 — Writes and provenance

**Single seam.** All writes go through `set_coverage(customer, coverage_type, status, source, actor, condition_code=None, vesting=None, detail=None, note=None)` in a new `app/coverage.py`. Mirrors the established seam pattern of `plan_provenance.set_cms_value()` and `app/customer_provenance.py`.

**Source precedence — the core rule.**
`agent_confirmed` > `customer_stated` > `import` > `inferred`

A weaker source **never overwrites a stronger one**. An import may freely create `suspected` rows, but a later re-run must not stomp a tag an agent has since confirmed on a call. This deliberately mirrors the CMS-over-First-Look precedence in `plan_provenance.py`.

**Provenance as columns, not JSON.** The existing engines use JSON `_meta` because they annotate many fields on one record; here each **row is one fact**, so `source` / `recorded_by_id` / `recorded_at` / `updated_by_id` / `updated_at` are real columns — queryable, so "everything Brian confirmed this week" is a WHERE clause.

**Audit.** Every write calls the existing `log_event()` (`app/audit.py`) with category `data_change`, capturing actor, customer, and what changed. `log_event` is already defensive — a logging failure never raises into the caller. Given the active compliance scrutiny, this trail is a feature, not overhead.

**Import path.** Dry-run first (the established pattern for every data-touching script in this repo): report would-create / would-update / skipped-by-precedence counts, and **list unmatched rows for human review rather than guessing**. Only then `--apply`. Idempotent via the unique constraint.

**No automatic expiry.** Tags do not decay on a timer. Coverage genuinely changes year to year, but "is this still true?" is a review workflow; a silent timestamp rule would quietly drop people off outreach lists.

## Section 4 — Testing

**Seam unit tests** (`set_coverage` is where the rules live):
- Create records source, actor, timestamp
- Re-tag the same `(customer, coverage_type, condition_code)` **updates, never duplicates**
- Precedence: `import` against an existing `agent_confirmed` row leaves it unchanged; the reverse overwrites
- `vesting` accepted only for retiree types, rejected elsewhere
- `ruled_out` customers stay off the outreach filter

**Import tested against the real list, not fixtures.** Lesson from the commission work: rules that pass unit tests fail real files. Dry-run creates nothing; matches produce `suspected` rows; unmatched rows are reported rather than guessed; a second run is a no-op.

**Filter tests** — correct set returned, and **agency-scoped**. Every query in this codebase is agency-scoped; a miss is a cross-tenant leak.

**Real-Postgres verification before done.** `UNIQUE(...)` plus a Core insert is precisely the shape that has bitten this project twice — the `ix_customers_mbi` partial-unique autoflush bug and the `provider_plans` SERIAL issue, both invisible to SQLite. Compile the migration against real Postgres; dry-run the import against prod data before apply.

## Seed data — the first import payload

AJ produced a cross-referenced list (email 2026-08-26) comparing PioneerRx patient/Rx exports for 10/1–12/31/2025 against 1/1–3/31/2026, identifying patients who moved from an NC State plan to a 2026 MAPD.

**Verified against production on 2026-08-26:** the PDF yields **54 patients** (49 → Humana 335, 5 → Devoted), matching AJ's stated counts. Joined to `customers` on normalized last/first name, **48 of 54 match** — 43 currently on Humana, 4 Devoted, 1 UHC. Seven names did not match (`Bange, James`; `Bost, Michael`; `Brewer, Linda`; `Christy, Bonnie`; `Jolley, James`; `LEMMOND, RONALD`; `Mccauley, Gaynell`) — some are likely name-format cases the existing normalizer handles (all-caps, `Mccauley` casing), others may not be Founders customers.

**These import as `status=suspected`, `source=import`.** The evidence is a *plan transition inferred from pharmacy claims* — strong, but it establishes neither that the person is **still** a state retiree in 2027 nor their **vesting**, which is the fact that decides the recommendation.

**Known coverage limits (AJ's own caveats):** one store only; misses anyone who filled at North or had no 2026 Rx. **48 is a floor, not a census.** The remaining book still needs tagging through conversations.

## Risks

- **Population is the project, not the schema.** ~5,458 customers tagged one at a time. The feature's value is entirely gated on that work happening — which is why the import path is in scope from the start rather than a follow-up.
- **Suspected-as-fact.** Mitigated by the visual distinction and by precedence, but an agent could still quote a suspected tag. The chip styling is protection, not a guarantee.
- **Unverified TRICARE/CHAMPVA Part D interaction.** Explicitly not encoded; belongs in the verification queue.
