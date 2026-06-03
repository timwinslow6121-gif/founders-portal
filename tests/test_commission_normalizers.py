"""
tests/test_commission_normalizers.py

Pure-logic tests for the MemberFact contract and per-carrier normalizers.
Fixtured from real raw commission files in tests/fixtures/commission/.
No database needed.
"""
import os

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "commission")


def test_memberfact_defaults_and_required_fields():
    from app.commission.member_fact import MemberFact, RowClass

    mf = MemberFact(
        carrier="Devoted",
        full_name="ELIZABETH BOLDER",
        first_name="ELIZABETH",
        last_name="BOLDER",
        carrier_member_id="DS97W3",
        row_class=RowClass.CHARGEBACK,
        amount=-347.0,
    )
    assert mf.carrier == "Devoted"
    assert mf.mbi is None                 # optional, defaults None
    assert mf.is_agency_share is False    # defaults False
    assert mf.split_flag is None
    assert mf.row_class == RowClass.CHARGEBACK
    assert mf.amount == -347.0


def test_rowclass_constants_exist():
    from app.commission.member_fact import RowClass
    assert RowClass.ENROLLMENT == "enrollment"
    assert RowClass.RENEWAL == "renewal"
    assert RowClass.CHARGEBACK == "chargeback"
    assert RowClass.NON_CUSTOMER == "non_customer"


def test_load_sheets_xlsx_healthspring():
    from app.commission.sheet_loader import load_sheets
    sheets = load_sheets(os.path.join(FIXTURES, "healthspring_sample.xlsx"))
    assert "Detail" in sheets
    assert "Summary" in sheets
    header = sheets["Detail"][0]
    assert header[0] == "Payment Type"
    assert header[9] == "Medicare Beneficiary Identifier (MBI)"


def test_load_sheets_pk_disguised_as_xls():
    # Devoted per-agent file uses .xls extension but is real XLSX (PK header).
    # The agency Devoted fixture is a true .xlsx; assert loader handles xlsx multi-sheet.
    from app.commission.sheet_loader import load_sheets
    sheets = load_sheets(os.path.join(FIXTURES, "devoted_sample.xlsx"))
    assert "Override" in sheets
    assert "Agent Portion" in sheets
    assert sheets["Agent Portion"][0][17] == "Base Amount"


def test_load_sheets_humana_spreadsheetml():
    from app.commission.sheet_loader import load_sheets
    sheets = load_sheets(os.path.join(FIXTURES, "humana_sample.xls"))
    # Humana SpreadsheetML worksheet name
    assert any("CommissionData" in name for name in sheets)
    name = next(n for n in sheets if "CommissionData" in n)
    header = sheets[name][0]
    assert "WaName" in header        # writing agent
    assert "UMID" in header          # MBI-shaped id
    assert "PaidAmount" in header


def test_normalize_healthspring_collapses_paired_rows():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_healthspring
    from app.commission.member_fact import RowClass

    sheets = load_sheets(os.path.join(FIXTURES, "healthspring_sample.xlsx"))
    facts = normalize_healthspring(sheets)

    assert facts, "expected MemberFacts"
    for f in facts:
        assert f.carrier == "Healthspring"
        assert f.row_class in (RowClass.ENROLLMENT, RowClass.RENEWAL, RowClass.CHARGEBACK)
        # collapsed fact's amount is the agent (Broker Level) share, never the $80 fee alone
        assert f.amount != 80.0 or f.agency_share_amount is None

    # WANDA LONG (member 71A2L3L49) appears as a single collapsed fact
    wanda = [f for f in facts if f.carrier_member_id == "71A2L3L49"]
    assert len(wanda) == 1
    assert wanda[0].mbi == "3AP7QV3RJ37"
    assert wanda[0].row_class == RowClass.ENROLLMENT   # "Initial - New to CMS"
    assert wanda[0].plan_contract == "H9725"
