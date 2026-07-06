"""UHC BOB parser tests — covers the agent-centric July-2026 format that carries
NO member identifier (no mbiNumber / member_id), only name + DOB + planStatus."""
import openpyxl
from app.parsers.uhc import parse


def _july_uhc_xlsx(tmp_path, rows):
    """Build a July-format UHC BOB: row0 blank, row1 notice, row2 headers, data.
    Columns match the real July file (no mbiNumber; planStatus drives active/termed)."""
    p = tmp_path / "UHC book of business.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append([])                                   # row0 blank
    ws.append(["Note: confidential"])               # row1 notice
    ws.append(["agentId", "agentEmail", "agentName", "agentIdStatus", "agentNpn",
               "memberFirstName", "memberLastName", "memberAddress1", "memberCity",
               "memberZip", "memberState", "dateOfBirth", "memberStatus", "memberPhone",
               "product", "planStatus", "policyTermDate", "planName"])  # row2 headers
    for r in rows:
        ws.append(r)
    wb.save(p)
    return str(p)


def test_july_no_mbi_format_parses_with_name_dob_key(tmp_path):
    """The July UHC BOB has no MBI/member_id. Parser must still import: synthesize a
    stable member_id from name+DOB, set status from planStatus (A=active), and NOT
    raise 'missing required columns: mbiNumber'."""
    p = _july_uhc_xlsx(tmp_path, [
        ["6448551", "j@x.com", "BASINGER, JUSTIN", "Active", "20446812",
         "JANIS", "MOSIER", "2676 BRACKLEY PL", "CONCORD", "28027", "NC",
         "08/21/1961", "", "704-533-0906", "MA", "A", "2300-01-01",
         "AARP Medicare Advantage"],
        # a termed member: planStatus 'T'
        ["6448551", "j@x.com", "BASINGER, JUSTIN", "Active", "20446812",
         "JOHN", "DOE", "1 MAIN ST", "CONCORD", "28027", "NC",
         "01/02/1955", "", "704-000-0000", "MA", "T", "2026-05-01",
         "AARP Medicare Advantage"],
    ])
    recs = parse(p)
    assert len(recs) == 2
    r = recs[0]
    assert r["carrier"] == "UHC"
    assert r["first_name"] == "Janis" and r["last_name"] == "Mosier"
    assert r["dob"] is not None
    # a stable, non-empty member_id was synthesized (DB requires non-null member_id)
    assert r["member_id"] and r["member_id"].strip()
    # same person → same synthesized member_id (stable across re-import)
    r2 = parse(p)[0]
    assert r2["member_id"] == r["member_id"]
    assert r["status"] == "active"                  # planStatus A
    assert recs[1]["status"] == "termed"            # planStatus T


def test_july_two_different_members_get_different_ids(tmp_path):
    """Distinct name+DOB → distinct synthesized member_id (no collision/merge)."""
    p = _july_uhc_xlsx(tmp_path, [
        ["1", "", "", "", "", "JANIS", "MOSIER", "", "", "", "NC", "08/21/1961",
         "", "", "MA", "A", "2300-01-01", "X"],
        ["1", "", "", "", "", "JANIS", "MOSIER", "", "", "", "NC", "03/03/1970",
         "", "", "MA", "A", "2300-01-01", "X"],
    ])
    recs = parse(p)
    assert recs[0]["member_id"] != recs[1]["member_id"]


def test_old_mbi_format_still_parses(tmp_path):
    """The older UHC BOB with mbiNumber must still work (keyed on the real MBI)."""
    p = tmp_path / "UHC old.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append([]); ws.append(["Note"])
    ws.append(["mbiNumber", "memberFirstName", "memberLastName", "dateOfBirth",
               "policyEffectiveDate", "policyTermDate", "product", "planName", "agentId"])
    ws.append(["8QV9Q10TC36", "JANIS", "MOSIER", "08/21/1961", "2026-01-01",
               "2300-01-01", "MA", "AARP MA", "6448551"])
    wb.save(p)
    recs = parse(str(p))
    assert len(recs) == 1
    assert recs[0]["mbi"] == "8QV9Q10TC36"
    assert recs[0]["member_id"] == "8QV9Q10TC36"
