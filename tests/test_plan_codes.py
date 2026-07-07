def test_policy_and_plan_new_columns_exist(app, db_session):
    from app.models import Policy, Plan
    with app.app_context():
        p = Policy(carrier="Humana", member_id="M1", contract_code="H1036-335-001",
                   plan_year=2026, status="active")
        db_session.add(p); db_session.flush()
        got = Policy.query.filter_by(member_id="M1").first()
        assert got.contract_code == "H1036-335-001"
        assert got.plan_year == 2026
        pl = Plan(agency_id=1, carrier="Humana", plan_name="X", year=2026,
                  plan_type="mapd", needs_review=True)
        db_session.add(pl); db_session.flush()
        assert Plan.query.filter_by(plan_name="X").first().needs_review is True


def test_extract_humana_code_from_plan_name():
    from app.plan_codes import extract_contract_code, cms_plan_id_of
    assert extract_contract_code("Humana", {"plan_name": "HUMANA GOLD PLUS HMO POS H1036-335"}) == "H1036-335"
    assert cms_plan_id_of("H1036-335-001") == "H1036-335"
    assert cms_plan_id_of("H1036-335") == "H1036-335"

def test_extract_aetna_code_from_contract_and_pbp():
    from app.plan_codes import extract_contract_code
    assert extract_contract_code("Aetna", {"plan_name": "Aetna Medicare Select (HMO-POS)",
        "cms_contract_number": "H5521", "pbp_code": "241"}) == "H5521-241"

def test_extract_healthspring_underscore_code():
    from app.plan_codes import extract_contract_code
    assert extract_contract_code("Healthspring",
        {"plan_name": "2026_NC_H9725_015_HealthSpring Preferred Savings (HMO)"}) == "H9725-015"

def test_extract_returns_none_when_no_code():
    from app.plan_codes import extract_contract_code
    assert extract_contract_code("UHC", {"plan_name": "AARP Medicare Advantage NC-0015"}) is None

def test_classify_uses_name_when_plan_type_is_messy():
    from app.plan_codes import classify_plan
    assert classify_plan("", "AARP MEDICARE SUPPLEMENT PLAN G") == "medigap"
    assert classify_plan("AARPMODMEDSUP", "") == "medigap"
    assert classify_plan("MES", "HUMANA MED SUPP PLAN G") == "medigap"
    assert classify_plan("DVH", "DVH 1000") == "named"
    assert classify_plan("Dental", "Dental Blue for Individuals PPO") == "named"
    assert classify_plan("IDV", "NC EXTEND 1250 MNTH DEL '23") == "named"
    assert classify_plan("", "Blue Medicare Freedom+ PPO") == "year_bound"
    assert classify_plan("MA", "AARP Medicare Advantage from UHC NC-0001") == "year_bound"
    assert classify_plan("PDP", "HUMANA VALUE RX PLAN PDP") == "year_bound"

def test_medigap_letter():
    from app.plan_codes import medigap_letter
    assert medigap_letter("AARP MEDICARE SUPPLEMENT PLAN G") == "G"
    assert medigap_letter("MedSup N 2019") == "N"
    assert medigap_letter("Some Random Plan") is None
