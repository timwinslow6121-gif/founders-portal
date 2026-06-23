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
