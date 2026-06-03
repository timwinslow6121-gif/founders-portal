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


def test_cms_writes_to_empty_field(plan):
    from app.plan_provenance import set_cms_value, get_field, make_value
    action = set_cms_value(plan, "dental_allowance", make_value(2000, "yr", "usd"), "cms_pbp")
    assert action == "written"
    rec = get_field(plan, "dental_allowance")
    assert rec["source"] == "cms_pbp"
    assert rec["trust"] == "cms_authoritative"
    assert rec["value"]["amount"] == 2000


def test_cms_overwrites_first_look(plan, agent_user):
    from app.plan_provenance import set_cms_value, get_field, make_value, _load, _save
    # seed a carrier_first_look value directly
    data = _load(plan)
    data.setdefault("_meta", {})["dental_allowance"] = {
        "value": make_value(2000, "yr", "usd"), "source": "carrier_first_look",
        "trust": "unverified", "as_of": "2026", "updated_at": "x",
        "updated_by": None, "history": [],
    }
    _save(plan, data)
    action = set_cms_value(plan, "dental_allowance", make_value(1500, "yr", "usd"), "cms_pbp")
    assert action == "overwrote_firstlook"
    rec = get_field(plan, "dental_allowance")
    assert rec["value"]["amount"] == 1500
    assert rec["trust"] == "cms_authoritative"
    assert len(rec["history"]) == 1  # change logged


def test_cms_refreshes_prior_cms(plan):
    from app.plan_provenance import set_cms_value, get_field, make_value
    set_cms_value(plan, "pcp_copay", make_value(0, None, "usd"), "cms_pbp")
    action = set_cms_value(plan, "pcp_copay", make_value(5, None, "usd"), "cms_pbp")
    assert action == "refreshed"
    assert get_field(plan, "pcp_copay")["value"]["amount"] == 5


def test_cms_matching_agent_value_promotes_to_verified(plan, agent_user):
    from app.plan_provenance import set_cms_value, set_human_value, get_field, make_value
    set_human_value(plan, "specialist_copay", make_value(35, None, "usd"), user=agent_user)
    action = set_cms_value(plan, "specialist_copay", make_value(35, None, "usd"), "cms_pbp")
    assert action == "promoted_verified"
    rec = get_field(plan, "specialist_copay")
    assert rec["trust"] == "human_verified"


def test_cms_differing_from_agent_flags_conflict(plan, agent_user):
    from app.plan_provenance import set_cms_value, set_human_value, get_field, list_conflicts, make_value
    set_human_value(plan, "dental_allowance", make_value(2000, "yr", "usd"), user=agent_user)
    action = set_cms_value(plan, "dental_allowance", make_value(1500, "yr", "usd"), "cms_pbp")
    assert action == "conflict_flagged"
    # agent value is NOT overwritten
    assert get_field(plan, "dental_allowance")["value"]["amount"] == 2000
    conflicts = list_conflicts(plan)
    assert len(conflicts) == 1
    assert conflicts[0]["field"] == "dental_allowance"
    assert conflicts[0]["incoming"]["value"] == "$1,500/yr"
    assert plan.has_unresolved_conflicts is True


def test_cms_skips_human_verified(plan, agent_user):
    from app.plan_provenance import set_cms_value, set_human_value, get_field, make_value
    set_human_value(plan, "er_copay", make_value(150, None, "usd"), user=agent_user, verify=True)
    action = set_cms_value(plan, "er_copay", make_value(200, None, "usd"), "cms_pbp")
    assert action == "skipped_human"
    assert get_field(plan, "er_copay")["value"]["amount"] == 150  # unchanged


def test_resolve_conflict_clears_flag(plan, agent_user, admin_user):
    from app.plan_provenance import (
        set_cms_value, set_human_value, resolve_conflict,
        list_conflicts, get_field, make_value,
    )
    set_human_value(plan, "dental_allowance", make_value(2000, "yr", "usd"), user=agent_user)
    set_cms_value(plan, "dental_allowance", make_value(1500, "yr", "usd"), "cms_pbp")
    assert plan.has_unresolved_conflicts is True

    # AJ accepts the CMS value
    resolve_conflict(plan, "dental_allowance",
                     chosen=make_value(1500, "yr", "usd"),
                     user=admin_user, note="CMS approved value is correct")

    assert list_conflicts(plan) == []
    assert plan.has_unresolved_conflicts is False
    rec = get_field(plan, "dental_allowance")
    assert rec["value"]["amount"] == 1500
    assert rec["trust"] == "human_verified"  # AJ's choice is authoritative
