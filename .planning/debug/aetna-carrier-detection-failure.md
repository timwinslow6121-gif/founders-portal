---
status: resolved
trigger: "Aetna commission CSV file is not being detected as Aetna by the carrier detection logic"
created: 2026-05-08T00:00:00
updated: 2026-06-01T00:00:00
resolution: "Fixed in commits de67e23 (Aetna commission upload — agency-level statement + correct column indices) and f2b5ef9 (Aetna per-row agent attribution in payment ledger). Deployed and verified in production."
---

## Current Focus

hypothesis: Two bugs — (1) commission_upload() calls openpyxl.load_workbook() on a CSV file, which throws an exception causing silent redirect before _detect_carrier() is ever called. (2) Even if the file were an XLSX, _detect_carrier() reads ws[1] (row 1, openpyxl 1-indexed) correctly, and the Aetna fingerprint "payee amount" + "sales event" would match. Bug #1 is the primary failure; bug #2 (_parse_aetna column indices) is a secondary parsing bug that would surface after detection is fixed.
test: Read commission_upload() to confirm it calls openpyxl.load_workbook() without CSV handling; verify _detect_carrier() fingerprint against actual CSV headers; check _parse_aetna column indices against actual file layout.
expecting: openpyxl.load_workbook() raises InvalidFileException on a CSV, caught by bare except, flashes "Could not read file" and redirects. Detection never runs.
next_action: confirmed — proceed to fix

## Symptoms

expected: Upload April 2026 Aetna CSV → detected as "Aetna" → _parse_aetna runs → commission line items created
actual: Carrier not detected / file misidentified or rejected (silent failure)
errors: None reported (silent detection failure — likely "Could not read file" flash)
reproduction: Upload Aetna April 2026 CSV via commission upload UI
started: First attempt ever

## Eliminated

- hypothesis: _detect_carrier() fingerprint for Aetna doesn't match the headers
  evidence: Actual CSV headers include "payee amount" and "sales event" — both fingerprint tokens present. Detection WOULD pass if the file reached that function.
  timestamp: 2026-05-08

## Evidence

- timestamp: 2026-05-08
  checked: commission_upload() in routes.py lines 523-529
  found: Loads file with openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True) — no CSV handling branch. If file is .csv, openpyxl raises InvalidFileException. Caught by bare except → flash "Could not read file" → redirect.
  implication: PRIMARY BUG — CSV files are completely rejected before detection runs. Fix: detect CSV by extension/sniff and use csv.reader instead of openpyxl.

- timestamp: 2026-05-08
  checked: _detect_carrier() line 345 — reads ws[1] (openpyxl 1-indexed = row 1 = header row)
  found: Aetna fingerprint: "payee amount" in header_str AND "sales event" in header_str. Actual CSV row 0 headers include "Payee Amount" and "Sales Event" — both present. Detection would succeed once file is loaded correctly.
  implication: Detection logic is correct. Only the loading step needs to be fixed.

- timestamp: 2026-05-08
  checked: _parse_aetna() lines 135-163 — col indices
  found: agent=col9 reads "Writing Agent NPN" (NPN number, not name). Actual Writing Agent Name is col16. Payee Amount is col20, not col10. stmt_date uses row[7] (Product, not a date). Action uses row[5] (Member State). Member uses row[3] (Legacy Member ID). These column indices are completely wrong for the April 2026 format.
  implication: SECONDARY BUG — even after detection is fixed, _parse_aetna() will produce garbage data (zeros for amounts, wrong member names, wrong agent detection). All column indices need updating to match actual file.

- timestamp: 2026-05-08
  checked: _detect_agent_id() Aetna col_idx = 9
  found: col9 = "Writing Agent NPN" (numeric NPN like "20182775"), not a name. _normalize_name("20182775") = "20182775" which won't match any user.name. Agent detection will fail for Aetna.
  implication: TERTIARY BUG — agent detection uses wrong column. Must use col16 (Writing Agent Name).

## Resolution

root_cause: Three layered bugs: (1) commission_upload() uses openpyxl exclusively — CSV files throw InvalidFileException before any parsing begins. (2) _parse_aetna() uses col9/col10 but actual file has agent name at col16 and Payee Amount at col20. (3) _detect_agent_id() Aetna mapping also points to col9 (NPN) instead of col16 (name).
fix: (1) Added _csv_bytes_to_workbook() helper that reads CSV bytes via csv.reader and writes into an openpyxl Workbook, then commission_upload() branches on .csv extension to use it instead of openpyxl.load_workbook(). (2) Rewrote _parse_aetna() with correct columns: amount=col20, mbi=col1, member=col4, plan=col9, eff_date=col12, action=col6, stmt_date from col0 (string "YYYY-MM-DD"), added string-to-float conversion for CSV string values, added footer row skip. (3) Fixed _detect_agent_id() Aetna col from 9 to 16 (Writing Agent Name).
verification: Syntax check passed. Awaiting human upload test.
files_changed: [app/commission/routes.py]
