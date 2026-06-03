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
