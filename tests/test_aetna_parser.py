import os, pytest
from app.parsers.aetna import parse

BASE = "docs/Commission DL/_ARCHIVE_original_messy_files/Commission docs"
AGENCY = f"{BASE}/Aetna - April - Founders Book of Business.xlsx"
AGENT = f"{BASE}/Aetna - Tim Winslow April Book of Business.xlsx"

@pytest.mark.skipif(not os.path.exists(AGENT), reason="real Aetna BOB fixture absent")
def test_per_agent_file_captures_fields():
    recs = parse(AGENT)
    assert len(recs) >= 5
    r = recs[0]
    assert r["carrier"] == "Aetna"
    assert r["mbi"] and r["member_id"] == r["mbi"]
    assert r["carrier_member_id"].startswith("NG")
    assert r["first_name"] and r["last_name"]          # name parsed
    assert " " not in r["first_name"]                  # not the whole "LAST,FIRST"
    assert r["agent_id"]                               # Writing Agent Name present
    assert r["effective_date"] is not None
    assert r["term_date"] is None                      # Aetna BOB has no term col
    assert r["state"] == "NC"
    assert r["plan_name"]                              # Plan ID captured
    assert r["renewal_date"] is not None               # Coverage Period

@pytest.mark.skipif(not os.path.exists(AGENCY), reason="real Aetna BOB fixture absent")
def test_agency_file_parses_and_has_writing_agents():
    recs = parse(AGENCY)
    assert len(recs) >= 5
    # the agency file names multiple agents (Long/Foster/Basinger…)
    agents = {r["agent_id"] for r in recs}
    assert len(agents) >= 2
    assert all(r["effective_date"] is not None for r in recs[:5])

@pytest.mark.skipif(not os.path.exists(AGENT), reason="real Aetna BOB fixture absent")
def test_summary_row_skipped():
    recs = parse(AGENT)
    # the trailing "$202.44 x.55" summary row has no Medicare Number → skipped
    assert all(r["mbi"] for r in recs)


def test_july_xlsx_with_csv_columns_parses(tmp_path):
    """The July 2026 Aetna BOB is an XLSX whose columns match the CSV/per-agent
    format (First Name / Last Name / Middle Initial / Writing Agent First+Last /
    Coverage Effective Date / Member Status / Date of Birth) — NOT the older
    'Member Name' + 'Writing Agent Name' agency shape. It must parse (route to the
    split-column path), not raise 'missing required columns'."""
    import openpyxl
    p = tmp_path / "Aetna Book of Business.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Member ID", "Legacy Member ID", "Medicare Number", "Application ID",
               "First Name", "Middle Initial", "Last Name", "Date of Birth",
               "Phone Number", "Address Line 1", "Address Line 2", "City", "State",
               "Zip Code", "Coverage Effective Date", "Member Status", "Plan Name",
               "Term Date", "Writing Agent NPN", "Writing Agent First Name",
               "Writing Agent Last Name"])
    ws.append(["NG102285989500", "", "2AH6DF6NM54", "DRXB988R1817N",
               "DENISE", "B", "EDDLEMAN", "1961-06-15", "7047871195",
               "10 OLD CONCORD", "", "CHINA GROVE", "NC", "28023",
               "2026-07-01", "A", "Aetna Eagle PPO", "", "12345678",
               "Justin", "Basinger"])
    wb.save(p)
    recs = parse(str(p))
    assert len(recs) == 1
    r = recs[0]
    assert r["carrier"] == "Aetna"
    assert r["mbi"] == "2AH6DF6NM54"
    assert r["first_name"] == "Denise" and r["last_name"] == "Eddleman"
    assert r["dob"] is not None
    assert r["status"] == "active"
    assert r["agent_name"] == "Justin Basinger"
    assert str(r["effective_date"]) == "2026-07-01"
