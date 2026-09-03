# Plan data sheets

`ALL-benefit-data.csv` is the local source of truth: one row per
plan x year x benefit.

## The shared Google Sheet

"Medicare Plan Data 2026-2027" (Tim's Drive) is where Tim and AJ edit.
One tab per carrier, same columns as this CSV minus `Carrier` (the tab
supplies it).

https://docs.google.com/spreadsheets/d/1EztiA6_LU7RFGSm9GC86P4x9ln4jwiETFZRRQjvhRwA/edit

Updating it is currently a **manual copy-paste** -- no connector here can
write cells into an existing Sheet. Append only the new rows; never
replace the whole sheet (that would wipe anyone's edits).

**Always verify the row count after a paste.** A short paste raises no
error and looks identical to a complete one. Note the expected count
before pasting, then filter the tab and confirm you got it.

## Derived files (do not hand-edit)

`comparison-2026-2027.csv` / `.json` -- 2026 and 2027 side by side.
Regenerate with `python3 scripts/build_plan_comparison.py`.

## Status

- 2026: CMS-published (`Source=CMS`)
- 2027: carrier First Look (`Source=FL`), preliminary
- Aetna 2027 (19 plans, 523 rows) is **Source=CMS, not FL**. The Plan
  Guides carry CMS material ID Y0001_8915303_2027_M NC01 (the _M suffix
  means File & Use approved), dated 20260818. "Not for distribution prior
  to 10/01" is a MARKETING-DATE restriction, not an approval caveat -- CMS
  bars marketing next-year plans before Oct 1 regardless of approval.
  Do not confuse it with BCBS/Devoted/UHC, which say "Pending CMS Approval"
  and ARE first looks. Parsed from the PDF text layer and cross-checked
  against it: 131 values verified, 0 mismatches.
- SilverScript Choice (S5601-016-000) 2027 added from its first look.
- **Wellcare has no 2027 rows and that is deliberate.** Founders is NOT
  contracted with Wellcare, so their benefits must not be shown -- we
  cannot legally market plans we are not appointed for. The existing 63
  Wellcare 2026 PDP rows came from the public CMS Landscape file, which is
  a different matter from redistributing a carrier's confidential broker
  deck. The 2027 Wellcare deck covers only MA/D-SNP (H1914/H4073), no PDPs,
  and states PDPs stay NON-COMMISSIONABLE for 2027. Wellcare 2027 PDP data
  will come from the CMS Landscape file (~late Sept/Oct), not from Wellcare.
- BCBS 2027 added 2026-09-03 from U20717b 9/26, marked "Pending CMS
  Approval" -- it supersedes the earlier BCBS first look, which is kept
  as `SUPERSEDED - ...pdf`

## Plans to handle with care

**Blue Medicare Freedom+ (H3404-004)** -- niche PPO for federal retirees.
Its 2027 rows carry a CAUTION note. Federal retiree (FEHB) coverage
interacts with Medicare in complicated ways, Founders has very few members
on it, and a wrong recommendation can permanently damage someone's
coverage. Deliberate decision (Tim, 2026-09-03): do not invest in
understanding it, do not build recommendations from this data, refer out
or escalate instead. The values also encode two columns (with vs without
federal retiree benefits) in one string, so they do not chart cleanly.

**Wellcare** -- see the compliance note above. Not contracted.

## The Compare Plans dashboard (in the Sheet)

`Master` tab = all 7 carrier tabs stacked, with a `Carrier` column inserted
at B: `CMS Code | Carrier | Plan Name | Year | Benefit | Value | Source`.
5,883 data rows + header = last row 5884.

`Compare Plans` tab is built by the Apps Script in
`docs/Medicare 2027 Plan Info/SHEET-compare-plans.gs`. Row 1 picks a CMS
code from a dropdown, row 2 derives the plan name, row 3 is the year, and
19 benefit rows fill in. Six columns, so plan-vs-plan or year-vs-year.

Two things that will break it, both learned the hard way:

1. **Match on CMS Code, never Plan Name.** 12 plan names in this data map
   to more than one plan -- "Aetna Medicare Signature (HMO)" is FOUR plans
   (H3146-001/-004/-048/-049) with different MOOPs and copays. A name match
   silently returns whichever is first.
2. **Compare years as text.** Sheets turns a pasted "2026" into the NUMBER
   2026, and inside FILTER text never equals a number, so every lookup
   returns blank with no error. The script wraps all three conditions in
   `TRIM(TO_TEXT(...))`.

Note CMS codes come in two shapes: 89 carry a segment suffix
(`H1036-137-000`), 22 do not (`H3146-001`). Each plan uses one form
consistently, so this is not a split -- but do not assume a suffix.

## Around December

CMS-approved PBP data replaces the 2027 first-look values. Do not delete
the FL rows -- add the CMS row alongside and set `Source=CMS`. Where CMS
differs from the first look, note it: that identifies plans we may have
described incorrectly during AEP prep.

At that volume, hand-pasting stops being verifiable by eye.
`scripts/push_plan_data_to_sheet.py` and `scripts/pull_plan_data.py` do
it programmatically but need a Google service-account key
(`.google-service-account.json`, gitignored) that does not exist yet.
