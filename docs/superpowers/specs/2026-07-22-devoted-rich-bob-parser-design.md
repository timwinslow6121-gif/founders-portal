# Devoted Rich Application-Status BOB Parser — Design

**Date:** 2026-07-22
**Status:** Approved (brainstorm complete) — ready for implementation plan
**Author:** Tim + assistant

## Problem

AJ delivered the **full Devoted Book of Business**
(`docs/Carrier BOB DL/July 2026 period/Devoted/Devoted Book of business.xlsx`,
sheet `application_status_report_2026_`, 529 data rows). Unlike the earlier
lossy Devoted exports, **every row carries a valid CMS-format MBI** plus CMS
plan ID, plan type, full address, county, phone, the writing-agent NAME, the
application date, and competing-application flags.

The current parser (`app/parsers/devoted.py`) has an
`_parse_application_status()` path written for an **older, lossy**
Application-Status export. Because this new file's headers also carry the
`"Application Status Report "` prefix, `parse()` routes it to that path — which
**discards the MBI (`mbi=""`), synthesizes a fake `DVND-<hash>` member_id, drops
plan ID / plan type / phone / address / county, and reads only the Agent NPN**.
Importing this file as-is would recreate the exact identity mess this
reconciliation is meant to fix.

This is why Devoted was hugely under-imported: **33 in the DB vs ~522 active in
the BOB (−489)**.

## Goal

A parser path that reads THIS rich format correctly — keyed by the real MBI —
so the file can be imported through the existing pipeline
(`resolve_customer()` already does crosswalk → MBI → name+DOB → stub, so no
import/matching changes are needed). Then reconcile Devoted the same careful way
as UHC/Aetna.

## Approach

Add a **rich** Application-Status parser path alongside the existing lossy one;
detect which variant a file is and route accordingly. The lossy path stays
unchanged (older files still parse). No change to the import pipeline or the
customer resolver.

## Column map (this file's headers, `"Application Status Report "` prefix stripped)

| Header (suffix) | Record field | Notes |
|-----------------|--------------|-------|
| `Mbi` | `mbi` (uppercased) **and** `member_id` | Real CMS MBI is the key; Devoted keys members by MBI in this export — no synthetic `DVND-`. |
| `First Name` / `Last Name` | `first_name` / `last_name` | ALL-CAPS in source → title-case. Fall back to splitting `Full Name` if either is blank. |
| `Full Name` | `full_name` | |
| `Birth Date` | `dob` | |
| `Phone Number` | `phone` | |
| `Address` / `City` / `State` / `Zip Code` / `County` | address fields / `county` | |
| `Start Date` | `effective_date` | |
| `Plan End Date` → else `Disenrollment Date` | `term_date` | Both blank in this file; map for future files. |
| `Plan Name` | `plan_name` | |
| `Plan ID` | (CMS code, e.g. `H5299-013`) | Used for plan-bucket sorting via the existing importer. |
| `Plan Type` | `plan_type` | e.g. `MAPD`. |
| `Agent Name` | writing agent (resolved by name, like other carriers) | |
| `Agent Npn` | `agent_id` / writing-agent NPN | keep as a secondary identifier. |
| `Application Date` | `application_date` (**NEW**) | The submitted date. Nothing captures this today; feeds the same-MBI tie-break here AND the backlog's AEP same-effective-date tie-break. |
| `Is New to Medicare Advantage (Yes / No)` | drives `commission_type` | `Yes` → `'initial'`, `No` → `'renewal'`. |
| `Is Winning App (Yes / No)` | `is_winning_app` (captured, used in dedup) | authoritative CMS competing-app winner. |
| `Current Status` | active/skip decision (see below) | |
| `Disenrollment Reason` / `Pending Reason` | (map if present) | blank in this file. |

## Active-status rule

- **`Current Status = Enrolled` → active.**
- **`Current Status = Approved` → active** (accepted, pending effective date;
  will be active imminently — import so we don't lose them; note the count in
  the reconcile report). Verified as a 7-row edge; do **not** build a separate
  `pending` policy state for it now.
- **Any other status → skip.**
- **`Is Winning App` is NOT a skip filter.** All 8 non-winning rows in this file
  are still `Enrolled`; 2 of them (Peggy Marsh → Brian; Cynthia Cauthen →
  Anjana) have NO winning counterpart and are real active clients. Filtering by
  winning-app would wrongly drop them. Status decides activity; winning-app only
  resolves same-MBI duplicates (below).

## Same-MBI competing-application resolution

When one MBI has more than one active row (a member with competing
applications — 6 such pairs in this file, all sharing the same effective date so
effective-date alone cannot resolve them), pick the survivor by this precedence:

1. **`Is Winning App = Yes` wins** — authoritative; this is CMS's actual
   decision as Devoted reports it. (Verified: in all 6 pairs the winning row is
   also the later-application-date row.)
2. **Else, latest `Application Date` wins** — matches the CMS "last application
   submitted wins" principle (the tie-break when the flag is missing/ambiguous
   or both rows carry the same flag).
3. **Else (flag AND application date both tied/ambiguous) → do NOT guess.** Flag
   the pair for human review in the reconcile report.

The losing row is the same person (same MBI) → it does not create a separate
customer; only the winning row is the active policy. A **lone** non-winning row
with no winning sibling (Peggy, Cynthia) is its own survivor → active.

**Data flow:** the parser EMITS `is_winning_app` (bool) and `application_date`
(date) on each record; the dedup step CONSUMES them. The existing
`_dedupe_bob_records` / `_rec_is_more_current` (`app/upload.py`) already collapses
repeated `(carrier, member_id)` active rows chronologically; extend its
tie-break so that when effective/term dates tie, it prefers `is_winning_app=True`,
then later `application_date`, before falling to last-in-file — and records an
ambiguous pair (same flag AND same application_date) for review rather than
silently choosing. Records from carriers that don't set these fields are
unaffected (missing `is_winning_app`/`application_date` → the existing behavior).

## Detection

Both Application-Status variants share the `"Application Status Report "` prefix.
Distinguish them by the presence of the **`Application Status Report Mbi`**
column: present → the rich path; absent → the existing lossy
`_parse_application_status` (unchanged). Non-Application-Status Devoted files
(older snake_case CSV) continue to use the CSV path.

## Testing

TDD against rows extracted from the **real file** (fixture):
- a rich Enrolled row yields the real MBI, CMS Plan ID, plan type, title-cased
  name, address, county, phone, effective date, application_date, and
  `commission_type` from the New-to-MA flag;
- an `Approved` row comes through as active;
- a same-MBI winning/losing pair collapses to the **winning** row (and to the
  **later-application-date** row when the flag is stripped in a test);
- a same-MBI pair with identical flag AND application date is **flagged for
  review**, not silently collapsed;
- a lone non-winning Enrolled row (Peggy/Cynthia shape) stays active;
- the OLD lossy Application-Status file still parses via the unchanged path
  (regression);
- detection routes each file to the correct path.

## Out of scope (follow-on, after the parser ships)

- The reconcile itself: read-only diff (BOB-active vs DB-active, categorized:
  match-by-MBI / match-by-name+DOB / create-new / status-flip / dup) → dry-run →
  DB backup → import via `scripts/import_bob_file.py` (row-driven, safe) → verify
  money ($) and active counts. Same method as UHC/Aetna.
- The **cross-carrier switcher pass** (UHC 89 + Aetna 4 + Humana 28 held rows)
  that needed Devoted's data — newest enrollment across all carriers wins;
  name+DOB+address, never dob-alone.
- A real `pending` policy state for `Approved` rows (revisit within the
  customer-plan domain model if it earns its keep).
- Wiring `application_date` into the AEP same-effective-date tie-break feature
  (this spec just captures the datum).
