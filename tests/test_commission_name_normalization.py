"""
tests/test_commission_name_normalization.py

Verifies every customer-bearing commission MemberFact name is routed through
app.names.normalize_person_name, so the parked-payment / needs-identity hub
shows clean "First MI. Last" names regardless of carrier raw-file shape.
"""


def test_commission_names_are_first_mi_last(app):
    """Each carrier's raw name shape normalizes to 'First MI. Last'."""
    from app.names import normalize_person_name
    # sanity: the normalizer itself (the standard we route through)
    assert normalize_person_name("CONNELLY, JOHN J.")[3] == "John J. Connelly"
    assert normalize_person_name("BRYANT D,KATHERINE")[3] == "Katherine D. Bryant"
    assert normalize_person_name("jane doe")[3] == "Jane Doe"


def test_aetna_normalizer_emits_clean_name(app):
    from app.commission.normalizers import normalize_aetna
    # one Aetna row: name in col4 = "CONNELLY, JOHN J."
    row = [None] * 21
    row[1] = "4RH5X85DC65"; row[2] = "M123"; row[4] = "CONNELLY, JOHN J."
    row[9] = "H1036-335"; row[12] = "2026-06-01"; row[16] = "Tim Winslow"; row[20] = 28.92
    sheets = {"Founders": [["header"], row]}
    facts = normalize_aetna(sheets)
    assert facts and facts[0].full_name == "John J. Connelly"
    assert facts[0].first_name == "John" and facts[0].last_name == "Connelly"


def test_uhc_normalizer_emits_clean_name(app):
    from app.commission.normalizers import normalize_uhc

    header = [""] * 24
    header[4] = "Writing Agent ID"; header[7] = "Member Name"; header[8] = "MedicareID"
    header[12] = "Plan Type"; header[19] = "Commission Action"; header[23] = "Commission"

    def row(member, amt):
        r = [""] * 24
        r[4] = "6435806"; r[7] = member; r[8] = "1AB2CD3EF45"
        r[12] = "MAPD"; r[19] = "Renewal"; r[23] = amt
        return r

    sheets = {"Commission Transactions": [header, row("CONNELLY, JOHN J.", 28.92)]}
    facts = normalize_uhc(sheets, writing_id_to_name={"6435806": "Rebekah Long"})
    assert len(facts) == 1
    assert facts[0].full_name == "John J. Connelly"
    assert facts[0].first_name == "John" and facts[0].last_name == "Connelly"


def test_humana_normalizer_emits_clean_name(app):
    from app.commission.normalizers import normalize_humana

    header = ["UMID", "GrpName", "PaidAmount", "PID", "EffDate", "Contract",
              "TxnTypeCd", "WaName"]
    row = ["5EN4NW3VF63", "CONNELLY JOHN", 231.33, "P1", "2026-01-01",
           "H5525", "ARCF", "Tim Winslow"]
    sheets = {"CommissionData": [header, row]}
    facts = normalize_humana(sheets)
    assert facts and facts[0].full_name == "John Connelly"
    assert facts[0].first_name == "John" and facts[0].last_name == "Connelly"
