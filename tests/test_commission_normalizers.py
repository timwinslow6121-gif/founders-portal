"""
tests/test_commission_normalizers.py

Pure-logic tests for the MemberFact contract and per-carrier normalizers.
Fixtured from real raw commission files in tests/fixtures/commission/.
No database needed.
"""
import os
import pytest

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

    # WANDA LONG (member 71A2L3L49) appears as a single collapsed fact
    wanda = [f for f in facts if f.carrier_member_id == "71A2L3L49"]
    assert len(wanda) == 1
    assert wanda[0].mbi == "3AP7QV3RJ37"
    assert wanda[0].row_class == RowClass.ENROLLMENT   # "Initial - New to CMS"
    assert wanda[0].plan_contract == "H9725"

    # 63X7U5U84 is genuinely PAIRED: a Service Fee ($80) row + a Broker Level
    # ($231.33) row collapse into ONE fact carrying both shares.
    paired = [f for f in facts if f.carrier_member_id == "63X7U5U84"]
    assert len(paired) == 1
    assert paired[0].agency_share_amount == 80.0   # Service Fee row folded in
    assert paired[0].amount == 231.33              # Broker Level (agent) share


def test_normalize_devoted_collapses_and_flags_chargebacks():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_devoted
    from app.commission.member_fact import RowClass

    sheets = load_sheets(os.path.join(FIXTURES, "devoted_sample.xlsx"))
    facts = normalize_devoted(sheets)
    assert facts

    # Elizabeth Bolder (DS97W3): eff 01/01/2026, disenroll 03/31/2026, Base -347 = chargeback
    bolder = [f for f in facts if f.carrier_member_id == "DS97W3"]
    assert len(bolder) == 1
    assert bolder[0].carrier == "Devoted"
    assert bolder[0].row_class == RowClass.CHARGEBACK
    assert bolder[0].amount == -347.0
    assert bolder[0].term_date is not None

    # Rene Barger (DGFY27): Apr enrollment, Base 260.25, no disenroll
    barger = [f for f in facts if f.carrier_member_id == "DGFY27"]
    assert len(barger) == 1
    assert barger[0].row_class == RowClass.ENROLLMENT
    assert barger[0].amount == 260.25
    assert barger[0].agency_share_amount == 125.0   # Override row for same member


def test_normalize_devoted_hra_is_non_customer():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_devoted
    from app.commission.member_fact import RowClass

    sheets = load_sheets(os.path.join(FIXTURES, "devoted_sample.xlsx"))
    facts = normalize_devoted(sheets)
    hras = [f for f in facts if f.row_class == RowClass.NON_CUSTOMER]
    assert hras, "expected HRA bonus rows as NON_CUSTOMER"
    assert all(f.carrier_member_id is None for f in hras)
    assert all(f.amount == 50.0 for f in hras)


def test_normalize_bcbs_group_types_and_no_mbi():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_bcbs
    from app.commission.member_fact import RowClass

    sheets = load_sheets(os.path.join(FIXTURES, "bcbs_sample.xlsx"))
    facts = normalize_bcbs(sheets)
    assert facts
    for f in facts:
        assert f.carrier == "BCBS"
        assert f.mbi is None                     # BCBS never has MBI
        assert f.carrier_member_id                # always a Customer No

    classes = {f.carrier_member_id: f.row_class for f in facts}
    # Buchanan,Andrea M 106815011 is FY → ENROLLMENT
    assert classes.get("106815011") == RowClass.ENROLLMENT
    # Allen,Brenda M 106729743 is RENEW → RENEWAL
    assert classes.get("106729743") == RowClass.RENEWAL


def test_normalize_bcbs_skips_total_row():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_bcbs
    sheets = load_sheets(os.path.join(FIXTURES, "bcbs_sample.xlsx"))
    facts = normalize_bcbs(sheets)
    assert all("total" not in f.full_name.lower() for f in facts)


def test_normalize_bcbs_real_14col_layout():
    """FAILING TEST (TDD): synthetic 14-col sheet (no 'Customer Type' col)
    must parse correctly — name from col 3, customer_no from col 4, commission
    from col 13.  The old fixed-index parser reads col 4/5/14 and skips ALL
    rows via the len(row) <= 14 guard, returning [].  The header-based parser
    must return 2 facts with the correct attributes.
    """
    from app.commission.normalizers import normalize_bcbs
    from app.commission.member_fact import RowClass

    hdr = [
        "Agent #", "Agent Name", "Group Type", "Customer Name",
        "Customer No", "ORIGEFFDATE", "Product", "COVERAGEFROM",
        "COVERAGETO", "Premium Period", "Orig Sub Count", "Renewal_Date",
        "Billed Amount", "Commission",
    ]
    rows_14col = [
        hdr,
        # FY row -> ENROLLMENT, commission col 13
        ["P0056227", "TIMOTHY WINSLOW", "FY", "Sanders,Sharon L",
         "106811352", "01/01/2026", "Blue Medicare Freedom+ (PPO)",
         "01/01/2026", "", "2026-06-01", 1, "01/01/2026", 0, 28.91],
        # RENEW row -> RENEWAL
        ["P0056227", "TIMOTHY WINSLOW", "RENEW", "Doe,John A",
         "106999001", "01/01/2025", "Blue Medicare Freedom+ (PPO)",
         "01/01/2025", "", "2026-06-01", 1, "01/01/2025", 0, 28.91],
        # Total row (no name / no customer no) -> skipped
        ["", "", "", "", "", "", "", "", "", "", "", "", 0, 57.82],
    ]
    sheets = {"Sheet1": rows_14col}
    facts = normalize_bcbs(sheets)
    assert len(facts) == 2, (
        f"expected 2 facts from 14-col BCBS sheet, got {len(facts)} — "
        "header-based column resolution required"
    )
    classes = {f.carrier_member_id: f.row_class for f in facts}
    assert classes.get("106811352") == RowClass.ENROLLMENT, "FY row must be ENROLLMENT"
    assert classes.get("106999001") == RowClass.RENEWAL, "RENEW row must be RENEWAL"
    amounts = {f.carrier_member_id: f.amount for f in facts}
    assert amounts["106811352"] == 28.91
    assert amounts["106999001"] == 28.91


def test_normalize_bcbs_missing_commission_column_raises_specific_error():
    """If a required column can't be resolved (BCBS/Tidewater format changed),
    the parser must raise a LOUD, SPECIFIC error naming the missing column —
    not silently return [] (which produced the vague 'No commission rows found')."""
    from app.commission.normalizers import normalize_bcbs, BcbsColumnError
    hdr = ["Agent #", "Agent Name", "Group Type", "Customer Name",
           "Customer No", "Product"]                       # NO Commission column
    sheets = {"Sheet1": [hdr, ["P1", "AGENT", "FY", "Doe,Jane", "123", "MAPD"]]}
    with pytest.raises(BcbsColumnError) as exc:
        normalize_bcbs(sheets)
    assert "commission" in str(exc.value).lower()
    assert "headers seen" in str(exc.value).lower()


def test_normalize_bcbs_alias_tolerates_renamed_commission_header():
    """A Tidewater header wording variant ('Commission Amount') still resolves."""
    from app.commission.normalizers import normalize_bcbs
    hdr = ["Agent #", "Agent Name", "Group Type", "Customer Name",
           "Customer No", "Commission Amount"]
    sheets = {"Sheet1": [hdr, ["P1", "AGENT", "FY", "Doe,Jane", "123", 42.5]]}
    facts = normalize_bcbs(sheets)
    assert len(facts) == 1
    assert facts[0].amount == 42.5


def test_normalize_aetna_sales_events_and_mbi():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_aetna
    from app.commission.member_fact import RowClass

    sheets = load_sheets(os.path.join(FIXTURES, "aetna_sample.xlsx"))
    facts = normalize_aetna(sheets)
    assert facts
    for f in facts:
        assert f.carrier == "Aetna"

    # BOBBY ADERHOLD (6CM1RV8NW05) Renewal 28.92
    aderhold = [f for f in facts if f.mbi == "6CM1RV8NW05"]
    assert len(aderhold) >= 1
    assert aderhold[0].row_class == RowClass.RENEWAL
    assert aderhold[0].plan_contract == "H3146"
    assert aderhold[0].plan_pbp == "006"

    # DAVID BURNER (1KR6UW2KP73) has a Pro-Rata Disenroll of -347 → chargeback
    burner_cb = [f for f in facts if f.mbi == "1KR6UW2KP73" and f.amount < 0]
    assert burner_cb
    assert burner_cb[0].row_class == RowClass.CHARGEBACK


def test_normalize_humana_txntype_taxonomy():
    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_humana
    from app.commission.member_fact import RowClass

    sheets = load_sheets(os.path.join(FIXTURES, "humana_sample.xls"))
    facts = normalize_humana(sheets)
    assert facts
    for f in facts:
        assert f.carrier == "Humana"

    # VILLEGAS ANASTACIO Z (UMID 5EN4NW3VF63) ARCF first-year +231.33 → enrollment
    vill = [f for f in facts if f.mbi == "5EN4NW3VF63"]
    assert vill and vill[0].row_class == RowClass.ENROLLMENT
    assert vill[0].amount == 231.33

    # MURRAY member (UMID 8QV9Q10TC36) ARCF but -231.33 → chargeback (negative wins)
    murray = [f for f in facts if f.mbi == "8QV9Q10TC36"]
    assert murray and murray[0].row_class == RowClass.CHARGEBACK

    # at least one ARCM renewal present
    assert any(f.row_class == RowClass.RENEWAL for f in facts)


def test_normalizer_registry_dispatch():
    from app.commission.normalizers import NORMALIZERS
    for carrier in ("Healthspring", "Devoted", "BCBS", "Aetna", "Humana"):
        assert carrier in NORMALIZERS
        assert callable(NORMALIZERS[carrier])


def test_normalize_devoted_statement_format():
    import os
    from app.commission.normalizers import normalize_devoted
    from app.commission.member_fact import RowClass
    from app.commission.sheet_loader import load_sheets
    FIX = os.path.join(os.path.dirname(__file__), "fixtures", "commission")
    sheets = load_sheets(os.path.join(FIX, "devoted_statement_sample.xlsx"))
    facts = normalize_devoted(sheets)

    detail = [f for f in facts if f.row_class in (RowClass.RENEWAL, RowClass.ENROLLMENT, RowClass.CHARGEBACK)
              and f.carrier_member_id]
    hra = [f for f in facts if f.row_class == RowClass.NON_CUSTOMER]
    assert len(detail) == 2
    assert len(hra) == 8
    assert all(f.source_ref.startswith("devoted::npn20182775::") for f in facts)
    assert all(f.amount < 0 for f in hra)   # negative HRA clawbacks


def test_normalize_devoted_agency_source_refs_file_tagged():
    import os
    from app.commission.normalizers import normalize_devoted
    from app.commission.sheet_loader import load_sheets
    FIX = os.path.join(os.path.dirname(__file__), "fixtures", "commission")
    sheets = load_sheets(os.path.join(FIX, "devoted_sample.xlsx"))
    facts = normalize_devoted(sheets)
    assert facts
    assert all(f.source_ref.startswith("devoted::agency::") for f in facts)


# ── UHC normalizer (raw 'Commission Transactions' sheet) ──────────────────

# Column layout of the raw UHC statement (verified against the real file):
#  5 Writing Agent Name | 7 Member Name | 8 MedicareID | 11 Orig Eff Date
#  12 Plan Type | 13 Contract | 14 PBP | 19 Commission Action | 23 Commission
_UHC_HEADER = (
    ["Party ID", "Agent Name", "Agent ID", "Statement Date", "Writing Agent ID",
     "Writing Agent Name", "Client Reference #", "Member Name", "MedicareID",
     "AARP Member ID", "Policy Number", "Original Effective Date", "Plan Type",
     "Contract", "PBP", "Plan Code", "Member State", "Area ID", "Member County",
     "Commission Action", "Payment Period", "Prem Amount", "UAD Activity", "Commission"]
)


def _uhc_row(agent="WINSLOW, TIMOTHY", member="DOE, JANE", mbi="1AB2CD3EF45",
             plan_type="MAPD", contract="H5253", pbp="037", action="Renewal",
             amount=33.51, eff="2025-01-01"):
    r = [""] * 24
    r[5] = agent; r[7] = member; r[8] = mbi; r[11] = eff
    r[12] = plan_type; r[13] = contract; r[14] = pbp
    r[19] = action; r[23] = amount
    return r


def test_classify_uhc_chargeback_renewal_enrollment():
    from app.commission.normalizers import _classify_uhc
    from app.commission.member_fact import RowClass
    M = "DOE, JANE"   # a named member (else the nameless→NON_CUSTOMER rule applies)
    assert _classify_uhc("New Chargeback", -268.0, "MAPD", M) == RowClass.CHARGEBACK
    assert _classify_uhc("Renewal", 33.51, "MAPD", M) == RowClass.RENEWAL
    assert _classify_uhc("New", 250.0, "MAPD", M) == RowClass.ENROLLMENT
    # any negative is a chargeback even if action says otherwise
    assert _classify_uhc("Renewal", -33.51, "MAPD", M) == RowClass.CHARGEBACK


def test_classify_uhc_ha_and_override_and_dust_are_non_customer():
    """HA bonus, pure override ($4.59), and PARTD dust must NOT create customers."""
    from app.commission.normalizers import _classify_uhc
    from app.commission.member_fact import RowClass
    M = "DOE, JANE"
    assert _classify_uhc("HA Payment", 50.0, "MAPD", M) == RowClass.NON_CUSTOMER
    assert _classify_uhc("Renewal", 4.59, "MAPD", M) == RowClass.NON_CUSTOMER   # override-only
    assert _classify_uhc("Renewal", 0.26, "PARTD", M) == RowClass.NON_CUSTOMER  # dust


def test_normalize_uhc_reduces_sheet_to_member_facts():
    from app.commission.normalizers import normalize_uhc
    from app.commission.member_fact import RowClass
    sheets = {"Commission Transactions": [
        _UHC_HEADER,
        _uhc_row(agent="WINSLOW, TIMOTHY", member="DOE, JANE", mbi="1AB2CD3EF45",
                 action="Renewal", amount=33.51),
        _uhc_row(agent="FREEMAN, BRIAN LEE", member="SMITH, BOB", mbi="9ZZ8YY7XX66",
                 action="New", amount=250.0, plan_type="DSNP"),
        _uhc_row(agent="WINSLOW, TIMOTHY", member="LEE, ANN", mbi="2BC3DE4FG56",
                 action="New Chargeback", amount=-268.0),
    ]}
    facts = normalize_uhc(sheets)
    assert len(facts) == 3
    assert all(f.carrier == "UHC" for f in facts)
    assert all(f.source_ref.startswith("uhc::0::") for f in facts)
    # full_name is now routed through normalize_person_name -> "First MI. Last"
    by_member = {f.full_name: f for f in facts}
    assert by_member["Jane Doe"].row_class == RowClass.RENEWAL
    assert by_member["Jane Doe"].mbi == "1AB2CD3EF45"
    assert by_member["Jane Doe"].writing_agent_raw == "WINSLOW, TIMOTHY"
    assert by_member["Bob Smith"].row_class == RowClass.ENROLLMENT
    assert by_member["Ann Lee"].row_class == RowClass.CHARGEBACK
    assert by_member["Ann Lee"].amount == -268.0


def test_normalize_uhc_skips_zero_and_empty_rows():
    from app.commission.normalizers import normalize_uhc
    sheets = {"Commission Transactions": [
        _UHC_HEADER,
        _uhc_row(amount=0.0),         # zero -> skip
        [""] * 24,                    # empty -> skip
        _uhc_row(member="REAL, ONE", amount=28.92),
    ]}
    facts = normalize_uhc(sheets)
    assert len(facts) == 1
    # full_name is now routed through normalize_person_name -> "First MI. Last"
    assert facts[0].full_name == "One Real"


def test_normalize_uhc_override_and_ha_are_non_customer():
    from app.commission.normalizers import normalize_uhc
    from app.commission.member_fact import RowClass
    sheets = {"Commission Transactions": [
        _UHC_HEADER,
        _uhc_row(member="OVR, ONLY", action="Renewal", amount=4.59),   # override-only
        _uhc_row(member="HA, BONUS", action="HA Payment", amount=50.0),
    ]}
    facts = normalize_uhc(sheets)
    # full_name is now routed through normalize_person_name -> "First MI. Last"
    assert {f.full_name: f.row_class for f in facts} == {
        "Only Ovr": RowClass.NON_CUSTOMER,
        "Bonus Ha": RowClass.NON_CUSTOMER,
    }


def test_normalize_uhc_attributes_by_writing_agent_id():
    """normalize_uhc must resolve the agent by Writing Agent ID (col 4), not the
    name (col 5) — Rebekah writes under 'FOUNDERS INSURANCE AGENCY, LLC'. Without
    this the customer-sync stub is left unassigned (the Sweatt→unassigned bug)."""
    from app.commission.normalizers import normalize_uhc

    header = [""] * 24
    header[4] = "Writing Agent ID"; header[5] = "Writing Agent Name"
    header[7] = "Member Name"; header[8] = "MedicareID"; header[12] = "Plan Type"
    header[19] = "Commission Action"; header[23] = "Commission"

    def row(wid, name, member, amt):
        r = [""] * 24
        r[4] = wid; r[5] = name; r[7] = member; r[12] = "MAPD"
        r[19] = "Renewal"; r[23] = amt
        return r

    sheets = {"Commission Transactions": [
        header,
        row("6435806", "FOUNDERS INSURANCE AGENCY, LLC", "SWEATT, RICKY L.", 28.92),
    ]}
    facts = normalize_uhc(sheets, writing_id_to_name={"6435806": "Rebekah Long"})
    assert len(facts) == 1
    assert facts[0].writing_agent_raw == "Rebekah Long"   # NOT the agency name


def test_normalize_uhc_nameless_no_mbi_row_is_non_customer():
    """A row with no member name AND no MBI (e.g. DVH Manual Payment — member is in
    the action string) must NOT spawn a junk stub customer."""
    from app.commission.normalizers import normalize_uhc
    from app.commission.member_fact import RowClass

    header = [""] * 24
    header[4] = "Writing Agent ID"; header[7] = "Member Name"; header[8] = "MedicareID"
    header[12] = "Plan Type"; header[19] = "Commission Action"; header[23] = "Commission"
    r = [""] * 24
    r[4] = "6435806"; r[7] = ""; r[8] = ""   # no member, no MBI
    r[12] = "MAPD"; r[19] = "New, DVH Manual Payment, ... for JANA BENSON"; r[23] = 29.53
    facts = normalize_uhc({"Commission Transactions": [header, r]},
                          writing_id_to_name={"6435806": "Rebekah Long"})
    assert len(facts) == 1
    assert facts[0].row_class == RowClass.NON_CUSTOMER   # payment only, no stub
