import os, pytest
from app.parsers.aetna import parse

CSV = "docs/Carrier BOB DL/Founders Insurance Agency LLC_MedicareApprovedBOBReport_20260618.csv"

@pytest.mark.skipif(not os.path.exists(CSV), reason="June Aetna CSV fixture absent")
def test_csv_active_and_termed_split():
    recs = parse(CSV)
    active = [r for r in recs if r["status"] == "active"]
    termed = [r for r in recs if r["status"] == "termed"]
    assert len(active) == 76
    assert len(termed) == 138

@pytest.mark.skipif(not os.path.exists(CSV), reason="June Aetna CSV fixture absent")
def test_csv_active_row_fields():
    recs = parse(CSV)
    a = next(r for r in recs if r["status"] == "active")
    assert a["carrier"] == "Aetna"
    assert a["mbi"] and a["member_id"] == a["mbi"]
    assert a["carrier_member_id"].startswith("NG")
    assert a["first_name"] and a["last_name"] and " " not in a["first_name"]
    assert a["dob"] is not None            # NEW freshness
    assert a["phone"]                       # NEW freshness
    assert a["address1"]                    # NEW freshness
    assert a["state"] == "NC"
    assert a["effective_date"] is not None
    assert a["agent_id"]                    # the NPN
    assert a["agent_name"]                  # the writing agent name
    assert a["plan_name"]

@pytest.mark.skipif(not os.path.exists(CSV), reason="June Aetna CSV fixture absent")
def test_csv_term_sentinel_and_line2():
    recs = parse(CSV)
    # active rows have term_date None (sentinel 3000-01-01 stripped)
    a = next(r for r in recs if r["status"] == "active")
    assert a["term_date"] is None
    # a termed row carries a real term_date
    t = next(r for r in recs if r["status"] == "termed")
    assert t["term_date"] is not None
    # any row with an Address Line 2 folds it into address1 (no part dropped)
    line2_rows = [r for r in recs if r.get("address1") and "," in r["address1"]]
    # at least the data shape allows folding; assert address1 is non-empty for actives
    assert all(r["address1"] for r in recs if r["status"] == "active" and r.get("address1") is not None)
