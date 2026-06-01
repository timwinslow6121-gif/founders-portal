---
status: resolved
trigger: "Commission statements are tagged with upload date instead of actual statement period; duplicate statements can be uploaded with no detection; agents cannot delete statements."
created: 2026-05-07T00:00:00Z
updated: 2026-06-01T00:00:00Z
resolution: "Fixed in commit f661417 (commission admin — statement delete, filename date fallback, period override). All three issues resolved: period now parsed from filename, admin delete route added, duplicate detection improved. Deployed and verified in production."
---

## Current Focus

hypothesis: CONFIRMED — three distinct root causes found and fixed
test: awaiting human verification before deploy
expecting: admin confirms fixes look correct
next_action: user verifies → commit → deploy

## Symptoms

expected: Portal detects actual statement period from file; blocks duplicate carrier+period uploads; allows delete
actual: Statements tagged with upload date (current month); same statement uploaded twice on 2026-04-13 and 2026-05-06 with no warning; $36k gross showing from 13 carriers with BCBS/UHC duplicated; no delete UI
errors: Silent data corruption — wrong period stored, duplicate rows created
reproduction: Upload any carrier commission statement; check period stored vs actual month; upload same file again — no warning
started: Since Phase 3 commission upload was implemented (2026-04-13)

## Eliminated

(none yet)

## Evidence

- timestamp: 2026-05-07T00:00:00Z
  checked: app/commission/routes.py parsers (_parse_bcbs, _parse_healthspring, _parse_wellable)
  found: BCBS line 208 sets stmt_date = date.today() as the default/initial value (not None), so it never gets corrected from file content. Healthspring line 302 and Wellable line 340 both fallback to date.today() when no date found in data. commission_upload() line 543-544 also falls back: `if not stmt_date: stmt_date = date.today()`. period_label is derived at line 563 via strftime.
  implication: Any carrier whose parser doesn't successfully parse a date from file content gets period_label = upload month, not statement month.

- timestamp: 2026-05-07T00:00:00Z
  checked: models.py CommissionStatement.__table_args__ and commission_upload() upsert logic
  found: Unique constraint on (carrier, agent_id, period_label) exists. Upsert at lines 583-589 looks up by carrier+agent_id+period_label+agency_id. BUT if the same file uploaded twice produces the same wrong period_label (both uploads happen in same month), the upsert will UPDATE the existing row rather than inserting a duplicate — so technically duplicates only appear when uploads happen in DIFFERENT calendar months. This explains April 2026 upload + May 2026 upload = two rows with different period_labels.
  implication: The dedup works ONLY when the wrong period_label accidentally matches. When period_label is derived from upload date and uploads span months, you get duplicate rows with different (wrong) period_labels.

- timestamp: 2026-05-07T00:00:00Z
  checked: app/commission/routes.py — all routes
  found: No DELETE route exists. commission_upload() has POST, commission_index/admin/agent_detail are GETs, override/review/close are POSTs. No route for removing a statement.
  implication: No way to delete mistakenly uploaded or duplicate statements.

- timestamp: 2026-05-07T00:00:00Z
  checked: app/templates/commission.html
  found: No delete button or form anywhere in the template. Admin recent uploads table shows carrier/period/status but no action column.
  implication: Even if a delete route existed, there is no UI to trigger it.

## Resolution

root_cause: Three issues: (1) BCBS parser initializes stmt_date=date.today() instead of None, so the fallback never fires; parsers for Healthspring/Wellable/UHC/Aetna/Humana/Devoted may also fail to extract date from some file formats; final fallback in commission_upload() uses date.today(). (2) The upsert dedup works by carrier+agent+period_label, but if period_label is wrong (= upload date), same statement uploaded in different calendar months creates two separate rows — the dedup only works if period_label accidentally collides. (3) No DELETE route or UI exists.
fix: |
  (1) BCBS parser: stmt_date=date.today() → stmt_date=None.
      Healthspring/Wellable: removed date.today() fallback inside parsers (was already at end of parser).
      commission_upload(): added 4-tier fallback: (a) form field "statement_month" (YYYY-MM) overrides all,
      (b) date from file content (parser result), (c) _parse_date_from_filename() extracts from filename
      patterns like "UHC_March_2026.xlsx" or "2026-04_Humana.xlsx", (d) last resort: date.today() + flash warning.
  (2) Duplicate upsert: added _was_update flag. When existing statement found, flash warning
      "already uploaded — re-uploading will overwrite". Also clears old PolicyPayment rows via
      DELETE WHERE statement_id=stmt.id before rebuilding from file, preventing ghost ledger rows.
  (3) DELETE route: POST /admin/commissions/<stmt_id>/delete — cascades to PolicyPayment rows,
      protected by agency_id scoping + admin guard. Delete buttons (✕) added to both
      "Recent Uploads" table and "Agent Commission Summary" table in commission.html, with confirm() dialog.
  Upload form: added <input type="month" name="statement_month"> with explanatory label.
  No schema migration needed — no DB columns added.
verification: awaiting human confirmation
files_changed: [app/commission/routes.py, app/templates/commission.html]
