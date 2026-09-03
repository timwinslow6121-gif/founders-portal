"""tests/test_humana_deceased_capture.py"""
from datetime import date


def test_the_parser_emits_a_deceased_date(tmp_path):
    import pandas as pd
    from app.parsers.humana import parse
    p = tmp_path / "humana.xlsx"
    pd.DataFrame([{
        "MbrFirstName": "JEANETTE", "MbrLastName": "EVANS", "Humana ID": "H59692289",
        "Medicare No": "XXXXXN4FP75", "Birth Date": "3/11/1949", "Status": "Active Policy",
        "Effective Date": "1/1/2026", "Inactive Date": "8/31/2026",
        "Deceased Date": "8/11/2026", "Plan Name": "HUMANA GOLD PLUS HMO POS",
        "Plan Type": "MA", "Contract-PBP-Segment ID": "H1036-335-002",
        "Mail City": "Concord", "Mail State": "NC", "Mail ZipCd": "28025",
        "Mail Cnty": "CABARRUS", "Primary Phone": "704-555-0134",
        "Mail Address": "1 Main St",
    }]).to_excel(p, index=False)
    recs = parse(str(p))
    assert recs[0]["deceased_date"] == date(2026, 8, 11)


def test_a_blank_deceased_date_is_none(tmp_path):
    import pandas as pd
    from app.parsers.humana import parse
    p = tmp_path / "humana.xlsx"
    pd.DataFrame([{
        "MbrFirstName": "ROBERT", "MbrLastName": "HAMRICK", "Humana ID": "H63268953",
        "Medicare No": "XXXXXN4FP76", "Birth Date": "3/11/1949", "Status": "Active Policy",
        "Effective Date": "1/1/2026", "Inactive Date": "", "Deceased Date": "",
        "Plan Name": "HUMANA GOLD PLUS HMO POS", "Plan Type": "MA",
        "Contract-PBP-Segment ID": "H1036-335-002", "Mail City": "Concord",
        "Mail State": "NC", "Mail ZipCd": "28025", "Mail Cnty": "CABARRUS",
        "Primary Phone": "704-555-0135", "Mail Address": "2 Main St",
    }]).to_excel(p, index=False)
    assert parse(str(p))[0]["deceased_date"] is None
