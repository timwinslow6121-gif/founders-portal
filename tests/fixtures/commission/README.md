# Commission test fixtures

Trimmed/whole copies of AJ's RAW commission files (2026-06-03), used by
`tests/test_commission_normalizers.py`. Source of truth for per-carrier
column layouts. See `docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md`
"Per-carrier reference" for the verified layouts.

- healthspring_sample.xlsx — 68_486966 (Summary/Detail/Legacy; 10 detail rows, paired Service Fee + Broker Level)
- devoted_sample.xlsx       — Founders Devoted (Total/Override/Agent Portion/HRA sheets)
- bcbs_sample.xlsx          — Brian Freeman BCBS (Sheet1; FY + RENEW + ADJUSTMENT group types)
- aetna_sample.xlsx         — Aetna Founders May 2026 (agency-level multi-agent; Renewal + Pro-Rata)
- humana_sample.xls         — CommissionData (5) (SpreadsheetML 2003 XML, broken `<xml version>` first line)
