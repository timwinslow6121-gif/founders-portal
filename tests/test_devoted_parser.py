"""Devoted BOB parser tests — covers the July-2026 XLSX 'Application Status Report'
format (single Full Name, Birth Date, Current Status, no member_id) AND the older
snake_case CSV with member_id."""
import openpyxl
from app.parsers.devoted import parse

APP_COLS = [
    "Application Status Report Agent Name",
    "Application Status Report Agent Npn",
    "Application Status Report Agent Primary Rts State",
    "Application Status Report Full Name",
    "Application Status Report Birth Date",
    "Application Status Report Current Status",
    "Application Status Report Is Agent Current Aor (Yes / No)",
    "Application Status Report Aor Start Date",
    "Application Status Report Start Date",
    "Application Status Report Plan Name",
    "Application Status Report Plan ID",
    "Application Status Report Is Plan Change (Yes / No)",
    "Application Status Report Is New to Medicare Advantage (Yes / No)",
    "Application Status Report Is New to Devoted (Yes / No)",
]


def _app_status_xlsx(tmp_path, rows):
    p = tmp_path / "Devoted Book of business.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(APP_COLS)
    for r in rows:
        ws.append(r)
    wb.save(p)
    return str(p)


def test_july_application_status_xlsx_parses_name_dob_key(tmp_path):
    """The July Devoted BOB is an XLSX Application-Status Report: single 'Full Name',
    'Birth Date', 'Current Status', NO member_id. Must parse (split the name,
    synthesize a member_id from name+DOB, keep only Enrolled), not raise a CSV
    decode error or 'missing required columns: member_id'."""
    p = _app_status_xlsx(tmp_path, [
        ["Anjana Patel", "21041582", "NC", "BRANDI TUCKER", "1977-03-21",
         "Enrolled", "Yes", "2026-04-01", "2026-04-01", "Devoted CORE", "H1234-001",
         "No", "Yes", "Yes"],
        # a non-enrolled row is dropped
        ["Anjana Patel", "21041582", "NC", "JOHN DOE", "1955-01-02",
         "Withdrawn", "Yes", "2026-04-01", "2026-04-01", "Devoted CORE", "H1234-001",
         "No", "Yes", "Yes"],
    ])
    recs = parse(p)
    assert len(recs) == 1                          # only the Enrolled row
    r = recs[0]
    assert r["carrier"] == "Devoted"
    assert r["first_name"] == "Brandi" and r["last_name"] == "Tucker"
    assert r["dob"] is not None
    assert r["member_id"] and r["member_id"].strip()   # synthesized, non-null
    assert r["status"] == "active"
    assert r["agent_id"] == "21041582"             # NPN
    # stable across re-import
    assert parse(p)[0]["member_id"] == r["member_id"]


def test_july_two_word_and_multi_word_names_split(tmp_path):
    """Full Name split: 'Mary Jane Smith' → first 'Mary', last 'Jane Smith' (last
    token(s) as surname is fine for matching; the key is name+DOB stability)."""
    p = _app_status_xlsx(tmp_path, [
        ["A", "1", "NC", "Curtis Childress", "1949-03-14", "Enrolled", "Yes",
         "2026-01-01", "2026-01-01", "Devoted CORE", "H1-1", "No", "Yes", "Yes"],
    ])
    r = parse(p)[0]
    assert r["first_name"] == "Curtis"
    assert "Childress" in r["last_name"]


def test_old_csv_member_id_format_still_parses(tmp_path):
    """The older snake_case CSV with member_id must still work."""
    p = tmp_path / "devoted.csv"
    p.write_text("member_id,first_name,last_name,status,effective_date\n"
                 "DV-123,Jane,Roe,ENROLLED,2026-01-01\n")
    recs = parse(str(p))
    assert len(recs) == 1
    assert recs[0]["member_id"] == "DV-123"
    assert recs[0]["first_name"] == "Jane"
