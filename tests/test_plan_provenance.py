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
