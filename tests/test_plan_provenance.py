"""
tests/test_plan_provenance.py

Tests for the plan provenance helper — structured values, precedence rules,
conflict lifecycle. Pure-logic tests; SQLite in-memory via conftest fixtures.
"""
import pytest


def test_make_value_money_with_period():
    from app.plan_provenance import make_value
    v = make_value(amount=2000, period="yr", unit="usd")
    assert v == {"amount": 2000, "period": "yr", "unit": "usd", "display": "$2,000/yr"}


def test_make_value_money_no_period():
    from app.plan_provenance import make_value
    v = make_value(amount=455, period=None, unit="usd")
    assert v["display"] == "$455"
    assert v["amount"] == 455
    assert v["period"] is None


def test_make_value_percent():
    from app.plan_provenance import make_value
    v = make_value(amount=18, period=None, unit="pct")
    assert v["display"] == "18%"
    assert v["unit"] == "pct"


def test_make_value_offered_no_amount():
    from app.plan_provenance import make_value
    v = make_value(amount=None, period="qtr", unit="usd")
    assert v["amount"] is None
    assert v["display"] == "Offered"


def test_parse_money_basic():
    from app.plan_provenance import parse_money
    assert parse_money("455.00") == 455
    assert parse_money("2000.00") == 2000
    assert parse_money("0.00") == 0


def test_parse_money_blank_is_none():
    from app.plan_provenance import parse_money
    assert parse_money("") is None
    assert parse_money(None) is None
    assert parse_money("   ") is None


def test_parse_money_decimal_preserved():
    from app.plan_provenance import parse_money
    assert parse_money("12.50") == 12.5


def test_period_code_to_token():
    from app.plan_provenance import period_code_to_token
    # CMS period codes: 1=mo, 2=qtr, 3=yr, 5=mo(alt), 7=yr(alt) per PBP dictionary
    assert period_code_to_token("2") == "qtr"
    assert period_code_to_token("3") == "yr"
    assert period_code_to_token("1") == "mo"
    assert period_code_to_token("") is None


@pytest.fixture
def plan(db_session, agency):
    """A minimal Plan row for provenance tests."""
    from app.models import Plan
    from app.extensions import db
    p = Plan(
        agency_id=agency.id, carrier="UHC", plan_name="Test Plan",
        year=2026, plan_type="mapd", cms_plan_id="H5253-117",
    )
    db.session.add(p)
    db.session.commit()
    db.session.refresh(p)
    return p


def test_get_field_missing_returns_none(plan):
    from app.plan_provenance import get_field
    assert get_field(plan, "dental_allowance") is None


def test_set_and_get_human_value_roundtrip(plan, agent_user):
    from app.plan_provenance import set_human_value, get_field, make_value
    set_human_value(plan, "dental_allowance",
                    make_value(2000, "yr", "usd"),
                    user=agent_user, note="BCBS first look")
    rec = get_field(plan, "dental_allowance")
    assert rec["value"]["amount"] == 2000
    assert rec["value"]["display"] == "$2,000/yr"
    assert rec["source"] == "agent_edit"
    assert rec["trust"] == "agent_entered"
    assert rec["updated_by"] == "Agent"
    assert len(rec["history"]) == 1
    assert rec["history"][0]["to"] == "$2,000/yr"
    assert rec["history"][0]["note"] == "BCBS first look"


def test_field_value_returns_plain_value(plan, agent_user):
    from app.plan_provenance import set_human_value, field_value, make_value
    set_human_value(plan, "otc_allowance", make_value(45, "qtr", "usd"), user=agent_user)
    assert field_value(plan, "otc_allowance") == {
        "amount": 45, "period": "qtr", "unit": "usd", "display": "$45/qtr"
    }
