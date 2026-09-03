"""tests/test_aetna_deceased_capture.py"""
from datetime import date


def test_the_four_death_codes_are_recognised():
    from app.carrier_term_codes import is_aetna_death
    for code in ("08", "NG08", "T090", "090", "QN090", "SBT2"):
        assert is_aetna_death(code), f"{code} should be a death code"


def test_relocation_is_not_death():
    """92 is the MOST COMMON code in the book (79 members) and means RELOCATION
    OUT OF PLAN SERVICE AREA. Treating it as death would suppress 79 living
    members."""
    from app.carrier_term_codes import is_aetna_death
    for code in ("92", "NG92", "092", "QN092"):
        assert not is_aetna_death(code)


def test_other_common_codes_are_not_death():
    from app.carrier_term_codes import is_aetna_death
    for code in ("13", "NG13", "T014", "8888", "", None, "11", "T810"):
        assert not is_aetna_death(code)


def test_matching_ignores_surrounding_whitespace_and_case():
    from app.carrier_term_codes import is_aetna_death
    assert is_aetna_death(" t090 ")
    assert is_aetna_death("ng08")


def test_the_parser_sets_deceased_date_from_the_term_date(tmp_path):
    """Aetna gives no separate death date — the Term Date IS the date of death
    when the reason code says death."""
    import pandas as pd
    from app.parsers.aetna import parse
    p = tmp_path / "aetna.xlsx"
    pd.DataFrame([{
        "Member ID": "NG102285989500", "Medicare Number": "6MV0WK0MP06",
        "First Name": "LINDA", "Last Name": "BOST", "Date of Birth": "1950-03-02",
        "Coverage Effective Date": "2026-01-01", "Member Status": "T",
        "Term Date": "2026-04-30", "Term Reason Code": "08",
        "Plan Name": "Aetna Medicare Value Plus", "CMS Contract Number": "H5521",
        "PBP Code": "081", "City": "Concord", "State": "NC", "Zip Code": "28025",
        "Phone Number": "704-555-0134", "Address Line 1": "1 Main St",
        "Writing Agent NPN": "1234567890",
    }]).to_excel(p, index=False)
    rec = parse(str(p))[0]
    assert rec["deceased_date"] == date(2026, 4, 30)
    assert rec["term_reason_raw"] == "08"


def test_a_non_death_termination_sets_no_deceased_date(tmp_path):
    import pandas as pd
    from app.parsers.aetna import parse
    p = tmp_path / "aetna.xlsx"
    pd.DataFrame([{
        "Member ID": "NG102285989501", "Medicare Number": "6MV0WK0MP07",
        "First Name": "JOHN", "Last Name": "DOE", "Date of Birth": "1950-03-02",
        "Coverage Effective Date": "2026-01-01", "Member Status": "T",
        "Term Date": "2026-04-30", "Term Reason Code": "92",
        "Plan Name": "Aetna Medicare Value Plus", "CMS Contract Number": "H5521",
        "PBP Code": "081", "City": "Concord", "State": "NC", "Zip Code": "28025",
        "Phone Number": "704-555-0135", "Address Line 1": "2 Main St",
        "Writing Agent NPN": "1234567890",
    }]).to_excel(p, index=False)
    rec = parse(str(p))[0]
    assert rec["deceased_date"] is None
    assert rec["term_reason_raw"] == "92"
